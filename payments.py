"""Owner management, minimal Student bills/payments, and protected documents."""
import hashlib
import uuid

from flask import Blueprint,abort,current_app,flash,g,jsonify,redirect,render_template,request,send_file,url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException,NotFound

from auth_access import load_current_account
from billing_service import identifier
from billing_calculator import BillingValidationError
from owner_confirmation import PasswordConfirmationError,confirm_owner_password
from payment_files import InvalidPaymentFile,evidence_path,upload_limit
from payment_service import (METHODS,STATUSES,PaymentConflict,PaymentNotFound,PaymentValidationError,
    cash_options,decide_payment,load_bill,load_history,load_payment,load_receipt,my_bills,record_cash,submit_bank_transfer,student_submission_options,withdraw_payment)
from tenancy_service import local_today

owner_payments=Blueprint('owner_payments',__name__,url_prefix='/owner/payments')
student_payments=Blueprint('student_payments',__name__,url_prefix='/student')
payment_documents=Blueprint('payment_documents',__name__,url_prefix='/payments')


def wants_modal(): return request.headers.get('X-Payment-Modal')=='1'


def account_required(role=None):
    account=load_current_account()
    if not account:
        if wants_modal():return jsonify(error='Your session expired. Log in again.',login_url=url_for('login')),401
        return redirect(url_for('login'))
    if account['role'] not in ('owner','student') or role and account['role']!=role: abort(403)
    g.payment_account=account
    if account['role']=='owner':g.current_owner=account
    else:g.current_student=account


owner_payments.before_request(lambda:account_required('owner'))
student_payments.before_request(lambda:account_required('student'))
payment_documents.before_request(account_required)


def context(**values):
    account=g.get('payment_account',{})
    statuses={key: label for key, label in STATUSES.items()
              if key!='withdrawn' or account.get('role')=='student'}
    return dict(owner_name=account.get('full_name','Owner'),student_name=account.get('full_name','Student'),
        payment_role=account.get('role','student'),payment_layout='owner/base.html' if account.get('role')=='owner' else 'student/base.html',
        methods=METHODS,statuses=statuses,today=local_today(),**values)


def preserved():
    return {key:request.form.get(key,'')[:500] for key in ('payment_date','bank_name','transaction_reference','note','request_key','rejection_reason')}


def render_error(error,status):
    if wants_modal():return jsonify(error=error),status
    return render_template('payments/error.html',**context(error=error)),status


def private_response(response):
    response.headers['Cache-Control']='no-store'; response.headers['X-Content-Type-Options']='nosniff'
    response.vary.add('X-Payment-Modal'); return response


def http_error(error):
    return render_error({400:'The form expired or contains invalid data. Refresh and try again.',403:'You do not have access to this payment.',
        404:'This bill, payment or document is not available.',413:'The upload is too large. Choose a slip within the displayed size limit.'}.get(error.code,'Could not complete this request.'),error.code)


def db_error(error):
    current_app.logger.error('Payment database operation failed (%s).',error.errno)
    if error.errno==1146:return render_error('Payments database setup is not available yet.',503)
    return render_error('Could not confirm this operation. Check payment history before retrying; do not repeat an uncertain payment decision blindly.',500)


for blueprint in (owner_payments,student_payments,payment_documents):
    blueprint.after_request(private_response)
    blueprint.register_error_handler(HTTPException,http_error)
    blueprint.register_error_handler(Error,db_error)
    blueprint.register_error_handler(PaymentNotFound,lambda error:http_error(NotFound()))
    blueprint.register_error_handler(PaymentConflict,lambda error:render_error(str(error),409))
    blueprint.register_error_handler(PaymentValidationError,lambda error:render_error(str(error),400))
    blueprint.register_error_handler(BillingValidationError,lambda error:render_error(str(error),400))
    blueprint.register_error_handler(OSError,lambda error:render_error('Evidence could not be read or saved. Check payment history before trying again.',500))
    blueprint.register_error_handler(InvalidPaymentFile,lambda error:render_error(str(error),400))


@owner_payments.get('')
def overview():
    return render_template('owner/payments.html',**context(data=load_history(g.payment_account['user_id'],'owner',request.args)))


def detail_response(payment_id,*,mode=None,errors=None,values=None,status=200):
    account=g.payment_account
    item=load_payment(account['user_id'],account['role'],payment_id)
    if account['role']=='owner' and current_app.config.get('MOBILE_SLIP_ENABLED'):
        from payment_notifications import notification
        item['email_notification']=notification(account['user_id'],payment_id)
    if account['role']=='student' and item['status'] in ('rejected','withdrawn'):
        item['can_resubmit']=load_bill(account['user_id'],'student',item['bill_id'])['can_submit']
    data=context(item=item,mode=mode,errors=errors or {},values=values or {})
    if wants_modal():return jsonify(html=render_template('payments/_details.html',**data),title='Payment Details'),status
    return render_template('payments/details.html',**data),status


@owner_payments.get('/<int:payment_id>')
def details(payment_id):return detail_response(payment_id,mode=request.args.get('decision') if request.args.get('decision') in ('verify','reject') else None)


@owner_payments.post('/<int:payment_id>/<decision>')
def decide(payment_id,decision):
    if decision not in ('verify','reject'):abort(404)
    owner=g.payment_account['user_id']; load_payment(owner,'owner',payment_id)
    try:
        credential=confirm_owner_password(owner,request.form.get('current_password',''))
        decide_payment(owner,payment_id,decision,request.form,credential)
    except (PaymentValidationError,PaymentConflict,PasswordConfirmationError) as invalid:
        return detail_response(payment_id,mode=decision,errors=getattr(invalid,'errors',{'current_password':str(invalid)}),
            values=preserved(),status=getattr(invalid,'status',400 if isinstance(invalid,(PaymentValidationError,PasswordConfirmationError)) else 409))
    flash('Payment verified and receipt issued. The Student can see the approval message in their portal.' if decision=='verify' else 'Payment rejected. Its evidence is preserved and the Student can resubmit.')
    return redirect(url_for('owner_payments.details',payment_id=payment_id),code=303)


def cash_response(*,selected=None,errors=None,values=None,status=200):
    owner=g.payment_account['user_id']
    raw=str(selected or request.args.get('bill_id',''))
    bill=load_bill(owner,'owner',identifier(raw,'bill')) if raw else None
    options=cash_options(owner,request.args.get('q',''))
    data=context(bill=bill,options=options,errors=errors or {},values=values or {},request_key=uuid.uuid4().hex,search=request.args.get('q',''))
    if wants_modal():return jsonify(html=render_template('payments/_cash.html',**data),title='Record Cash / Settle Zero Bill'),status
    return render_template('owner/payment_cash.html',**data),status


@owner_payments.get('/cash')
def cash():return cash_response()


@owner_payments.post('/cash')
def cash_save():
    owner=g.payment_account['user_id']; bill_id=identifier(request.form.get('bill_id',''),'bill')
    load_bill(owner,'owner',bill_id)
    try:
        credential=confirm_owner_password(owner,request.form.get('current_password',''))
        payment_id=record_cash(owner,bill_id,request.form,credential)
    except (PaymentValidationError,PaymentConflict,PasswordConfirmationError) as invalid:
        return cash_response(selected=bill_id,errors=getattr(invalid,'errors',{'current_password':str(invalid)}),values=preserved(),
            status=getattr(invalid,'status',400 if isinstance(invalid,(PaymentValidationError,PasswordConfirmationError)) else 409))
    flash('Confirmed settlement saved and receipt issued. The payment method records whether cash was actually collected.')
    return redirect(url_for('owner_payments.details',payment_id=payment_id),code=303)


@student_payments.get('/bills')
def bills():return render_template('student/bills.html',**context(data=my_bills(g.payment_account['user_id'],request.args)))


@student_payments.get('/bills/<int:bill_id>')
def bill_details(bill_id):
    from invoice_builder import paper_from_bill
    bill=load_bill(g.payment_account['user_id'],'student',bill_id)
    data=context(bill=bill,invoice=paper_from_bill(bill),print_view=request.args.get('print')=='1')
    if wants_modal():return jsonify(html=render_template('student/_bill_details.html',**data),title='Bill Details')
    return render_template('student/bill_details.html',**data)


@student_payments.get('/bills/<int:bill_id>/pdf')
def invoice_download(bill_id):
    from io import BytesIO
    from invoice_pdf import invoice_pdf,filename
    bill=load_bill(g.payment_account['user_id'],'student',bill_id)
    return send_file(BytesIO(invoice_pdf(bill)),mimetype='application/pdf',as_attachment=True,download_name=filename(bill),max_age=0)


def submission_response(bill_id=None,errors=None,values=None,status=200):
    student=g.payment_account['user_id']
    options=student_submission_options(student,request.args.get('option_page','1'))
    if bill_id is None and options['total']==1:bill_id=options['rows'][0]['bill_id']
    bill=load_bill(student,'student',bill_id) if bill_id else None
    data=context(bill=bill,options=options,errors=errors or {},values=values or {},request_key=uuid.uuid4().hex,
        limit_mb=upload_limit()/(1024*1024))
    if wants_modal():return jsonify(html=render_template('student/_payment_submission.html',**data),title='Upload from Computer',modal_kind='submission'),status
    return render_template('student/payment_form.html',**data),status


@student_payments.get('/payments/submit')
def new_submission():
    raw=request.args.get('bill_id')
    return submission_response(identifier(raw,'bill') if raw else None)


@student_payments.get('/bills/<int:bill_id>/submit-payment')
def submission(bill_id):return submission_response(bill_id)


@student_payments.post('/bills/<int:bill_id>/submit-payment')
def submit(bill_id):
    try: payment_id=submit_bank_transfer(g.payment_account['user_id'],bill_id,request.form,request.files.get('slip'))
    except (PaymentValidationError,PaymentConflict,InvalidPaymentFile) as invalid:
        return submission_response(bill_id,getattr(invalid,'errors',{'slip' if isinstance(invalid,InvalidPaymentFile) else 'form':str(invalid)}),preserved(),409 if isinstance(invalid,PaymentConflict) else 400)
    if current_app.config.get('MOBILE_SLIP_ENABLED'):
        from payment_notifications import dispatch
        dispatch(payment_id)
    flash('Payment Submitted Successfully — Awaiting Owner Verification. Your bill is not marked Paid yet.')
    return redirect(url_for('student_payments.details',payment_id=payment_id),code=303)


@student_payments.get('/payments')
def history():
    student=g.payment_account['user_id'];options=student_submission_options(student,request.args.get('option_page','1'))
    data=load_history(student,'student',request.args)
    raw=request.args.get('bill_id')
    selected=identifier(raw,'bill') if raw else options['rows'][0]['bill_id'] if options['rows'] else None
    # Keep the submitted invoice visible while its one payment awaits review.
    if selected is None and not options['total'] and data['rows']:selected=data['rows'][0]['bill_id']
    bill=load_bill(student,'student',selected) if selected else None
    return render_template('student/payments.html',**context(data=data,options=options,mobile_bill=bill))


@student_payments.route('/payments/mobile-upload',methods=['GET','POST'])
def mobile_upload():
    import mobile_payment_service as links
    if not links.enabled():abort(404)
    options=student_submission_options(g.payment_account['user_id'],request.args.get('option_page','1'))
    raw=request.form.get('bill_id') if request.method=='POST' else request.args.get('bill_id')
    if not raw and request.method=='GET' and options['total']==1:raw=str(options['rows'][0]['bill_id'])
    bill=load_bill(g.payment_account['user_id'],'student',identifier(raw,'bill')) if raw else None
    result=None;error=None;configured=True;status=200
    try:links.public_base()
    except links.UploadLinkError as invalid:configured=False;error=str(invalid)
    if request.method=='POST':
        try:
            if not bill or not bill['transfer_eligible']:raise PaymentConflict('Choose an eligible unpaid invoice.')
            result=links.generate_link(g.payment_account['user_id'],bill['bill_id'],request.form.get('whatsapp_number'))
        except (links.UploadLinkError,PaymentConflict) as invalid:error=str(invalid);status=400
    data=context(options=options,bill=bill,mobile_result=result,mobile_error=error,mobile_configured=configured,whatsapp_value=request.form.get('whatsapp_number','')[:32])
    if wants_modal():return jsonify(html=render_template('student/_mobile_payment.html',**data),title='Scan QR Code',modal_kind='qr'),status
    return render_template('student/mobile_payment.html',**data),status


@student_payments.get('/bills/<int:bill_id>/bank-details')
def bank_details(bill_id):
    bill=load_bill(g.payment_account['user_id'],'student',bill_id)
    if not bill['transfer_eligible']:raise PaymentConflict('Bank transfer is not available for this invoice.')
    data=context(bill=bill)
    if wants_modal():return jsonify(html=render_template('student/_mobile_bank_details.html',**data),title='View Bank Details',modal_kind='bank')
    return render_template('student/bank_details.html',**data)


@owner_payments.post('/<int:payment_id>/retry-notification')
def retry_notification(payment_id):
    if not current_app.config.get('MOBILE_SLIP_ENABLED'):abort(404)
    from payment_notifications import retry,dispatch
    retry(g.payment_account['user_id'],payment_id);dispatch(payment_id)
    flash('Notification queued for retry. The payment decision is unchanged.')
    return redirect(url_for('owner_payments.details',payment_id=payment_id),code=303)


@student_payments.get('/payments/<int:payment_id>',endpoint='details')
def student_details(payment_id):return detail_response(payment_id)


@student_payments.get('/payments/<int:payment_id>/withdraw')
def confirm_withdrawal(payment_id):
    student = g.payment_account['user_id']
    item = load_payment(student, 'student', payment_id)
    if item['submitted_by'] != student or item['method'] != 'bank_transfer':
        abort(404)
    if item['status'] != 'submitted':
        raise PaymentConflict('Only slips pending verification can be deleted.')
    data = context(item=item)
    if wants_modal():
        return jsonify(title='Delete Submission', modal_kind='withdrawal',
                       html=render_template('student/_confirm_withdrawal.html', **data))
    return render_template('student/withdraw_payment.html', **data)


@student_payments.post('/payments/<int:payment_id>/withdraw')
def withdraw(payment_id):
    if request.form.get('confirm_withdrawal') != 'yes':
        raise PaymentValidationError('Confirm that you want to delete this pending slip.')
    bill_id = withdraw_payment(g.payment_account['user_id'], payment_id)
    flash('Payment submission deleted from Owner review. You can now upload the correct slip.')
    return redirect(url_for('student_payments.history', bill_id=bill_id), code=303)


@payment_documents.get('/<int:payment_id>/slip')
def slip(payment_id):
    account=g.payment_account; item=load_payment(account['user_id'],account['role'],payment_id)
    if not item['evidence_id'] or item['status']=='withdrawn':abort(404)
    path=evidence_path(item['stored_filename'])
    if not path.is_file():abort(404)
    if path.stat().st_size!=item['byte_count'] or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
        return render_error('Evidence needs an integrity review. Contact the Owner.',409)
    suffix=path.suffix
    response=send_file(path,mimetype=item['media_type'],as_attachment=item['media_type']=='application/pdf' or request.args.get('download')=='1',
        download_name='bank-slip-'+item['payment_reference']+suffix,conditional=False,max_age=0)
    response.headers['Content-Security-Policy']="sandbox; default-src 'none'; img-src 'self'"
    response.headers['X-Frame-Options']='DENY'; response.headers['Cross-Origin-Resource-Policy']='same-origin'
    response.headers['Referrer-Policy']='no-referrer'; return response


@payment_documents.get('/receipts/<int:receipt_id>')
def receipt(receipt_id):
    account=g.payment_account
    return render_template('payments/receipt.html',**context(receipt=load_receipt(account['user_id'],account['role'],receipt_id)))
