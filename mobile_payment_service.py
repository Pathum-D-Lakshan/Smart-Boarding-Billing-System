"""Short-lived bill-scoped upload capabilities; never a portal login."""
from datetime import timedelta
import hashlib,hmac,ipaddress,re,secrets,uuid
from urllib.parse import urlsplit,urlencode
from flask import current_app,has_app_context
from auth_email import password_stamp
from admin_security import account_guard
from db import get_db_connection
import payment_service as payments
from settings_service import student_bank_instructions
from mobile_upload_health import require_available

TOKEN=re.compile(r'[A-Za-z0-9_-]{43}')
LINK_TTL_SECONDS=900


class UploadLinkError(ValueError):pass


def enabled():return has_app_context() and current_app.config.get('MOBILE_SLIP_ENABLED',False)


def public_base():
    raw=current_app.config.get('MOBILE_PUBLIC_BASE_URL','').strip()
    try:
        p=urlsplit(raw)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('','/') or any(c in raw for c in '\r\n\\ '):raise ValueError()
        if p.hostname.lower()=='localhost':raise ValueError()
        try:
            address=ipaddress.ip_address(p.hostname)
        except ValueError:address=None
        if address and (address.is_loopback or address.is_unspecified or address.is_link_local):raise ValueError()
        host=p.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:host='['+host+']'
        port=p.port
        return 'https://'+host+(':'+str(port) if port and port!=443 else '')
    except (ValueError,UploadLinkError):raise UploadLinkError('Mobile upload is not configured yet. A phone-accessible HTTPS address is required; use desktop upload meanwhile.') from None


def normalize_mobile(value):
    if not isinstance(value,str) or len(value)>32 or re.search(r'[^0-9+()\s-]',value):raise UploadLinkError('Enter a valid Sri Lankan WhatsApp mobile number.')
    value=re.sub(r'[\s()-]','',value)
    if value.startswith('+94'):value='0'+value[3:]
    elif value.startswith('94'):value='0'+value[2:]
    elif re.fullmatch(r'7[0-9]{8}',value):value='0'+value
    if not re.fullmatch(r'07[0-9]{8}',value):raise UploadLinkError('Use a Sri Lankan mobile such as 0771234567 or +94771234567.')
    return '94'+value[1:]


def token_digest(token):return hashlib.sha256(token.encode('ascii')).digest() if isinstance(token,str) and TOKEN.fullmatch(token) else None
def credential_stamp(value):return hashlib.sha256(password_stamp(value).encode('ascii')).digest()
def csrf_for(token):return hmac.new(current_app.config['SECRET_KEY'].encode(),('mobile-slip:'+token).encode(),hashlib.sha256).hexdigest()


def generate_link(student,bill_id,phone=None):
    # QR and generic WhatsApp sharing need no recipient phone number.
    number=normalize_mobile(phone) if phone is not None else None;origin=public_base()
    # Check before taking financial row locks or creating/revoking a capability.
    require_available(origin)
    token=secrets.token_urlsafe(32)
    with payments._transaction(student,'student',bill_id) as (q,bill,owner):
        payments._issued(bill)
        if bill['final_total']<=0 or payments._active(q,bill_id):raise payments.PaymentConflict('This bill already has a pending/verified payment or needs no transfer.')
        q.execute('SELECT UTC_TIMESTAMP(6) AS now');now=q.fetchone()['now']
        q.execute('SELECT COUNT(*) AS recent,MAX(created_at) AS last_created FROM payment_upload_links WHERE student_id=%s AND created_at>%s-INTERVAL 1 HOUR',(student,now));history=q.fetchone()
        if history['recent']>=10 or history['last_created'] and (now-history['last_created']).total_seconds()<15:
            raise UploadLinkError('Please wait before generating another upload link. Use the latest link or try again later.')
        q.execute('SELECT password_hash FROM users WHERE user_id=%s',(student,));stamp=credential_stamp(q.fetchone()['password_hash'])
        q.execute('UPDATE payment_upload_links SET revoked_at=%s WHERE student_id=%s AND bill_id=%s AND used_at IS NULL AND revoked_at IS NULL',(now,student,bill_id))
        expires=now+timedelta(seconds=LINK_TTL_SECONDS)
        q.execute('''INSERT INTO payment_upload_links(token_digest,student_id,bill_id,credential_stamp,request_key,created_at,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s)''',(token_digest(token),student,bill_id,stamp,uuid.uuid4().hex,now,expires))
    link=origin+'/mobile/payment-slip#token='+token
    message='Smart Boarding — Secure Bank Slip Upload\n\nOpen this link on your phone to upload the bank transfer receipt for your boarding invoice:\n\n'+link+'\n\nThis link expires in 15 minutes. Do not share it with anyone else.'
    from payment_upload_qr import upload_qr_data_uri
    return dict(upload_url=link,whatsapp_url='https://wa.me/'+(number or '')+'?'+urlencode({'text':message}),
        qr_data_uri=upload_qr_data_uri(link),expires_at=expires,expires_in_seconds=LINK_TTL_SECONDS)


def validate_link(q,token,*,lock=False):
    digest=token_digest(token)
    if digest is None:raise UploadLinkError('This upload link is invalid. Generate a new link from My Payments.')
    # Stored earlier five-minute links keep their original expiry; longer
    # legacy links are capped at fifteen minutes without changing any records.
    q.execute('''SELECT *,LEAST(expires_at,created_at+INTERVAL 15 MINUTE)<=UTC_TIMESTAMP(6) AS expired,
        GREATEST(0,TIMESTAMPDIFF(SECOND,UTC_TIMESTAMP(6),LEAST(expires_at,created_at+INTERVAL 15 MINUTE))) AS seconds_left
        FROM payment_upload_links WHERE token_digest=%s'''+(' FOR UPDATE' if lock else ''),(digest,));link=q.fetchone()
    if not link or link['revoked_at']:raise UploadLinkError('This upload link is invalid or replaced. Generate a new link from My Payments.')
    if link['expired']:raise UploadLinkError('This upload link has expired. Please generate a new link from My Payments.')
    if link['used_at']:raise UploadLinkError('This upload link has already been used. Check My Payments for your submission.')
    q.execute("SELECT password_hash FROM users WHERE user_id=%s AND role='student' AND is_active=TRUE"+account_guard(),(link['student_id'],));account=q.fetchone()
    if not account or not hmac.compare_digest(credential_stamp(account['password_hash']),link['credential_stamp']):raise UploadLinkError('This account or upload link is unavailable. Sign in again to generate a new link.')
    return link


def inspect_link(token):
    with get_db_connection() as c,c.cursor(dictionary=True) as q:
        c.start_transaction(readonly=True);link=validate_link(q,token)
        bill=payments._bill(q,link['student_id'],'student',link['bill_id']);payments._issued(bill)
        q.execute("SELECT user_id FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard(),(bill['owner_id'],))
        if not q.fetchone():raise UploadLinkError('The Boarding Owner account is unavailable.')
        if bill['final_total']<=0:raise UploadLinkError('No bank transfer is required for this bill.')
        q.execute("SELECT payment_id FROM payments WHERE bill_id=%s AND status IN ('submitted','verified')",(bill['bill_id'],))
        if q.fetchone():raise UploadLinkError('A pending or verified payment already exists. Check My Payments.')
        # The phone displays advice when bank instructions are unavailable.
        bill['bank_ready']=bool(student_bank_instructions(q,link['student_id'],bill['bill_id']))
        return link,bill


def consume_link(q,token,bill,payment_id):
    link=validate_link(q,token,lock=True)
    if link['student_id']!=bill['student_id'] or link['bill_id']!=bill['bill_id']:raise UploadLinkError('This link does not match the intended invoice.')
    q.execute('UPDATE payment_upload_links SET used_at=UTC_TIMESTAMP(6),payment_id=%s WHERE link_id=%s',(payment_id,link['link_id']))


def submit_mobile(token,form,upload):
    link,bill=inspect_link(token)
    values=dict(request_key=link['request_key'],amount=format(bill['final_total'],'.2f'),payment_date=form.get('payment_date',''),
        transaction_reference=(form.get('transaction_reference','').strip() or 'Invoice '+bill['bill_reference']),
        note='Submitted through a bill-scoped secure mobile link. If no bank transfer ID was supplied, the reference identifies the invoice.')
    return payments.submit_bank_transfer(link['student_id'],link['bill_id'],values,upload,mobile_token=token)
