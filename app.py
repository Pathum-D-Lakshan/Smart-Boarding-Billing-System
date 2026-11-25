import os
import re
import secrets
import time
from datetime import timedelta

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
from auth_access import load_current_account
from auth_sessions import SessionCreationConflict, create_login_session, revoke_login_session
from owner_boarding import owner_boarding
from boarding_images import MAX_COVER_BYTES
from owner_rooms import owner_rooms
from owner_listings import owner_listings
from owner_join_requests import owner_join_requests
from owner_dashboard_service import load_owner_dashboard
from student_requests import student_requests
from public_boardings import homepage, public_boardings
from student_portal_service import load_student_dashboard
from owner_tenants import owner_tenants
from owner_bills import owner_bills
from payments import owner_payments,student_payments,payment_documents
from mobile_payments import mobile_payments
from payment_notifications import deliver_pending as deliver_payment_notifications
from owner_finance import owner_finance
from maintenance import owner_maintenance,student_maintenance
from owner_reports import owner_reports
from owner_settings import owner_settings
from student_settings import student_settings
from admin_portal import admin_portal
from admin_provisioning import provision_admin
from account_reactivation import account_reactivation
from bill_delivery import deliver_pending
from admin_security import reactivation_enabled
from reactivation_service import create_restricted_login, decision_notices, local_time
from payment_files import upload_limit
from maintenance_photos import MAX_PHOTO_BYTES,photo_enabled

# db.py already loads the project's .env file.
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ["SECRET_KEY"], SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("APP_ENV") == "production" or os.environ.get("SESSION_COOKIE_SECURE") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7), SESSION_REFRESH_EACH_REQUEST=False,
    AUTH_SESSION_STORE_ENABLED=os.environ.get("AUTH_SESSION_STORE_ENABLED") == "1",
    PAYMENT_MAX_UPLOAD_BYTES=int(os.environ.get('PAYMENT_MAX_UPLOAD_BYTES',5*1024*1024)),
    MAINTENANCE_PHOTOS_ENABLED=os.environ.get('MAINTENANCE_PHOTOS_ENABLED')=='1',
    STUDENT_SETTINGS_ENABLED=os.environ.get('STUDENT_SETTINGS_ENABLED')=='1',
    ADMIN_PORTAL_ENABLED=os.environ.get('ADMIN_PORTAL_ENABLED')=='1',
    TENANT_REMOVAL_REQUESTS_ENABLED=os.environ.get('TENANT_REMOVAL_REQUESTS_ENABLED')=='1',
    ACCOUNT_REACTIVATION_RETRY_ENABLED=os.environ.get('ACCOUNT_REACTIVATION_RETRY_ENABLED')=='1',
    ACCOUNT_REACTIVATION_ENABLED=os.environ.get('ACCOUNT_REACTIVATION_ENABLED')=='1',
    BILLING_REDESIGN_ENABLED=os.environ.get('BILLING_REDESIGN_ENABLED')=='1',
    SHARED_EXPENSE_BILLING_ENABLED=os.environ.get('SHARED_EXPENSE_BILLING_ENABLED')=='1',
    APP_PUBLIC_URL=os.environ.get('APP_PUBLIC_URL','http://127.0.0.1:5000'),
    MOBILE_SLIP_ENABLED=os.environ.get('MOBILE_SLIP_ENABLED')=='1',
    MOBILE_PUBLIC_BASE_URL=os.environ.get('MOBILE_PUBLIC_BASE_URL') or os.environ.get('PUBLIC_BASE_URL') or os.environ.get('APP_PUBLIC_URL',''),
    MOBILE_TRUST_LOCAL_PROXY=os.environ.get('MOBILE_TRUST_LOCAL_PROXY')=='1',
)
app.register_blueprint(owner_boarding)
app.register_blueprint(owner_rooms)
app.register_blueprint(owner_listings)
app.register_blueprint(owner_join_requests)
app.register_blueprint(student_requests)
app.register_blueprint(public_boardings)
app.register_blueprint(owner_tenants)
app.register_blueprint(owner_bills)
app.register_blueprint(owner_payments)
app.register_blueprint(student_payments)
app.register_blueprint(payment_documents)
app.register_blueprint(mobile_payments)
app.register_blueprint(owner_finance)
app.register_blueprint(owner_maintenance)
app.register_blueprint(student_maintenance)
app.register_blueprint(owner_reports)
app.register_blueprint(owner_settings)
app.register_blueprint(student_settings)
app.register_blueprint(admin_portal)
app.cli.add_command(provision_admin)
app.cli.add_command(deliver_pending)
app.cli.add_command(deliver_payment_notifications)
app.register_blueprint(account_reactivation)
app.add_template_filter(local_time,'sri_lanka_time')

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


@app.context_processor
def login_capabilities():
    return {"persistent_login_available": app.config["AUTH_SESSION_STORE_ENABLED"]}


@app.after_request
def prevent_auth_caching(response):
    if request.endpoint in AUTH_POSTS:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.before_request
def check_form_token():
    if request.blueprint in ('owner_finance','owner_maintenance','student_maintenance','owner_settings','student_settings','admin_portal','account_reactivation'):
        request.max_content_length = 64 * 1024
    if request.blueprint=='student_maintenance' and photo_enabled():
        request.max_content_length = MAX_PHOTO_BYTES + 512 * 1024
    if request.blueprint in ('owner_payments','student_payments'):
        request.max_content_length = upload_limit() + 512 * 1024
    if request.blueprint == 'owner_bills':
        request.max_content_length = 256 * 1024
    if request.blueprint == "owner_boarding":
        # Bound multipart parsing before CSRF reads request.form; auth routes keep their limits.
        request.max_content_length = MAX_COVER_BYTES + 1024 * 1024
    if request.method == "POST" and (
        request.endpoint in AUTH_POSTS or request.blueprint in ("owner_boarding", "owner_rooms", "owner_listings", "owner_join_requests", "student_requests", "owner_tenants", "owner_bills", "owner_payments", "student_payments", "owner_finance", "owner_maintenance", "student_maintenance", "owner_settings", "student_settings", "admin_portal", "account_reactivation")
    ):
        expected = session.get("csrf_token", "")
        submitted = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(expected.encode(), submitted.encode()):
            abort(400, description="Form expired. Open the form and try again.")


@app.before_request
def restrict_identity_routes():
    if session.get('restricted_account') is not None and request.endpoint not in {
        'static','login','logout','account_reactivation.dashboard','account_reactivation.submit','account_reactivation.acknowledge_decision'
    }:
        abort(403,description='Restricted account access. Use the Account Access Restricted page or sign in again.')


def auth_step(mode, title, subtitle="", *, status=200, **context):
    response = make_response(render_template(
        "auth_step.html", mode=mode, title=title, subtitle=subtitle, **context
    ), status)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/")
def home():
    response = make_response(homepage())
    response.headers["Cache-Control"] = "no-store"
    return response


def requested_boarding(raw):
    if re.fullmatch(r"[1-9][0-9]{0,9}", raw) and int(raw) <= 4_294_967_295:
        return int(raw)
    return None


@app.route("/login", methods=["GET", "POST"])
def login():
    boarding = requested_boarding(request.values.get("boarding", ""))
    if request.method != "POST":
        return render_template("login.html", boarding=boarding)

    email = normalize_email(request.form.get("email", ""))
    password = request.form.get("password", "")
    remember = request.form.get("remember_me") == "1"

    def invalid_login(message, status=400):
        return render_template("login.html", error=message, email=email, remember_me=remember, boarding=boarding), status

    if not email or not password or len(password) > 128:
        return invalid_login("Enter your email and password.")
    if remember and not app.config["AUTH_SESSION_STORE_ENABLED"]:
        return invalid_login("Keep me signed in is unavailable right now. Sign in without it or try later.", 503)

    try:
        user = find_account(email)
    except Error as error:
        app.logger.error("Login database error (%s).", error.errno)
        return invalid_login("Could not check your login details.", 500)

    if not user or not check_password_hash(user["password_hash"], password):
        return invalid_login("Invalid email or password.")

    restricted=session.get('restricted_account')
    previous_token=session.get('auth_session_token') or (restricted.get('token') if isinstance(restricted,dict) else None)
    if reactivation_enabled() and user.get('admin_suspended') and user['role'] in ('student','owner'):
        try:context=create_restricted_login(user,previous_token)
        except SessionCreationConflict as error:return invalid_login(str(error),409)
        except Error as error:
            app.logger.error('Restricted login database error (%s).',error.errno)
            return invalid_login('Could not open restricted account access. Please try again.',503)
        session.clear();session.permanent=False;session['restricted_account']=context
        return redirect(url_for('account_reactivation.dashboard'),code=303)
    if not user['is_active']:return invalid_login('Invalid email or password.')

    token = None
    if app.config["AUTH_SESSION_STORE_ENABLED"]:
        try:
            token, role = create_login_session(user, remember, previous_token)
            user["role"] = role
        except SessionCreationConflict as conflict:
            return invalid_login(str(conflict))
        except Error as error:
            app.logger.error("Login session creation failed (%s).", error.errno)
            return invalid_login("Could not complete login. Please try again.", 500)

    session.clear()
    session["user_id"] = user["user_id"]
    session["password_stamp"] = password_stamp(user["password_hash"])
    if token is not None:
        session["auth_session_token"] = token
        session.permanent = remember
    if boarding and user["role"] == "student":
        return redirect(url_for("student_requests.boarding", boarding_id=boarding), code=303)
    return redirect(url_for("dashboard", role=user["role"]), code=303)


@app.route("/dashboard")
@app.route("/dashboard/<role>")
def dashboard(role=None):
    if "user_id" not in session:
        return redirect(url_for("login"))

    try:
        user = load_current_account()
    except Error as error:
        app.logger.error("Dashboard database error (%s).", error.errno)
        return "Could not load your dashboard.", 500

    if not user:
        return redirect(url_for("login"))
    if role is None:
        return redirect(url_for("dashboard", role=user["role"]))
    if role != user["role"] or role not in DASHBOARD_TITLES:
        abort(403)
    if role == 'admin':
        return redirect(url_for('admin_portal.dashboard'))
    notices=decision_notices(user['user_id']) if reactivation_enabled() else []

    if role == "owner":
        try:
            data = load_owner_dashboard(user["user_id"])
        except Error as error:
            app.logger.error("Owner dashboard lookup failed (%s).", error.errno)
            data = None
        response = make_response(render_template(
            "owner/dashboard.html", owner_name=user["full_name"], data=data,
            join_requests_pending_count=data["pending"] if data is not None else None,
            account_decisions=notices,
        ), 200 if data is not None else 503)
        response.headers["Cache-Control"] = "no-store"
        return response

    if role == 'student':
        try:
            data = load_student_dashboard(user['user_id'])
        except Error as error:
            app.logger.error('Student dashboard lookup failed (%s).', error.errno)
            data = None
        if data and data['state'] == 'review':
            app.logger.warning('Student dashboard requires agreement review.')
        response = make_response(render_template('student/dashboard.html', student_name=user['full_name'], data=data,account_decisions=notices), 200 if data is not None else 503)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    return auth_step("dashboard", DASHBOARD_TITLES[role], f"Welcome, {user['full_name']}.")


@app.route("/logout", methods=["POST"])
def logout():
    if app.config["AUTH_SESSION_STORE_ENABLED"]:
        try:
            context=session.get('restricted_account')
            revoke_login_session(session.get("auth_session_token") or (context.get('token') if isinstance(context,dict) else None))
        except Error as error:
            app.logger.error("Logout revocation failed (%s).", error.errno)
            return auth_step("logout_error", "Could not sign out", "Please try again to finish signing out.", status=500)
    session.clear()
    return redirect(url_for("login"), code=303)


# Registration form and live Gmail check.
@app.route("/register", methods=["GET", "POST"])
def register():
    boarding = requested_boarding(request.values.get("boarding", ""))
    if request.method != "POST":
        return render_template("register.html", boarding=boarding)

    email = normalize_email(request.form.get("email", ""))
    name = request.form.get("full_name", "").strip()
    role = request.form.get("role", "")
    password = request.form.get("password", "")
    fields = {"email": email, "full_name": name, "role": role, "boarding": boarding}

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
    if boarding and role == "student":
        session["pending_register_boarding"] = boarding
    else:
        session.pop("pending_register_boarding", None)
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
    title = "Forgot Your Password?"
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
        title = "Verify Reset Code"
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
            return redirect(url_for("login", boarding=session.pop("pending_register_boarding", None)), code=303)

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
        return redirect(url_for("login", boarding=session.pop("pending_register_boarding", None)), code=303)

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
    title = "Reset Password"
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
        return auth_step("new_password", title, subtitle, error="Could not change your password. Please try again.", status=500)

    session.pop("verified_reset", None)
    return auth_step(
        "forgot", "Forgot Your Password?", "Enter the email address you registered with.",
        error="Your reset session ended. Request a new code.", status=400,
    )
