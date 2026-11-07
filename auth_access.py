"""Resolve authenticated accounts against their current database state."""

import secrets

from flask import session

from auth_email import password_stamp
from db import get_db_connection


def load_current_account():
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
               WHERE user_id = %s AND is_active = TRUE""",
            (user_id,),
        )
        user = cursor.fetchone()

    stamp = session.get("password_stamp")
    if not user or not isinstance(stamp, str) or not secrets.compare_digest(
        stamp.encode(), password_stamp(user["password_hash"]).encode()
    ):
        session.clear()
        return None
    return user
