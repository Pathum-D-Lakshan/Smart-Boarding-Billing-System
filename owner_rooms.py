"""Owner-scoped room and bed management."""

from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone, timedelta
import re

from flask import Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, request, url_for
from mysql.connector import Error, errorcode

from auth_access import current_password_error, load_current_account
from db import get_db_connection


owner_rooms = Blueprint("owner_rooms", __name__, url_prefix="/owner/rooms")
ROOM_TYPES = ("shared", "private")
ROOM_STATUSES = ("ready", "maintenance")
FLOOR_CHOICES = (
    ("", "Not specified"), ("0", "Ground Floor"), ("1", "1st Floor"),
    ("2", "2nd Floor"), ("3", "3rd Floor"),
) + tuple((str(number), f"{number}th Floor") for number in range(4, 21))
FLOOR_LABELS = dict(FLOOR_CHOICES)
CAPACITY_CHOICES = tuple(str(number) for number in range(1, 21))
ROOM_SELECT = """SELECT r.*,
    EXISTS(SELECT 1 FROM tenancies t WHERE t.room_id = r.room_id AND t.tenancy_status = 'open'
      AND (t.end_date IS NULL OR t.end_date > DATE(CONVERT_TZ(UTC_TIMESTAMP(),'+00:00','+05:30')))) AS has_open_tenancy,
    (SELECT COUNT(*) FROM beds b WHERE b.room_id = r.room_id) AS bed_count,
    (SELECT rr.monthly_rent FROM room_rent_rates rr WHERE rr.room_id = r.room_id
       AND rr.effective_from <= UTC_TIMESTAMP(6)
       ORDER BY rr.effective_from DESC LIMIT 1) AS room_rent
    FROM rooms r JOIN boardings bo ON bo.boarding_id = r.boarding_id
    WHERE bo.owner_id = %s"""
BED_SELECT = """SELECT bed_id, bed_label, operational_status,
    (SELECT rate.monthly_rent FROM bed_rent_rates rate WHERE rate.bed_id=beds.bed_id
     AND rate.effective_from<=UTC_TIMESTAMP(6) ORDER BY rate.effective_from DESC LIMIT 1) AS monthly_rent
    FROM beds WHERE room_id=%s AND bed_id=%s"""


def bed_has_assignment(cursor, room_id, bed_id):
    cursor.execute("""SELECT 1 FROM tenancies WHERE room_id=%s AND tenancy_status='open'
        AND (rent_unit='room' OR bed_id=%s)
        AND (end_date IS NULL OR end_date>DATE(CONVERT_TZ(UTC_TIMESTAMP(),'+00:00','+05:30'))) LIMIT 1""",
        (room_id, bed_id))
    return cursor.fetchone() is not None


class DuplicateRoom(ValueError):
    pass


class BoardingUnavailable(ValueError):
    pass


class RoomUnavailable(ValueError):
    pass


class InvalidRoomEdit(ValueError):
    def __init__(self, field, message):
        self.field, self.message = field, message


@owner_rooms.app_template_filter("room_floor_label")
def room_floor_label(value):
    # Zero is a saved ground floor, not an empty optional value.
    value = "" if value is None else str(value)
    return FLOOR_LABELS.get(value, f"Floor {value}")


def rooms_response(template="owner/rooms_beds.html", *, status=200, **context):
    return make_response(render_template(
        template, owner_name=g.current_owner["full_name"] if g.get("current_owner") else "Owner",
        boarding=g.get("current_boarding"), floor_choices=FLOOR_CHOICES,
        capacity_choices=CAPACITY_CHOICES, **context,
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
                      COALESCE(SUM((SELECT COUNT(*) FROM beds b WHERE b.room_id = r.room_id)), 0) AS total_beds,
                      COALESCE(SUM((SELECT COUNT(*) FROM tenancies t WHERE t.room_id=r.room_id
                        AND t.tenancy_status='open'
                        AND t.start_date<=DATE(CONVERT_TZ(UTC_TIMESTAMP(),'+00:00','+05:30'))
                        AND (t.end_date IS NULL OR t.end_date>DATE(CONVERT_TZ(UTC_TIMESTAMP(),'+00:00','+05:30'))))),0) AS active_tenants
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
    if capacity not in CAPACITY_CHOICES:
        errors["capacity"] = "Choose a Bed Capacity between 1 and 20."
    try:
        values["monthly_rent"] = format(parse_monthly_rent(values["monthly_rent"]), ".2f")
    except InvalidOperation:
        errors["monthly_rent"] = "Enter a positive LKR amount up to 99,999,999.99, with at most 2 decimal places."
    if values["floor"] not in FLOOR_LABELS:
        errors["floor"] = "Choose Not specified, Ground Floor or a floor from 1st to 20th."
    if len(values["description"].encode("utf-8")) > 65535:
        errors["description"] = "Description is too long. Use no more than 65,535 UTF-8 bytes."
    if values["operational_status"] not in ROOM_STATUSES:
        errors["operational_status"] = "Choose Ready or Maintenance."
    return values, errors


def parse_monthly_rent(value):
    if not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,2})?", value):
        raise InvalidOperation
    amount = Decimal(value)
    if amount <= 0:
        raise InvalidOperation
    return amount


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


def find_owned_room(owner_id, room_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute(ROOM_SELECT + " AND r.room_id = %s", (owner_id, room_id))
        return cursor.fetchone()


def update_room(owner_id, room_id, values):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            # Approval and price changes serialize on the same owned Boarding first.
            cursor.execute("SELECT boarding_id FROM boardings WHERE owner_id = %s FOR UPDATE", (owner_id,))
            if cursor.fetchone() is None:
                raise RoomUnavailable
            # Bed registration must lock this same parent before checking capacity.
            cursor.execute(
                """SELECT r.room_id, r.boarding_id, r.room_type FROM rooms r
                   JOIN boardings bo ON bo.boarding_id = r.boarding_id
                   WHERE bo.owner_id = %s AND r.room_id = %s FOR UPDATE""",
                (owner_id, room_id),
            )
            room = cursor.fetchone()
            if room is None:
                raise RoomUnavailable
            cursor.execute("SELECT tenancy_id FROM tenancies WHERE room_id = %s AND tenancy_status = 'open' AND (end_date IS NULL OR end_date>DATE(CONVERT_TZ(UTC_TIMESTAMP(),'+00:00','+05:30'))) LIMIT 1", (room_id,))
            if cursor.fetchone() is not None:
                raise InvalidRoomEdit("room_number", "Room details are locked while a tenant is assigned.")
            cursor.execute("SELECT bed_id FROM beds WHERE room_id = %s FOR UPDATE", (room_id,))
            registered_beds = len(cursor.fetchall())
            changing_type = values["room_type"] != room["room_type"]
            # Existing beds retain their rental unit and individual rent history.
            if changing_type and registered_beds:
                raise InvalidRoomEdit("room_type", "Room Type can only be changed when no beds are registered, including beds under maintenance.")
            if int(values["capacity"]) < registered_beds:
                raise InvalidRoomEdit("capacity", f"Bed Capacity cannot be below {registered_beds} registered beds, including beds under maintenance.")
            cursor.execute(
                "SELECT room_id FROM rooms WHERE boarding_id = %s AND room_number = %s AND room_id <> %s",
                (room["boarding_id"], values["room_number"], room_id),
            )
            if cursor.fetchone() is not None:
                raise DuplicateRoom
            rent = Decimal(values["monthly_rent"])
            if values["room_type"] == "private":
                cursor.execute(
                    """SELECT monthly_rent FROM room_rent_rates WHERE room_id = %s
                       AND effective_from <= UTC_TIMESTAMP(6)
                       ORDER BY effective_from DESC LIMIT 1""", (room_id,),
                )
                previous_rate = cursor.fetchone()
                if changing_type or previous_rate is None or previous_rate["monthly_rent"] != rent:
                    # New prices take effect now; historical rate rows stay unchanged.
                    cursor.execute(
                        """INSERT INTO room_rent_rates (room_id, monthly_rent, effective_from)
                           VALUES (%s, %s, UTC_TIMESTAMP(6))""", (room_id, rent),
                    )
            cursor.execute(
                """UPDATE rooms r JOIN boardings bo ON bo.boarding_id = r.boarding_id
                   SET r.room_number = %s, r.capacity = %s, r.default_bed_rent = %s,
                       r.floor = %s, r.description = %s, r.operational_status = %s, r.room_type = %s,
                       r.updated_at = CURRENT_TIMESTAMP
                   WHERE r.room_id = %s AND bo.owner_id = %s""",
                (values["room_number"], int(values["capacity"]), rent if values["room_type"] == "shared" else None,
                 values["floor"] or None, values["description"] or None, values["operational_status"],
                 values["room_type"], room_id, owner_id),
            )
            connection.commit()
        except (Error, RoomUnavailable, InvalidRoomEdit, DuplicateRoom):
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


@owner_rooms.route("/<int:room_id>/edit", methods=["GET", "POST"])
def edit(room_id):
    values, errors = {}, {}
    room, error, status = None, None, 200
    try:
        room = find_owned_room(g.current_owner["user_id"], room_id)
        if room is None:
            abort(404)
        if request.method == "GET" and room.get("has_open_tenancy"):
            flash("Room details are locked while a tenant is assigned.", "error")
            return redirect(url_for("owner_rooms.details", room_id=room_id), code=303)
        if request.method == "POST":
            values, errors = validate_room_form(request.form)
            password_error = current_password_error(g.current_owner, request.form.get("current_password", ""))
            if password_error:
                errors["current_password"] = password_error
            if errors:
                status = 400
            else:
                try:
                    update_room(g.current_owner["user_id"], room_id, values)
                except InvalidRoomEdit as invalid:
                    errors[invalid.field], status = invalid.message, 409
                except DuplicateRoom:
                    errors["room_number"], status = "This room number already exists in your boarding.", 409
                else:
                    flash("Room changes saved successfully.", "success")
                    return redirect(url_for("owner_rooms.details", room_id=room_id), code=303)
        else:
            values = {name: "" if room[name] is None else str(room[name]) for name in (
                "room_number", "room_type", "capacity", "floor", "description", "operational_status",
            )}
            rent = room["room_rent"] if room["room_type"] == "private" else room["default_bed_rent"]
            values["monthly_rent"] = "" if rent is None else format(rent, ".2f")
    except RoomUnavailable:
        abort(404)
    except Error as database_error:
        if database_error.errno == errorcode.ER_DUP_ENTRY:
            errors["room_number"], status = "This room number already exists in your boarding.", 409
        else:
            current_app.logger.error("Room edit failed (%s).", database_error.errno)
            error, status = "Could not save your room changes. Please try again.", 500
        if room is None:
            return rooms_response(error="Could not load this room. Please try again.", status=500)
    return rooms_response("owner/room_form.html", values=values, errors=errors, error=error,
                          status=status, editing=True, room=room)


def save_bed(owner_id, room_id, bed_id, shown_type, values):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            # Serialize registration, capacity changes and tenancy approval on the owning boarding.
            cursor.execute("SELECT boarding_id FROM boardings WHERE owner_id=%s FOR UPDATE", (owner_id,))
            boarding = cursor.fetchone()
            if not boarding:
                raise RoomUnavailable
            cursor.execute("SELECT room_type, capacity FROM rooms WHERE boarding_id=%s AND room_id=%s FOR UPDATE",
                           (boarding["boarding_id"], room_id))
            room = cursor.fetchone()
            if not room:
                raise RoomUnavailable
            if room["room_type"] != shown_type:
                raise InvalidRoomEdit("bed_label", "The room type changed. Reopen this form before saving.")
            rent = parse_monthly_rent(values["monthly_rent"]) if shown_type == "shared" else None
            if bed_id is None:
                cursor.execute("SELECT COUNT(*) AS registered FROM beds WHERE room_id=%s", (room_id,))
                if cursor.fetchone()["registered"] >= room["capacity"]:
                    raise InvalidRoomEdit("bed_label", "This room has reached its bed capacity.")
                cursor.execute("INSERT INTO beds (room_id, bed_label, operational_status) VALUES (%s,%s,%s)",
                               (room_id, values["bed_label"], values["operational_status"]))
                saved_id, previous_rent = cursor.lastrowid, None
            else:
                cursor.execute(BED_SELECT + " FOR UPDATE", (room_id, bed_id))
                bed = cursor.fetchone()
                if not bed:
                    raise RoomUnavailable
                if bed_has_assignment(cursor, room_id, bed_id):
                    raise InvalidRoomEdit("bed_label", "This bed is locked while a tenant is assigned.")
                cursor.execute("""UPDATE beds SET bed_label=%s, operational_status=%s, updated_at=CURRENT_TIMESTAMP
                    WHERE room_id=%s AND bed_id=%s""",
                    (values["bed_label"], values["operational_status"], room_id, bed_id))
                saved_id, previous_rent = bed_id, bed["monthly_rent"]
            if rent is not None and rent != previous_rent:
                # Append the new offer; existing agreements keep their saved rates.
                cursor.execute("""INSERT INTO bed_rent_rates (bed_id, monthly_rent, effective_from)
                    VALUES (%s,%s,UTC_TIMESTAMP(6))""", (saved_id, rent))
            connection.commit()
        except (Error, RoomUnavailable, InvalidRoomEdit):
            connection.rollback()
            raise


@owner_rooms.route("/<int:room_id>/beds/create", methods=["GET", "POST"], defaults={"bed_id": None})
@owner_rooms.route("/<int:room_id>/beds/<int:bed_id>/edit", methods=["GET", "POST"])
def bed_form(room_id, bed_id):
    owner = g.current_owner
    room, errors, status = None, {}, 200
    try:
        room = find_owned_room(owner["user_id"], room_id)
        if not room:
            abort(404)
        bed = None
        if bed_id is not None:
            with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
                cursor.execute(BED_SELECT, (room_id, bed_id))
                bed = cursor.fetchone()
                if not bed:
                    abort(404)
                if request.method == "GET" and bed_has_assignment(cursor, room_id, bed_id):
                    flash("This bed is locked while a tenant is assigned.", "error")
                    return redirect(url_for("owner_rooms.details", room_id=room_id), code=303)
        values = dict(bed or {"operational_status": "ready", "monthly_rent": room["default_bed_rent"]})
        if request.method == "POST":
            values = {key: request.form.get(key, "").strip() for key in ("bed_label", "operational_status", "monthly_rent")}
            values["bed_label"] = values["bed_label"].upper()
            if not 1 <= len(values["bed_label"]) <= 50 or any(ord(char) < 32 for char in values["bed_label"]):
                errors["bed_label"] = "Enter a bed label up to 50 characters."
            if values["operational_status"] not in ROOM_STATUSES:
                errors["operational_status"] = "Choose Ready or Maintenance."
            if room["room_type"] == "shared":
                try:
                    parse_monthly_rent(values["monthly_rent"])
                except InvalidOperation:
                    errors["monthly_rent"] = "Enter a positive LKR amount up to 99,999,999.99."
            if bed is not None:
                password_error = current_password_error(owner, request.form.get("current_password", ""))
                if password_error:
                    errors["current_password"] = password_error
            if not errors:
                save_bed(owner["user_id"], room_id, bed_id, room["room_type"], values)
                flash("Bed changes saved." if bed_id is not None else "Bed added successfully.", "success")
                return redirect(url_for("owner_rooms.details", room_id=room_id), code=303)
            status = 400
    except RoomUnavailable:
        abort(404)
    except InvalidRoomEdit as invalid:
        errors[invalid.field], status = invalid.message, 409
    except Error as error:
        if error.errno == errorcode.ER_DUP_ENTRY:
            errors["bed_label"], status = "This bed label already exists in this room.", 409
        else:
            current_app.logger.error("Bed management failed (%s).", error.errno)
            return rooms_response(error="Could not save or load this bed. Please try again.", status=500)
    return rooms_response("owner/bed_form.html", room=room, bed=bed, values=values, errors=errors, status=status)


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
            cursor.execute('''SELECT t.tenancy_id,t.student_id,t.rent_unit,t.bed_id,t.start_date,t.end_date,
                u.full_name AS student_name FROM tenancies t JOIN users u ON u.user_id=t.student_id
                JOIN boardings b ON b.boarding_id=t.boarding_id WHERE t.room_id=%s AND b.owner_id=%s
                AND t.tenancy_status='open' AND (t.end_date IS NULL OR t.end_date>DATE(CONVERT_TZ(UTC_TIMESTAMP(),'+00:00','+05:30')))
                ORDER BY t.start_date,t.tenancy_id''',(room_id,g.current_owner['user_id']))
            assignments=cursor.fetchall()
            today=datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=5,minutes=30))).date()
            for assignment in assignments:
                assignment['phase']='Scheduled' if assignment['start_date']>today else 'Active'
    except Error as error:
        current_app.logger.error("Room details failed (%s).", error.errno)
        return rooms_response(error="Could not load this room. Please try again.", status=500)
    return rooms_response("owner/room_details.html", room=room, beds=beds,assignments=assignments,
        active_assignments=[row for row in assignments if row['phase']=='Active'])
