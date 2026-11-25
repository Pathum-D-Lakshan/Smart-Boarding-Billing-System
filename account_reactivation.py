"""Suspended accounts receive only restricted identity and appeal/acknowledgement routes."""
from flask import Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, request, session, url_for
from mysql.connector import Error
from auth_access import load_current_account
from admin_security import reactivation_enabled
from admin_service import AdminConflict, AdminNotFound, AdminValidationError
from reactivation_service import RestrictedExpired, acknowledge, restricted_dashboard, submit_appeal

account_reactivation=Blueprint('account_reactivation',__name__,url_prefix='/account')


def restricted_page(status=200,errors=None):
    return make_response(render_template('account/restricted.html',user=g.get('restricted_user'),errors=errors or {},
        message=request.form.get('message','')[:1000]),status)


@account_reactivation.before_request
def require_identity():
    if not reactivation_enabled():abort(404)
    context=session.get('restricted_account')
    if context is not None:
        g.restricted_user=restricted_dashboard(context);g.restricted_context=context
    elif request.endpoint=='account_reactivation.acknowledge_decision':
        user=load_current_account()
        if user is None:return redirect(url_for('login'))
        if user['role'] not in ('owner','student'):abort(403)
        g.normal_account=user
    else:return redirect(url_for('login'))


@account_reactivation.after_request
def no_cache(response):
    response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response


@account_reactivation.errorhandler(RestrictedExpired)
def expired(error):
    session.clear();flash(str(error),'error');return redirect(url_for('login'),code=303)


@account_reactivation.errorhandler(Error)
def db_error(error):
    current_app.logger.error('Account reactivation database error (%s).',error.errno)
    return restricted_page(503,{'request':'Could not confirm this operation. Reload the page before trying again.'})


@account_reactivation.errorhandler(AdminNotFound)
def missing(error):return restricted_page(404,{'request':'This decision is not available for your account.'})


@account_reactivation.get('/restricted')
def dashboard():return restricted_page()


@account_reactivation.post('/reactivation-request')
def submit():
    try:submit_appeal(g.restricted_context,request.form.get('message',''),request.form.get('previous_request_id'))
    except AdminValidationError as error:return restricted_page(error.status,error.errors)
    except AdminConflict as error:
        g.restricted_user=restricted_dashboard(g.restricted_context)
        return restricted_page(409,{'request':str(error)})
    flash('Reactivation Request Submitted Successfully. Your request has been sent to the Platform Administrator for review.','success')
    return redirect(url_for('account_reactivation.dashboard'),code=303)


@account_reactivation.post('/decisions/<int:request_id>/acknowledge')
def acknowledge_decision(request_id):
    user=g.get('restricted_user') or g.normal_account
    acknowledge(user['user_id'],request_id,session.get('auth_session_token'),g.get('restricted_context'))
    return redirect(url_for('account_reactivation.dashboard') if g.get('restricted_context') else url_for('dashboard',role=user['role']),code=303)
