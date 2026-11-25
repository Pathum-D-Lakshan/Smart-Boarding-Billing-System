"""Five-minute, login-bound Settings gate and freshly confirmed Owner saves."""
import hashlib
import secrets
import time
from flask import Blueprint,abort,current_app,flash,g,redirect,render_template,request,session,url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException,NotFound
from auth_access import load_current_account
from auth_email import password_stamp
from owner_confirmation import PasswordConfirmationError,confirm_owner_password
from settings_service import SettingsConflict,SettingsNotFound,SettingsValidationError,load_settings,save_settings

owner_settings=Blueprint('owner_settings',__name__,url_prefix='/owner/settings')
SECTIONS={'account':'Account Settings','security':'Security Settings','bank':'Bank Details','appearance':'Appearance'}
GRANT_SECONDS=300


def binding():
    # Session clear/rotation changes the CSRF/token binding, including legacy logins.
    return hashlib.sha256((str(session.get('auth_session_token',''))+'|'+str(session.get('csrf_token',''))).encode()).hexdigest()


def grant_valid(account,*,key='settings_grant',identity='owner'):
    grant=session.get(key);now=int(time.time())
    return isinstance(grant,dict) and type(grant.get('issued')) is int and 0<=now-grant['issued']<GRANT_SECONDS and grant.get(identity)==account['user_id'] and secrets.compare_digest(str(grant.get('binding','')),binding()) and secrets.compare_digest(str(grant.get('credential','')),password_stamp(account['password_hash']))


@owner_settings.app_context_processor
def available():return {'settings_navigation_enabled':True}


@owner_settings.before_request
def require_owner():
    owner=load_current_account()
    if not owner:return redirect(url_for('login'))
    if owner['role']!='owner':abort(403)
    g.settings_owner=owner
    if request.endpoint not in ('owner_settings.access','owner_settings.unlock') and not grant_valid(owner):
        session.pop('settings_grant',None)
        flash('Verify your current password to access Settings. Access lasts five minutes.')
        return redirect(url_for('owner_settings.access'),code=303)


@owner_settings.after_request
def private(response):
    response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response


def page(section=None,*,errors=None,values=None,status=200):
    data=load_settings(g.settings_owner['user_id']) if section else None
    approved=session.pop('settings_approved_theme',None) if section=='appearance' else None
    return render_template('owner/settings.html',section=section,section_title=SECTIONS.get(section,'Settings'),
        data=data,errors=errors or {},values=values or {},approved_theme=approved,
        owner_name=g.settings_owner['full_name']),status


def failure(message,status):
    return render_template('owner/settings.html',section='error',section_title='Settings',data=None,
        errors={'form':message},values={},owner_name=g.settings_owner['full_name'] if g.get('settings_owner') else 'Owner'),status


@owner_settings.errorhandler(HTTPException)
def http_error(error):return failure({400:'The form expired. Open Settings and try again.',403:'Owner access is required.',404:'This Settings section is unavailable.'}.get(error.code,'This action is unavailable.'),error.code)


@owner_settings.errorhandler(SettingsNotFound)
def missing(error):return http_error(NotFound())


@owner_settings.errorhandler(Error)
def database_error(error):
    current_app.logger.error('Settings operation failed (%s).',error.errno)
    return failure('Could not confirm this operation. Review the saved values or log in again before retrying.',503)


@owner_settings.get('')
def access():
    # Normal sidebar entry always demands fresh verification, even within the TTL.
    session.pop('settings_grant',None);session.pop('settings_approved_theme',None)
    return render_template('owner/settings_access.html',errors={},owner_name=g.settings_owner['full_name'])


@owner_settings.post('/access')
def unlock():
    session.pop('settings_grant',None)
    try:
        credential=confirm_owner_password(g.settings_owner['user_id'],request.form.get('current_password',''))
        if not secrets.compare_digest(credential,password_stamp(g.settings_owner['password_hash'])):raise PasswordConfirmationError('Your login changed. Log in again.')
    except PasswordConfirmationError as invalid:
        return render_template('owner/settings_access.html',errors={'current_password':str(invalid)},owner_name=g.settings_owner['full_name']),invalid.status
    session['settings_grant']={'owner':g.settings_owner['user_id'],'issued':int(time.time()),'binding':binding(),'credential':credential}
    return redirect(url_for('owner_settings.home'),code=303)


@owner_settings.get('/home')
def home():return page()


@owner_settings.get('/<section>')
def section_page(section):
    if section not in SECTIONS:abort(404)
    return page(section)


@owner_settings.post('/<section>')
def save(section):
    if section not in SECTIONS:abort(404)
    values={key:request.form.get(key,'')[:150] for key in ('full_name','contact_phone','bank_name','account_holder','account_number','bank_branch','theme')}
    try:
        credential=confirm_owner_password(g.settings_owner['user_id'],request.form.get('current_password',''))
        save_settings(g.settings_owner['user_id'],section,request.form,credential,session.get('auth_session_token'))
    except (PasswordConfirmationError,SettingsValidationError,SettingsConflict) as invalid:
        return page(section,errors=getattr(invalid,'errors',{'current_password' if isinstance(invalid,PasswordConfirmationError) else 'form':str(invalid)}),values=values,
            status=getattr(invalid,'status',409 if isinstance(invalid,SettingsConflict) else 400))
    if section=='security':
        session.clear();flash('Password updated successfully. Log in again with your new password.')
        return redirect(url_for('login'),code=303)
    if section=='appearance':session['settings_approved_theme']=request.form['theme']
    flash({'account':'Account details saved.','bank':'Bank details saved. Authorized Student payment instructions now use these details.','appearance':'Appearance preference approved.'}[section])
    return redirect(url_for('owner_settings.section_page',section=section),code=303)
