"""Platform Admin routes: UC31, UC32 and UC33 only."""
from flask import Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, request, send_file, session, url_for
from mysql.connector import Error
from auth_access import load_current_account
from admin_security import admin_enabled, reactivation_enabled,tenant_removal_enabled
from tenant_removal_service import list_removals,load_removal,removal_count,decide_removal
from reactivation_service import decide_appeal, list_appeals, load_appeal, pending_count
from admin_service import (AdminConflict, AdminNotFound, AdminValidationError, decide,
                           load_cover, load_record, load_records, load_summary, parse_filters)
from owner_confirmation import PasswordConfirmationError
from join_request_service import JoinRequestConflict

admin_portal = Blueprint('admin_portal', __name__, url_prefix='/admin')


def page(template, status=200, **context):
    context.setdefault('removal_enabled',tenant_removal_enabled())
    context.setdefault('appeals_enabled',reactivation_enabled())
    return make_response(render_template('admin/' + template, admin_name=g.admin_account['full_name'] if g.get('admin_account') else 'Admin', **context), status)


@admin_portal.before_request
def require_admin():
    account = load_current_account()
    if account is None: return redirect(url_for('login'))
    if account['role'] != 'admin': abort(403)
    g.admin_account = account
    if not admin_enabled(): return page('error.html', status=503, error='Admin Portal is awaiting its approved database rollout.')
    if not current_app.config.get('AUTH_SESSION_STORE_ENABLED'):
        return page('error.html', status=503, error='Revocable login sessions must be enabled before Admin decisions are available.')


@admin_portal.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@admin_portal.errorhandler(Error)
def database_error(error):
    current_app.logger.error('Admin operation database error (%s).', error.errno)
    return page('error.html', status=503, error='Could not confirm this operation. Reload the record before trying again.')


@admin_portal.errorhandler(AdminNotFound)
def not_found(error):
    return page('error.html', status=404, error='This record is not available for Admin management.')


@admin_portal.errorhandler(AdminValidationError)
def invalid_filter(error):
    return page('error.html', status=error.status, error=' '.join(error.errors.values()))


@admin_portal.errorhandler(ValueError)
@admin_portal.errorhandler(OSError)
def invalid_saved_data(error):
    current_app.logger.error('Admin view contains invalid or unreadable saved data.')
    return page('error.html', status=503, error='Could not load these details. Please try again.')


@admin_portal.get('')
@admin_portal.get('/dashboard')
def dashboard():
    return page('dashboard.html', data=load_summary(),appeals_enabled=reactivation_enabled(),appeals_pending=pending_count() if reactivation_enabled() else 0,removal_pending=removal_count() if tenant_removal_enabled() else 0)


@admin_portal.get('/users')
def users():
    filters = parse_filters(request.args, 'users')
    return page('records.html', kind='users', filters=filters, data=load_records('users', filters),appeals_enabled=reactivation_enabled(),appeals_pending=pending_count() if reactivation_enabled() else 0)


@admin_portal.get('/listings')
def listings():
    filters = parse_filters(request.args, 'listings')
    return page('records.html', kind='listings', filters=filters, data=load_records('listings', filters))


@admin_portal.get('/reports')
def reports():
    period = request.args.get('period', '6')
    if period not in ('3','6','12'): raise AdminValidationError({'period':'Choose 3, 6 or 12 months.'})
    data = load_summary(int(period))
    data['peak'] = max(1, max(max(row['student'],row['owner']) for row in data['trend']))
    return page('reports.html', data=data)


def record_response(kind, target_id, action='', errors=None, status=200):
    if kind not in ('users','listings'): raise AdminNotFound()
    if action not in (('', 'suspend','reactivate') if kind == 'users' else ('','hide','restore')): raise AdminNotFound()
    dialog = request.headers.get('X-Requested-With') == 'AdminDialog'
    return page('_record.html' if dialog else 'record.html', status=status, kind=kind,
                record=load_record(kind, target_id), action=action, errors=errors or {},
                reason=request.form.get('reason', '')[:500], confirm=request.form.get('confirm') == '1',public_reason_enabled=reactivation_enabled())


@admin_portal.get('/<kind>/<int:target_id>')
def record(kind, target_id):
    return record_response(kind, target_id, request.args.get('action', ''))


@admin_portal.post('/<kind>/<int:target_id>/<action>')
def action(kind, target_id, action):
    if kind not in ('users','listings'): raise AdminNotFound()
    try:
        decide(g.admin_account['user_id'], kind, target_id, action, request.form, session.get('auth_session_token'))
    except AdminValidationError as error:
        return record_response(kind, target_id, action, error.errors, error.status)
    except PasswordConfirmationError as error:
        return record_response(kind, target_id, action, {'current_password':str(error)}, error.status)
    except AdminConflict as error:
        return record_response(kind, target_id, action, {'conflict':str(error)}, 409)
    flash({'suspend':'Account suspended. Existing sessions were revoked.', 'reactivate':'Suspension removed. The user must log in normally.',
           'hide':'Listing hidden from public discovery.', 'restore':'Moderation block removed. Owner publication rules still apply.'}[action], 'success')
    return redirect(url_for('admin_portal.' + ('users' if kind == 'users' else 'listings')), code=303)


@admin_portal.get('/listings/<int:target_id>/cover')
def cover(target_id):
    return send_file(load_cover(target_id), mimetype='image/webp', conditional=False, max_age=0)


@admin_portal.get('/users/reactivation-requests')
def appeals():
    if not reactivation_enabled():abort(404)
    return page('reactivation_requests.html',data=list_appeals(request.args))


def appeal_response(request_id,decision='',errors=None,status=200):
    if decision not in ('','approve','reject'):raise AdminNotFound()
    template='_reactivation_request.html' if request.headers.get('X-Requested-With')=='AdminDialog' else 'reactivation_request.html'
    return page(template,status=status,record=load_appeal(request_id),decision=decision,errors=errors or {},
        decision_note=request.form.get('decision_note','')[:1000],confirm=request.form.get('confirm')=='1')


@admin_portal.get('/users/reactivation-requests/<int:request_id>')
def appeal(request_id):
    if not reactivation_enabled():abort(404)
    return appeal_response(request_id,request.args.get('decision',''))


@admin_portal.post('/users/reactivation-requests/<int:request_id>/<decision>')
def appeal_decision(request_id,decision):
    if not reactivation_enabled():abort(404)
    try:decide_appeal(g.admin_account['user_id'],request_id,decision,request.form,session.get('auth_session_token'))
    except AdminValidationError as error:return appeal_response(request_id,decision,error.errors,error.status)
    except PasswordConfirmationError as error:return appeal_response(request_id,decision,{'current_password':str(error)},error.status)
    except AdminConflict as error:return appeal_response(request_id,decision,{'request':str(error)},409)
    flash('Reactivation Request Approved Successfully' if decision=='approve' else 'Reactivation Request Rejected','success')
    return redirect(url_for('admin_portal.appeals'),code=303)


@admin_portal.get('/users/tenant-removal-requests')
def removals():
    if not tenant_removal_enabled():abort(404)
    return page('tenant_removals.html',data=list_removals(request.args))


def removal_response(request_id,decision='',errors=None,status=200):
    if decision not in ('','approve','reject'):raise AdminNotFound()
    fragment=request.headers.get('X-Requested-With')=='AdminDialog'
    return page('_tenant_removal.html' if fragment else 'tenant_removal.html',status=status,record=load_removal(request_id),decision=decision,
        errors=errors or {},decision_note=request.form.get('decision_note','')[:400])


@admin_portal.get('/users/tenant-removal-requests/<int:request_id>')
def removal(request_id):
    if not tenant_removal_enabled():abort(404)
    return removal_response(request_id,request.args.get('decision',''))


@admin_portal.post('/users/tenant-removal-requests/<int:request_id>/<decision>')
def removal_decision(request_id,decision):
    if not tenant_removal_enabled():abort(404)
    try:decide_removal(g.admin_account['user_id'],request_id,decision,request.form,session.get('auth_session_token'))
    except AdminValidationError as error:return removal_response(request_id,decision,error.errors,error.status)
    except PasswordConfirmationError as error:return removal_response(request_id,decision,{'current_password':str(error)},error.status)
    except (AdminConflict,JoinRequestConflict) as error:return removal_response(request_id,decision,{'request':str(error)},409)
    flash('Removal approved. Agreement ended/reservation cancelled; account, bills and unpaid debt preserved.' if decision=='approve' else 'Removal request rejected. Agreement remains unchanged.','success')
    return redirect(url_for('admin_portal.removals'),code=303)
