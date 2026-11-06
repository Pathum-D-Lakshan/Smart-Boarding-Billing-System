import os
import re
import secrets
import time

from flask import (
    Flask, abort, flash, jsonify, make_response, redirect, render_template,
    request, session, url_for,
)
from mysql.connector import Error, errorcode
from werkzeug.security import check_password_hash, generate_password_hash

from auth_email import (
    OTP_SECONDS, allow_request, can_change_password, change_password, find_account,
    issue_code, mail_is_configured, normalize_email, password_error, password_stamp,
    reset_request_id, seconds_left, valid_email, verify_code,
)
from db import get_db_connection

# db.py already loads the project's .env file.
app = Flask(__name__)
app.config.update(SECRET_KEY=os.environ["SECRET_KEY"], SESSION_COOKIE_SAMESITE="Lax")

AUTH_POSTS = {
    "login", "logout", "register", "check_email", "verify_email",
    "forgot_password", "reset_password", "new_password",
}
DASHBOARD_TITLES = {
    "student": "Student Dashboard",
    "owner": "Boarding Owner Dashboard",
    "admin": "Admin Dashboard",
}


@app.template_global()
def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


@app.before_request
def check_form_token():
    if request.method == "POST" and request.endpoint in AUTH_POSTS:
        expected = session.get("csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected.encode(), submitted.encode()):
            abort(400, description="Form expired. Open the form and try again.")


def auth_step(mode, title, subtitle="", *, status=200, **context):
    response = make_response(render_template(
        "auth_step.html", mode=mode, title=title, subtitle=subtitle, **context
    ), status)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method != "POST":
        return render_template("login.html")

    email = normalize_email(request.form.get("email", ""))
    password = request.form.get("password", "")

    if not email or not password:
        return render_template("login.html", error="Enter your email and password."), 400

    try:
        user = find_account(email)
    except Error as error:
        app.logger.error("Login database error (%s).", error.errno)
        return render_template("login.html", error="Could not check your login details."), 500

    if not user or not user["is_active"] or not check_password_hash(user["password_hash"], password):
        return render_template("login.html", error="Invalid email or password."), 400

    session.clear()
    session["user_id"] = user["user_id"]
    session["password_stamp"] = password_stamp(user["password_hash"])
    return redirect(url_for("dashboard", role=user["role"]), code=303)


@app.route("/dashboard")
@app.route("/dashboard/<role>")
def dashboard(role=None):
    if "user_id" not in session:
        return redirect(url_for("login"))

    try:
        with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                """SELECT full_name, role, password_hash FROM users
                   WHERE user_id = %s AND is_active = TRUE""",
                (session["user_id"],),
            )
            user = cursor.fetchone()
    except Error as error:
        app.logger.error("Dashboard database error (%s).", error.errno)
        return "Could not load your dashboard.", 500

    if not user or session.get("password_stamp") != password_stamp(user["password_hash"]):
        session.clear()
        return redirect(url_for("login"))
    if role is None:
        return redirect(url_for("dashboard", role=user["role"]))
    if role != user["role"] or role not in DASHBOARD_TITLES:
        abort(403)

    return auth_step("dashboard", DASHBOARD_TITLES[role], f"Welcome, {user['full_name']}.")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"), code=303)


# Registration form and live Gmail check.
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method != "POST":
        return render_template("register.html")

    email = normalize_email(request.form.get("email", ""))
    name = request.form.get("full_name", "").strip()
    role = request.form.get("role", "")
    password = request.form.get("password", "")
    fields = {"email": email, "full_name": name, "role": role}

    if not valid_email(email, gmail_only=True):
        return render_template("register.html", **fields, email_error="Enter a valid @gmail.com address."), 400

    error = password_error(password, request.form.get("confirm_password", ""))
    if role not in ("student", "owner"):
        error = "Choose Student or Boarding Owner."
    elif not 1 <= len(name) <= 150:
        error = "Enter your full name (up to 150 characters)."
    if error:
        return render_template("register.html", **fields, error=error), 400

    try:
        if not allow_request("register", 20, 600):
            return render_template("register.html", **fields, error="Too many requests. Try again later."), 429
        if find_account(email):
            return render_template("register.html", **fields, email_error="That Gmail is already registered."), 409
        if not mail_is_configured():
            return render_template("register.html", **fields, error="Email delivery is not configured."), 503

        pending = issue_code(
            "register", email, full_name=name, role=role,
            password_hash=generate_password_hash(password),
        )
        if not pending:
            previous = session.get("pending_register", {})
            if previous.get("email") == email:
                return redirect(url_for("verify_email"), code=303)
            return render_template("register.html", **fields, error="Wait before requesting another code."), 429
    except Error as error:
        app.logger.error("Registration failed (%s).", error.errno)
        return render_template("register.html", **fields, error="Could not start registration."), 500
    except (OSError, ValueError, KeyError) as error:
        app.logger.error("Registration email failed (%s).", type(error).__name__)
        return render_template("register.html", **fields, error="Could not send the verification code."), 503

    session["pending_register"] = pending
    return redirect(url_for("verify_email"), code=303)


@app.route("/register/check-email", methods=["POST"])
def check_email():
    email = normalize_email(request.form.get("email", ""))

    if not valid_email(email, gmail_only=True):
        return jsonify(error="Enter a valid @gmail.com address."), 400

    try:
        if not allow_request("check-email", 50, 60):
            return jsonify(error="Too many checks. Try again later."), 429
        response = jsonify(registered=bool(find_account(email)))
    except Error as error:
        app.logger.error("Email check failed (%s).", error.errno)
        return jsonify(error="Email check is unavailable."), 503

    response.headers["Cache-Control"] = "no-store"
    return response


# Reset requests use the same public response whether or not an account exists.
def begin_reset(email, previous_id=""):
    request_id = reset_request_id(csrf_token(), email, previous_id)
    user = find_account(email)

    if user and user["is_active"]:
        pending = issue_code("reset", email, user_id=user["user_id"], request_id=request_id)
        if pending:
            return pending

    return {"email": email, "id": request_id, "expires_at": int(time.time()) + OTP_SECONDS}


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    title = "Forgot your password?"
    subtitle = "Enter the email address you registered with."

    if request.method != "POST":
        return auth_step("forgot", title, subtitle)

    email = normalize_email(request.form.get("email", ""))
    if not valid_email(email):
        return auth_step("forgot", title, subtitle, email=email, error="Enter a valid email address.", status=400)
    if not mail_is_configured():
        return auth_step("forgot", title, subtitle, email=email, error="Email delivery is unavailable.", status=503)

    try:
        if not allow_request("reset-request", 10, 600):
            return auth_step("forgot", title, subtitle, email=email, error="Too many requests. Try again later.", status=429)

        grant = session.get("verified_reset")
        if grant and grant["email"] == email and can_change_password(grant):
            return redirect(url_for("new_password"), code=303)

        previous = session.get("pending_reset", {})
        previous_id = ""
        if previous.get("email") == email:
            if seconds_left("reset", previous):
                return redirect(url_for("reset_password"), code=303)
            previous_id = previous.get("id") or ""

        session["pending_reset"] = begin_reset(email, previous_id)
    except Error as error:
        app.logger.error("Password reset request failed (%s).", error.errno)
        return auth_step("forgot", title, subtitle, email=email, error="Could not start password reset.", status=500)

    return redirect(url_for("reset_password"), code=303)


def code_screen(purpose, pending, remaining, *, error=None, status=200):
    if purpose == "register":
        title = "Check your Gmail"
        subtitle = f"Enter the code sent to {pending['email']}."
        endpoint, restart = "verify_email", "register"
    else:
        title = "Verify your reset code"
        subtitle = "If an active account matches that email, we’ll send a code."
        endpoint, restart = "reset_password", "forgot_password"

    return auth_step(
        "code", title, subtitle, endpoint=endpoint, restart=restart,
        remaining=remaining, error=error, status=status,
    )


def handle_code(purpose):
    registering = purpose == "register"
    pending_key = "pending_register" if registering else "pending_reset"
    endpoint = "verify_email" if registering else "reset_password"
    restart = "register" if registering else "forgot_password"
    pending = session.get(pending_key)

    if not pending:
        return redirect(url_for(restart))

    remaining = 0
    try:
        remaining = seconds_left(purpose, pending)
        if request.method != "POST":
            return code_screen(purpose, pending, remaining)

        if request.form.get("action") == "resend":
            # Check time and rate limits again on the server.
            if remaining:
                return code_screen(purpose, pending, remaining, error="Wait for the timer to finish.", status=429)

            scope, limit = ("register", 20) if registering else ("reset-request", 10)
            if not allow_request(scope, limit, 600):
                return code_screen(purpose, pending, 0, error="Too many requests. Try again later.", status=429)
            if not mail_is_configured():
                return code_screen(purpose, pending, 0, error="Email delivery is unavailable.", status=503)

            if registering:
                replacement = issue_code("register", pending["email"], previous_id=pending["id"])
                if not replacement:
                    return code_screen(
                        purpose, pending, 0, error="Could not resend yet. Try later or start again.", status=429
                    )
                flash("A new verification code was sent.")
            else:
                replacement = begin_reset(pending["email"], pending.get("id") or "")

            session[pending_key] = replacement
            return redirect(url_for(endpoint), code=303)

        if not remaining:
            return code_screen(purpose, pending, 0, status=400)

        code = request.form.get("code", "").strip()
        if not re.fullmatch(r"[0-9]{8}", code):
            return code_screen(purpose, pending, remaining, error="Enter the 8-digit code.", status=400)

        scope = "verify-email" if registering else "reset-verify"
        if not allow_request(scope, 25, 600):
            return code_screen(purpose, pending, remaining, error="Too many attempts. Try again later.", status=429)

        result = verify_code(purpose, pending, code)
    except Error as error:
        if registering and error.errno == errorcode.ER_DUP_ENTRY:
            session.pop(pending_key, None)
            flash("That Gmail is already registered. Log in to continue.")
            return redirect(url_for("login"), code=303)

        app.logger.error("Code request failed (%s).", error.errno)
        return code_screen(purpose, pending, remaining, error="Could not process the code. Try again.", status=500)
    except (OSError, ValueError, KeyError) as error:
        app.logger.error("Code delivery failed (%s).", type(error).__name__)
        return code_screen(purpose, pending, remaining, error="Could not send a new code. Try again.", status=503)

    if not result:
        return code_screen(purpose, pending, remaining, error="The code is incorrect, expired, or already used.", status=400)

    session.pop(pending_key, None)

    if registering:
        flash("Gmail verified. Your account is ready. Log in to continue.")
        return redirect(url_for("login"), code=303)

    session["verified_reset"] = {"email": pending["email"], "id": result}
    return redirect(url_for("new_password"), code=303)


@app.route("/register/verify", methods=["GET", "POST"])
def verify_email():
    return handle_code("register")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    return handle_code("reset")


# The new-password page is accessible only after the reset code was verified.
@app.route("/reset-password/new", methods=["GET", "POST"])
def new_password():
    title = "Choose a new password"
    subtitle = "Code verified. Enter your new password."
    grant = session.get("verified_reset")

    if not grant:
        return redirect(url_for("reset_password"))

    try:
        if can_change_password(grant):
            if request.method != "POST":
                return auth_step("new_password", title, subtitle)

            password = request.form.get("password", "")
            error = password_error(password, request.form.get("confirm_password", ""))
            if error:
                return auth_step("new_password", title, subtitle, error=error, status=400)

            if change_password(grant, generate_password_hash(password)):
                session.clear()
                flash("Password changed. Log in with your new password.")
                return redirect(url_for("login"), code=303)
    except Error as error:
        app.logger.error("Password change failed (%s).", error.errno)
        return "Could not change your password. Please try again.", 500

    session.pop("verified_reset", None)
    return auth_step(
        "forgot", "Forgot your password?", "Enter the email address you registered with.",
        error="Your reset session ended. Request a new code.", status=400,
    )