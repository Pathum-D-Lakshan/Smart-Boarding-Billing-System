"""A limited HTTPS upload capability, separate from application login."""
import hmac

from flask import Blueprint,abort,current_app,jsonify,render_template,request,session
from mysql.connector import Error
from werkzeug.exceptions import HTTPException
from auth_email import allow_request
from payment_files import InvalidPaymentFile,upload_limit
from payment_service import PaymentConflict,PaymentNotFound,PaymentValidationError
from payment_service import _json
from tenancy_service import local_today
import mobile_payment_service as links

mobile_payments=Blueprint('mobile_payments',__name__,url_prefix='/mobile/payment-slip')
COOKIE='boarding_slip_capability'
COOKIE_PATH='/mobile/payment-slip'


@mobile_payments.before_request
def protect():
    if not links.enabled():abort(404)
    request.max_content_length=upload_limit()+128*1024 if request.endpoint=='mobile_payments.save' else 8192
    secure=request.is_secure or (current_app.config.get('MOBILE_TRUST_LOCAL_PROXY') and request.remote_addr in ('127.0.0.1','::1') and request.headers.get('X-Forwarded-Proto')=='https')
    if not secure:abort(403,description='Use the secure HTTPS upload address.')
    if request.method=='POST':
        if request.headers.get('Origin')!=links.public_base() or request.headers.get('X-Mobile-Upload')!='1':abort(403,description='Open the original secure upload page.')
        if not allow_request('mobile-slip-submit' if request.endpoint=='mobile_payments.save' else 'mobile-slip-open',12 if request.endpoint=='mobile_payments.save' else 30,600):
            abort(429,description='Too many attempts. Please wait before trying again.')


@mobile_payments.after_request
def private(response):
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Content-Type-Options':'nosniff',
        'Content-Security-Policy':"default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        'Permissions-Policy':'camera=(self), microphone=(), geolocation=()'})
    if request.endpoint=='mobile_payments.page' and response.status_code==200:
        from mobile_upload_health import origin_fingerprint
        response.headers['X-Smart-Boarding-Upload']=origin_fingerprint(links.public_base())
    return response


def identity(token):
    link,bill=links.inspect_link(token)
    # A capability never switches an existing browser's signed-in identity.
    if session.get('user_id') and session['user_id']!=link['student_id']:abort(403,description='This upload link belongs to a different Student. Open it in a private browser window.')
    return link,bill


@mobile_payments.get('')
def page():return render_template('mobile/payment_slip.html')


@mobile_payments.post('/open')
def exchange():
    payload=request.get_json(silent=True)
    if payload is not None and not isinstance(payload,dict):abort(400,description='Open the original secure upload link.')
    token=(payload or {}).get('token') or request.cookies.get(COOKIE,'')
    link,bill=identity(token)
    response=jsonify(boarding_name=_json(bill['boarding_snapshot'])['boarding_name'],bill_reference=bill['bill_reference'],amount=format(bill['final_total'],'.2f'),student_name=bill['recipient_name'],
        today=local_today().isoformat(),csrf_token=links.csrf_for(token),max_bytes=upload_limit(),bank_details_available=bill['bank_ready'],expires_in_seconds=link['seconds_left'])
    # This cookie grants only this one upload and is never a portal session.
    response.set_cookie(COOKIE,token,max_age=max(1,min(links.LINK_TTL_SECONDS,link['seconds_left'])),secure=True,httponly=True,samesite='Strict',path=COOKIE_PATH)
    return response


@mobile_payments.post('/save')
def save():
    token=request.cookies.get(COOKIE,'')
    if not links.token_digest(token) or not hmac.compare_digest(links.csrf_for(token).encode(),request.form.get('csrf_token','').encode()):abort(400,description='Upload form expired. Open the secure link again.')
    identity(token)
    payment_id=links.submit_mobile(token,request.form,request.files.get('slip'))
    from payment_notifications import dispatch
    dispatch(payment_id)
    response=jsonify(message='Payment Slip Submitted Successfully',status='Pending Verification',detail='Your Owner will review the transfer. This does not mark the bill Paid.')
    response.delete_cookie(COOKIE,path=COOKIE_PATH,secure=True,httponly=True,samesite='Strict')
    return response


def failure(error):
    status=error.code if isinstance(error,HTTPException) else (404 if isinstance(error,PaymentNotFound) else 409 if isinstance(error,PaymentConflict) else 400)
    message=error.description if isinstance(error,HTTPException) else str(error)
    if status==413:message='This file is too large. Choose a slip within the displayed size limit.'
    if request.method=='GET':return render_template('mobile/payment_slip.html',initial_error=message),status
    return jsonify(error=message),status


for error in (HTTPException,links.UploadLinkError,PaymentConflict,PaymentNotFound,PaymentValidationError,InvalidPaymentFile):mobile_payments.register_error_handler(error,failure)


@mobile_payments.errorhandler(Error)
@mobile_payments.errorhandler(OSError)
def unavailable(error):
    # Never expose database, upload contents or bearer secrets in diagnostics.
    return jsonify(error='Could not save or confirm the upload. Check My Payments before retrying; do not pay again.'),503
