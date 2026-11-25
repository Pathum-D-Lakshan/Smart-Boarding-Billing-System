"""Payment evidence notification outbox; email never decides a payment."""
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from threading import BoundedSemaphore
from urllib.parse import urlsplit
import hashlib
import os
import uuid
import click

from flask import current_app
from flask.cli import with_appcontext
from auth_email import valid_email,mail_is_configured
from admin_security import account_guard
from bill_delivery import smtp_deliver
from db import get_db_connection
from payment_files import evidence_path,upload_limit
from payment_service import PaymentConflict,PaymentNotFound

workers=ThreadPoolExecutor(max_workers=2,thread_name_prefix='payment-email')
slots=BoundedSemaphore(12)


def enqueue(q,payment_id,owner):
    # Part of the evidence transaction: either both records commit or neither does.
    q.execute('INSERT INTO payment_notifications(payment_id,owner_id,message_id,created_at) VALUES(%s,%s,%s,UTC_TIMESTAMP(6))',
        (payment_id,owner,'<payment-'+uuid.uuid4().hex+'@smartboarding.local>'))


def notification(owner,payment_id):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        q.execute('SELECT * FROM payment_notifications WHERE payment_id=%s AND owner_id=%s',(payment_id,owner))
        return q.fetchone()


def retry(owner,payment_id):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction()
            q.execute('''SELECT n.*,n.last_attempt_at>UTC_TIMESTAMP(6)-INTERVAL 60 SECOND AS cooling,p.status AS payment_status
                FROM payment_notifications n JOIN payments p ON p.payment_id=n.payment_id
                JOIN monthly_bills m ON m.bill_id=p.bill_id JOIN boardings b ON b.boarding_id=m.boarding_id
                WHERE n.payment_id=%s AND n.owner_id=%s AND b.owner_id=%s FOR UPDATE''',(payment_id,owner,owner))
            job=q.fetchone()
            if not job:raise PaymentNotFound()
            if job['status'] not in ('failed','pending') or job['cooling'] or job['payment_status']!='submitted':
                raise PaymentConflict('This notification cannot be retried now. Accepted or uncertain emails are not sent again automatically.')
            q.execute("UPDATE payment_notifications SET status='pending',error_code=NULL WHERE payment_id=%s",(payment_id,));c.commit()
        except Exception:c.rollback();raise


def _claim(payment_id):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED')
            q.execute('SELECT *,claimed_at<UTC_TIMESTAMP(6)-INTERVAL 5 MINUTE AS expired FROM payment_notifications WHERE payment_id=%s FOR UPDATE',(payment_id,))
            job=q.fetchone()
            if not job:return None
            if job['status']=='sending' and job['expired']:
                q.execute("UPDATE payment_notifications SET status='uncertain',error_code='interrupted_attempt' WHERE payment_id=%s",(payment_id,));c.commit();return None
            if job['status']!='pending':return None
            q.execute('''SELECT p.*,m.bill_reference,m.recipient_name,m.state,b.owner_id,e.stored_filename,e.media_type,e.byte_count,e.sha256,
                u.email AS owner_email FROM payments p JOIN monthly_bills m ON m.bill_id=p.bill_id
                JOIN boardings b ON b.boarding_id=m.boarding_id JOIN users u ON u.user_id=b.owner_id
                JOIN payment_evidence e ON e.payment_id=p.payment_id WHERE p.payment_id=%s
                AND u.role='owner' AND u.is_active=TRUE'''+account_guard('u'),(payment_id,))
            item=q.fetchone();code=None
            if not item or item['owner_id']!=job['owner_id'] or item['state']!='issued' or item['status']!='submitted':code='payment_unavailable'
            elif not valid_email(item['owner_email'],gmail_only=True):code='verified_gmail_required'
            else:
                q.execute("""SELECT 1 FROM auth_email_challenges WHERE email=%s AND purpose='register'
                    AND challenge_id IS NULL AND code_digest IS NULL AND expires_at=0 AND pending_password_hash IS NULL
                    AND pending_name IS NULL AND pending_role IS NULL AND last_sent_at>0 AND sends_in_window>0""",(item['owner_email'],))
                if not q.fetchone():code='verified_gmail_required'
                elif not mail_is_configured():code='smtp_not_configured'
            if code:
                q.execute("UPDATE payment_notifications SET status='failed',error_code=%s,last_attempt_at=UTC_TIMESTAMP(6) WHERE payment_id=%s",(code,payment_id));c.commit();return None
            claim=uuid.uuid4().hex
            q.execute("UPDATE payment_notifications SET status='sending',claim_token=%s,claimed_at=UTC_TIMESTAMP(6),last_attempt_at=UTC_TIMESTAMP(6),attempt_count=attempt_count+1,error_code=NULL WHERE payment_id=%s",(claim,payment_id))
            c.commit();return job,item,claim
        except Exception:c.rollback();raise


def build_message(item,message_id):
    origin=current_app.config['APP_PUBLIC_URL'].rstrip('/');p=urlsplit(origin)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.query or p.fragment or (p.scheme=='http' and p.hostname not in ('127.0.0.1','localhost','::1')):raise ValueError('invalid_origin')
    path=evidence_path(item['stored_filename']);data=path.read_bytes()
    if len(data)!=item['byte_count'] or len(data)>upload_limit() or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('evidence_integrity')
    media=item['media_type']
    if media not in ('image/jpeg','image/png','application/pdf'):raise ValueError('evidence_type')
    message=EmailMessage();message['From']=os.environ['SMTP_FROM'];message['To']=item['owner_email']
    message['Message-ID']=message_id;message['Subject']='Bank slip awaiting verification - '+item['bill_reference']
    message.set_content('\n'.join(['A Student submitted bank-slip evidence.','Student: '+item['recipient_name'],
        'Invoice: '+item['bill_reference'],'Amount: LKR '+format(item['amount'],',.2f'),
        'Status: Pending Verification. This is not a paid receipt.',
        'Independently check your bank account before approving.',
        'Review Payment (Owner login required): '+origin+'/owner/payments/'+str(item['payment_id'])]))
    main,sub=media.split('/');message.add_attachment(data,maintype=main,subtype=sub,filename='bank-slip'+path.suffix)
    return message


def deliver_one(payment_id):
    claimed=_claim(payment_id)
    if not claimed:return
    job,item,claim=claimed
    try:message=build_message(item,job['message_id'])
    except Exception:status,code='failed','message_configuration'
    else:
        if current_app.testing and not current_app.config.get('PAYMENT_EMAIL_TEST_TRANSPORT'):status,code='failed','test_transport_disabled'
        else:status,code=smtp_deliver(message)
    with get_db_connection() as c,c.cursor() as q:
        q.execute("UPDATE payment_notifications SET status=%s,error_code=%s,sent_at=IF(%s='sent',UTC_TIMESTAMP(6),NULL),claim_token=NULL WHERE payment_id=%s AND status='sending' AND claim_token=%s",(status,code,status,payment_id,claim));c.commit()


def dispatch(payment_id):
    app=current_app._get_current_object()
    # A committed payment stays submitted even when email is unavailable.
    if app.testing or not slots.acquire(blocking=False):return
    def work():
        try:
            with app.app_context():deliver_one(payment_id)
        except Exception:app.logger.warning('Payment notification needs retry or delivery review.')
        finally:slots.release()
    try:workers.submit(work)
    except Exception:slots.release()


@click.command('deliver-payment-notifications')
@click.option('--limit',type=click.IntRange(1,100),default=20)
@with_appcontext
def deliver_pending(limit):
    """Recover queued jobs; never replay accepted or uncertain deliveries."""
    if not current_app.config.get('MOBILE_SLIP_ENABLED'):raise click.ClickException('Mobile payment notifications are disabled.')
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        q.execute("SELECT payment_id FROM payment_notifications WHERE status='pending' OR (status='sending' AND claimed_at<UTC_TIMESTAMP(6)-INTERVAL 5 MINUTE) ORDER BY created_at LIMIT %s",(limit,))
        ids=[row['payment_id'] for row in q.fetchall()]
    for payment_id in ids:deliver_one(payment_id)
    click.echo('Reviewed '+str(len(ids))+' queued notification jobs. SMTP acceptance is not inbox confirmation.')
