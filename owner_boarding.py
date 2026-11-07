"""Owner-scoped boarding profile pages."""

import json
import re

from flask import (
    Blueprint, abort, current_app, flash, g, make_response, redirect, render_template,
    request, send_file, url_for,
)
from mysql.connector import Error, errorcode
from werkzeug.datastructures import MultiDict
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash

from auth_access import load_current_account
from auth_email import normalize_email, valid_email
from boarding_images import InvalidCoverImage, cover_image_path, remove_cover_image, save_cover_image
from db import get_db_connection


owner_boarding = Blueprint("owner_boarding", __name__, url_prefix="/owner/boarding")
FACILITY_OPTIONS = (
    ("Wi-Fi", "📶"), ("Parking", "🚗"), ("Kitchen", "🍳"),
    ("Laundry", "🧺"), ("Study Area", "📚"), ("CCTV", "📹"),
)
FIELD_LIMITS = {
    "boarding_name": 150, "address": 255, "city": 100, "district": 100,
    "contact_phone": 20, "contact_email": 254,
}
FIELD_LABELS = {
    "boarding_name": "Boarding Name", "description": "Description", "address": "Address",
    "city": "City/Town", "district": "District", "contact_phone": "Contact Phone",
    "contact_email": "Contact Email", "house_rules": "House Rules",
}
REQUIRED_FIELDS = ("boarding_name", "description", "address", "city", "district", "contact_phone")
TEXT_BYTE_LIMIT = 65_535
UNCERTAIN_COMMIT_ERRORS = (2006, 2013, 2055)


def validate_boarding_form(form):
    values = {field: form.get(field, "").strip() for field in FIELD_LABELS}
    values["contact_email"] = normalize_email(values["contact_email"])
    errors = {}
    for field in REQUIRED_FIELDS:
        if not values[field]:
            errors[field] = f"Enter {FIELD_LABELS[field]}."
    for field, limit in FIELD_LIMITS.items():
        if len(values[field]) > limit:
            errors[field] = f"Use no more than {limit} characters for {FIELD_LABELS[field]}."
    # MySQL TEXT limits bytes, so multibyte text must be checked after encoding.
    for field in ("description", "house_rules"):
        if len(values[field].encode("utf-8")) > TEXT_BYTE_LIMIT:
            errors[field] = f"{FIELD_LABELS[field]} is too long. Use no more than 65,535 UTF-8 bytes."

    if values["contact_phone"] and "contact_phone" not in errors:
        compact_phone = re.sub(r"[ -]", "", values["contact_phone"])
        if not re.fullmatch(r"(?:0[1-9][0-9]{8}|\+94[1-9][0-9]{8})", compact_phone):
            errors["contact_phone"] = "Enter a Sri Lankan phone number, such as 077 123 4567 or +94 77 123 4567."
        else:
            values["contact_phone"] = "+94" + compact_phone[1:] if compact_phone.startswith("0") else compact_phone
    if values["contact_email"] and "contact_email" not in errors and not valid_email(values["contact_email"]):
        errors["contact_email"] = "Enter a valid email address or leave this field empty."

    selected = form.getlist("facilities")
    allowed = {label for label, emoji in FACILITY_OPTIONS}
    if any(value not in allowed for value in selected):
        errors["facilities"] = "Choose facilities from the available options only."
    values["facilities"] = [label for label, emoji in FACILITY_OPTIONS if label in selected]
    return values, errors


def form_response(*, values=None, errors=None, error=None, status=200,
                  mode="create", boarding_status="draft", has_cover=False):
    return make_response(render_template(
        "owner/boarding_form.html", values=values or {}, errors=errors or {}, error=error,
        owner_name=g.current_owner["full_name"], facility_options=FACILITY_OPTIONS,
        field_limits=FIELD_LIMITS, text_byte_limit=TEXT_BYTE_LIMIT,
        form_mode=mode, boarding_status=boarding_status,
        has_cover=has_cover,
    ), status)


def profile_response(*, boarding=None, error=None, publish_errors=None, status=200):
    return make_response(render_template(
        "owner/boarding_profile.html", boarding=boarding, error=error,
        owner_name=g.current_owner["full_name"] if g.get("current_owner") else "Owner",
        facility_icons=dict(FACILITY_OPTIONS),
        publish_errors=publish_errors or {},
    ), status)


@owner_boarding.before_request
def require_owner():
    try:
        owner = load_current_account()
    except Error as error:
        current_app.logger.error("Owner account database error (%s).", error.errno)
        return profile_response(error="Could not load your boarding profile. Please try again.", status=500)
    if owner is None:
        return redirect(url_for("login"))
    if owner["role"] != "owner":
        abort(403)
    g.current_owner = owner


@owner_boarding.after_request
def prevent_profile_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@owner_boarding.errorhandler(RequestEntityTooLarge)
def cover_request_too_large(error):
    return profile_response(error="The upload is too large. Choose a photo no larger than 5 MB and try again.", status=413)


def find_owner_boarding(owner_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        # The owner comes from the current account, never a browser-supplied ID.
        cursor.execute(
            """SELECT boarding_id, owner_id, boarding_name, description, address, city,
                      district, contact_phone, contact_email, facilities, house_rules,
                      status, created_at, updated_at, cover_image_filename
               FROM boardings WHERE owner_id = %s""",
            (owner_id,),
        )
        boarding = cursor.fetchone()

    if boarding:
        facilities = boarding["facilities"]
        if isinstance(facilities, (str, bytes, bytearray)):
            facilities = json.loads(facilities)
        if not isinstance(facilities, list) or not all(isinstance(item, str) for item in facilities):
            raise ValueError("Invalid saved facilities")
        boarding["facilities"] = facilities
        boarding.setdefault("cover_image_filename", None)
    return boarding


@owner_boarding.get("")
def profile():
    try:
        boarding = find_owner_boarding(g.current_owner["user_id"])
    except Error as error:
        current_app.logger.error("Boarding profile database error (%s).", error.errno)
        return profile_response(error="Could not load your boarding profile. Please try again.", status=500)
    except (ValueError, TypeError):
        current_app.logger.error("Boarding profile contains invalid facilities data.")
        return profile_response(error="Could not load your boarding profile. Please try again.", status=500)
    return profile_response(boarding=boarding)


def insert_owner_boarding(owner_id, values, cover_filename=None):
    with get_db_connection() as connection, connection.cursor() as cursor:
        try:
            cover_column = ", cover_image_filename" if cover_filename else ""
            cover_value = ", %s" if cover_filename else ""
            parameters = (
                owner_id, values["boarding_name"], values["description"], values["address"],
                values["city"], values["district"], values["contact_phone"],
                values["contact_email"] or None, json.dumps(values["facilities"]),
                values["house_rules"] or None,
            )
            if cover_filename:
                parameters += (cover_filename,)
            cursor.execute(
                """INSERT INTO boardings
                   (owner_id, boarding_name, description, address, city, district,
                    contact_phone, contact_email, facilities, house_rules, status""" + cover_column +
                ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft'" + cover_value + ")",
                parameters,
            )
            # Commit only the new Draft; errors must leave existing profiles intact.
            connection.commit()
        except Error:
            connection.rollback()
            raise


def existing_profile_redirect():
    flash("You already have a boarding profile. Your existing profile has been kept.", "error")
    return redirect(url_for("owner_boarding.profile"), code=303)


@owner_boarding.route("/create", methods=["GET", "POST"])
def create():
    values, errors = validate_boarding_form(request.form) if request.method == "POST" else ({}, {})
    new_cover = None
    saved = False
    keep_staged_cover = False
    try:
        owner_id = g.current_owner["user_id"]
        if find_owner_boarding(owner_id):
            return existing_profile_redirect()
        if request.method == "GET":
            return form_response()
        if errors:
            return form_response(values=values, errors=errors, status=400)
        new_cover = save_cover_image(request.files.get("cover_photo"))
        insert_owner_boarding(owner_id, values, new_cover)
        saved = True
    except InvalidCoverImage as error:
        errors["cover_photo"] = str(error)
        return form_response(values=values, errors=errors, status=400)
    except OSError:
        current_app.logger.error("Could not store boarding cover image.")
        return form_response(values=values, errors=errors, error="Could not store your photo. Please try again.", status=500)
    except Error as error:
        # A lost connection may hide a completed commit; keep its image reference usable.
        keep_staged_cover = error.errno in UNCERTAIN_COMMIT_ERRORS
        # UNIQUE(owner_id) also guards two submissions that pass the initial read.
        if error.errno == errorcode.ER_DUP_ENTRY:
            return existing_profile_redirect()
        current_app.logger.error("Create boarding database error (%s).", error.errno)
        return form_response(
            values=values, errors=errors,
            error="Could not save your boarding profile. Please try again.", status=500,
        )
    except (ValueError, TypeError):
        current_app.logger.error("Existing boarding profile contains invalid facilities data.")
        return form_response(values=values, error="Could not load your boarding profile. Please try again.", status=500)
    finally:
        if new_cover and not saved and not keep_staged_cover:
            remove_cover_image(new_cover)

    flash("Boarding saved as Draft!", "success")
    return redirect(url_for("owner_boarding.profile"), code=303)


def update_owner_boarding(owner_id, boarding_id, values, cover_filename=None):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            # Lock the owned row; zero changed rows can simply mean an unchanged form.
            cursor.execute(
                """SELECT boarding_id, cover_image_filename FROM boardings
                   WHERE boarding_id = %s AND owner_id = %s FOR UPDATE""",
                (boarding_id, owner_id),
            )
            locked_boarding = cursor.fetchone()
            if locked_boarding is None:
                connection.rollback()
                return False, None
            cover_assignment = ", cover_image_filename = %s" if cover_filename else ""
            parameters = (
                values["boarding_name"], values["description"], values["address"],
                values["city"], values["district"], values["contact_phone"],
                values["contact_email"] or None, json.dumps(values["facilities"]),
                values["house_rules"] or None,
            )
            if cover_filename:
                parameters += (cover_filename,)
            cursor.execute(
                """UPDATE boardings SET boarding_name = %s, description = %s, address = %s,
                       city = %s, district = %s, contact_phone = %s, contact_email = %s,
                       facilities = %s, house_rules = %s""" + cover_assignment +
                " WHERE boarding_id = %s AND owner_id = %s",
                parameters + (boarding_id, owner_id),
            )
            # MySQL maintains updated_at; created_at, IDs and status stay untouched.
            connection.commit()
            return True, locked_boarding.get("cover_image_filename")
        except Error:
            connection.rollback()
            raise


@owner_boarding.route("/edit", methods=["GET", "POST"])
def edit():
    values, errors = validate_boarding_form(request.form) if request.method == "POST" else ({}, {})
    boarding_status = None
    has_cover = False
    new_cover = None
    saved = False
    keep_staged_cover = False
    try:
        owner_id = g.current_owner["user_id"]
        boarding = find_owner_boarding(owner_id)
        if not boarding:
            flash("Create a boarding profile before editing its details.", "error")
            return redirect(url_for("owner_boarding.profile"), code=303)
        boarding_status = boarding["status"]
        has_cover = bool(boarding.get("cover_image_filename"))
        if request.method == "GET":
            values = {field: boarding[field] or "" for field in FIELD_LABELS}
            values["facilities"] = boarding["facilities"]
            return form_response(values=values, mode="edit", boarding_status=boarding_status, has_cover=has_cover)

        # Read the password separately so it never enters saved or rendered form values.
        current_password = request.form.get("current_password", "")
        if not current_password:
            errors["current_password"] = "Enter your current password to save changes."
        elif len(current_password) > 128 or not check_password_hash(
            g.current_owner["password_hash"], current_password
        ):
            errors["current_password"] = "Your current password is incorrect. Please try again."
        if errors:
            return form_response(values=values, errors=errors, status=400,
                                 mode="edit", boarding_status=boarding_status, has_cover=has_cover)
        new_cover = save_cover_image(request.files.get("cover_photo"))
        saved, previous_cover = update_owner_boarding(owner_id, boarding["boarding_id"], values, new_cover)
        if not saved:
            flash("Your boarding profile is no longer available. Please reload the page.", "error")
            return redirect(url_for("owner_boarding.profile"), code=303)
        if new_cover and previous_cover:
            remove_cover_image(previous_cover)
    except InvalidCoverImage as error:
        errors["cover_photo"] = str(error)
        return form_response(values=values, errors=errors, status=400, mode="edit",
                             boarding_status=boarding_status, has_cover=has_cover)
    except OSError:
        current_app.logger.error("Could not store replacement boarding cover image.")
        return form_response(values=values, errors=errors, mode="edit", boarding_status=boarding_status,
                             has_cover=has_cover, error="Could not store your photo. Please try again.", status=500)
    except Error as error:
        keep_staged_cover = error.errno in UNCERTAIN_COMMIT_ERRORS
        current_app.logger.error("Edit boarding database error (%s).", error.errno)
        return form_response(
            values=values, errors=errors, mode="edit", boarding_status=boarding_status, has_cover=has_cover,
            error="Could not save your boarding changes. Please try again.", status=500,
        )
    except (ValueError, TypeError):
        current_app.logger.error("Could not read saved boarding data for editing.")
        return form_response(
            values=values, mode="edit", boarding_status=boarding_status, has_cover=has_cover,
            error="Could not load your boarding profile. Please try again.", status=500,
        )
    finally:
        if new_cover and not saved and not keep_staged_cover:
            remove_cover_image(new_cover)

    flash("Boarding profile updated successfully.", "success")
    return redirect(url_for("owner_boarding.profile"), code=303)


@owner_boarding.get("/cover")
def cover():
    try:
        boarding = find_owner_boarding(g.current_owner["user_id"])
    except (Error, ValueError, TypeError):
        current_app.logger.error("Could not load boarding cover reference.")
        abort(503)
    path = cover_image_path(boarding.get("cover_image_filename")) if boarding else None
    if path is None or not path.is_file():
        abort(404)
    response = send_file(path, mimetype="image/webp", conditional=False, max_age=0)
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def saved_boarding_errors(boarding):
    form = MultiDict({field: boarding.get(field) or "" for field in FIELD_LABELS})
    facilities = boarding.get("facilities")
    try:
        if isinstance(facilities, (str, bytes, bytearray)):
            facilities = json.loads(facilities)
        if not isinstance(facilities, list) or not all(isinstance(item, str) for item in facilities):
            raise ValueError("Invalid saved facilities")
    except (ValueError, TypeError):
        return {"facilities": "Edit your profile and choose facilities from the available options."}
    form.setlist("facilities", facilities)
    _, errors = validate_boarding_form(form)
    return errors


def update_owner_boarding_status(owner_id, target_status):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            # Validate the saved row under the same lock that protects the status update.
            cursor.execute(
                """SELECT boarding_id, owner_id, boarding_name, description, address, city,
                          district, contact_phone, contact_email, facilities, house_rules,
                          status, created_at, updated_at, cover_image_filename
                   FROM boardings WHERE owner_id = %s FOR UPDATE""",
                (owner_id,),
            )
            boarding = cursor.fetchone()
            if boarding is None:
                connection.rollback()
                return None, {}, False
            errors = saved_boarding_errors(boarding) if target_status == "published" else {}
            if errors or boarding["status"] == target_status:
                connection.rollback()
                return boarding, errors, False
            cursor.execute(
                """UPDATE boardings SET status = %s, updated_at = CURRENT_TIMESTAMP
                   WHERE boarding_id = %s AND owner_id = %s AND status = %s""",
                (target_status, boarding["boarding_id"], owner_id, boarding["status"]),
            )
            connection.commit()
            return boarding, {}, True
        except Error:
            connection.rollback()
            raise


def change_profile_status(target_status):
    try:
        boarding, errors, changed = update_owner_boarding_status(g.current_owner["user_id"], target_status)
    except Error as error:
        current_app.logger.error("Boarding status database error (%s).", error.errno)
        return profile_response(error="Could not change your boarding status. Reload the profile and try again.", status=500)
    if boarding is None:
        flash("Create a boarding profile before changing its status.", "error")
    elif errors:
        # Preserve the stored details; only make facilities safe to render after validation fails.
        facilities = boarding.get("facilities")
        try:
            if isinstance(facilities, (str, bytes, bytearray)):
                facilities = json.loads(facilities)
            boarding["facilities"] = facilities if isinstance(facilities, list) and all(isinstance(item, str) for item in facilities) else []
        except (ValueError, TypeError):
            boarding["facilities"] = []
        return profile_response(boarding=boarding, publish_errors=errors, status=400)
    elif not changed:
        flash("Your boarding is already " + ("Published." if target_status == "published" else "Draft."), "success")
    else:
        flash("Boarding published successfully." if target_status == "published" else "Boarding unpublished. Your profile is now Draft.", "success")
    return redirect(url_for("owner_boarding.profile"), code=303)


@owner_boarding.post("/publish")
def publish():
    return change_profile_status("published")


@owner_boarding.post("/unpublish")
def unpublish():
    return change_profile_status("draft")
