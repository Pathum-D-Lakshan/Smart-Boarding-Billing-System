"""Owner-only Income & Expenses with progressive forms and centered edit/archive."""
import uuid
from flask import Blueprint,abort,current_app,flash,g,jsonify,redirect,render_template,request,url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException,NotFound
from auth_access import load_current_account
from finance_service import (FinanceConflict,FinanceNotFound,FinanceValidationError,add_expense,change_expense,
    effective_expense_period,expense_date_window,filters,has_expense_accounting,load_expense,load_finance,period)
from tenancy_service import local_today
from billing_sources import enabled

owner_finance=Blueprint('owner_finance',__name__,url_prefix='/owner/income-expenses')


@owner_finance.app_context_processor
def navigation_available():
    # Old running app processes can still render the shared template safely until
    # the approved schema/code rollout restarts them with this blueprint registered.
    return {'finance_navigation_enabled':True}


def json_request():return request.headers.get('X-Finance-Request')=='1' or request.headers.get('X-Finance-Modal')=='1'


@owner_finance.before_request
def require_owner():
    owner=load_current_account()
    if not owner:
        if json_request():return jsonify(error='Your session expired. Log in again.',login_url=url_for('login')),401
        return redirect(url_for('login'))
    if owner['role']!='owner':abort(403)
    g.finance_owner=owner


@owner_finance.after_request
def private_response(response):
    response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
    response.vary.add('X-Finance-Request');response.vary.add('X-Finance-Modal');return response


def safe_values():return {key:request.form[key][:500] for key in ('expense_name','amount','expense_date','request_key','category','utility_period','notes','charge_to_tenants','accounting_period') if key in request.form}


def recording_dates(month,allocated):
    first,last,default=expense_date_window(month,allocated)
    return dict(first_expense_date=first,last_expense_date=last,default_date=default,
        accounting_month_label=period(month)[0].strftime('%B %Y'))


def workspace(view,*,errors=None,values=None,notice=None,status=200):
    data=load_finance(g.finance_owner['user_id'],view,request.args.get('attempt_key'))
    context=dict(data=data,values=values or {},errors=errors or {},notice=notice,
        request_key=uuid.uuid4().hex,owner_name=g.finance_owner['full_name'],
        **recording_dates(data['filters']['month'],data.get('accounting_available',False)))
    if json_request():return jsonify(workspace_html=render_template('owner/_finance_workspace.html',**context),
        filters=dict(data['filters'],page=data['page']),notice=notice,recovered=data['recovered']),status
    return render_template('owner/income_expenses.html',**context),status


def error_response(message,status):
    if json_request():return jsonify(error=message,recovery_required=status>=500),status
    return render_template('owner/income_expenses.html',data=None,error=message,owner_name=g.finance_owner['full_name'] if g.get('finance_owner') else 'Owner'),status


@owner_finance.errorhandler(HTTPException)
def http_error(error):return error_response({400:'The form expired. Refresh before trying again.',403:'Owner access is required.',404:'This expense is not available.'}.get(error.code,'Could not complete this request.'),error.code)


@owner_finance.errorhandler(FinanceNotFound)
def missing(error):return http_error(NotFound())


@owner_finance.errorhandler(Error)
def db_error(error):
    current_app.logger.error('Finance database operation failed (%s).',error.errno)
    return error_response('Income & Expenses database setup is unavailable.' if error.errno==1146 else
        'Could not confirm this save. Refresh saved records before trying again; do not repeat an uncertain expense blindly.',503 if error.errno==1146 else 500)


@owner_finance.errorhandler(FinanceValidationError)
def validation_error(error):return error_response(str(error),400)


@owner_finance.errorhandler(FinanceConflict)
def conflict(error):return error_response(str(error),409)


@owner_finance.get('')
def overview():return workspace(filters(request.args))


@owner_finance.post('/expenses')
def create():
    month=request.form.get('view_month','')
    if not month:raise FinanceValidationError('Choose an Accounting Month before adding an expense.','month')
    view=filters({'month':month})
    try:row=add_expense(g.finance_owner['user_id'],request.form,accounting_month=view['month'])
    except (FinanceValidationError,FinanceConflict) as invalid:
        if enabled():return add_modal(view,errors=getattr(invalid,'errors',{'form':str(invalid)}),values=safe_values(),status=400 if isinstance(invalid,FinanceValidationError) else 409)
        return workspace(view,errors=getattr(invalid,'errors',{'form':str(invalid)}),values=safe_values(),
            status=400 if isinstance(invalid,FinanceValidationError) else 409)
    notice='Expense saved in '+effective_expense_period(row).strftime('%B %Y')+'.'
    if json_request():return workspace(view,notice=notice)
    flash(notice);return redirect(url_for('owner_finance.overview',month=view['month']),code=303)


def add_modal(view,errors=None,values=None,status=200):
    context=dict(view=view,errors=errors or {},values=values or {},request_key=uuid.uuid4().hex,
        **recording_dates(view['month'],has_expense_accounting()),
        owner_name=g.finance_owner['full_name'])
    if json_request():return jsonify(modal_html=render_template('owner/_expense_add.html',**context)),status
    return render_template('owner/expense_add.html',**context),status


@owner_finance.get('/expenses/new')
def add_form():return add_modal(filters(request.args))


def modal(expense_id,action,view,*,errors=None,values=None,status=200,stale=False):
    expense=load_expense(g.finance_owner['user_id'],expense_id)
    if view is None:view=filters({'month':effective_expense_period(expense).strftime('%Y-%m')})
    context=dict(expense=expense,action=action,view=view,errors=errors or {},values=values or {},stale=stale,
        today=local_today(),owner_name=g.finance_owner['full_name'])
    if json_request():return jsonify(modal_html=render_template('owner/_expense_form.html',**context)),status
    return render_template('owner/expense_form.html',**context),status


@owner_finance.get('/expenses/<int:expense_id>/<action>')
def form(expense_id,action):
    if action not in ('edit','archive'):abort(404)
    return modal(expense_id,action,filters(request.args) if request.args.get('month') or request.args.get('view_month') else None)


@owner_finance.post('/expenses/<int:expense_id>/<action>')
def save(expense_id,action):
    if action not in ('edit','archive'):abort(404)
    view=filters(request.form);owner=g.finance_owner['user_id']
    load_expense(owner,expense_id) # Authorize even a direct POST before mutation.
    try:
        row=change_expense(owner,expense_id,action,request.form)
    except (FinanceValidationError,FinanceConflict) as invalid:
        return modal(expense_id,action,view,errors=getattr(invalid,'errors',{'form':str(invalid)}),values=safe_values(),
            status=400 if isinstance(invalid,FinanceValidationError) else 409,stale=isinstance(invalid,FinanceConflict))
    if action=='edit':view=dict(month=effective_expense_period(row).strftime('%Y-%m'),q='',page='1')
    notice='Expense archived and excluded from active totals.' if action=='archive' else 'Expense changes saved.'
    if json_request():return workspace(view,notice=notice)
    flash(notice);return redirect(url_for('owner_finance.overview',**view),code=303)
