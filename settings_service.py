"""Owner account/bank/password settings with fresh credentials and atomic audit."""
from contextlib import contextmanager
import hashlib
import hmac
import re
import secrets

from flask import current_app,has_app_context
from mysql.connector import Error
from werkzeug.security import check_password_hash,generate_password_hash
from auth_email import _clear_challenge,password_error,password_stamp
from auth_sessions import credential_digest,token_digest
from billing_calculator import canonical
from db import get_db_connection


class SettingsNotFound(LookupError):pass
class SettingsConflict(RuntimeError):pass
class SettingsValidationError(ValueError):
    def __init__(self,message,field='form'):
        super().__init__(message);self.errors={field:message}


def required_text(form,key,limit):
    raw=form.get(key,'')
    if any(ord(c)<32 for c in raw):raise SettingsValidationError('Use one line without control characters.',key)
    value=' '.join(raw.split())
    if not value or len(value)>limit:raise SettingsValidationError(f'Enter {key.replace("_"," ").title()} using 1-{limit} characters.',key)
    return value


def account_values(form):
    name=required_text(form,'full_name',150);phone=form.get('contact_phone','').strip()
    if len(phone)>20:raise SettingsValidationError('Enter a valid Sri Lankan phone number.','contact_phone')
    compact=re.sub(r'[ -]','',phone)
    if re.fullmatch(r'0[1-9][0-9]{8}',compact):compact='+94'+compact[1:]
    elif re.fullmatch(r'[1-9][0-9]{8}',compact):compact='+94'+compact
    if not re.fullmatch(r'[+]94[1-9][0-9]{8}',compact):raise SettingsValidationError('Use 0771234567, 771234567 or +94771234567.','contact_phone')
    return {'full_name':name,'contact_phone':compact}


def bank_values(form,current_number=None):
    values={key:required_text(form,key,limit) for key,limit in (('bank_name',100),('account_holder',150),('bank_branch',100))}
    raw=form.get('account_number','').strip()
    number=re.sub(r'[ -]','',raw) if raw else current_number
    if len(raw)>60 or not number or not re.fullmatch(r'[0-9]{6,34}',number):
        raise SettingsValidationError('Enter a bank account number using 6-34 digits.','account_number')
    return {**values,'account_number':number}


def masked_number(number):return 'Ending '+number[-4:] if number else 'Not configured'


def student_contact_phone(cursor,student):
    """Call only after an Owner-scoped request/tenancy has authorized its Student."""
    if not has_app_context() or not current_app.config.get('STUDENT_SETTINGS_ENABLED'):return None
    cursor.execute("SELECT contact_phone FROM users WHERE user_id=%s AND role='student'",(student,))
    row=cursor.fetchone()
    return row['contact_phone'] if row else None


def _bank_audit(values):
    number=values.get('account_number')
    return {key:values.get(key) for key in ('bank_name','account_holder','bank_branch','bank_boarding_id')}|{
        'account_last4':number[-4:] if number else None,
        'account_fingerprint':hmac.new(current_app.secret_key.encode(),('settings-bank:'+number).encode(),hashlib.sha256).hexdigest() if number else None}


def load_settings(owner):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute("SELECT user_id,full_name,email FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE",(owner,));account=cursor.fetchone()
        if not account:raise SettingsNotFound()
        cursor.execute('SELECT contact_phone,bank_boarding_id,bank_name,account_holder,account_number,bank_branch,revision FROM owner_settings WHERE owner_id=%s',(owner,))
        saved=cursor.fetchone() or dict(contact_phone=None,bank_boarding_id=None,bank_name=None,account_holder=None,account_number=None,bank_branch=None,revision=0)
        # Stored full numbers never enter Settings templates or signed session cookies.
        saved['account_mask']=masked_number(saved.pop('account_number'))
        cursor.execute('SELECT boarding_id,boarding_name FROM boardings WHERE owner_id=%s',(owner,));boarding=cursor.fetchone()
        return {'account':account,'saved':saved,'boarding':boarding}


def _check_session(cursor,owner,account,token):
    if not current_app.config.get('AUTH_SESSION_STORE_ENABLED'):return
    digest=token_digest(token)
    if digest is None:raise SettingsConflict('Your login changed. Log in again before saving settings.')
    cursor.execute('''SELECT user_id FROM auth_sessions WHERE token_digest=%s AND user_id=%s
        AND credential_stamp=%s AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP(6) FOR UPDATE''',
        (digest,owner,credential_digest(account['password_hash'])))
    if not cursor.fetchone():raise SettingsConflict('Your login expired or was revoked. Log in again before saving settings.')


@contextmanager
def _write(owner,section,credential,token,revision):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED')
            boarding=None;reset_email=None
            if section=='bank':
                # Match Boarding -> Owner lock order used by existing Owner modules.
                cursor.execute('SELECT boarding_id FROM boardings WHERE owner_id=%s FOR UPDATE',(owner,));boarding=cursor.fetchone()
                if not boarding:raise SettingsValidationError('Create your Boarding Profile before saving bank details.')
            if section=='security':
                cursor.execute('SELECT email FROM users WHERE user_id=%s',(owner,));hint=cursor.fetchone()
                if not hint:raise SettingsNotFound()
                reset_email=hint['email']
                # Reset already locks challenge -> user; use that order to retire old grants safely.
                cursor.execute("SELECT email FROM auth_email_challenges WHERE purpose='reset' AND email=%s FOR UPDATE",(reset_email,));cursor.fetchone()
            cursor.execute("SELECT user_id,full_name,email,password_hash FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE FOR UPDATE",(owner,));account=cursor.fetchone()
            if not account:raise SettingsNotFound()
            if not credential or not secrets.compare_digest(password_stamp(account['password_hash']),credential):
                raise SettingsConflict('Your account changed. Verify your current password again.')
            if reset_email is not None and account['email']!=reset_email:raise SettingsConflict('Your account changed. Log in again.')
            _check_session(cursor,owner,account,token)
            cursor.execute('SELECT * FROM owner_settings WHERE owner_id=%s FOR UPDATE',(owner,));saved=cursor.fetchone()
            if not saved:
                cursor.execute('INSERT INTO owner_settings(owner_id,created_at,updated_at) VALUES(%s,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))',(owner,))
                cursor.execute('SELECT * FROM owner_settings WHERE owner_id=%s',(owner,));saved=cursor.fetchone()
            if str(saved['revision'])!=revision:raise SettingsConflict('Settings changed after opening this form. Reopen the section and review the saved values.')
            yield cursor,account,saved,boarding
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):raise SettingsConflict('Another settings update changed. Review the saved values before trying again.') from None
            raise


def _event(cursor,owner,revision,kind,before,after):
    cursor.execute('UPDATE owner_settings SET revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE owner_id=%s',(owner,))
    cursor.execute('''INSERT INTO owner_settings_events(owner_id,actor_id,revision,event_type,before_values,after_values,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(owner,owner,revision+1,kind,canonical(before) if before is not None else None,canonical(after)))


def save_settings(owner,section,form,credential,token):
    if section not in ('account','security','bank','appearance'):raise SettingsNotFound()
    with _write(owner,section,credential,token,form.get('revision','')) as (cursor,account,saved,boarding):
        if section=='account':
            values=account_values(form);before={'full_name':account['full_name'],'contact_phone':saved['contact_phone']}
            if before==values:return
            cursor.execute('UPDATE users SET full_name=%s WHERE user_id=%s',(values['full_name'],owner))
            cursor.execute('UPDATE owner_settings SET contact_phone=%s WHERE owner_id=%s',(values['contact_phone'],owner))
            _event(cursor,owner,saved['revision'],'account_updated',before,values)
        elif section=='bank':
            values={**bank_values(form,saved['account_number']),'bank_boarding_id':boarding['boarding_id']}
            if all(saved[key]==value for key,value in values.items()):return
            cursor.execute('''UPDATE owner_settings SET bank_name=%s,account_holder=%s,account_number=%s,bank_branch=%s,bank_boarding_id=%s
                WHERE owner_id=%s''',(values['bank_name'],values['account_holder'],values['account_number'],values['bank_branch'],values['bank_boarding_id'],owner))
            _event(cursor,owner,saved['revision'],'bank_updated',_bank_audit(saved),_bank_audit(values))
        elif section=='security':
            password=form.get('new_password','');error=password_error(password,form.get('confirm_password',''))
            if error:raise SettingsValidationError(error,'new_password')
            if check_password_hash(account['password_hash'],password):raise SettingsValidationError('Choose a different password from your current password.','new_password')
            new_hash=generate_password_hash(password)
            cursor.execute('UPDATE users SET password_hash=%s WHERE user_id=%s',(new_hash,owner))
            cursor.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE user_id=%s AND revoked_at IS NULL',(owner,))
            _clear_challenge(cursor,'reset',account['email'])
            _event(cursor,owner,saved['revision'],'password_changed',None,{'all_sessions_revoked':True,'reset_authorizations_retired':True})
        else:
            theme=form.get('theme','')
            if theme not in ('light','dark'):raise SettingsValidationError('Choose Light Mode or Dark Mode.','theme')
            _event(cursor,owner,saved['revision'],'appearance_saved',None,{'theme':theme,'storage':'existing browser preference'})


def student_bank_instructions(cursor,student,bill_id):
    """Only an owned, payable issued bill can disclose its Boarding's destination."""
    cursor.execute('''SELECT s.bank_name,s.account_holder,s.account_number,s.bank_branch FROM monthly_bills m
        JOIN boardings b ON b.boarding_id=m.boarding_id JOIN owner_settings s
            ON s.owner_id=b.owner_id AND s.bank_boarding_id=b.boarding_id
        WHERE m.bill_id=%s AND m.student_id=%s AND m.state='issued' AND m.final_total>0
        AND s.account_number IS NOT NULL AND NOT EXISTS
            (SELECT 1 FROM payments p WHERE p.bill_id=m.bill_id AND p.status IN ('submitted','verified'))''',(bill_id,student))
    return cursor.fetchone()
