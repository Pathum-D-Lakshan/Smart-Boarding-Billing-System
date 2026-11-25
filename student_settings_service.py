"""Student-owned account edits with the existing Settings/password/session policy."""
from contextlib import contextmanager
import secrets
from mysql.connector import Error
from werkzeug.security import check_password_hash,generate_password_hash
from auth_email import _clear_challenge,password_error,password_stamp
from billing_calculator import canonical
from db import get_db_connection
from settings_service import (SettingsConflict,SettingsNotFound,SettingsValidationError,
    required_text,account_values,_check_session)

SECTIONS=('account','security','appearance')


def student_account_values(form):
    name=required_text(form,'full_name',150)
    if not form.get('contact_phone','').strip():return {'full_name':name,'contact_phone':None}
    return account_values(form)


def revision(cursor,student):
    cursor.execute('SELECT COALESCE(MAX(revision),0) AS revision FROM student_settings_events WHERE student_id=%s',(student,))
    return int(cursor.fetchone()['revision'])


def load_student_settings(student):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute("SELECT user_id,full_name,email,contact_phone FROM users WHERE user_id=%s AND role='student' AND is_active=TRUE",(student,))
        account=cursor.fetchone()
        if not account:raise SettingsNotFound()
        return {'account':account,'saved':{'revision':revision(cursor,student)}}


@contextmanager
def _write(student,section,credential,token,expected_revision):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED');reset_email=None
            if section=='security':
                cursor.execute("SELECT email FROM users WHERE user_id=%s AND role='student' AND is_active=TRUE",(student,));hint=cursor.fetchone()
                if not hint:raise SettingsNotFound()
                reset_email=hint['email']
                # Password reset and existing Owner Settings lock challenge -> user.
                cursor.execute("SELECT email FROM auth_email_challenges WHERE purpose='reset' AND email=%s FOR UPDATE",(reset_email,));cursor.fetchone()
            cursor.execute("SELECT user_id,full_name,email,contact_phone,password_hash FROM users WHERE user_id=%s AND role='student' AND is_active=TRUE FOR UPDATE",(student,))
            account=cursor.fetchone()
            if not account:raise SettingsNotFound()
            if not credential or not secrets.compare_digest(password_stamp(account['password_hash']),credential):
                raise SettingsConflict('Your account changed. Verify your current password again.')
            if reset_email is not None and account['email']!=reset_email:raise SettingsConflict('Your account changed. Log in again.')
            _check_session(cursor,student,account,token)
            # A locked users row serializes the audit revision without a second profile table.
            saved_revision=revision(cursor,student)
            if str(saved_revision)!=expected_revision:raise SettingsConflict('Settings changed after opening this form. Reopen the section and review the saved values.')
            yield cursor,account,saved_revision
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise SettingsConflict('Another account update changed. Review your saved values before trying again.') from None
            raise


def _event(cursor,student,saved_revision,kind,before,after):
    cursor.execute('''INSERT INTO student_settings_events(student_id,actor_id,revision,event_type,before_values,after_values,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(student,student,saved_revision+1,kind,
        canonical(before) if before is not None else None,canonical(after)))


def save_student_settings(student,section,form,credential,token):
    if section not in SECTIONS:raise SettingsNotFound()
    with _write(student,section,credential,token,form.get('revision','')) as (cursor,account,saved_revision):
        if section=='account':
            values=student_account_values(form)
            before={key:account[key] for key in ('full_name','contact_phone')}
            if before==values:return
            # Never use browser IDs, email, role or tenancy fields to select an account.
            cursor.execute("UPDATE users SET full_name=%s,contact_phone=%s WHERE user_id=%s AND role='student'",(values['full_name'],values['contact_phone'],student))
            _event(cursor,student,saved_revision,'account_updated',before,values)
        elif section=='security':
            password=form.get('new_password','');error=password_error(password,form.get('confirm_password',''))
            if error:raise SettingsValidationError(error,'new_password')
            if check_password_hash(account['password_hash'],password):raise SettingsValidationError('Choose a different password from your current password.','new_password')
            cursor.execute("UPDATE users SET password_hash=%s WHERE user_id=%s AND role='student'",(generate_password_hash(password),student))
            cursor.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE user_id=%s AND revoked_at IS NULL',(student,))
            _clear_challenge(cursor,'reset',account['email'])
            _event(cursor,student,saved_revision,'password_changed',None,{'all_sessions_revoked':True,'reset_authorizations_retired':True})
        else:
            theme=form.get('theme','')
            if theme not in ('light','dark'):raise SettingsValidationError('Choose Light Mode or Dark Mode.','theme')
            _event(cursor,student,saved_revision,'appearance_saved',None,{'theme':theme,'storage':'existing browser preference'})
