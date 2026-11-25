"""Owner requests removal; only an authenticated Admin decision ends the agreement."""
import json,math,re,secrets
from decimal import Decimal
from mysql.connector import Error
from auth_email import password_stamp
from admin_security import account_guard
from admin_service import AdminConflict,AdminNotFound,AdminValidationError,_check_actor
from billing_calculator import canonical
from db import get_db_connection
from join_request_service import JoinRequestConflict,JoinRequestNotFound
from owner_confirmation import confirm_account_password
from tenant_settlement import load_settlement
from tenancy_service import local_today


def balance_projection(balance):
    # Request-specific aggregate consent does not grant Admin invoice/bank/slip browsing.
    return {key:balance[key] for key in ('total','paid','outstanding','pending','bill_count','paid_count','review_count','label','token')}


def parse_removal(form):
    reason=form.get('reason','').strip();revision=form.get('revision','');token=form.get('settlement_token','');errors={}
    if not 1<=len(reason)<=500 or '\x00' in reason:errors['reason']='Explain why you are requesting removal, using 1–500 characters.'
    if not re.fullmatch(r'[0-9]{1,10}',revision) or int(revision)>4294967295:errors['revision']='Refresh the agreement before requesting removal.'
    if not re.fullmatch(r'[a-f0-9]{64}',token):errors['settlement']='Review the current payment balance first.'
    if form.get('confirm_financial')!='1':errors['confirm_financial']='Confirm the payment review and request-specific aggregate disclosure to Admin.'
    if errors:raise AdminValidationError(errors)
    return dict(reason=reason,revision=int(revision),settlement_token=token)


def _removable(tenancy):
    today=local_today()
    # Future reservations also need Admin cancellation; ended and zero-night periods are read-only.
    return tenancy['tenancy_status']=='open' and (tenancy['end_date'] is None or tenancy['end_date']>max(today,tenancy['start_date']))


def _lock_tenancy(q,tenancy_id,owner_id):
    q.execute('SELECT t.student_id,t.boarding_id,t.room_id FROM tenancies t JOIN boardings b ON b.boarding_id=t.boarding_id WHERE t.tenancy_id=%s AND b.owner_id=%s',(tenancy_id,owner_id));hint=q.fetchone()
    if not hint:raise JoinRequestNotFound()
    q.execute('SELECT user_id FROM users WHERE user_id=%s FOR UPDATE',(hint['student_id'],));q.fetchone()
    q.execute('SELECT boarding_id FROM boardings WHERE boarding_id=%s AND owner_id=%s FOR UPDATE',(hint['boarding_id'],owner_id))
    if not q.fetchone():raise JoinRequestNotFound()
    q.execute('SELECT room_id FROM rooms WHERE room_id=%s AND boarding_id=%s FOR UPDATE',(hint['room_id'],hint['boarding_id']));q.fetchone()
    q.execute("SELECT t.* FROM tenancies t JOIN join_requests j ON j.request_id=t.source_request_id AND j.student_id=t.student_id AND j.boarding_id=t.boarding_id AND j.status='approved' WHERE t.tenancy_id=%s AND t.boarding_id=%s FOR UPDATE",(tenancy_id,hint['boarding_id']));tenancy=q.fetchone()
    if not tenancy:raise JoinRequestNotFound()
    return tenancy


def _event(q,request_id,actor,action):
    q.execute('INSERT INTO tenant_removal_events(request_id,actor_id,action,created_at) VALUES(%s,%s,%s,UTC_TIMESTAMP(6))',(request_id,actor,action))


def submit_removal(owner_id,tenancy_id,values,stamp):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED')
            tenancy=_lock_tenancy(q,tenancy_id,owner_id)
            q.execute("SELECT password_hash FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard()+" FOR UPDATE",(owner_id,));owner=q.fetchone()
            if not owner or not secrets.compare_digest(password_stamp(owner['password_hash']),stamp):raise JoinRequestConflict('Your account changed. Log in and confirm again.')
            if not _removable(tenancy) or tenancy['revision']!=values['revision']:raise JoinRequestConflict('The agreement changed or is no longer active/scheduled. Review it again.')
            balance=load_settlement(q,owner_id,tenancy['boarding_id'],tenancy['student_id'])
            if not secrets.compare_digest(balance['token'],values['settlement_token']):raise JoinRequestConflict('Bills or payments changed. Review the new balance before requesting removal.')
            q.execute("SELECT request_id FROM tenant_removal_requests WHERE tenancy_id=%s AND status='pending' FOR UPDATE",(tenancy_id,))
            if q.fetchone():raise JoinRequestConflict('A removal request is already Pending. Wait for the Admin decision.')
            q.execute('''INSERT INTO tenant_removal_requests(tenancy_id,owner_id,boarding_id,student_id,reason,submitted_balance,tenancy_revision,submitted_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(tenancy_id,owner_id,tenancy['boarding_id'],tenancy['student_id'],values['reason'],canonical(balance_projection(balance)),tenancy['revision']))
            request_id=q.lastrowid;_event(q,request_id,owner_id,'submitted');c.commit();return request_id
        except Exception as error:
            c.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise JoinRequestConflict('Another operation changed this request. Refresh before trying again.') from None
            raise


def owner_removals(q,owner_id,tenancy_id):
    q.execute('''SELECT r.request_id,r.reason,r.status,r.submitted_at,r.decided_at,r.decision_note
        FROM tenant_removal_requests r JOIN boardings b ON b.boarding_id=r.boarding_id
        WHERE r.owner_id=%s AND b.owner_id=%s AND r.tenancy_id=%s ORDER BY r.request_id DESC LIMIT 20''',(owner_id,owner_id,tenancy_id))
    return q.fetchall()


def owner_removal_states(q,owner_id,tenancy_ids):
    if not tenancy_ids:return {}
    # One scoped query for the visible page; status comes from MySQL, not a UI flag.
    marks=','.join(['%s']*len(tenancy_ids))
    q.execute('''SELECT x.tenancy_id,x.status FROM tenant_removal_requests x
        JOIN boardings b ON b.boarding_id=x.boarding_id AND b.owner_id=x.owner_id
        WHERE x.owner_id=%s AND x.tenancy_id IN ('''+marks+''')
        AND x.request_id=(SELECT MAX(y.request_id) FROM tenant_removal_requests y
            WHERE y.owner_id=x.owner_id AND y.tenancy_id=x.tenancy_id)''',(owner_id,*tenancy_ids))
    return {row['tenancy_id']:row['status'] for row in q.fetchall()}


REQUEST_FROM=''' FROM tenant_removal_requests x JOIN tenancies t ON t.tenancy_id=x.tenancy_id
    JOIN users s ON s.user_id=x.student_id JOIN users o ON o.user_id=x.owner_id
    JOIN boardings b ON b.boarding_id=x.boarding_id JOIN rooms room ON room.room_id=t.room_id'''
FIELDS='''x.*,s.full_name AS student_name,o.full_name AS owner_name,b.boarding_name,room.room_number,
    b.owner_id AS current_owner_id,t.student_id AS current_student_id,t.boarding_id AS current_boarding_id,
    t.revision AS current_tenancy_revision,t.start_date,t.end_date,t.tenancy_status,t.rent_unit'''


def removal_count():
    with get_db_connection() as c,c.cursor() as q:
        q.execute("SELECT COUNT(*) FROM tenant_removal_requests WHERE status='pending'");return q.fetchone()[0]


def list_removals(args):
    status=args.get('status','');search=args.get('search','').strip();page=args.get('page','1')
    if status not in ('','pending','approved','rejected') or len(search)>150 or not re.fullmatch(r'[1-9][0-9]{0,6}',str(page)):
        raise AdminValidationError({'filters':'Choose valid removal-request filters.'})
    where=' WHERE 1=1';params=[]
    if status:where+=' AND x.status=%s';params.append(status)
    if search:where+=' AND (s.full_name LIKE %s OR o.full_name LIKE %s OR b.boarding_name LIKE %s)';params+=['%'+search+'%']*3
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        c.start_transaction(readonly=True)
        q.execute('SELECT COUNT(*) AS n'+REQUEST_FROM+where,tuple(params));total=q.fetchone()['n'];pages=max(1,math.ceil(total/15));page=min(int(page),pages)
        q.execute('SELECT '+FIELDS+REQUEST_FROM+where+" ORDER BY (x.status='pending') DESC,x.request_id DESC LIMIT 15 OFFSET %s",tuple(params)+((page-1)*15,));rows=q.fetchall()
        q.execute("SELECT COUNT(*) AS n FROM tenant_removal_requests WHERE status='pending'");pending=q.fetchone()['n']
        return dict(rows=rows,total=total,pages=pages,page=page,status=status,search=search,pending=pending)


def load_removal(request_id):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        c.start_transaction(readonly=True)
        q.execute('SELECT '+FIELDS+REQUEST_FROM+' WHERE x.request_id=%s',(request_id,));row=q.fetchone()
        if not row:raise AdminNotFound()
        row['submitted_balance']=json.loads(row['submitted_balance']) if isinstance(row['submitted_balance'],str) else row['submitted_balance']
        for key in ('total','paid','outstanding','pending'):row['submitted_balance'][key]=Decimal(row['submitted_balance'][key])
        row['balance']=balance_projection(load_settlement(q,row['owner_id'],row['boarding_id'],row['student_id']))
        row['scheduled']=row['start_date']>local_today()
        row['actionable']=(_removable(row) and row['current_tenancy_revision']==row['tenancy_revision'] and row['current_owner_id']==row['owner_id']
                           and row['current_student_id']==row['student_id'] and row['current_boarding_id']==row['boarding_id'])
        return row


def decide_removal(admin_id,request_id,decision,form,session_token):
    if decision not in ('approve','reject'):raise AdminNotFound()
    note=form.get('decision_note','').strip();errors={}
    if len(note)>400 or '\x00' in note or decision=='reject' and not note:errors['decision_note']='Enter a decision explanation up to 400 characters; rejection requires a reason.'
    if form.get('confirm')!='1' or form.get('revision')!='0':errors['confirm']='Review and confirm this Pending request.'
    if decision=='approve' and (form.get('confirm_financial')!='1' or not re.fullmatch(r'[a-f0-9]{64}',form.get('settlement_token',''))):errors['balance']='Review the current payment totals and acknowledge preserved debt.'
    if errors:raise AdminValidationError(errors)
    stamp=confirm_account_password(admin_id,form.get('current_password',''),'admin')
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED');_check_actor(q,admin_id,stamp,session_token)
            q.execute('SELECT x.tenancy_id,x.owner_id,b.owner_id AS current_owner_id FROM tenant_removal_requests x JOIN boardings b ON b.boarding_id=x.boarding_id WHERE x.request_id=%s',(request_id,));hint=q.fetchone()
            if not hint:raise AdminNotFound()
            tenancy=_lock_tenancy(q,hint['tenancy_id'],hint['current_owner_id'])
            # Match Owner submission's parent order; never lock Request before Owner.
            q.execute('SELECT role,is_active,admin_suspended FROM users WHERE user_id=%s FOR UPDATE',(hint['owner_id'],));owner=q.fetchone()
            q.execute('SELECT * FROM tenant_removal_requests WHERE request_id=%s FOR UPDATE',(request_id,));row=q.fetchone()
            if not row or row['status']!='pending':raise AdminConflict('This request has already been decided. Refresh it.')
            snapshot=None
            if decision=='approve':
                if not owner or owner['role']!='owner' or not owner['is_active'] or owner['admin_suspended']:raise AdminConflict('The requesting Owner account is no longer active. Review this request before proceeding.')
                if (not _removable(tenancy) or tenancy['revision']!=row['tenancy_revision'] or hint['current_owner_id']!=row['owner_id']
                    or tenancy['student_id']!=row['student_id'] or tenancy['boarding_id']!=row['boarding_id']):raise AdminConflict('The agreement changed or has ended. Reject this stale request and ask the Owner to review it again.')
                balance=load_settlement(q,row['owner_id'],row['boarding_id'],row['student_id'])
                if not secrets.compare_digest(balance['token'],form['settlement_token']):raise AdminConflict('Bills or payments changed. Review current totals before approving.')
                snapshot=canonical(balance_projection(balance));today=local_today()
                # A cancelled future reservation holds zero nights. Preserve its original start
                # and valid end>=start constraint instead of backdating or altering financial history.
                checkout=max(today,tenancy['start_date'])
                explanation=('Admin cancelled scheduled tenancy before start; removal request #' if tenancy['start_date']>today else 'Admin approved Owner removal request #')+str(request_id)+'. '+note
                q.execute("UPDATE tenancies SET end_date=%s,tenancy_status='ended',revision=revision+1 WHERE tenancy_id=%s AND revision=%s",(checkout,tenancy['tenancy_id'],tenancy['revision']))
                if q.rowcount!=1:raise AdminConflict('The agreement changed. Refresh it.')
                q.execute('''INSERT INTO tenancy_events(tenancy_id,actor_id,event_type,old_start_date,new_start_date,old_end_date,new_end_date,old_status,new_status,reason,revision,created_at)
                    VALUES(%s,%s,'move_out_confirmed',%s,%s,%s,%s,%s,'ended',%s,%s,UTC_TIMESTAMP(6))''',
                    (tenancy['tenancy_id'],admin_id,tenancy['start_date'],tenancy['start_date'],tenancy['end_date'],checkout,tenancy['tenancy_status'],explanation,tenancy['revision']+1))
            status='approved' if decision=='approve' else 'rejected'
            q.execute('UPDATE tenant_removal_requests SET status=%s,decided_by=%s,decision_note=%s,decision_balance=%s,decided_at=UTC_TIMESTAMP(6),revision=1 WHERE request_id=%s',(status,admin_id,note or None,snapshot,request_id))
            _event(q,request_id,admin_id,status);c.commit()
        except JoinRequestNotFound:
            c.rollback();raise AdminConflict('The tenancy or boarding ownership changed. Review the request again.') from None
        except Exception as error:
            c.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise AdminConflict('Another operation changed this request. Refresh and review it.') from None
            raise
