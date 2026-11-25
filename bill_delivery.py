"""Durable invoice-email outbox. SMTP acceptance never means inbox delivery."""
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from html import escape
import json
import os
import smtplib
import ssl
import uuid
from threading import BoundedSemaphore
from urllib.parse import urlsplit

from flask import current_app
from flask.cli import with_appcontext
import click
from db import get_db_connection
from auth_email import valid_email,mail_is_configured
from admin_security import account_guard

workers=ThreadPoolExecutor(max_workers=2,thread_name_prefix='bill-email')
mail_slots=BoundedSemaphore(12)


def enqueue_bill(cursor,bill_id):
    cursor.execute('''INSERT INTO bill_email_deliveries(bill_id,message_id,created_at)
        VALUES(%s,%s,UTC_TIMESTAMP(6))''',(bill_id,'<bill-'+uuid.uuid4().hex+'@smartboarding.local>'))


def _audit(cursor,bill,owner,kind,details):
    from billing_service import _audit as audit
    audit(cursor,bill['cycle_id'],owner,kind,details,bill_id=bill['bill_id'])


def _bill(cursor,owner,bill_id):
    from billing_service import BillingNotFound
    cursor.execute('''SELECT m.*,u.email AS current_email,u.is_active,u.role
        FROM monthly_bills m JOIN boardings b ON b.boarding_id=m.boarding_id
        JOIN users u ON u.user_id=m.student_id WHERE m.bill_id=%s AND b.owner_id=%s''',(bill_id,owner))
    row=cursor.fetchone()
    if not row:raise BillingNotFound()
    return row


def queue_retry(owner,bill_id):
    from billing_service import BillingConflict
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED')
            # Same Boarding -> Owner order as financial corrections. No new invoice.
            q.execute('SELECT boarding_id FROM boardings WHERE owner_id=%s FOR UPDATE',(owner,))
            if not q.fetchone():raise BillingConflict('Your boarding is unavailable.')
            q.execute("SELECT user_id FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard()+' FOR UPDATE',(owner,))
            if not q.fetchone():raise BillingConflict('Your account is unavailable.')
            bill=_bill(q,owner,bill_id)
            if bill['state']!='issued':raise BillingConflict('Voided bills cannot be emailed.')
            q.execute('SELECT *,last_attempt_at>UTC_TIMESTAMP(6)-INTERVAL 60 SECOND AS cooling FROM bill_email_deliveries WHERE bill_id=%s FOR UPDATE',(bill_id,))
            delivery=q.fetchone()
            if delivery:
                if delivery['status'] in ('sent','sending','uncertain'):
                    raise BillingConflict('This email was accepted, is being sent, or needs delivery review. It was not sent again.')
                if delivery['cooling']:raise BillingConflict('Wait one minute before retrying this email.')
                q.execute("UPDATE bill_email_deliveries SET status='pending',error_code=NULL WHERE bill_id=%s",(bill_id,))
            else:enqueue_bill(q,bill_id)
            _audit(q,bill,owner,'bill_email_requested',{})
            c.commit()
        except Exception:c.rollback();raise


def _claim(owner,bill_id):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction(isolation_level='READ COMMITTED')
            bill=_bill(q,owner,bill_id)
            q.execute('SELECT *,claimed_at<UTC_TIMESTAMP(6)-INTERVAL 5 MINUTE AS expired FROM bill_email_deliveries WHERE bill_id=%s FOR UPDATE',(bill_id,))
            job=q.fetchone()
            if not job:return None
            if job['status']=='sending' and job['expired']:
                q.execute("UPDATE bill_email_deliveries SET status='uncertain',error_code='interrupted_attempt' WHERE bill_id=%s",(bill_id,))
                _audit(q,bill,owner,'bill_email_uncertain',{'code':'interrupted_attempt'});c.commit();return None
            if job['status']!='pending':return None
            q.execute("SELECT user_id FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard(),(owner,))
            owner_ok=q.fetchone() is not None
            q.execute("SELECT user_id FROM users WHERE user_id=%s AND role='student' AND is_active=TRUE"+account_guard(),(bill['student_id'],))
            student_ok=q.fetchone() is not None
            q.execute('''SELECT 1 AS verified FROM auth_email_challenges WHERE email=%s AND purpose='register'
                AND challenge_id IS NULL AND code_digest IS NULL AND expires_at=0 AND pending_password_hash IS NULL
                AND pending_name IS NULL AND pending_role IS NULL AND last_sent_at>0 AND sends_in_window>0''',(bill['current_email'],))
            verified=q.fetchone() is not None
            code=None
            if bill['state']!='issued':code='bill_void'
            elif not owner_ok or not student_ok:code='account_unavailable'
            elif bill['current_email']!=bill['recipient_email'] or not valid_email(bill['current_email'],gmail_only=True) or not verified:code='verified_gmail_required'
            elif not mail_is_configured():code='smtp_not_configured'
            if code:
                q.execute("UPDATE bill_email_deliveries SET status='failed',error_code=%s,last_attempt_at=UTC_TIMESTAMP(6) WHERE bill_id=%s",(code,bill_id))
                _audit(q,bill,owner,'bill_email_failed',{'code':code});c.commit();return None
            token=uuid.uuid4().hex
            q.execute("UPDATE bill_email_deliveries SET status='sending',claim_token=%s,claimed_at=UTC_TIMESTAMP(6),last_attempt_at=UTC_TIMESTAMP(6),attempt_count=attempt_count+1,error_code=NULL WHERE bill_id=%s",(token,bill_id))
            q.execute('SELECT kind,description,amount,details FROM bill_line_items WHERE bill_id=%s ORDER BY line_number',(bill_id,));bill['lines']=q.fetchall()
            _audit(q,bill,owner,'bill_email_attempt',{'attempt':job['attempt_count']+1})
            c.commit();return bill,job,token
        except Exception:c.rollback();raise


def build_message(bill,message_id):
    from invoice_items import display_lines,issue_time
    boarding=json.loads(bill['boarding_snapshot']) if isinstance(bill['boarding_snapshot'],str) else bill['boarding_snapshot']
    unit=json.loads(bill['unit_snapshot']) if isinstance(bill['unit_snapshot'],str) else bill['unit_snapshot']
    origin=current_app.config['APP_PUBLIC_URL'].rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('invalid_public_url')
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('https_required')
    link=origin+'/student/bills/'+str(bill['bill_id'])
    month=bill['period_start'].strftime('%B %Y');due=bill['due_date'].strftime('%d %B %Y')
    invoice_lines=display_lines(bill['lines'])
    issued=issue_time(bill.get('issued_at'))
    lines=[f"{row['description']} | Amount LKR {row['amount']:,.2f}" for row in invoice_lines if not row['waived']]
    lines += [row['description']+' | Waived: '+row['details']['adjustment_reason'] for row in invoice_lines if row['waived']]
    text='\n'.join(['SMART BOARDING & BILLING SYSTEM','MONTHLY RENT INVOICE','Hello '+bill['recipient_name']+',',
        'Your monthly boarding bill is now available. Please find your monthly invoice attached as a PDF.',boarding['boarding_name'],
        'Student: '+bill['recipient_name'],'Invoice: '+bill['bill_reference'],'Issued At: '+issued,'Month: '+month,'Due: '+due,
        'Room: '+str(unit['room_number'])+(' / Bed '+str(unit['bed_label']) if unit.get('bed_label') else ' (Entire Room)'),
        '',*lines,'',f"Total Amount Due: LKR {bill['final_total']:,.2f}",
        'View your bill and payment instructions (Student login required): '+link,
        'Issuing this bill does not record a payment.'])
    message=EmailMessage();message['From']=os.environ['SMTP_FROM'];message['To']=bill['current_email']
    message['Message-ID']=message_id;message['Subject']='Monthly Boarding Invoice — '+month+' — '+boarding['boarding_name']
    message.set_content(text)
    rows=''.join('<tr><td style="padding:10px;border-bottom:1px solid #d9e7ef">'+escape(row['description'])+
        '</td><td style="padding:10px;text-align:right;border-bottom:1px solid #d9e7ef">LKR '+
        format(row['amount'],',.2f')+'</td></tr>' for row in invoice_lines if not row['waived'])
    notes=''.join('<p>'+escape(row['description'])+' — Waived: '+escape(row['details']['adjustment_reason'])+'</p>' for row in invoice_lines if row['waived'])
    html='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
        <body style="margin:0;background:#eaf4fb;color:#12304b;font:16px/1.6 Arial,sans-serif">
        <div style="max-width:600px;margin:24px auto;background:white;border:1px solid #cee2ef;border-radius:14px;overflow:hidden">
        <div style="background:#0c2038;color:white;padding:24px"><p style="margin:0;color:#31d9ed">SMART BOARDING &amp; BILLING SYSTEM</p>
        <h1 style="font-size:26px;margin:10px 0 0">Monthly Rent Invoice</h1></div><div style="padding:24px">
        <p>Hello '''+escape(bill['recipient_name'])+''',</p><p>Your bill for <strong>'''+escape(month)+'''</strong> is now available.</p>
        <h2 style="font-size:20px">'''+escape(boarding['boarding_name'])+'''</h2><p>Invoice: '''+escape(bill['bill_reference'])+'''<br>
        Issued At (Sri Lanka): '''+escape(issued)+'''<br>
        Payment Due Date: <strong>'''+escape(due)+'''</strong><br>Room: '''+escape(str(unit['room_number']))+(
        ' / Bed '+escape(str(unit['bed_label'])) if unit.get('bed_label') else ' (Entire Room)')+'''</p>
        <table style="width:100%;border-collapse:collapse"><thead><tr style="background:#eaf4fb"><th style="padding:10px;text-align:left">Breakdown</th>
        <th style="padding:10px;text-align:right">Amount (LKR)</th></tr></thead><tbody>'''+rows+'''</tbody></table>'''+notes+'''
        <p style="padding:16px;background:#dff9fc;border-radius:8px;font-size:20px;font-weight:bold">Total Due: LKR '''+format(bill['final_total'],',.2f')+'''</p>
        <p><a style="display:inline-block;background:#06cbe0;color:#082536;padding:12px 22px;border-radius:8px;font-weight:bold;text-decoration:none" href="'''+escape(link,quote=True)+'''">View My Invoice</a></p>
        <p>Student login is required to view your bill and payment details.</p><p>Regards,<br>Smart Boarding &amp; Billing System</p>
        </div></div></body></html>'''
    message.add_alternative(html,subtype='html')
    from invoice_pdf import invoice_pdf,filename
    message.add_attachment(invoice_pdf(bill),maintype='application',subtype='pdf',filename=filename(bill))
    return message


def smtp_deliver(message):
    """Return acceptance; failures during DATA may have an unknown outcome."""
    host=os.environ['SMTP_HOST'];port=int(os.getenv('SMTP_PORT','587'));tls=ssl.create_default_context()
    entered_data=False
    try:
        transport=smtplib.SMTP_SSL(host,port,context=tls,timeout=10) if port==465 else smtplib.SMTP(host,port,timeout=10)
        with transport as smtp:
            if port!=465:smtp.starttls(context=tls)
            smtp.login(os.environ['SMTP_USER'],''.join(os.environ['SMTP_PASSWORD'].split()))
            entered_data=True
            refused=smtp.send_message(message)
            if refused:return 'failed','recipient_refused'
        return 'sent',None
    except (smtplib.SMTPRecipientsRefused,smtplib.SMTPSenderRefused,smtplib.SMTPDataError):return 'failed','smtp_rejected'
    except smtplib.SMTPAuthenticationError:return 'failed','smtp_authentication'
    except (smtplib.SMTPException,OSError,ValueError,KeyError):
        return ('uncertain','smtp_outcome_unknown') if entered_data else ('failed','smtp_connection')


def deliver_one(owner,bill_id):
    claimed=_claim(owner,bill_id)
    if not claimed:return
    bill,job,token=claimed
    try:message=build_message(bill,job['message_id'])
    except Exception:
        # Rendering failed before SMTP; retry the same stored invoice safely.
        # Never log database text, addresses or document exception payloads.
        status,code='failed','message_configuration'
    else:
        # Test harnesses must explicitly replace this transport; never send real mail.
        if current_app.testing and not current_app.config.get('BILL_EMAIL_TEST_TRANSPORT'):
            status,code='failed','test_transport_disabled'
        else:status,code=smtp_deliver(message)
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        try:
            c.start_transaction()
            q.execute('SELECT status,claim_token FROM bill_email_deliveries WHERE bill_id=%s FOR UPDATE',(bill_id,))
            saved=q.fetchone()
            if saved and saved['status']=='sending' and saved['claim_token']==token:
                q.execute("UPDATE bill_email_deliveries SET status=%s,error_code=%s,sent_at=IF(%s='sent',UTC_TIMESTAMP(6),NULL),claim_token=NULL WHERE bill_id=%s",(status,code,status,bill_id))
                _audit(q,bill,owner,'bill_email_'+status,{'code':code})
            c.commit()
        except Exception:c.rollback();raise


def dispatch(owner,bill_ids):
    app=current_app._get_current_object()
    def work():
        try:
            with app.app_context():
                for bill_id in bill_ids:
                    try:deliver_one(owner,bill_id)
                    except Exception:
                        # No exception payload: SMTP responses may contain private addresses.
                        app.logger.error('Bill email worker interrupted; inspect delivery status.')
        finally:
            if not app.testing:mail_slots.release()
    if app.testing:
        if app.config.get('BILL_EMAIL_TEST_TRANSPORT'):work()
        return
    # Busy workers leave durable Pending jobs available for a later retry/recovery.
    if mail_slots.acquire(blocking=False):
        try:workers.submit(work)
        except RuntimeError:mail_slots.release()


@click.command('deliver-bill-emails')
@click.option('--owner-id',type=click.IntRange(min=1),required=True)
@click.option('--limit',type=click.IntRange(1,500),default=50)
@with_appcontext
def deliver_pending(owner_id,limit):
    """Recover already-authorized pending jobs after a process restart."""
    from billing_sources import enabled
    if not enabled():raise click.ClickException('Billing delivery is not activated.')
    with get_db_connection() as c,c.cursor() as q:
        q.execute('''SELECT d.bill_id FROM bill_email_deliveries d JOIN monthly_bills m ON m.bill_id=d.bill_id
            JOIN boardings b ON b.boarding_id=m.boarding_id WHERE b.owner_id=%s
            AND (d.status='pending' OR (d.status='sending' AND d.claimed_at<UTC_TIMESTAMP()-INTERVAL 5 MINUTE))
            ORDER BY d.created_at LIMIT %s''',(owner_id,limit));ids=[r[0] for r in q.fetchall()]
    for bill_id in ids:deliver_one(owner_id,bill_id)
    click.echo('Reviewed '+str(len(ids))+' existing delivery jobs. Inspect tracked outcomes; inbox arrival is not confirmed.')
