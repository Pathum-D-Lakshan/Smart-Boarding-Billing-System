"""Monthly bill generation and owned invoice history in the main Owner workspace."""
import uuid
import json

from flask import Blueprint,abort,current_app,flash,g,jsonify,redirect,render_template,request,url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException,NotFound

from auth_access import load_current_account
from billing_calculator import BillingValidationError
from billing_service import (BillingConflict,BillingNotFound,add_adjustment,correct_due_date,generate_bills,
    load_bill,load_billing,load_history,open_cycle,preview_billing,remove_adjustment,replace_cycle,save_utilities,selected_ids)
from owner_confirmation import PasswordConfirmationError,confirm_owner_password
from tenancy_service import local_today
from billing_sources import enabled

owner_bills=Blueprint('owner_bills',__name__,url_prefix='/owner/monthly-bills')
from invoice_items import issue_time
owner_bills.app_template_filter('invoice_time')(issue_time)


def wants_json(): return request.headers.get('X-Bill-Preview')=='1' or request.headers.get('X-Bill-Dialog')=='1' or request.headers.get('X-Invoice-Builder')=='1'


@owner_bills.before_request
def require_owner():
    account=load_current_account()
    if not account:
        if wants_json(): return jsonify(error='Your session expired. Log in again.',login_url=url_for('login')),401
        return redirect(url_for('login'))
    if account['role']!='owner': abort(403)
    g.current_owner=account


@owner_bills.after_request
def private_response(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.vary.add('X-Bill-Preview'); response.vary.add('X-Bill-Dialog')
    response.vary.add('X-Invoice-Builder')
    return response


def safe_values():
    # Passwords, amounts submitted as calculated totals and arbitrary IDs are never
    # echoed. Only editable form fields are preserved after a validation failure.
    names=('month','due_date','electricity_total','water_total','kind','name','category','value','value_type',
        'application_method','discount_scope','apply_to','recurrence','effective_to','description','request_key','reason')
    values={name:request.form.get(name,'')[:500] for name in names}
    values['targets']=request.form.getlist('targets')[:500]
    return values


def selected_from(data):
    if not data.getlist('selected_ids') and data.get('selection_empty')!='1': return None
    return selected_ids(data.getlist('selected_ids'))


def page(month=None,chosen=None,*,errors=None,values=None,modal=None,status=200,error=None):
    month=month or request.args.get('month') or local_today().strftime('%Y-%m')
    data=load_billing(g.current_owner['user_id'],month,chosen)
    if enabled() and data.get('cycle'):
        from billing_service import _signer,_token_data
        data['single_tokens']={row['tenancy_id']:_signer().dumps(_token_data(data['cycle'],data,[row['tenancy_id']]))
            for row in data['rows'] if not row['issued_bill']} if data.get('preview_token') else {}
    template='owner/billing_simple.html' if enabled() and request.endpoint!='owner_bills.advanced' else 'owner/monthly_bills.html'
    return render_template(template,data=data,owner_name=g.current_owner['full_name'],
        errors=errors or {},values=values or {},modal=modal,error=error,
        charge_key=uuid.uuid4().hex,discount_key=uuid.uuid4().hex),status


def go_month(month,chosen=None):
    params={'month':month}
    if chosen is not None:
        params['selected_ids']=chosen
        if not chosen: params['selection_empty']='1'
    return redirect(url_for('owner_bills.overview',**params),code=303)


@owner_bills.errorhandler(HTTPException)
def http_error(error):
    if wants_json(): return jsonify(error={400:'The form expired. Refresh before trying again.',403:'Owner access is required.',404:'This billing record is not available.'}.get(error.code,'Could not complete this request.')),error.code
    return error


@owner_bills.errorhandler(BillingNotFound)
def not_found(error): return http_error(NotFound())


@owner_bills.errorhandler(Error)
def database_error(error):
    current_app.logger.error('Monthly Bills database operation failed (%s).',error.errno)
    message=('Monthly Bills database setup is not available yet.' if error.errno==1146 else
        'Could not confirm this operation. Check Generated Bills before retrying; do not repeat generation blindly.')
    if wants_json(): return jsonify(error=message),503 if error.errno==1146 else 500
    return render_template('owner/monthly_bills.html',data=None,owner_name=g.current_owner['full_name'] if g.get('current_owner') else 'Owner',
        error=message,errors={},values={},modal=None),503 if error.errno==1146 else 500


@owner_bills.errorhandler(BillingValidationError)
@owner_bills.errorhandler(BillingConflict)
def financial_error(error):
    status=400 if isinstance(error,BillingValidationError) else 409
    if wants_json(): return jsonify(error=str(error)),status
    if enabled():
        from billing_calculator import month_period
        month=request.form.get('month') or request.args.get('month') or local_today().strftime('%Y-%m')
        try:month_period(month)
        except (ValueError,TypeError):month=local_today().strftime('%Y-%m')
        return page(month,error=str(error),status=status)
    return render_template('owner/monthly_bills.html',data=None,owner_name=g.current_owner['full_name'],
        error=str(error),errors={},values={},modal=None),status


@owner_bills.get('')
def overview():
    if not enabled():return page(chosen=selected_from(request.args))
    from invoice_builder import choices
    month=request.args.get('month') or local_today().strftime('%Y-%m')
    data=choices(g.current_owner['user_id'],month)
    return render_template('owner/invoice_builder.html',data=data,owner_name=g.current_owner['full_name'])


@owner_bills.get('/batch')
def batch():return page(chosen=selected_from(request.args))


def invoice_payload():
    raw=request.form.get('payload','')
    if len(raw)>24000:raise BillingValidationError('This invoice contains too much data.')
    try:payload=json.loads(raw)
    except (ValueError,TypeError):raise BillingValidationError('Reload the invoice form and try again.') from None
    if not isinstance(payload,dict):raise BillingValidationError('Choose a valid invoice draft.')
    return payload


@owner_bills.post('/builder/preview')
def builder_preview():
    if not enabled():abort(404)
    from invoice_builder import preview as invoice_preview
    data=invoice_preview(g.current_owner['user_id'],invoice_payload())
    return jsonify(items_html=render_template('owner/_invoice_builder_items.html',data=data),
        paper_html=render_template('owner/_invoice_builder_paper.html',data=data),
        student_html=render_template('owner/_invoice_builder_student.html',data=data),
        confirmation_html=render_template('owner/_invoice_builder_confirmation.html',data=data),
        messages=data['messages'],items=data['items'],overrides=data['overrides'],selected_expenses=data['selected_expenses'],discount=data['discount'],
        expenses=[dict(expense_id=row['expense_id'],name=row['expense_name'],category=row['category'],date=row['expense_date'].strftime('%d %b %Y'),
            amount=format(row['amount'],'.2f'),share=format(row['share'],'.2f'),available=row['available'],state=row['state']) for row in data['expenses']],
        ready=data['ready'],eligible=data['eligible'] and not data['issued_bill'],
        charges=[dict(key=line['key'],description=line['description'],amount=format(line['amount'],'.2f'),
            original=line['details'].get('original_amount',format(line['amount'],'.2f')),
            reason=line['details'].get('adjustment_reason',''),waived=line['waived'],editable=line.get('editable',False)) for line in data['lines'] if line.get('key')],
        preview_token=data['token'],cycle_id=data['cycle_id'])


@owner_bills.post('/builder/issue')
def builder_issue():
    if not enabled():abort(404)
    from invoice_builder import issue as issue_invoice
    payload=invoice_payload();references=issue_invoice(g.current_owner['user_id'],payload)
    from bill_delivery import dispatch
    from billing_service import get_db_connection
    with get_db_connection() as c,c.cursor() as q:
        q.execute('SELECT m.bill_id FROM monthly_bills m JOIN boardings b ON b.boarding_id=m.boarding_id WHERE b.owner_id=%s AND m.bill_reference=%s',
            (g.current_owner['user_id'],references[0]));bill_id=q.fetchone()[0]
    dispatch(g.current_owner['user_id'],[bill_id])
    flash('Invoice Issued Successfully. Available in Student My Bills. Email status is shown separately below.')
    return jsonify(bill_id=bill_id,redirect_url=url_for('owner_bills.details',bill_id=bill_id),
        message='Invoice issued in Student My Bills. Email delivery is tracked separately.')


@owner_bills.get('/settings')
def advanced():return page()


@owner_bills.post('/prepare')
def prepare():
    if not enabled():abort(404)
    from billing_service import prepare_expense_preview
    month=request.form.get('month','')
    try:prepare_expense_preview(g.current_owner['user_id'],month,request.form.get('due_date',''))
    except (BillingValidationError,BillingConflict) as invalid:
        from billing_calculator import month_period
        try:month_period(month)
        except (ValueError,TypeError):month=local_today().strftime('%Y-%m')
        return page(month,values=safe_values(),errors=getattr(invalid,'errors',{}),error=str(invalid),status=400 if isinstance(invalid,BillingValidationError) else 409)
    return go_month(month)


@owner_bills.post('/cycles/<int:cycle_id>/send')
def send(cycle_id):
    if not enabled():abort(404)
    if request.form.get('confirm_send')!='yes':raise BillingValidationError('Confirm the number of bills before sending.')
    chosen=selected_ids(request.form.getlist('selected_ids'))
    if request.form.get('recipient_count')!=str(len(chosen)):raise BillingValidationError('The recipient count changed. Review again.')
    references=generate_bills(g.current_owner['user_id'],cycle_id,chosen,request.form.get('preview_token',''))
    from bill_delivery import dispatch
    from billing_service import get_db_connection
    with get_db_connection() as c,c.cursor() as q:
        q.execute('SELECT m.bill_id FROM monthly_bills m JOIN boardings b ON b.boarding_id=m.boarding_id WHERE b.owner_id=%s AND m.bill_reference IN ('+','.join(['%s']*len(references))+')',(g.current_owner['user_id'],*references))
        ids=[row[0] for row in q.fetchall()]
    dispatch(g.current_owner['user_id'],ids)
    flash(str(len(references))+' bill(s) published to Student My Bills. Email delivery is tracked separately.')
    return redirect(url_for('owner_bills.history',month=request.form.get('month','')),code=303)


@owner_bills.post('/bills/<int:bill_id>/email')
def retry_email(bill_id):
    if not enabled():abort(404)
    from bill_delivery import queue_retry,dispatch
    queue_retry(g.current_owner['user_id'],bill_id);dispatch(g.current_owner['user_id'],[bill_id])
    flash('Email queued. Check delivery status; the bill was not issued again.')
    return redirect(url_for('owner_bills.history'),code=303)


@owner_bills.post('/cycles')
def create_cycle():
    month=request.form.get('month','')
    try: open_cycle(g.current_owner['user_id'],month,request.form.get('due_date',''))
    except (BillingValidationError,BillingConflict) as invalid:
        return page(month=month,errors=getattr(invalid,'errors',{}),values=safe_values(),error=str(invalid),status=400)
    flash('Billing period and draft due date saved.')
    return go_month(month)


def configuration_change(cycle_id,operation,modal_name):
    month=request.form.get('month','')
    chosen=selected_from(request.form)
    try: operation()
    except (BillingValidationError,BillingConflict) as invalid:
        return page(month,chosen,errors=getattr(invalid,'errors',{}),values=safe_values(),modal=modal_name,error=str(invalid),status=400 if isinstance(invalid,BillingValidationError) else 409)
    flash('Billing inputs saved. The preview has been recalculated.')
    return go_month(month,chosen)


@owner_bills.post('/cycles/<int:cycle_id>/utilities')
def utilities(cycle_id):
    return configuration_change(cycle_id,lambda:save_utilities(g.current_owner['user_id'],cycle_id,request.form),'utilities')


@owner_bills.post('/cycles/<int:cycle_id>/adjustments')
def adjustment(cycle_id):
    kind=request.form.get('kind','charge')
    return configuration_change(cycle_id,lambda:add_adjustment(g.current_owner['user_id'],cycle_id,request.form),'discount' if kind=='discount' else 'charge')


@owner_bills.post('/cycles/<int:cycle_id>/adjustments/<int:rule_id>/remove')
def remove_rule(cycle_id,rule_id):
    return configuration_change(cycle_id,lambda:remove_adjustment(g.current_owner['user_id'],cycle_id,rule_id,request.form),None)


@owner_bills.post('/cycles/<int:cycle_id>/preview')
def preview(cycle_id):
    chosen=selected_ids(request.form.getlist('selected_ids'))
    data=preview_billing(g.current_owner['user_id'],cycle_id,chosen)
    if wants_json():
        return jsonify(html=render_template('owner/_bill_preview.html',data=data),preview_token=data['preview_token'],
            cycle_version=data['cycle']['version'],
            selected_ids=chosen,summary={key:format(value,'.2f') if hasattr(value,'quantize') else value for key,value in data['selected_summary'].items()},
            blocked=data['stale'] or bool(data['validation_error']),
            message=data['validation_error'] or ('Source data changed; correct this issued cycle.' if data['stale'] else None))
    return go_month(data['cycle']['period_start'].strftime('%Y-%m'),chosen)


@owner_bills.post('/cycles/<int:cycle_id>/generate')
def generate(cycle_id):
    if enabled():raise BillingValidationError('Generate Bills prepares a preview. Use the separate Send confirmation on Monthly Bills to publish it.')
    chosen=selected_ids(request.form.getlist('selected_ids')); month=request.form.get('month','')
    try:
        if request.form.get('confirm_generate')!='yes': raise BillingValidationError('Confirm that you reviewed the selected bills.')
        references=generate_bills(g.current_owner['user_id'],cycle_id,chosen,request.form.get('preview_token',''))
    except (BillingValidationError,BillingConflict) as invalid:
        return page(month,chosen,error=str(invalid),status=400 if isinstance(invalid,BillingValidationError) else 409)
    flash(str(len(references))+' monthly bill(s) issued. Issuance does not record a payment.')
    return redirect(url_for('owner_bills.history',month=month),code=303)


@owner_bills.get('/generated')
def history():
    data=load_history(g.current_owner['user_id'],request.args)
    return render_template('owner/sent_bills.html' if enabled() else 'owner/generated_bills.html',data=data,owner_name=g.current_owner['full_name'],today=local_today())


def bill_response(bill_id,*,errors=None,values=None,status=200,print_mode=False):
    bill=load_bill(g.current_owner['user_id'],bill_id)
    if enabled():
        from billing_service import get_db_connection
        with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
            cursor.execute('SELECT status,error_code FROM bill_email_deliveries WHERE bill_id=%s',(bill_id,));bill['delivery']=cursor.fetchone()
    from invoice_builder import paper_from_bill
    context=dict(bill=bill,invoice=paper_from_bill(bill),owner_name=g.current_owner['full_name'],errors=errors or {},values=values or {},print_mode=print_mode)
    if wants_json(): return jsonify(html=render_template('owner/_bill_details.html',**context)),status
    return render_template('owner/bill_details.html',**context),status


@owner_bills.get('/bills/<int:bill_id>')
def details(bill_id): return bill_response(bill_id)


@owner_bills.get('/bills/<int:bill_id>/print')
def print_bill(bill_id): return bill_response(bill_id,print_mode=True)


@owner_bills.get('/bills/<int:bill_id>/pdf')
def download_pdf(bill_id):
    from io import BytesIO
    from flask import send_file
    from invoice_pdf import invoice_pdf,filename
    bill=load_bill(g.current_owner['user_id'],bill_id)
    return send_file(BytesIO(invoice_pdf(bill)),mimetype='application/pdf',as_attachment=True,download_name=filename(bill),max_age=0)


@owner_bills.post('/bills/<int:bill_id>/due-date')
def due_correction(bill_id):
    load_bill(g.current_owner['user_id'],bill_id) # Authorize before checking a password.
    try:
        stamp=confirm_owner_password(g.current_owner['user_id'],request.form.get('current_password',''))
        correct_due_date(g.current_owner['user_id'],bill_id,request.form,stamp)
    except (BillingValidationError,BillingConflict,PasswordConfirmationError) as invalid:
        errors=getattr(invalid,'errors',{'current_password':str(invalid)})
        return bill_response(bill_id,errors=errors,values=safe_values(),status=getattr(invalid,'status',400))
    flash('Bill due date corrected. The original due date and reason remain in audit history.')
    return redirect(url_for('owner_bills.details',bill_id=bill_id),code=303)


@owner_bills.post('/cycles/<int:cycle_id>/correct')
def cycle_correction(cycle_id):
    current=preview_billing(g.current_owner['user_id'],cycle_id,[]) # Ownership first.
    month=current['cycle']['period_start'].strftime('%Y-%m')
    try:
        stamp=confirm_owner_password(g.current_owner['user_id'],request.form.get('current_password',''))
        replace_cycle(g.current_owner['user_id'],cycle_id,request.form,stamp)
    except (BillingValidationError,BillingConflict,PasswordConfirmationError) as invalid:
        return page(month,errors=getattr(invalid,'errors',{'current_password':str(invalid)}),values=safe_values(),modal='correction',error=str(invalid),status=getattr(invalid,'status',400))
    flash('Previous cycle bills were voided and preserved. Review the replacement draft inputs, recalculate and issue its new bills.')
    return go_month(month)
