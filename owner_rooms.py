"""Owner-scoped room overview, creation and room/bed details."""

from decimal import Decimal, InvalidOperation
import re

from flask import Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, request, url_for
from mysql.connector import Error, errorcode

from auth_access import load_current_account
from db import get_db_connection


owner_rooms = Blueprint("owner_rooms", __name__, url_prefix="/owner/rooms")
ROOM_TYPES = ("shared", "private")
ROOM_STATUSES = ("ready", "maintenance")
ROOM_SELECT = """SELECT r.*,
    (SELECT COUNT(*) FROM beds b WHERE b.room_id = r.room_id) AS bed_count,
    (SELECT rr.monthly_rent FROM room_rent_rates rr WHERE rr.room_id = r.room_id
       AND rr.effective_from <= UTC_TIMESTAMP(6)
       ORDER BY rr.effective_from DESC LIMIT 1) AS room_rent
    FROM rooms r JOIN boardings bo ON bo.boarding_id = r.boarding_id
    WHERE bo.owner_id = %s"""


class DuplicateRoom(ValueError):
    pass


class BoardingUnavailable(ValueError):
    pass


def rooms_response(template="owner/rooms_beds.html", *, status=200, **context):
    return make_response(render_template(
        template, owner_name=g.current_owner["full_name"] if g.get("current_owner") else "Owner",
        boarding=g.get("current_boarding"), **context,
    ), status)


@owner_rooms.before_request
def require_room_owner():
    try:
        owner = load_current_account()
        if owner is None:
            return redirect(url_for("login"))
        if owner["role"] != "owner":
            abort(403)
        g.current_owner = owner
        with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
            cursor.execute(
                "SELECT boarding_id, boarding_name, status FROM boardings WHERE owner_id = %s",
                (owner["user_id"],),
            )
            g.current_boarding = cursor.fetchone()
    except Error as error:
        current_app.logger.error("Rooms account lookup failed (%s).", error.errno)
        return rooms_response(error="Could not load your rooms. Please try again.", status=500)


@owner_rooms.after_request
def prevent_rooms_caching(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def get_room_summary(owner_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        # Count beds per room first so joins cannot multiply the summary totals.
        cursor.execute(
            """SELECT COUNT(*) AS total_rooms,
                      COALESCE(SUM(r.room_type = 'shared'), 0) AS shared_rooms,
                      COALESCE(SUM(r.room_type = 'private'), 0) AS private_rooms,
                      COALESCE(SUM((SELECT COUNT(*) FROM beds b WHERE b.room_id = r.room_id)), 0) AS total_beds
               FROM rooms r JOIN boardings bo ON bo.boarding_id = r.boarding_id
               WHERE bo.owner_id = %s""",
            (owner_id,),
        )
        return cursor.fetchone()


def find_rooms(owner_id, search="", room_type=""):
    query, parameters = ROOM_SELECT, [owner_id]
    if search:
        pattern = "%" + search.replace("=", "==").replace("%", "=%").replace("_", "=_") + "%"
        query += " AND r.room_number LIKE %s ESCAPE '='"
        parameters.append(pattern)
    if room_type:
        query += " AND r.room_type = %s"
        parameters.append(room_type)
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute(query + " ORDER BY r.room_number, r.room_id", tuple(parameters))
        return cursor.fetchall()


@owner_rooms.get("")
def overview():
    search = request.args.get("q", "").strip()
    room_type = request.args.get("room_type", "")
    filter_error = None
    if len(search) > 50:
        filter_error = "Use no more than 50 characters for your room search."
    elif room_type and room_type not in ROOM_TYPES:
        filter_error = "Choose Shared, Private or All Room Types."
    if filter_error:
        return rooms_response(error=filter_error, search=search[:50], room_type="", status=400)
    try:
        summary = get_room_summary(g.current_owner["user_id"])
        rooms = find_rooms(g.current_owner["user_id"], search, room_type) if g.current_boarding else []
    except Error as error:
        current_app.logger.error("Rooms overview failed (%s).", error.errno)
        return rooms_response(error="Could not load your rooms. Please try again.", status=500)
    return rooms_response(summary=summary, rooms=rooms, search=search, room_type=room_type)


def validate_room_form(form):
    values = {name: form.get(name, "").strip() for name in (
        "room_number", "room_type", "capacity", "monthly_rent", "floor", "description", "operational_status",
    )}
    values["room_number"] = values["room_number"].upper()
    errors = {}
    if not 1 <= len(values["room_number"]) <= 50:
        errors["room_number"] = "Enter a Room Number / Name up to 50 characters."
    if values["room_type"] not in ROOM_TYPES:
        errors["room_type"] = "Choose Shared or Private."
    capacity = values["capacity"]
    if not re.fullmatch(r"[1-9][0-9]{0,4}", capacity) or int(capacity) > 65535:
        errors["capacity"] = "Enter a whole-number capacity between 1 and 65,535."
    try:
        rent = Decimal(values["monthly_rent"])
        if not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,2})?", values["monthly_rent"]) or not rent.is_finite() or not Decimal("0") < rent <= Decimal("99999999.99"):
            raise InvalidOperation
        values["monthly_rent"] = format(rent, ".2f")
    except InvalidOperation:
        errors["monthly_rent"] = "Enter a positive LKR amount up to 99,999,999.99, with at most 2 decimal places."
    if len(values["floor"]) > 50:
        errors["floor"] = "Use no more than 50 characters for Floor."
    if len(values["description"].encode("utf-8")) > 65535:
        errors["description"] = "Description is too long. Use no more than 65,535 UTF-8 bytes."
    if values["operational_status"] not in ROOM_STATUSES:
        errors["operational_status"] = "Choose Ready or Maintenance."
    return values, errors


def insert_room(owner_id, boarding_id, values):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            # Serialize room creation under the owned boarding, including duplicate checks.
            cursor.execute(
                "SELECT boarding_id FROM boardings WHERE boarding_id = %s AND owner_id = %s FOR UPDATE",
                (boarding_id, owner_id),
            )
            if cursor.fetchone() is None:
                raise BoardingUnavailable
            cursor.execute("SELECT room_id FROM rooms WHERE boarding_id = %s AND room_number = %s", (boarding_id, values["room_number"]))
            if cursor.fetchone() is not None:
                raise DuplicateRoom
            rent = Decimal(values["monthly_rent"])
            cursor.execute(
                """INSERT INTO rooms (boarding_id, room_number, room_type, capacity, default_bed_rent,
                                      floor, description, operational_status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (boarding_id, values["room_number"], values["room_type"], int(values["capacity"]),
                 rent if values["room_type"] == "shared" else None, values["floor"] or None,
                 values["description"] or None, values["operational_status"]),
            )
            room_id = cursor.lastrowid
            if values["room_type"] == "private":
                # A private room is one rental unit; its physical beds have no separate rent.
                cursor.execute(
                    """INSERT INTO room_rent_rates (room_id, monthly_rent, effective_from)
                       VALUES (%s, %s, UTC_TIMESTAMP(6))""", (room_id, rent),
                )
            connection.commit()
            return room_id
        except (Error, DuplicateRoom, BoardingUnavailable):
            connection.rollback()
            raise


@owner_rooms.route("/create", methods=["GET", "POST"])
def create():
    if not g.current_boarding:
        flash("Create your Boarding Profile before adding rooms.", "error")
        return redirect(url_for("owner_rooms.overview"), code=303)
    values = {"room_type": "shared", "operational_status": "ready"}
    errors, error, status = {}, None, 200
    if request.method == "POST":
        values, errors = validate_room_form(request.form)
        if errors:
            status = 400
        else:
            try:
                room_id = insert_room(g.current_owner["user_id"], g.current_boarding["boarding_id"], values)
            except BoardingUnavailable:
                flash("Your boarding is no longer available. Please reload the page.", "error")
                return redirect(url_for("owner_rooms.overview"), code=303)
            except DuplicateRoom:
                errors["room_number"], status = "This room number already exists in your boarding.", 409
            except Error as database_error:
                if database_error.errno == errorcode.ER_DUP_ENTRY:
                    errors["room_number"], status = "This room number already exists in your boarding.", 409
                else:
                    current_app.logger.error("Room creation failed (%s).", database_error.errno)
                    error, status = "Could not save your room. Please try again.", 500
            else:
                flash("Room saved successfully.", "success")
                return redirect(url_for("owner_rooms.details", room_id=room_id), code=303)
    return rooms_response("owner/room_form.html", values=values, errors=errors, error=error, status=status)


@owner_rooms.get("/<int:room_id>")
def details(room_id):
    try:
        with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
            cursor.execute(ROOM_SELECT + " AND r.room_id = %s", (g.current_owner["user_id"], room_id))
            room = cursor.fetchone()
            if room is None:
                abort(404)
            cursor.execute(
                """SELECT b.bed_id, b.bed_label, b.operational_status, b.created_at, b.updated_at,
                          CASE WHEN r.room_type = 'shared' THEN
                            (SELECT br.monthly_rent FROM bed_rent_rates br WHERE br.bed_id = b.bed_id
                              AND br.effective_from <= UTC_TIMESTAMP(6)
                              ORDER BY br.effective_from DESC LIMIT 1)
                          ELSE NULL END AS monthly_rent
                   FROM beds b JOIN rooms r ON r.room_id = b.room_id
                   JOIN boardings bo ON bo.boarding_id = r.boarding_id
                   WHERE b.room_id = %s AND bo.owner_id = %s ORDER BY b.bed_label, b.bed_id""",
                (room_id, g.current_owner["user_id"]),
            )
            beds = cursor.fetchall()
    except Error as error:
        current_app.logger.error("Room details failed (%s).", error.errno)
        return rooms_response(error="Could not load this room. Please try again.", status=500)
    return rooms_response("owner/room_details.html", room=room, beds=beds)
