"""Owner tenancy reads and audited lifecycle changes; never mutate agreed prices."""

from dataclasses import dataclass
from datetime import date, timedelta
import math
import re
import secrets

from mysql.connector import Error

from auth_email import password_stamp
from db import get_db_connection
from settings_service import student_contact_phone
import billing_guard
from admin_security import account_guard,tenant_removal_enabled
from tenant_settlement import load_settlement
from join_request_service import JoinRequestConflict, JoinRequestNotFound
from tenancy_service import local_today

PHASES = {'active': 'Active', 'scheduled': 'Scheduled', 'moving_out': 'Moving Out Soon', 'moved_out': 'Moved Out'}
PAGE_SIZE = 10
MOVING_OUT_DAYS = 30
JOINS = '''FROM tenancies t JOIN boardings b ON b.boarding_id=t.boarding_id
    JOIN users u ON u.user_id=t.student_id
    JOIN rooms r ON r.room_id=t.room_id AND r.boarding_id=b.boarding_id
    LEFT JOIN beds bed ON bed.bed_id=t.bed_id AND bed.room_id=r.room_id
    JOIN join_requests j ON j.request_id=t.source_request_id AND j.student_id=t.student_id
        AND j.boarding_id=t.boarding_id AND j.status='approved'
    '''
COLUMNS = '''t.tenancy_id,t.source_request_id,t.student_id,t.boarding_id,t.room_id,t.bed_id,
    t.start_date,t.end_date,t.tenancy_status,t.rent_unit,t.agreed_monthly_rent,t.revision,
    t.created_at,t.updated_at,u.full_name AS student_name,u.email AS student_email,
    b.boarding_name,r.room_number,CASE WHEN t.rent_unit='bed' THEN 'shared' ELSE 'private' END AS room_type,
    bed.bed_label,j.decided_at AS approved_at'''
ACTIVE = "t.tenancy_status='open' AND t.start_date<=%s AND (t.end_date IS NULL OR t.end_date>%s)"
ENDED = "(t.tenancy_status='ended' OR (t.end_date IS NOT NULL AND t.end_date<=%s))"


class TenancyValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('Check the highlighted fields.')


@dataclass(frozen=True)
class TenantFilters:
    search: str = ''
    status: str = ''
    room: str = ''
    sort: str = 'newest'
    page: int = 1

    @classmethod
    def parse(cls, data):
        q, status, room, sort, page = (data.get(key, default).strip() for key, default in
            (('q',''),('status',''),('room',''),('sort','newest'),('page','1')))
        if len(q)>150 or '\x00' in q or status and status not in PHASES or sort not in ('newest','oldest'):
            raise TenancyValidationError({'filters':'Choose valid search and filter values.'})
        if room and (not re.fullmatch(r'[1-9][0-9]{0,9}',room) or int(room)>4294967295):
            raise TenancyValidationError({'filters':'Choose a room from your boarding.'})
        if not re.fullmatch(r'[0-9]{1,7}',page) or not 1<=int(page)<=1000000:
            raise TenancyValidationError({'filters':'Choose a valid page number.'})
        return cls(q,status,room,sort,int(page))

    def params(self, page=None):
        return dict(q=self.search,status=self.status,room=self.room,sort=self.sort,page=page or self.page)


def phase(row, today=None):
    today = today or local_today()
    if row['tenancy_status']=='ended' or row['end_date'] is not None and row['end_date']<=today:
        return 'moved_out'
    return 'scheduled' if row['start_date']>today else 'active'


def decorate(row, today=None):
    today=today or local_today()
    row['phase']=phase(row,today)
    row['phase_label']=PHASES[row['phase']]
    row['moving_soon']=row['phase']=='active' and row['end_date'] is not None and row['end_date']<=today+timedelta(days=MOVING_OUT_DAYS)
    row['initials']=''.join(part[0] for part in row['student_name'].split()[:2]).upper() or '?'
    return row


def load_tenants(owner_id, filters, selected_id=None):
    today=local_today()
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute('SELECT boarding_id,boarding_name FROM boardings WHERE owner_id=%s',(owner_id,))
        boarding=cursor.fetchone()
        cursor.execute(f'''SELECT COALESCE(SUM({ACTIVE}),0) AS active,
            COALESCE(SUM(t.tenancy_status='open' AND t.start_date>%s AND (t.end_date IS NULL OR t.end_date>=%s)),0) AS scheduled,
            COALESCE(SUM({ACTIVE} AND t.end_date<=%s),0) AS moving_out,
            COALESCE(SUM({ENDED}),0) AS moved_out {JOINS} WHERE b.owner_id=%s''',
            (today,today,today,today,today,today,today+timedelta(days=MOVING_OUT_DAYS),today,owner_id))
        summary={key:int(value) for key,value in cursor.fetchone().items()}
        cursor.execute('SELECT r.room_id,r.room_number FROM rooms r JOIN boardings b ON b.boarding_id=r.boarding_id WHERE b.owner_id=%s ORDER BY r.room_number',(owner_id,))
        rooms=cursor.fetchall()
        where=' WHERE b.owner_id=%s'; params=[owner_id]
        if filters.room:
            if int(filters.room) not in {r['room_id'] for r in rooms}:
                raise TenancyValidationError({'filters':'Choose a room from your boarding.'})
            where+=' AND t.room_id=%s'; params.append(int(filters.room))
        if filters.search:
            escaped=filters.search.replace('!','!!').replace('%','!%').replace('_','!_')
            where+=" AND (u.full_name LIKE %s ESCAPE '!' OR u.email LIKE %s ESCAPE '!' OR CAST(t.student_id AS CHAR)=%s)"
            params += ['%'+escaped+'%','%'+escaped+'%',filters.search.upper().removeprefix('STU-')]
        if filters.status=='active': where+=' AND '+ACTIVE; params += [today,today]
        elif filters.status=='scheduled':
            where+=" AND t.tenancy_status='open' AND t.start_date>%s AND (t.end_date IS NULL OR t.end_date>=%s)"; params += [today,today]
        elif filters.status=='moving_out':
            where+=' AND '+ACTIVE+' AND t.end_date<=%s'; params += [today,today,today+timedelta(days=MOVING_OUT_DAYS)]
        elif filters.status=='moved_out': where+=' AND '+ENDED; params.append(today)
        cursor.execute('SELECT COUNT(*) AS total '+JOINS+where,tuple(params))
        total=cursor.fetchone()['total']; pages=max(1,math.ceil(total/PAGE_SIZE)); page=min(filters.page,pages)
        order='DESC' if filters.sort=='newest' else 'ASC'
        cursor.execute('SELECT '+COLUMNS+' '+JOINS+where+f' ORDER BY t.created_at {order},t.tenancy_id {order} LIMIT %s OFFSET %s',(*params,PAGE_SIZE,(page-1)*PAGE_SIZE))
        rows=[decorate(row,today) for row in cursor.fetchall()]
        removal_states={}
        if rows and tenant_removal_enabled():
            from tenant_removal_service import owner_removal_states
            removal_states=owner_removal_states(cursor,owner_id,[row['tenancy_id'] for row in rows])
        for row in rows:row['removal_status']=removal_states.get(row['tenancy_id'])
        selected,events=None,[]
        if selected_id is not None:
            cursor.execute('SELECT '+COLUMNS+' '+JOINS+' WHERE t.tenancy_id=%s AND b.owner_id=%s',(selected_id,owner_id))
            selected=cursor.fetchone()
            if selected is None: raise JoinRequestNotFound()
            decorate(selected,today)
            selected['student_phone']=student_contact_phone(cursor,selected['student_id'])
            selected['settlement']=load_settlement(cursor,owner_id,selected['boarding_id'],selected['student_id'])
            selected['removal_ready']=tenant_removal_enabled()
            selected['removals']=[]
            if selected['removal_ready']:
                from tenant_removal_service import owner_removals
                selected['removals']=owner_removals(cursor,owner_id,selected_id)
            selected['removal_pending']=any(row['status']=='pending' for row in selected['removals'])
            cursor.execute('''SELECT e.event_type,e.old_start_date,e.new_start_date,e.old_end_date,e.new_end_date,
                e.old_status,e.new_status,e.reason,e.created_at,u.full_name AS actor_name
                FROM tenancy_events e JOIN users u ON u.user_id=e.actor_id JOIN tenancies t ON t.tenancy_id=e.tenancy_id
                JOIN boardings b ON b.boarding_id=t.boarding_id WHERE t.tenancy_id=%s AND b.owner_id=%s ORDER BY e.revision DESC''',(selected_id,owner_id))
            events=cursor.fetchall()
        return dict(boarding=boarding,summary=summary,rows=rows,rooms=rooms,selected=selected,events=events,
            filtered_total=total,page=page,page_count=pages,today=today,
            first_row=(page-1)*PAGE_SIZE+1 if total else 0,last_row=min(page*PAGE_SIZE,total))


def parse_change(form):
    action=form.get('action','').strip(); reason=form.get('reason','').strip()
    revision=form.get('revision',''); raw=form.get('date','').strip(); errors={}
    if action not in ('start','schedule','confirm','cancel','end_stay'):
        errors['action']='Choose a permitted tenancy action.'
    if not re.fullmatch(r'[0-9]{1,10}',revision) or int(revision)>4294967295:
        errors['revision']='Refresh this tenancy before trying again.'
    if len(reason)>500 or '\x00' in reason: errors['reason']='Use no more than 500 characters.'
    value=None
    if action!='cancel':
        try:
            if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',raw): raise ValueError()
            value=date.fromisoformat(raw)
        except ValueError: errors['date']='Choose a valid date.'
    if errors: raise TenancyValidationError(errors)
    result=dict(action=action,date=value,reason=reason or None,revision=int(revision))
    if action=='end_stay':
        if not re.fullmatch(r'[a-f0-9]{64}',form.get('settlement_token','')):
            raise TenancyValidationError({'settlement':'Refresh and review the latest bill balance before ending this stay.'})
        if form.get('confirm_financial')!='1':
            raise TenancyValidationError({'confirm_financial':'Confirm that you reviewed the balance and existing issued bills will remain unchanged.'})
        result.update(settlement_token=form['settlement_token'],confirm_financial=True)
    return result


def change_tenancy(owner_id, tenancy_id, values, credential_stamp):
    """Student -> Boarding -> Room locks match approval; audit and edit commit together."""
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED')
            cursor.execute('SELECT t.student_id,t.boarding_id,t.room_id FROM tenancies t JOIN boardings b ON b.boarding_id=t.boarding_id WHERE t.tenancy_id=%s AND b.owner_id=%s',(tenancy_id,owner_id))
            hint=cursor.fetchone()
            if hint is None: raise JoinRequestNotFound()
            cursor.execute('SELECT user_id FROM users WHERE user_id=%s FOR UPDATE',(hint['student_id'],)); cursor.fetchone()
            cursor.execute('SELECT boarding_id FROM boardings WHERE boarding_id=%s AND owner_id=%s FOR UPDATE',(hint['boarding_id'],owner_id))
            if cursor.fetchone() is None: raise JoinRequestNotFound()
            cursor.execute('SELECT room_id FROM rooms WHERE room_id=%s AND boarding_id=%s FOR UPDATE',(hint['room_id'],hint['boarding_id'])); cursor.fetchone()
            cursor.execute('SELECT * FROM tenancies WHERE tenancy_id=%s AND boarding_id=%s AND student_id=%s FOR UPDATE',(tenancy_id,hint['boarding_id'],hint['student_id']))
            old=cursor.fetchone()
            if old is None: raise JoinRequestNotFound()
            cursor.execute("SELECT password_hash FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard()+" FOR UPDATE",(owner_id,))
            account=cursor.fetchone()
            if not account or not secrets.compare_digest(password_stamp(account['password_hash']),credential_stamp):
                raise JoinRequestConflict('Your account changed. Log in again and confirm this action.')
            if old['revision']!=values['revision']:
                raise JoinRequestConflict('This tenancy changed after you opened it. Review the current values and try again.')
            today=local_today(); action=values['action']; selected=values['date']
            if phase(old,today)=='moved_out':
                raise JoinRequestConflict('Completed agreements are read-only. Historical dates cannot be changed.')
            start,end,status=old['start_date'],old['end_date'],old['tenancy_status']
            if action=='start':
                if start<=today or selected<=today:
                    raise TenancyValidationError({'date':'Only a future scheduled start can be changed to another future date.'})
                start=selected; event='start_rescheduled'
            elif action=='schedule':
                if selected<=today: raise TenancyValidationError({'date':'Choose a future checkout date, or use Confirm Move-Out for today.'})
                end=selected; event='move_out_rescheduled' if end is not None and old['end_date'] is not None else 'move_out_scheduled'
            elif action in ('confirm','end_stay'):
                if selected>today: raise TenancyValidationError({'date':'A completed move-out cannot be in the future.'})
                if action=='end_stay':
                    if phase(old,today)!='active' or selected!=today:
                        raise TenancyValidationError({'date':'End Stay is available for an active tenant with checkout today. Use the existing scheduling flow for other dates.'})
                    # Payment and billing writers also lock Student -> Boarding before changes.
                    # Re-read under those locks so a bill/slip/verification cannot race this review.
                    settlement=load_settlement(cursor,owner_id,old['boarding_id'],old['student_id'])
                    if not values.get('confirm_financial') or not secrets.compare_digest(settlement['token'],values.get('settlement_token','')):
                        raise JoinRequestConflict('Bills or payments changed after your review. Review the latest balance and confirm again.')
                end=selected; status='ended'; event='move_out_confirmed'
            else:
                if end is None: raise JoinRequestConflict('There is no scheduled move-out to cancel.')
                end=None; event='move_out_cancelled'
            if end is not None and end<start:
                raise TenancyValidationError({'date':'Checkout cannot be before the tenancy start date.'})
            if (start,end,status)==(old['start_date'],old['end_date'],old['tenancy_status']):
                raise JoinRequestConflict('No change was made. Review the existing dates.')
            if action!='end_stay':
                billing_guard.guard_period_change(cursor,old,start,end)
            # Explicit End Stay releases today's unit without rewriting a frozen invoice/allocation.
            # Scheduling/backdating still follows the original frozen-period correction guard.
            # Every other agreement is checked, including other boardings for this Student.
            # A checkout day is free for the next agreement; zero-day periods hold no nights.
            if end is None or end>start:
                cursor.execute('''SELECT tenancy_id FROM tenancies WHERE tenancy_id<>%s
                    AND (student_id=%s OR (room_id=%s AND (%s='room' OR rent_unit='room' OR bed_id=%s)))
                    AND (end_date IS NULL OR end_date>%s) AND (%s IS NULL OR start_date<%s)
                    AND (end_date IS NULL OR end_date>start_date) LIMIT 1''',
                    (tenancy_id,old['student_id'],old['room_id'],old['rent_unit'],old['bed_id'],start,end,end))
                if cursor.fetchone(): raise JoinRequestConflict('These dates overlap another approved Student or Room/Bed assignment. Keep the existing agreement.')
            cursor.execute('''UPDATE tenancies SET start_date=%s,end_date=%s,tenancy_status=%s,revision=revision+1
                WHERE tenancy_id=%s AND boarding_id=%s AND revision=%s''',(start,end,status,tenancy_id,old['boarding_id'],old['revision']))
            if cursor.rowcount!=1: raise JoinRequestConflict('This tenancy changed. Refresh before trying again.')
            cursor.execute('''INSERT INTO tenancy_events (tenancy_id,actor_id,event_type,old_start_date,new_start_date,
                old_end_date,new_end_date,old_status,new_status,reason,revision,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',
                (tenancy_id,owner_id,event,old['start_date'],start,old['end_date'],end,old['tenancy_status'],status,
                 values['reason'] or ('Owner ended the stay after reviewing issued bills. Bills and any unpaid balance are preserved.' if action=='end_stay' else None),old['revision']+1))
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):
                raise JoinRequestConflict('Another operation changed this agreement. Refresh before trying again.') from None
            raise
