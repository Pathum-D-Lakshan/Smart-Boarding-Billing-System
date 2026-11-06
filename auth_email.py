"""One-time codes, mail delivery, and password reset authorization."""

import hashlib
import hmac
import os
import re
import secrets
import smtplib
import ssl
import string
import time
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from threading import BoundedSemaphore

from flask import current_app, request

from db import get_db_connection

OTP_SECONDS = 60
RESET_FORM_SECONDS = 300
MAX_CODE_ATTEMPTS = 5
MAX_SENDS_PER_HOUR = 5
HOUR = 3600

GMAIL = re.compile(r"[a-z0-9]+(?:\.[a-z0-9]+)*(?:\+[a-z0-9._-]+)?@gmail\.com")
EMAIL = re.compile(r"[a-z0-9.!#$%&'*+/=?^_\x60{}|~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+")
mail_workers = ThreadPoolExecutor(max_workers=2, thread_name_prefix="reset-email")
mail_slots = BoundedSemaphore(12)


def normalize_email(value):
    return value.strip().lower()


def valid_email(email, *, gmail_only=False):
    pattern = GMAIL if gmail_only else EMAIL
    return len(email) <= 254 and bool(pattern.fullmatch(email))


def password_error(password, confirmation):
    if not 8 <= len(password) <= 128:
        return "Use a password between 8 and 128 characters."
    if not any(character in string.punctuation for character in password):
        return "Add a symbol like !, @ or #."
    if password != confirmation:
        return "Passwords do not match."
    return None


def _signature(label, value):
    key = current_app.secret_key.encode()
    return hmac.new(key, f"{label}:{value}".encode(), hashlib.sha256).hexdigest()


def reset_request_id(form_token, email, previous_id):
    # Two submissions from the same reset form share the same request ID.
    return _signature("reset-request", f"{form_token}:{email}:{previous_id}")[:32]


def password_stamp(password_hash):
    return _signature("login", password_hash)


def find_account(email):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute(
            "SELECT user_id, role, password_hash, is_active FROM users WHERE email = %s",
            (email,),
        )
        return cursor.fetchone()


def allow_request(scope, limit, seconds):
    """Share request limits across Flask requests and processes."""
    now = int(time.time())
    client = _signature("rate-limit", request.remote_addr or "unknown")

    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute(
            """INSERT INTO auth_request_limits (scope, client_key, window_start, hits)
               VALUES (%s, %s, %s, 0) ON DUPLICATE KEY UPDATE hits = hits""",
            (scope, client, now),
        )
        cursor.execute(
            """SELECT window_start, hits FROM auth_request_limits
               WHERE scope = %s AND client_key = %s FOR UPDATE""",
            (scope, client),
        )
        row = cursor.fetchone()
        start, hits = row["window_start"], row["hits"]

        if now - start >= seconds:
            start, hits = now, 0
        if hits >= limit:
            return False

        cursor.execute(
            """UPDATE auth_request_limits SET window_start = %s, hits = %s
               WHERE scope = %s AND client_key = %s""",
            (start, hits + 1, scope, client),
        )
        connection.commit()

    return True


def mail_is_configured():
    return all(os.getenv(name, "").strip() for name in (
        "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM",
    ))


def send_code(email, code, purpose):
    # Read the SMTP settings already saved in .env.
    host = os.environ["SMTP_HOST"]
    port = int(os.getenv("SMTP_PORT", "587"))
    password = "".join(os.environ["SMTP_PASSWORD"].split())
    action = "verify your email" if purpose == "register" else "reset your password"

    message = EmailMessage()
    message["From"] = os.environ["SMTP_FROM"]
    message["To"] = email
    message["Subject"] = "Smart Boarding & Billing System verification code"
    message.set_content(
        f"Your code to {action} is {code}.\n\n"
        "This code expires in 1 minute and can be used once."
    )

    tls = ssl.create_default_context()
    if port == 465:
        client = smtplib.SMTP_SSL(host, port, context=tls, timeout=10)
    else:
        client = smtplib.SMTP(host, port, timeout=10)

    with client as smtp:
        if port != 465:
            smtp.starttls(context=tls)
        smtp.login(os.environ["SMTP_USER"], password)
        smtp.send_message(message)


def _queue_reset_code(email, code, expires_at):
    # Keep the public reset response independent of SMTP delivery time.
    logger = current_app.logger
    if not mail_slots.acquire(blocking=False):
        logger.warning("Password reset email queue is full.")
        return

    def deliver():
        try:
            if time.time() < expires_at:
                send_code(email, code, "reset")
        except (OSError, ValueError, KeyError) as error:
            logger.error("Reset email delivery failed (%s).", type(error).__name__)
        finally:
            mail_slots.release()

    try:
        mail_workers.submit(deliver)
    except RuntimeError:
        mail_slots.release()
        logger.warning("Password reset email worker is unavailable.")


def _otp_deadline(row):
    # Apply the one-minute limit to codes issued before this update too.
    return min(row["expires_at"], row["last_sent_at"] + OTP_SECONDS)


def seconds_left(purpose, pending):
    deadline = pending.get("expires_at")

    if deadline is None and pending.get("id"):
        # Older browser sessions only stored the email and challenge ID.
        with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """SELECT expires_at, last_sent_at FROM auth_email_challenges
                   WHERE purpose = %s AND email = %s AND challenge_id = %s
                     AND code_digest IS NOT NULL""",
                (purpose, pending["email"], pending["id"]),
            )
            row = cursor.fetchone()

        deadline = _otp_deadline(row) if row else 0

    return max(0, (deadline or 0) - int(time.time()))


def issue_code(purpose, email, *, full_name=None, role=None, password_hash=None,
               user_id=None, previous_id=None, request_id=None):
    """Issue a code. A registration resend reuses the saved signup details."""
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        if previous_id is None:
            cursor.execute(
                """INSERT INTO auth_email_challenges (purpose, email, send_window_start)
                   VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE sends_in_window = sends_in_window""",
                (purpose, email, int(time.time())),
            )

        cursor.execute(
            """SELECT challenge_id, code_digest, expires_at, last_sent_at, send_window_start,
                      sends_in_window, pending_name, pending_role, pending_password_hash
               FROM auth_email_challenges WHERE purpose = %s AND email = %s FOR UPDATE""",
            (purpose, email),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        if previous_id is not None:
            if row["challenge_id"] != previous_id or row["code_digest"] is None:
                return None
            full_name = row["pending_name"]
            role = row["pending_role"]
            password_hash = row["pending_password_hash"]

        now = int(time.time())

        if request_id and row["challenge_id"] == request_id and row["code_digest"]:
            deadline = _otp_deadline(row)
            if deadline > now:
                return {"email": email, "id": request_id, "expires_at": deadline}

        if now < row["last_sent_at"] + OTP_SECONDS:
            return None

        if purpose == "reset" and row["challenge_id"] and row["code_digest"] is None:
            if row["expires_at"] > now:
                return None

        start, sends = row["send_window_start"], row["sends_in_window"]
        if now - start >= HOUR:
            start, sends = now, 0
        if sends >= MAX_SENDS_PER_HOUR:
            return None

        challenge_id = request_id or secrets.token_hex(16)
        code = f"{secrets.randbelow(100_000_000):08d}"
        digest = _signature("email-code", f"{purpose}:{email}:{challenge_id}:{code}")

        if purpose == "register":
            # If SMTP fails, closing this transaction preserves the previous challenge.
            send_code(email, code, purpose)

        sent_at = int(time.time())
        expires_at = sent_at + OTP_SECONDS
        cursor.execute(
            """UPDATE auth_email_challenges
               SET challenge_id = %s, code_digest = %s, expires_at = %s, attempts = 0,
                   last_sent_at = %s, send_window_start = %s, sends_in_window = %s,
                   pending_name = %s, pending_role = %s, pending_password_hash = %s,
                   reset_user_id = %s
               WHERE purpose = %s AND email = %s""",
            (challenge_id, digest, expires_at, sent_at, start, sends + 1,
             full_name, role, password_hash, user_id, purpose, email),
        )
        connection.commit()

    if purpose == "reset":
        _queue_reset_code(email, code, expires_at)

    return {"email": email, "id": challenge_id, "expires_at": expires_at}


def _clear_challenge(cursor, purpose, email):
    # Keep the delivery counters while removing the one-time authorization.
    cursor.execute(
        """UPDATE auth_email_challenges
           SET challenge_id = NULL, code_digest = NULL, expires_at = 0,
               pending_name = NULL, pending_role = NULL, pending_password_hash = NULL,
               reset_user_id = NULL
           WHERE purpose = %s AND email = %s""",
        (purpose, email),
    )


def verify_code(purpose, pending, code):
    """Create the account or exchange a valid reset code for a one-use grant."""
    email, challenge_id = pending["email"], pending.get("id")
    if not challenge_id:
        return None

    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute(
            """SELECT code_digest, expires_at, last_sent_at, attempts, pending_name,
                      pending_role, pending_password_hash, reset_user_id
               FROM auth_email_challenges
               WHERE purpose = %s AND email = %s AND challenge_id = %s FOR UPDATE""",
            (purpose, email, challenge_id),
        )
        row = cursor.fetchone()
        now = int(time.time())

        if row is None or row["code_digest"] is None or _otp_deadline(row) <= now:
            return None
        if row["attempts"] >= MAX_CODE_ATTEMPTS:
            return None

        digest = _signature("email-code", f"{purpose}:{email}:{challenge_id}:{code}")
        if not hmac.compare_digest(row["code_digest"], digest):
            cursor.execute(
                """UPDATE auth_email_challenges SET attempts = attempts + 1
                   WHERE purpose = %s AND email = %s""",
                (purpose, email),
            )
            connection.commit()
            return None

        if purpose == "register":
            cursor.execute(
                """INSERT INTO users (full_name, email, role, password_hash)
                   VALUES (%s, %s, %s, %s)""",
                (row["pending_name"], email, row["pending_role"], row["pending_password_hash"]),
            )
            _clear_challenge(cursor, purpose, email)
        else:
            if row["reset_user_id"] is None:
                return None

            # Retire the OTP and issue a separate grant for the new-password form.
            challenge_id = secrets.token_hex(16)
            cursor.execute(
                """UPDATE auth_email_challenges
                   SET challenge_id = %s, code_digest = NULL, expires_at = %s
                   WHERE purpose = 'reset' AND email = %s""",
                (challenge_id, now + RESET_FORM_SECONDS, email),
            )

        connection.commit()

    return challenge_id


def _reset_grant(cursor, grant, *, lock=False):
    query = """SELECT reset_user_id, expires_at FROM auth_email_challenges
               WHERE purpose = 'reset' AND email = %s AND challenge_id = %s
                 AND code_digest IS NULL AND reset_user_id IS NOT NULL"""

    if lock:
        query += " FOR UPDATE"

    cursor.execute(query, (grant["email"], grant["id"]))
    row = cursor.fetchone()

    if row and row["expires_at"] > int(time.time()):
        return row

    return None


def can_change_password(grant):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        return _reset_grant(cursor, grant) is not None


def change_password(grant, password_hash):
    """Consume the grant in the same transaction that changes the password."""
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        row = _reset_grant(cursor, grant, lock=True)
        if row is None:
            return False

        cursor.execute(
            """UPDATE users SET password_hash = %s
               WHERE user_id = %s AND email = %s AND is_active = TRUE""",
            (password_hash, row["reset_user_id"], grant["email"]),
        )
        changed = cursor.rowcount == 1
        _clear_challenge(cursor, "reset", grant["email"])
        connection.commit()

    return changed