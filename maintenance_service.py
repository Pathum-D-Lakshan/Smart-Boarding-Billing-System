"""Owner-scoped operational requests with current-tenancy Student submission."""
from contextlib import contextmanager
import json
import math
import re
import secrets
import uuid

from mysql.connector import Error
from auth_email import password_stamp
from billing_calculator import canonical
from db import get_db_connection
from tenancy_service import local_today
from maintenance_photos import photo_enabled,photo_path,store_photo

STATUSES={'pending':'Pending','in_progress':'In Progress','resolved':'Resolved'}
PRIORITIES={'low':'Low','medium':'Medium','high':'High'}
SUBMISSION_LIMIT=20
ACTIVE_SQL='''SELECT t.tenancy_id,t.boarding_id,t.room_id,b.boarding_name,r.room_number
    FROM tenancies t JOIN boardings b ON b.boarding_id=t.boarding_id
    JOIN rooms r ON r.room_id=t.room_id AND r.boarding_id=t.boarding_id
    JOIN join_requests j ON j.request_id=t.source_request_id AND j.student_id=t.student_id
        AND j.boarding_id=t.boarding_id AND j.status='approved'
    WHERE t.student_id=%s AND t.tenancy_status='open' AND t.start_date<=%s
        AND (t.end_date IS NULL OR t.end_date>%s)'''


class MaintenanceNotFound(LookupError):pass
class MaintenanceConflict(RuntimeError):pass
class MaintenanceValidationError(ValueError):
    def __init__(self,message,field='form'):
        super().__init__(message);self.errors={field:message}


class MaintenanceRateLimit(MaintenanceValidationError):
    status=429


def text(form,name,limit,required=False):
    value=form.get(name,'').strip()
    if required and not value or len(value)>limit or any(ord(c)<32 and c not in '\n\r\t' for c in value):
        raise MaintenanceValidationError('Enter '+name.replace('_',' ').title()+' using '+('1–' if required else 'up to ')+str(limit)+' characters.',name)
    if name=='issue_title' and any(c in value for c in '\n\r\t'):raise MaintenanceValidationError('Use one line for the issue title.','issue_title')
    return value or None


def parse_issue(form):
    priority=form.get('priority','medium')
    if priority not in PRIORITIES:raise MaintenanceValidationError('Choose Low, Medium or High priority.','priority')
    return dict(issue_title=text(form,'issue_title',150,True),description=text(form,'description',1000,True),priority=priority)


def filters(params):
    values={key:str(params.get(key,default)).strip() for key,default in (('q',''),('status',''),('sort','newest'),('page','1'))}
    if len(values['q'])>150 or any(ord(c)<32 for c in values['q']) or values['status'] not in ('',*STATUSES) or values['sort'] not in ('newest','oldest'):
        raise MaintenanceValidationError('Choose valid maintenance filters.')
    if not re.fullmatch(r'[0-9]{1,6}',values['page']) or int(values['page'])<1:raise MaintenanceValidationError('Choose a valid records page.')
    return values


def student_filters(params):
    view=filters(params);tab=params.get('tab','requests')
    if tab not in ('requests','history'):raise MaintenanceValidationError('Choose My Requests or Request History.')
    return {**view,'tab':tab}


def _scope(actor,role):
    if role=='owner':return 'b.owner_id=%s',(actor,)
    if role=='student':return "m.reported_by_user_id=%s AND m.reporter_role='student'",(actor,)
    raise MaintenanceNotFound()


def _request(cursor,actor,role,maintenance_id,lock=False):
    where,args=_scope(actor,role)
    cursor.execute('SELECT m.* FROM maintenance_requests m JOIN boardings b ON b.boarding_id=m.boarding_id WHERE m.maintenance_id=%s AND '+where+(' FOR UPDATE' if lock else ''),(maintenance_id,*args))
    row=cursor.fetchone()
    if not row:raise MaintenanceNotFound()
    return row


def _current(cursor,student):
    today=local_today();cursor.execute(ACTIVE_SQL,(student,today,today));rows=cursor.fetchall()
    if len(rows)>1:raise MaintenanceConflict('Your current tenancy needs review. Contact the Owner before reporting a new issue.')
    return rows[0] if rows else None


def current_tenancy(student):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:return _current(cursor,student)


def load_requests(actor,role,params):
    view=student_filters(params) if role=='student' else filters(params)
    where,args=_scope(actor,role);args=list(args)
    joins=' FROM maintenance_requests m JOIN boardings b ON b.boarding_id=m.boarding_id JOIN users reporter ON reporter.user_id=m.reported_by_user_id'
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        boarding=None;active_tenancy=None;eligibility_message=None
        if role=='owner':
            cursor.execute('SELECT boarding_id,boarding_name FROM boardings WHERE owner_id=%s',(actor,));boarding=cursor.fetchone()
        else:
            # Eligibility must not hide the Student's historical requests after checkout.
            try:active_tenancy=_current(cursor,actor)
            except MaintenanceConflict as invalid:eligibility_message=str(invalid)
            if not active_tenancy and not eligibility_message:
                eligibility_message='You need an active boarding to report maintenance issues.'
        cursor.execute("SELECT COUNT(*) AS total,COALESCE(SUM(m.status='pending'),0) AS pending,COALESCE(SUM(m.status='in_progress'),0) AS in_progress,COALESCE(SUM(m.status='resolved'),0) AS resolved"+joins+' WHERE '+where,tuple(args))
        summary={key:int(value) for key,value in cursor.fetchone().items()}
        if role=='student' and view['tab']=='history':where+=" AND m.status='resolved'"
        if view['status']:where+=' AND m.status=%s';args.append(view['status'])
        if view['q']:
            escaped=view['q'].replace('!','!!').replace('%','!%').replace('_','!_')
            search_fields=['m.issue_title','m.maintenance_reference']
            if role=='owner':search_fields+=['m.reporter_name','reporter.full_name']
            where+=' AND ('+' OR '.join(field+" LIKE %s ESCAPE '!'" for field in search_fields)+')';args+=['%'+escaped+'%']*len(search_fields)
        cursor.execute('SELECT COUNT(*) AS total'+joins+' WHERE '+where,tuple(args));total=cursor.fetchone()['total']
        pages=max(1,math.ceil(total/15));page=min(int(view['page']),pages);direction=' DESC' if view['sort']=='newest' else ' ASC'
        cursor.execute('''SELECT m.maintenance_id,m.maintenance_reference,m.reporter_name,m.reporter_role,m.issue_title,
            m.room_label,m.priority,m.status,m.owner_note,m.resolution_note,m.created_at,m.updated_at,m.resolved_at'''+joins+' WHERE '+where+' ORDER BY m.created_at'+direction+',m.maintenance_id'+direction+' LIMIT 15 OFFSET %s',(*args,(page-1)*15))
        return dict(boarding=boarding,rows=cursor.fetchall(),summary=summary,total=total,page=page,page_count=pages,filters=view,
            active_tenancy=active_tenancy,eligibility_message=eligibility_message)


def maintenance_summary(owner):return load_requests(owner,'owner',{})['summary']


def load_request(actor,role,maintenance_id):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        row=_request(cursor,actor,role,maintenance_id);row['expense']=None;row['events']=[]
        if role=='owner':
            if row['expense_id']:
                cursor.execute('SELECT expense_id,expense_name,amount,expense_date,archived_at FROM expenses WHERE expense_id=%s AND boarding_id=%s',(row['expense_id'],row['boarding_id']))
                row['expense']=cursor.fetchone()
            cursor.execute('''SELECT e.event_type,e.before_values,e.after_values,e.created_at,u.full_name AS actor_name
                FROM maintenance_events e JOIN users u ON u.user_id=e.actor_id WHERE e.maintenance_id=%s
                ORDER BY revision DESC LIMIT 10''',(maintenance_id,))
            row['events']=cursor.fetchall()
            for event in row['events']:
                for key in ('before_values','after_values'):
                    if isinstance(event[key],(str,bytes)):event[key]=json.loads(event[key])
        else:
            # Owner repair costs/audit are private, even for the reporting Student.
            row.pop('expense_id',None)
        row['photo']=None
        if photo_enabled():
            cursor.execute('SELECT sha256,byte_count,width,height,created_at FROM maintenance_photos WHERE maintenance_id=%s',(maintenance_id,))
            row['photo']=cursor.fetchone()
        return row


def load_photo(actor,role,maintenance_id):
    if not photo_enabled():raise MaintenanceNotFound()
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        _request(cursor,actor,role,maintenance_id)
        cursor.execute('SELECT stored_filename,sha256,byte_count FROM maintenance_photos WHERE maintenance_id=%s',(maintenance_id,))
        photo=cursor.fetchone()
        if not photo:raise MaintenanceNotFound()
        return photo


def _room(cursor,boarding,room_id):
    cursor.execute('SELECT room_id,room_number FROM rooms WHERE room_id=%s AND boarding_id=%s FOR UPDATE',(room_id,boarding))
    row=cursor.fetchone()
    if not row:raise MaintenanceValidationError('Choose a Room from your own Boarding.','location')
    return row


def _snapshot(row):return {key:row[key] for key in ('issue_title','description','priority','status','room_id','room_label','owner_note','resolution_note','expense_id','resolved_at','resolved_by')}


def _event(cursor,row,actor,kind,before):
    cursor.execute('''INSERT INTO maintenance_events(maintenance_id,revision,actor_id,event_type,before_values,after_values,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(row['maintenance_id'],row['revision'],actor,kind,
            canonical(before) if before is not None else None,canonical(_snapshot(row))))


def _duplicate(cursor,actor,role,key,values,location,photo=None):
    cursor.execute('SELECT * FROM maintenance_requests WHERE reported_by_user_id=%s AND request_key=%s',(actor,key));old=cursor.fetchone()
    if not old:return None
    expected='common' if old['room_id'] is None else ('room' if role=='student' else 'room:'+str(old['room_id']))
    if old['reporter_role']!=role or location!=expected or any(old[field]!=value for field,value in values.items()):
        raise MaintenanceConflict('This form already created a different report. Open a fresh form before reporting another issue.')
    if photo_enabled():
        cursor.execute('SELECT sha256 FROM maintenance_photos WHERE maintenance_id=%s',(old['maintenance_id'],));saved=cursor.fetchone()
        if (saved['sha256'] if saved else None)!=(photo['sha256'] if photo else None):
            raise MaintenanceConflict('This form already saved a different photo. Read the saved request before submitting another issue.')
    return old['maintenance_id']


def create_request(actor,role,form,photo=None):
    # Submission is Student-only, including direct service callers.
    if role!='student':raise MaintenanceNotFound()
    if photo is not None and not photo_enabled():raise MaintenanceValidationError('Photo attachments are not available.','photo')
    values=parse_issue(form);location=form.get('location','');key=form.get('request_key','')
    if not re.fullmatch(r'[a-f0-9]{32}',key):raise MaintenanceValidationError('Refresh this form before submitting again.')
    if role=='student' and location not in ('room','common'):raise MaintenanceValidationError('Choose your Assigned Room or Common Area.','location')
    stored_filename=None;commit_started=False
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED')
            cursor.execute("SELECT full_name FROM users WHERE user_id=%s AND role='student' AND is_active=TRUE FOR UPDATE",(actor,));account=cursor.fetchone()
            if not account:raise MaintenanceConflict('Your account changed. Log in again.')
            old=_duplicate(cursor,actor,role,key,values,location,photo)
            if old:connection.commit();return old
            hint=_current(cursor,actor)
            if not hint:raise MaintenanceConflict('Only a currently active tenant can report a new issue. Scheduled or ended tenancies are not current occupancy.')
            # Match lifecycle's Student -> Boarding -> Room -> Tenancy locks,
            # then recheck dates so concurrent checkout cannot submit as active.
            cursor.execute('SELECT boarding_id,boarding_name FROM boardings WHERE boarding_id=%s FOR UPDATE',(hint['boarding_id'],));boarding=cursor.fetchone()
            _room(cursor,hint['boarding_id'],hint['room_id'])
            cursor.execute('SELECT tenancy_id FROM tenancies WHERE tenancy_id=%s FOR UPDATE',(hint['tenancy_id'],));cursor.fetchone()
            current=_current(cursor,actor)
            if not current or current['tenancy_id']!=hint['tenancy_id']:raise MaintenanceConflict('Your active tenancy changed. Refresh before reporting.')
            # The locked Student row serializes this limit across workers. A retry
            # of an already saved request was handled above without consuming it.
            cursor.execute('SELECT COUNT(*) AS recent FROM maintenance_requests WHERE reported_by_user_id=%s AND created_at>=UTC_TIMESTAMP(6)-INTERVAL 1 MINUTE',(actor,))
            if cursor.fetchone()['recent']>=SUBMISSION_LIMIT:
                raise MaintenanceRateLimit('Too many reports were submitted recently. Wait a minute before reporting another issue.')
            tenancy_id=current['tenancy_id'];room_id=current['room_id'] if location=='room' else None
            room_label=current['room_number'] if room_id else None
            reference='MNT-'+local_today().strftime('%Y%m')+'-'+uuid.uuid4().hex[:16].upper()
            cursor.execute('''INSERT INTO maintenance_requests(maintenance_reference,boarding_id,tenancy_id,reported_by_user_id,
                reporter_role,reporter_name,boarding_label,room_id,room_label,issue_title,description,priority,request_key,
                created_at,updated_at,status_changed_at,status_changed_by)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),UTC_TIMESTAMP(6),%s)''',
                (reference,boarding['boarding_id'],tenancy_id,actor,role,account['full_name'],boarding['boarding_name'],room_id,room_label,
                 values['issue_title'],values['description'],values['priority'],key,actor))
            maintenance_id=cursor.lastrowid
            if photo:
                stored_filename=store_photo(photo)
                cursor.execute('''INSERT INTO maintenance_photos(maintenance_id,stored_filename,sha256,byte_count,width,height,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(maintenance_id,stored_filename,photo['sha256'],photo['byte_count'],photo['width'],photo['height']))
            row=_request(cursor,actor,role,maintenance_id);_event(cursor,row,actor,'created',None)
            commit_started=True;connection.commit();return maintenance_id
        except Exception as error:
            try:connection.rollback()
            except Error:pass
            if stored_filename and not commit_started:
                # Never clean up after an ambiguous COMMIT, even if another read
                # has not observed it yet. Only known pre-commit failures qualify.
                try:
                    with get_db_connection() as check,check.cursor() as verify:
                        verify.execute('SELECT COUNT(*) FROM maintenance_photos WHERE stored_filename=%s',(stored_filename,))
                        if verify.fetchone()[0]==0:photo_path(stored_filename).unlink(missing_ok=True)
                except (Error,OSError):pass
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise MaintenanceConflict('Another operation changed this report or tenancy. Check saved requests before trying again.') from None
            raise


@contextmanager
def _owner_write(owner,maintenance_id,credential,critical):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED');hint=_request(cursor,owner,'owner',maintenance_id)
            cursor.execute('SELECT boarding_id FROM boardings WHERE boarding_id=%s AND owner_id=%s FOR UPDATE',(hint['boarding_id'],owner))
            if not cursor.fetchone():raise MaintenanceNotFound()
            cursor.execute("SELECT password_hash FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE FOR UPDATE",(owner,));account=cursor.fetchone()
            if not account or critical and (not credential or not secrets.compare_digest(password_stamp(account['password_hash']),credential)):
                raise MaintenanceConflict('Your account changed. Log in again and confirm your current password.')
            row=_request(cursor,owner,'owner',maintenance_id,True)
            yield cursor,row
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise MaintenanceConflict('Another status update changed. Refresh the saved request before trying again.') from None
            raise


def update_request(owner,maintenance_id,action,form,credential=None):
    if action not in ('start','resolve'):raise MaintenanceValidationError('Choose Start Work or Resolve.')
    with _owner_write(owner,maintenance_id,credential,action!='start') as (cursor,row):
        if row['reporter_role']!='student':raise MaintenanceConflict('Historical Owner reports are read-only. Only Student requests can be managed.')
        if str(row['revision'])!=form.get('revision',''):raise MaintenanceConflict('This request changed after opening. Refresh its saved details before trying again.')
        if form.get('status',row['status'])!=row['status']:raise MaintenanceValidationError('Use Start Work or Resolve for status changes.','status')
        before=_snapshot(row)
        if action=='start':
            if row['status']!='pending':raise MaintenanceConflict('Only a Pending request can start work. The saved progress is preserved.')
            note=text(form,'owner_note',1000)
            cursor.execute("""UPDATE maintenance_requests SET status='in_progress',owner_note=%s,started_at=UTC_TIMESTAMP(6),started_by=%s,
                status_changed_at=UTC_TIMESTAMP(6),status_changed_by=%s,updated_at=UTC_TIMESTAMP(6),revision=revision+1 WHERE maintenance_id=%s""",(note,owner,owner,maintenance_id));kind='started'
        else:
            if row['status'] not in ('pending','in_progress'):raise MaintenanceConflict('This issue is already Resolved. Its original resolution is preserved.')
            note=text(form,'resolution_note',1000,True)
            if form.get('confirm_resolution')!='yes':raise MaintenanceValidationError('Confirm that the issue has been fixed.','confirm_resolution')
            cursor.execute("""UPDATE maintenance_requests SET status='resolved',resolution_note=%s,resolved_at=UTC_TIMESTAMP(6),resolved_by=%s,
                status_changed_at=UTC_TIMESTAMP(6),status_changed_by=%s,updated_at=UTC_TIMESTAMP(6),revision=revision+1 WHERE maintenance_id=%s""",(note,owner,owner,maintenance_id));kind='resolved'
        saved=_request(cursor,owner,'owner',maintenance_id);_event(cursor,saved,owner,kind,before)
    return maintenance_id
