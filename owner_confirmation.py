"""Reusable role-scoped current-password verification with database-backed limits."""

import hashlib
import time

from auth_access import current_password_error
from auth_email import password_stamp
from db import get_db_connection
from admin_security import account_guard


class PasswordConfirmationError(ValueError):
    def __init__(self, message, status=400):
        self.status=status
        super().__init__(message)


def confirm_owner_password(owner_id, password):
    return confirm_account_password(owner_id,password,'owner')


def confirm_student_password(student_id,password):
    return confirm_account_password(student_id,password,'student')


def confirm_account_password(user_id,password,role):
    if role not in ('owner','student','admin'):raise PasswordConfirmationError('Could not confirm your account. Log in again.')
    # Account identity and role, rather than IP/cookie, prevent browser bypass.
    key=hashlib.sha256((role+'-confirm:'+str(user_id)).encode()).hexdigest()
    scope=role+'_confirmation'; now=int(time.time())
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            cursor.execute('''INSERT INTO auth_request_limits(scope,client_key,window_start,hits)
                VALUES(%s,%s,%s,0) ON DUPLICATE KEY UPDATE hits=hits''',(scope,key,now))
            cursor.execute('SELECT window_start,hits FROM auth_request_limits WHERE scope=%s AND client_key=%s FOR UPDATE',(scope,key))
            row=cursor.fetchone(); start,hits=row['window_start'],row['hits']
            if now-start>=900: start,hits=now,0
            if hits>=5:
                connection.rollback()
                raise PasswordConfirmationError('Too many failed confirmations. Wait 15 minutes before trying again.',429)
            cursor.execute("SELECT password_hash FROM users WHERE user_id=%s AND role=%s AND is_active=TRUE"+account_guard(),(user_id,role))
            account=cursor.fetchone()
            failure=current_password_error(account,password) if account else 'Could not confirm your account. Log in again.'
            cursor.execute('UPDATE auth_request_limits SET window_start=%s,hits=%s WHERE scope=%s AND client_key=%s',
                (start,hits+1 if failure else 0,scope,key))
            connection.commit()
            if failure: raise PasswordConfirmationError(failure)
            return password_stamp(account['password_hash'])
        except PasswordConfirmationError:
            raise
        except Exception:
            connection.rollback()
            raise
