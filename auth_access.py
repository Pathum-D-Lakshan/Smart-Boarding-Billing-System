"""Resolve authenticated accounts against their current database state."""

import secrets

from flask import current_app, session
from werkzeug.security import check_password_hash

from auth_email import password_stamp
from db import get_db_connection
from auth_sessions import login_session_is_valid
from admin_security import account_guard


def current_password_error(account, password):
    """Verify an edit without putting the password into rendered form values."""
    if not password:
        return "Enter your current password to save changes."
    if len(password) > 128 or not check_password_hash(account["password_hash"], password):
        return "Your current password is incorrect. Please try again."
    return None


def load_current_account():
    # A restricted identity never satisfies normal authentication, even after approval.
    if session.get('restricted_account') is not None:
        return None
    user_id = session.get("user_id")
    if user_id is None:
        return None
    if type(user_id) is not int or user_id <= 0:
        session.clear()
        return None

    # Recheck the account so role, activation and password changes take effect.
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute(
            """SELECT user_id, full_name, role, password_hash FROM users
               WHERE user_id = %s AND is_active = TRUE""" + account_guard(),
            (user_id,),
        )
        user = cursor.fetchone()

    stamp = session.get("password_stamp")
    if not user or not isinstance(stamp, str) or not secrets.compare_digest(
        stamp.encode(), password_stamp(user["password_hash"]).encode()
    ):
        session.clear()
        return None
    if current_app.config.get("AUTH_SESSION_STORE_ENABLED") and not login_session_is_valid(session.get("auth_session_token"), user):
        session.clear()
        return None
    return user
