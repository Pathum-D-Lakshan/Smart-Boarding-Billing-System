"""Authenticated Owner tenancy management in the existing main application."""

from flask import Blueprint, abort, current_app, flash, g, jsonify, redirect, render_template, request, url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException

from auth_access import load_current_account
from join_request_service import JoinRequestConflict, JoinRequestNotFound
from owner_confirmation import PasswordConfirmationError, confirm_owner_password
from tenancy_lifecycle import PHASES, TenantFilters, TenancyValidationError, change_tenancy, load_tenants, parse_change
from admin_security import tenant_removal_enabled
from admin_service import AdminValidationError
from tenant_removal_service import parse_removal,submit_removal

owner_tenants=Blueprint('owner_tenants',__name__,url_prefix='/owner/tenants')


def modal_request():
    return request.endpoint=='owner_tenants.dialog' or request.headers.get('X-Tenant-Modal')=='1'


@owner_tenants.before_request
def require_owner():
    account=load_current_account()
    if account is None:
        if modal_request(): return jsonify(error='Your session expired. Log in again.',login_url=url_for('login')),401
        return redirect(url_for('login'))
    if account['role']!='owner': abort(403)
    g.current_owner=account


@owner_tenants.after_request
def private_response(response):
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    response.vary.add('X-Tenant-Modal')
    return response


@owner_tenants.errorhandler(HTTPException)
def http_error(error):
    if modal_request():
        return jsonify(error={400:'The form expired. Refresh before trying again.',403:'Owner access is required.',404:'This tenancy is not available to your account.'}.get(error.code,'Could not complete this request.')),error.code
    return error


@owner_tenants.errorhandler(Error)
def database_error(error):
    current_app.logger.error('Tenants database operation failed (%s).',error.errno)
    message='Could not confirm this operation. Refresh the tenancy to check its current status before trying again.'
    if modal_request(): return jsonify(error=message),500
    return render_template('owner/tenants.html',owner_name=g.current_owner['full_name'] if g.get('current_owner') else 'Owner',data=None,error=message,filters=TenantFilters(),statuses=PHASES),500


def page(tenancy_id=None, *, filters=None, values=None, errors=None, error=None, notice=None, status=200):
    try:
        filters=filters or TenantFilters.parse(request.args)
        data=load_tenants(g.current_owner['user_id'],filters,tenancy_id)
    except JoinRequestNotFound: abort(404)
    except TenancyValidationError as invalid:
        if modal_request(): return jsonify(error=str(next(iter(invalid.errors.values())))),400
        return render_template('owner/tenants.html',owner_name=g.current_owner['full_name'],data=None,
            filters=TenantFilters(),statuses=PHASES,error=next(iter(invalid.errors.values()))),400
    if request.method=='POST' and request.form.get('action') in ('end_stay','request_removal') and data['selected']:
        current=data['selected'].get('settlement')
        if current and request.form.get('settlement_token')!=current['token']:
            # Even password-error retries must not carry an acknowledgement of an older balance.
            values={**(values or {}),'confirm_financial':''}
            errors={**(errors or {}),'settlement':'The bill balance changed. Review the new amounts and confirm them again.'}
    context=dict(owner_name=g.current_owner['full_name'],data=data,filters=filters,statuses=PHASES,
        values=values or {},errors=errors or {},error=error,notice=notice)
    if modal_request():
        return jsonify(html=render_template('owner/_tenant_details.html',**context),
            results_html=render_template('owner/_tenant_results.html',**context),summary=data['summary'],notice=notice,error=error),status
    return render_template('owner/tenants.html',**context),status


@owner_tenants.get('')
def overview(): return page()


@owner_tenants.get('/<int:tenancy_id>')
def details(tenancy_id): return page(tenancy_id)


@owner_tenants.get('/<int:tenancy_id>/dialog')
def dialog(tenancy_id): return page(tenancy_id)


@owner_tenants.post('/<int:tenancy_id>/change')
def change(tenancy_id):
    # Authorize the target before attempting a password or revealing form errors.
    try: load_tenants(g.current_owner['user_id'],TenantFilters(),tenancy_id)
    except JoinRequestNotFound: abort(404)
    values={key:request.form.get(key,'')[:limit] for key,limit in (('action',20),('date',20),('reason',500),('revision',10),('confirm_financial',1))}
    try:
        filters=TenantFilters.parse(request.form)
        removal=request.form.get('action')=='request_removal'
        if request.form.get('action')=='end_stay':
            raise TenancyValidationError({'action':'Send a Tenant Removal Request to Admin instead. Direct Owner removal is unavailable.'})
        if removal and not tenant_removal_enabled():
            raise TenancyValidationError({'action':'Tenant removal requests are awaiting their approved database activation.'})
        parsed=parse_removal(request.form) if removal else parse_change(request.form)
        stamp=confirm_owner_password(g.current_owner['user_id'],request.form.get('current_password',''))
        if removal:submit_removal(g.current_owner['user_id'],tenancy_id,parsed,stamp)
        else:change_tenancy(g.current_owner['user_id'],tenancy_id,parsed,stamp)
    except AdminValidationError as invalid:
        return page(tenancy_id,values=values,errors=invalid.errors,status=invalid.status)
    except TenancyValidationError as invalid:
        return page(tenancy_id,values=values,errors=invalid.errors,status=400)
    except PasswordConfirmationError as invalid:
        return page(tenancy_id,values=values,errors={'current_password':str(invalid)},status=invalid.status)
    except JoinRequestConflict as conflict:
        values['confirm_financial']='' # A changed balance must be explicitly reviewed again.
        return page(tenancy_id,values=values,error=str(conflict),status=409)
    except JoinRequestNotFound: abort(404)
    notice=('Tenant Removal Request sent to Admin. The agreement/reservation stays unchanged until Admin approval; bills and any unpaid balance are preserved.' if removal else
            'Tenancy updated. The previous agreement values and your decision are preserved in history.')
    if modal_request(): return page(tenancy_id,filters=filters,notice=notice)
    flash(notice)
    return redirect(url_for('owner_tenants.details',tenancy_id=tenancy_id,**filters.params()),code=303)
