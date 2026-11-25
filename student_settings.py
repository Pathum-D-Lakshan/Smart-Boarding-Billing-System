"""Three Student Settings sections reusing Owner access binding and confirmation."""
import secrets
import time
from flask import Blueprint,abort,current_app,flash,g,redirect,render_template,request,session,url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException,NotFound
from auth_access import load_current_account
from auth_email import password_stamp
from owner_confirmation import PasswordConfirmationError,confirm_student_password
from owner_settings import binding,grant_valid
from settings_service import SettingsConflict,SettingsNotFound,SettingsValidationError
from student_settings_service import load_student_settings,save_student_settings

student_settings=Blueprint('student_settings',__name__,url_prefix='/student/settings')
SECTIONS={'account':'Account Settings','security':'Security Settings','appearance':'Appearance'}
GRANT_KEY='student_settings_grant'
THEME_KEY='student_settings_approved_theme'


@student_settings.app_context_processor
def available():return {'student_settings_navigation_enabled':current_app.config.get('STUDENT_SETTINGS_ENABLED',False)}


def authorized(account):return grant_valid(account,key=GRANT_KEY,identity='student')


@student_settings.before_request
def require_student():
    account=load_current_account()
    if not account:return redirect(url_for('login'))
    if account['role']!='student':abort(403)
    g.settings_student=account
    if not current_app.config.get('STUDENT_SETTINGS_ENABLED',False):return failure('Student Settings is not available yet.',503)
    if request.endpoint not in ('student_settings.access','student_settings.unlock') and not authorized(account):
        session.pop(GRANT_KEY,None);session.pop(THEME_KEY,None)
        flash('Verify your current password to access Settings. Access lasts five minutes.')
        return redirect(url_for('student_settings.access'),code=303)


@student_settings.after_request
def private(response):
    response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response


def page(section=None,*,errors=None,values=None,status=200):
    data=load_student_settings(g.settings_student['user_id']) if section else None
    approved=session.pop(THEME_KEY,None) if section=='appearance' else None
    return render_template('student/settings.html',section=section,section_title=SECTIONS.get(section,'Settings'),data=data,
        errors=errors or {},values=values or {},approved_theme=approved,student_name=g.settings_student['full_name']),status


def failure(message,status):
    return render_template('student/settings.html',section='error',section_title='Settings',data=None,
        errors={'form':message},values={},approved_theme=None,
        student_name=g.settings_student['full_name'] if g.get('settings_student') else 'Student'),status


@student_settings.errorhandler(HTTPException)
def http_error(error):return failure({400:'The form expired. Open Settings and try again.',403:'Student access is required.',404:'This Settings section is unavailable.'}.get(error.code,'This action is unavailable.'),error.code)


@student_settings.errorhandler(SettingsNotFound)
def missing(error):return http_error(NotFound())


@student_settings.errorhandler(Error)
def database_error(error):
    current_app.logger.error('Student Settings operation failed (%s).',error.errno)
    return failure('Could not confirm this operation. Review the saved values or log in again before retrying.',503)


@student_settings.get('')
def access():
    session.pop(GRANT_KEY,None);session.pop(THEME_KEY,None)
    return render_template('student/settings_access.html',errors={},student_name=g.settings_student['full_name'])


@student_settings.post('/access')
def unlock():
    session.pop(GRANT_KEY,None);session.pop(THEME_KEY,None);account=g.settings_student
    try:
        credential=confirm_student_password(account['user_id'],request.form.get('current_password',''))
        if not secrets.compare_digest(credential,password_stamp(account['password_hash'])):raise PasswordConfirmationError('Your login changed. Log in again.')
    except PasswordConfirmationError as invalid:
        return render_template('student/settings_access.html',errors={'current_password':str(invalid)},student_name=account['full_name']),invalid.status
    session[GRANT_KEY]={'student':account['user_id'],'issued':int(time.time()),'binding':binding(),'credential':credential}
    return redirect(url_for('student_settings.home'),code=303)


@student_settings.get('/home')
def home():return page()


@student_settings.get('/<section>')
def section_page(section):
    if section not in SECTIONS:abort(404)
    return page(section)


@student_settings.post('/<section>')
def save(section):
    if section not in SECTIONS:abort(404)
    values={key:request.form.get(key,'')[:150] for key in ('full_name','contact_phone','theme')}
    try:
        credential=confirm_student_password(g.settings_student['user_id'],request.form.get('current_password',''))
        save_student_settings(g.settings_student['user_id'],section,request.form,credential,session.get('auth_session_token'))
    except (PasswordConfirmationError,SettingsValidationError,SettingsConflict) as invalid:
        return page(section,errors=getattr(invalid,'errors',{'current_password' if isinstance(invalid,PasswordConfirmationError) else 'form':str(invalid)}),
            values=values,status=getattr(invalid,'status',409 if isinstance(invalid,SettingsConflict) else 400))
    if section=='security':
        session.clear();flash('Password updated successfully. Log in again with your new password.')
        return redirect(url_for('login'),code=303)
    if section=='appearance':session[THEME_KEY]=request.form['theme']
    flash({'account':'Account details saved.','appearance':'Appearance preference approved.'}[section])
    return redirect(url_for('student_settings.section_page',section=section),code=303)
