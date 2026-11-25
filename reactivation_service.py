"""UC31 appeals, credential-bound restricted sessions and explicit decision acknowledgements."""
from datetime import timedelta, timezone
import hashlib
import math
import secrets
import time

from mysql.connector import Error
from auth_sessions import credential_digest, token_digest, SessionCreationConflict
from admin_service import AdminConflict, AdminNotFound, AdminValidationError, _check_actor
from admin_security import reactivation_retry_enabled
from db import get_db_connection
from owner_confirmation import confirm_account_password
from join_request_service import SRI_LANKA_TIME

LIFETIME = timedelta(minutes=15)
PAGE_SIZE = 15
USER_COLUMNS = 'user_id,full_name,email,role,password_hash,is_active,admin_suspended,admin_revision'
PUBLIC_USER = ('user_id','full_name','email','role','is_active','admin_suspended','admin_revision')


class RestrictedExpired(ValueError):
    pass


def local_time(value):
    if value is None: return ''
    if value.tzinfo is None: value = value.replace(tzinfo=timezone.utc)
    # Reuse the project's Asia/Colombo UTC+05:30 timezone; no Windows tzdata install.
    return value.astimezone(SRI_LANKA_TIME).strftime('%d %B %Y — %I:%M %p (Sri Lanka Time)')


def _context(context):
    if not isinstance(context, dict) or type(context.get('user_id')) is not int or context['user_id'] <= 0 or token_digest(context.get('token')) is None:
        raise RestrictedExpired('Your restricted login expired. Sign in again.')
    return context


def _restricted(cursor, context, lock=False):
    context = _context(context)
    cursor.execute('SELECT '+USER_COLUMNS+' FROM users WHERE user_id=%s'+(' FOR UPDATE' if lock else ''), (context['user_id'],))
    user = cursor.fetchone()
    if not user or user['role'] not in ('owner','student') or not user['admin_suspended']:
        raise RestrictedExpired('Your account access changed. Sign in again to continue.')
    cursor.execute("""SELECT suspension_event_id FROM auth_sessions WHERE token_digest=%s AND user_id=%s
        AND credential_stamp=%s AND session_scope='restricted' AND remember_me=FALSE
        AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP(6)"""+(' FOR UPDATE' if lock else ''),
        (token_digest(context['token']), user['user_id'], credential_digest(user['password_hash'])))
    login = cursor.fetchone()
    if not login: raise RestrictedExpired('Your restricted login expired. Sign in again.')
    cursor.execute("""SELECT event_id,user_visible_reason,created_at FROM admin_events
        WHERE event_id=%s AND target_user_id=%s AND action='user_suspended' AND revision=%s""",
        (login['suspension_event_id'], user['user_id'], user['admin_revision']))
    event = cursor.fetchone()
    if not event: raise RestrictedExpired('Your suspension changed. Sign in again.')
    return {key:user[key] for key in PUBLIC_USER} | {'suspension':event}


def create_restricted_login(account, previous_token=None):
    token = secrets.token_urlsafe(32)
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction()
            cursor.execute('SELECT '+USER_COLUMNS+' FROM users WHERE user_id=%s FOR UPDATE', (account['user_id'],))
            user = cursor.fetchone()
            if not user or user['role'] not in ('student','owner') or not user['admin_suspended'] or not secrets.compare_digest(user['password_hash'],account['password_hash']):
                raise SessionCreationConflict('Your account changed. Please sign in again.')
            cursor.execute("SELECT event_id FROM admin_events WHERE target_user_id=%s AND action='user_suspended' AND revision=%s",(user['user_id'],user['admin_revision']))
            event = cursor.fetchone()
            if not event: raise SessionCreationConflict('Could not verify this restriction. Please contact the Platform Administrator.')
            old = token_digest(previous_token)
            if old is not None: cursor.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE token_digest=%s AND revoked_at IS NULL',(old,))
            cursor.execute('SELECT UTC_TIMESTAMP(6) AS now');now = cursor.fetchone()['now']
            cursor.execute("""INSERT INTO auth_sessions(token_digest,user_id,credential_stamp,remember_me,created_at,expires_at,session_scope,suspension_event_id)
                VALUES(%s,%s,%s,FALSE,%s,%s,'restricted',%s)""",(token_digest(token),user['user_id'],credential_digest(user['password_hash']),now,now+LIFETIME,event['event_id']))
            connection.commit()
            return {'user_id':user['user_id'],'token':token}
        except Exception:
            connection.rollback();raise


def restricted_dashboard(context):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        user = _restricted(cursor,context)
        # Each retry is a separate record; latest status and previous decisions remain distinct.
        cursor.execute('SELECT * FROM reactivation_requests WHERE user_id=%s AND suspension_event_id=%s ORDER BY request_id DESC LIMIT 20',(user['user_id'],user['suspension']['event_id']))
        user['appeal_history'] = cursor.fetchall()
        user['appeal'] = user['appeal_history'][0] if user['appeal_history'] else None
        user['can_retry'] = bool(reactivation_retry_enabled() and user['appeal'] and user['appeal']['status']=='rejected')
        return user


def _rate_limit(user_id):
    # A fixed account key prevents a new cookie/IP from bypassing submission limits.
    key=hashlib.sha256(('reactivation:'+str(user_id)).encode()).hexdigest();now=int(time.time())
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        q.execute("INSERT INTO auth_request_limits(scope,client_key,window_start,hits) VALUES('reactivation_submit',%s,%s,0) ON DUPLICATE KEY UPDATE hits=hits",(key,now))
        q.execute("SELECT window_start,hits FROM auth_request_limits WHERE scope='reactivation_submit' AND client_key=%s FOR UPDATE",(key,))
        row=q.fetchone();start,hits=(now,0) if now-row['window_start']>=900 else (row['window_start'],row['hits'])
        if hits>=5:
            c.rollback();raise AdminValidationError({'message':'Too many submissions. Wait 15 minutes and try again.'},429)
        q.execute("UPDATE auth_request_limits SET window_start=%s,hits=%s WHERE scope='reactivation_submit' AND client_key=%s",(start,hits+1,key));c.commit()


def _event(cursor,request_id,actor,action):
    cursor.execute('INSERT INTO reactivation_events(request_id,actor_id,action,created_at) VALUES(%s,%s,%s,UTC_TIMESTAMP(6))',(request_id,actor,action))


def submit_appeal(context,message,previous_request_id=None):
    context=_context(context);_rate_limit(context['user_id'])
    message=message.strip()
    if not 1<=len(message)<=1000 or '\x00' in message:
        raise AdminValidationError({'message':'Enter a message between 1 and 1,000 characters.'})
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED')
            user=_restricted(q,context,True)
            q.execute('SELECT request_id,status FROM reactivation_requests WHERE user_id=%s AND suspension_event_id=%s ORDER BY request_id DESC LIMIT 1 FOR UPDATE',(user['user_id'],user['suspension']['event_id']))
            latest=q.fetchone()
            if latest:
                if latest['status']=='pending':raise AdminConflict('Your request is already Pending. Wait for the administrator’s decision.')
                if not reactivation_retry_enabled() or latest['status']!='rejected':
                    raise AdminConflict('A request already exists for this suspension. Its current status is shown below.')
                # Bind retries to the rejection actually reviewed, including concurrent/stale forms.
                if str(previous_request_id)!=str(latest['request_id']):
                    raise AdminConflict('The latest request changed. Reload and review its decision before requesting again.')
            elif previous_request_id not in (None,'','0'):
                raise AdminConflict('The request history changed. Reload before submitting.')
            q.execute('INSERT INTO reactivation_requests(user_id,suspension_event_id,message,submitted_at) VALUES(%s,%s,%s,UTC_TIMESTAMP(6))',(user['user_id'],user['suspension']['event_id'],message))
            request_id=q.lastrowid;_event(q,request_id,user['user_id'],'submitted');c.commit();return request_id
        except Exception as error:
            c.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise AdminConflict('A request already exists or another action changed the account. Reload this page.') from None
            raise


def current_event(cursor,user):
    cursor.execute("SELECT event_id,user_visible_reason,created_at FROM admin_events WHERE target_user_id=%s AND action='user_suspended' AND revision=%s",(user['user_id'],user['admin_revision']))
    return cursor.fetchone()


def resolve_pending_manual(cursor,user,admin_id):
    event=current_event(cursor,user)
    if not event:return
    cursor.execute("SELECT request_id FROM reactivation_requests WHERE user_id=%s AND suspension_event_id=%s AND status='pending' FOR UPDATE",(user['user_id'],event['event_id']))
    pending=cursor.fetchone()
    if pending:
        cursor.execute("UPDATE reactivation_requests SET status='approved',decided_by=%s,decision_note=%s,decided_at=UTC_TIMESTAMP(6),revision=1 WHERE request_id=%s AND status='pending'",(admin_id,'Approved through manual administrative reactivation.',pending['request_id']))
        _event(cursor,pending['request_id'],admin_id,'approved')


REQUEST_FIELDS='''r.request_id,r.user_id,r.suspension_event_id,r.message,r.status,r.submitted_at,r.decided_by,r.decision_note,r.decided_at,r.acknowledged_at,r.revision,
    u.full_name,u.email,u.role,u.is_active,u.admin_suspended,u.admin_revision,e.revision AS suspension_revision,e.user_visible_reason,e.created_at AS suspended_at'''
REQUEST_FROM=" FROM reactivation_requests r JOIN users u ON u.user_id=r.user_id JOIN admin_events e ON e.event_id=r.suspension_event_id AND e.target_user_id=r.user_id WHERE u.role IN ('student','owner')"


def list_appeals(args):
    status=args.get('status','');search=args.get('search','').strip();page=args.get('page','1')
    if status not in ('','pending','approved','rejected') or len(search)>200 or not str(page).isascii() or not str(page).isdigit() or not 1<=int(page)<=1000000:
        raise AdminValidationError({'filters':'Choose a valid request status, search and page.'})
    where=REQUEST_FROM;params=[]
    if status:where+=' AND r.status=%s';params.append(status)
    if search:where+=' AND (u.full_name LIKE %s OR u.email LIKE %s)';params+=['%'+search+'%']*2
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        c.start_transaction(readonly=True)
        try:
            q.execute('SELECT COUNT(*) AS n'+where,tuple(params));total=int(q.fetchone()['n']);pages=max(1,math.ceil(total/PAGE_SIZE));page=min(int(page),pages)
            q.execute('SELECT '+REQUEST_FIELDS+where+" ORDER BY (r.status='pending') DESC,r.submitted_at DESC,r.request_id DESC LIMIT %s OFFSET %s",tuple(params)+(PAGE_SIZE,(page-1)*PAGE_SIZE))
            rows=q.fetchall();q.execute('SELECT status,COUNT(*) AS n FROM reactivation_requests GROUP BY status')
            counts={key:0 for key in ('pending','approved','rejected')}
            counts.update({row['status']:int(row['n']) for row in q.fetchall()})
            return {'rows':rows,'total':total,'page':page,'pages':pages,'pending':counts['pending'],'counts':counts,'status':status,'search':search}
        finally:c.rollback()


def pending_count():
    with get_db_connection() as c,c.cursor() as q:
        q.execute("SELECT COUNT(*) FROM reactivation_requests WHERE status='pending'");return int(q.fetchone()[0])


def load_appeal(request_id):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        q.execute('SELECT '+REQUEST_FIELDS+REQUEST_FROM+' AND r.request_id=%s',(request_id,));row=q.fetchone()
    if row is None:raise AdminNotFound()
    row['current']=bool(row['admin_suspended'] and row['admin_revision']==row['suspension_revision'])
    return row


def decide_appeal(admin_id,request_id,decision,form,session_token):
    if decision not in ('approve','reject'):raise AdminNotFound()
    note=form.get('decision_note','').strip();errors={}
    if len(note)>1000 or '\x00' in note or decision=='reject' and not note:errors['decision_note']='Enter a user-visible decision explanation, up to 1,000 characters.'
    if form.get('confirm')!='1':errors['confirm']='Confirm that you reviewed this request.'
    if form.get('revision')!='0':errors['revision']='Reload the request before deciding.'
    if errors:raise AdminValidationError(errors)
    stamp=confirm_account_password(admin_id,form.get('current_password',''),'admin')
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED');_check_actor(q,admin_id,stamp,session_token)
            q.execute('SELECT user_id FROM reactivation_requests WHERE request_id=%s',(request_id,));hint=q.fetchone()
            if not hint:raise AdminNotFound()
            # Match manual Reactivate: actor -> target user -> appeal, never appeal -> user.
            q.execute('SELECT '+USER_COLUMNS+' FROM users WHERE user_id=%s FOR UPDATE',(hint['user_id'],));user=q.fetchone()
            q.execute('SELECT * FROM reactivation_requests WHERE request_id=%s FOR UPDATE',(request_id,));appeal=q.fetchone()
            event=current_event(q,user) if user else None
            if not user or user['role'] not in ('student','owner') or not user['admin_suspended'] or not event or not appeal or appeal['status']!='pending' or appeal['suspension_event_id']!=event['event_id']:
                raise AdminConflict('This request is no longer Pending for the current suspension. Reload it.')
            status='approved' if decision=='approve' else 'rejected'
            if decision=='approve':
                if not user['is_active']:raise AdminConflict('This account has an independent inactive restriction. It cannot be overridden by appeal approval.')
                q.execute('UPDATE users SET admin_suspended=FALSE,admin_revision=admin_revision+1 WHERE user_id=%s',(user['user_id'],))
                q.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE user_id=%s AND revoked_at IS NULL',(user['user_id'],))
                q.execute("""INSERT INTO admin_events(actor_id,target_user_id,action,previous_state,new_state,revision,reason,created_at)
                    VALUES(%s,%s,'user_reactivated','suspended','clear',%s,%s,UTC_TIMESTAMP(6))""",(admin_id,user['user_id'],user['admin_revision']+1,'Approved reactivation request '+str(request_id)+'.'))
            q.execute('UPDATE reactivation_requests SET status=%s,decided_by=%s,decision_note=%s,decided_at=UTC_TIMESTAMP(6),revision=1 WHERE request_id=%s AND status=\'pending\'',(status,admin_id,note or None,request_id))
            _event(q,request_id,admin_id,status);c.commit()
        except Exception as error:
            c.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise AdminConflict('Another decision changed this request. Reload before trying again.') from None
            raise


def decision_notices(user_id):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        q.execute("SELECT request_id,status,decision_note,decided_at FROM reactivation_requests WHERE user_id=%s AND status='approved' AND acknowledged_at IS NULL ORDER BY decided_at DESC,request_id DESC LIMIT 10",(user_id,))
        return q.fetchall()


def acknowledge(user_id,request_id,token,restricted_context=None):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED')
            if restricted_context:
                user=_restricted(q,restricted_context,True);wanted='rejected'
                if user['user_id']!=user_id:raise AdminNotFound()
            else:
                q.execute('SELECT '+USER_COLUMNS+' FROM users WHERE user_id=%s FOR UPDATE',(user_id,));user=q.fetchone();wanted='approved'
                if not user or user['role'] not in ('student','owner') or not user['is_active'] or user['admin_suspended']:raise AdminNotFound()
                q.execute("SELECT user_id FROM auth_sessions WHERE token_digest=%s AND user_id=%s AND credential_stamp=%s AND session_scope='normal' AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP(6) FOR UPDATE",(token_digest(token),user_id,credential_digest(user['password_hash'])))
                if not q.fetchone():raise AdminNotFound()
            q.execute('SELECT * FROM reactivation_requests WHERE request_id=%s AND user_id=%s FOR UPDATE',(request_id,user_id));row=q.fetchone()
            if not row or row['status']!=wanted or restricted_context and row['suspension_event_id']!=user['suspension']['event_id']:raise AdminNotFound()
            if row['acknowledged_at'] is None:
                q.execute('UPDATE reactivation_requests SET acknowledged_at=UTC_TIMESTAMP(6) WHERE request_id=%s AND user_id=%s',(request_id,user_id));_event(q,request_id,user_id,'acknowledged')
            c.commit()
        except Exception:c.rollback();raise
