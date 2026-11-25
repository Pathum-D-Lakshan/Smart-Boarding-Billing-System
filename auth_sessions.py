"""Revocable login sessions; activate only after the approved additive migration."""

from datetime import timedelta
import hashlib
import re
import secrets

from auth_email import password_stamp
from db import get_db_connection
from admin_security import admin_enabled, normal_scope_guard


NORMAL_LIFETIME = timedelta(hours=8)
REMEMBER_LIFETIME = timedelta(days=7)
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


class SessionCreationConflict(ValueError):
    pass


def token_digest(token):
    if not isinstance(token, str) or not TOKEN_PATTERN.fullmatch(token):
        return None
    return hashlib.sha256(token.encode("ascii")).digest()


def credential_digest(password_hash):
    return hashlib.sha256(password_stamp(password_hash).encode("ascii")).digest()


def create_login_session(account, remember, previous_token=None):
    token = secrets.token_urlsafe(32)
    lifetime = REMEMBER_LIFETIME if remember else NORMAL_LIFETIME
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction()
            # Recheck credentials under a lock so a racing reset cannot create a new session.
            active = '(is_active AND NOT admin_suspended) AS is_active' if admin_enabled() else 'is_active'
            cursor.execute("SELECT user_id,role,password_hash," + active + " FROM users WHERE user_id=%s FOR UPDATE", (account["user_id"],))
            current = cursor.fetchone()
            if (not current or not current["is_active"] or current["role"] not in ("owner", "student", "admin")
                    or not secrets.compare_digest(current["password_hash"].encode(), account["password_hash"].encode())):
                raise SessionCreationConflict("Your account changed. Please log in again.")
            old_digest = token_digest(previous_token)
            if old_digest is not None:
                cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE token_digest=%s AND revoked_at IS NULL", (old_digest,))
            cursor.execute("SELECT UTC_TIMESTAMP(6) AS created_at")
            created = cursor.fetchone()["created_at"]
            cursor.execute("""INSERT INTO auth_sessions
                (token_digest,user_id,credential_stamp,remember_me,created_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s)""",
                (token_digest(token), current["user_id"], credential_digest(current["password_hash"]),
                 bool(remember), created, created+lifetime))
            # New token and previous-token revocation succeed together.
            connection.commit()
            return token, current["role"]
        except Exception:
            connection.rollback()
            raise


def login_session_is_valid(token, account):
    digest = token_digest(token)
    if digest is None:
        return False
    with get_db_connection() as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT user_id FROM auth_sessions WHERE token_digest=%s
            AND user_id=%s AND credential_stamp=%s AND revoked_at IS NULL
            AND expires_at > UTC_TIMESTAMP(6)""" + normal_scope_guard(),
            (digest, account["user_id"], credential_digest(account["password_hash"])))
        return cursor.fetchone() is not None


def revoke_login_session(token):
    digest = token_digest(token)
    if digest is None:
        return
    with get_db_connection() as connection, connection.cursor() as cursor:
        try:
            connection.start_transaction()
            cursor.execute("UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE token_digest=%s AND revoked_at IS NULL", (digest,))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
