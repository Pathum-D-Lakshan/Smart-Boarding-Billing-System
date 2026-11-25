"""Published boarding discovery and real Student requests on the existing tables."""

from datetime import date
from decimal import Decimal, InvalidOperation
import math
import re

from mysql.connector import Error

from db import get_db_connection
from join_request_service import JoinRequestConflict, JoinRequestNotFound, REQUEST_STATUSES
from listing_data import build_listing
from tenancy_service import available_rental_units, local_today, rental_unit_queries
from owner_boarding import FACILITY_OPTIONS
from admin_security import account_guard, admin_enabled, listing_guard


PAGE_SIZE = 12
PUBLISHED_COLUMNS = """b.boarding_id, b.owner_id, b.boarding_name, b.description,
    b.city, b.district, b.facilities, b.status, b.cover_image_filename"""
PUBLISHED_FROM = """FROM boardings b JOIN users owner ON owner.user_id=b.owner_id
    WHERE b.status='published' AND owner.role='owner' AND owner.is_active=TRUE"""
HISTORY_COLUMNS = """j.request_id, j.boarding_id, b.boarding_name, b.city, b.district,
    j.preferred_room_type, preferred.room_number AS preferred_room_number,
    j.intended_start_date, j.status, j.requested_at, j.decided_at,
    t.tenancy_id, t.start_date, t.end_date, t.tenancy_status, t.rent_unit,
    t.agreed_monthly_rent, assigned.room_number, bed.bed_label"""
HISTORY_FROM = """FROM join_requests j JOIN boardings b ON b.boarding_id=j.boarding_id
    LEFT JOIN rooms preferred ON preferred.room_id=j.preferred_room_id AND preferred.boarding_id=j.boarding_id
    LEFT JOIN tenancies t ON t.source_request_id=j.request_id AND t.student_id=j.student_id
        AND t.boarding_id=j.boarding_id
    LEFT JOIN rooms assigned ON assigned.room_id=t.room_id AND assigned.boarding_id=t.boarding_id
    LEFT JOIN beds bed ON bed.bed_id=t.bed_id AND bed.room_id=t.room_id
    WHERE j.student_id=%s"""


class StudentRequestValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Check the highlighted request fields.")


def parse_page(raw):
    if not isinstance(raw, str) or not re.fullmatch(r"[1-9][0-9]{0,5}", raw):
        raise ValueError("Choose a valid page number.")
    return int(raw)


def parse_submission(form):
    room = form.get("preferred_room_id", "").strip()
    intended = form.get("intended_start_date", "").strip()
    message = form.get("message", "").strip()
    errors = {}
    if room and (not re.fullmatch(r"[1-9][0-9]{0,9}", room) or int(room) > 4_294_967_295):
        errors["preferred_room_id"] = "Choose a room from this boarding's available options."
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", intended):
            raise ValueError()
        start = date.fromisoformat(intended)
        if start < local_today():
            raise ValueError()
    except ValueError:
        errors["intended_start_date"] = "Choose today or a future intended start date."
    if len(message) > 1000 or "\x00" in message:
        errors["message"] = "Use no more than 1,000 characters without null characters."
    if errors:
        raise StudentRequestValidationError(errors)
    return {"room_id": int(room) if room else None, "intended_start_date": start, "message": message or None}


def submission_block(cursor, student_id, from_date=None):
    cursor.execute("SELECT tenancy_id FROM tenancies WHERE held_student_id=%s AND (end_date IS NULL OR end_date>%s) LIMIT 1", (student_id,from_date or local_today()))
    if cursor.fetchone():
        return "You already have an active or scheduled tenancy. You cannot send another join request."
    cursor.execute("SELECT request_id FROM join_requests WHERE pending_student_id=%s", (student_id,))
    if cursor.fetchone():
        return "You already have a pending join request. Check My Join Requests for the Owner's decision."
    return None


def parse_discovery_filters(args):
    """Reject ambiguous inputs before SQL; every search control is server-enforced."""
    values = {key: args.get(key, '').strip() for key in ('location', 'budget', 'room_type', 'sort')}
    facilities = args.getlist('facility') if hasattr(args, 'getlist') else args.get('facility', [])
    if isinstance(facilities, str):
        facilities = [facilities]
    allowed = {name for name, _ in FACILITY_OPTIONS}
    errors = {}
    if len(values['location']) > 150 or any(ord(c) < 32 for c in values['location']):
        errors['location'] = 'Use an area or location of up to 150 characters.'
    if values['room_type'] not in ('', 'shared', 'private'):
        errors['room_type'] = 'Choose All, Shared or Private.'
    if values['sort'] not in ('', 'relevant', 'price_asc', 'price_desc', 'newest'):
        errors['sort'] = 'Choose one of the available sort options.'
    if len(facilities) > len(allowed) or any(item not in allowed for item in facilities):
        errors['facility'] = 'Choose facilities from the supported list.'
    amount = None
    if values['budget']:
        try:
            if not re.fullmatch(r'[0-9]{1,8}(?:\.[0-9]{1,2})?', values['budget']):
                raise ValueError()
            amount = Decimal(values['budget'])
            if not Decimal('0') < amount <= Decimal('99999999.99'):
                raise ValueError()
        except (ValueError, InvalidOperation):
            errors['budget'] = 'Enter a positive budget up to LKR 99,999,999.99, with at most two decimal places.'
    if errors:
        raise StudentRequestValidationError(errors)
    return {**values, 'sort': values['sort'] or 'relevant', 'facilities': list(dict.fromkeys(facilities)), 'amount': amount}


def discovery_query(filters, *, include_address=True):
    # Reuse approval's effective-rate, physical-bed and reservation predicates.
    queries = rental_unit_queries({'start_date': local_today()}, published=True)
    params = [value for _, parameters in queries for value in parameters]
    units = 'SELECT * FROM rental_options WHERE 1=1'
    if filters['room_type']:
        units += ' AND kind=%s'
        params.append('bed' if filters['room_type'] == 'shared' else 'room')
    if filters['amount'] is not None:
        units += ' AND monthly_rent<=%s'
        params.append(filters['amount'])
    sql = 'WITH rental_options AS (' + ' UNION ALL '.join(sql for sql, _ in queries) + '), matching_units AS (' + units + """),
        stock AS (SELECT boarding_id, SUM(kind='bed') AS available_beds, SUM(kind='room') AS available_rooms,
            MIN(CASE WHEN kind='bed' THEN monthly_rent END) AS shared_min,
            MAX(CASE WHEN kind='bed' THEN monthly_rent END) AS shared_max,
            MIN(CASE WHEN kind='room' THEN monthly_rent END) AS private_min,
            MAX(CASE WHEN kind='room' THEN monthly_rent END) AS private_max,
            MIN(monthly_rent) AS starting_rent FROM matching_units GROUP BY boarding_id)
        """
    where = PUBLISHED_FROM + listing_guard() + account_guard("owner")
    if filters['location']:
        columns = ["b.boarding_name", "b.city", "b.district"]
        if include_address:
            columns.append("b.address")
        where += " AND (" + " OR ".join(column + " LIKE %s ESCAPE '!'" for column in columns) + ")"
        needle = '%' + filters['location'].replace('!', '!!').replace('%', '!%').replace('_', '!_') + '%'
        params.extend([needle] * len(columns))
    for facility in filters['facilities']:
        where += ' AND JSON_CONTAINS(b.facilities,JSON_QUOTE(%s))'
        params.append(facility)
    if filters['room_type'] or filters['amount'] is not None:
        where += ' AND EXISTS (SELECT 1 FROM stock s WHERE s.boarding_id=b.boarding_id)'
    # Insert the pre-aggregated stock join before WHERE so pagination happens in MySQL.
    where = where.replace("WHERE b.status=", 'LEFT JOIN stock s ON s.boarding_id=b.boarding_id WHERE b.status=', 1)
    return sql, where, tuple(params)


def load_published_boardings(page, filters=None, *, include_address=True):
    filters = filters or parse_discovery_filters({})
    cte, scope, params = discovery_query(filters, include_address=include_address)
    order = {'relevant': 'b.boarding_name,b.boarding_id', 'price_asc': 's.starting_rent IS NULL,s.starting_rent,b.boarding_id',
             'price_desc': 's.starting_rent IS NULL,s.starting_rent DESC,b.boarding_id', 'newest': 'b.created_at DESC,b.boarding_id DESC'}[filters['sort']]
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        try:
            cursor.execute(cte + 'SELECT COUNT(*) AS total ' + scope, params)
            total = int(cursor.fetchone()["total"])
            pages = max(1, math.ceil(total / PAGE_SIZE))
            page = min(page, pages)
            cursor.execute(cte + 'SELECT ' + PUBLISHED_COLUMNS + ',s.available_beds,s.available_rooms,s.shared_min,s.shared_max,s.private_min,s.private_max,s.starting_rent ' + scope
                           + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s', params + (PAGE_SIZE, (page - 1) * PAGE_SIZE))
            listings = []
            for row in cursor.fetchall():
                rents = [{'room_type': kind, 'monthly_rent': row[kind + '_' + bound]} for kind in ('shared', 'private') for bound in ('min', 'max') if row[kind + '_' + bound] is not None]
                item = build_listing(row, rents)
                item.update(available_beds=int(row['available_beds'] or 0), available_rooms=int(row['available_rooms'] or 0),
                    starting_rent=row['starting_rent'], starting_unit='bed' if row['shared_min'] is not None and row['shared_min'] == row['starting_rent'] else 'entire room')
                listings.append(item)
            return {'listings': listings, 'page': page, 'page_count': pages, 'total': total, 'filters': filters}
        finally:
            connection.rollback()


def group_room_options(options):
    rooms = {}
    for option in options:
        room = rooms.setdefault(option["room_id"], {
            "room_id": option["room_id"], "room_number": option["room_number"],
            "room_type": "shared" if option["kind"] == "bed" else "private", "amounts": [],
        })
        room["amounts"].append(option["monthly_rent"])
    for room in rooms.values():
        room["minimum_rent"], room["maximum_rent"] = min(room["amounts"]), max(room["amounts"])
        room["available_count"] = len(room.pop("amounts"))
    return list(rooms.values())


def load_student_boarding(student_id, boarding_id, from_date=None):
    from_date=from_date or local_today()
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        try:
            cursor.execute("SELECT " + PUBLISHED_COLUMNS + " " + PUBLISHED_FROM + listing_guard()
                           + account_guard("owner") + " AND b.boarding_id=%s", (boarding_id,))
            row = cursor.fetchone()
            if row is None:
                raise JoinRequestNotFound()
            options = available_rental_units(cursor, row["owner_id"], {
                "boarding_id": boarding_id, "preferred_room_id": None, "preferred_room_type": None,
                "start_date":from_date,
            })
            listing = build_listing(row, [{"room_type": "shared" if o["kind"] == "bed" else "private",
                                            "monthly_rent": o["monthly_rent"]} for o in options])
            blocked = submission_block(cursor, student_id, from_date) if student_id is not None else None
            if not blocked and not options:
                blocked = "No Shared Beds or Private Rooms are currently available for a join request. Please check again later."
            return {"listing": listing, "room_options": group_room_options(options), "blocked": blocked}
        finally:
            connection.rollback()


def load_student_cover(boarding_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT b.cover_image_filename " + PUBLISHED_FROM + listing_guard()
                       + account_guard("owner") + " AND b.boarding_id=%s", (boarding_id,))
        row = cursor.fetchone()
        if row is None:
            raise JoinRequestNotFound()
        return row["cover_image_filename"]


def submit_student_request(student_id, boarding_id, form):
    values = parse_submission(form)
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level="READ COMMITTED")
            # The same Student -> Boarding lock order as approval closes submit/approve races.
            cursor.execute("SELECT user_id, role, is_active FROM users WHERE user_id=%s" + account_guard() + " FOR UPDATE", (student_id,))
            account = cursor.fetchone()
            if account is None or account["role"] != "student" or not account["is_active"]:
                raise JoinRequestConflict("An active Student account is required to send a request.")
            blocked = submission_block(cursor, student_id,values['intended_start_date'])
            if blocked:
                raise JoinRequestConflict(blocked)
            moderation_column = ',admin_hidden' if admin_enabled() else ''
            cursor.execute("SELECT boarding_id, owner_id, status" + moderation_column + " FROM boardings WHERE boarding_id=%s FOR UPDATE", (boarding_id,))
            boarding = cursor.fetchone()
            if boarding is None or boarding["status"] != "published" or boarding.get('admin_hidden', False):
                raise JoinRequestNotFound()
            cursor.execute("SELECT user_id FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"
                           + account_guard(), (boarding["owner_id"],))
            if cursor.fetchone() is None:
                raise JoinRequestNotFound()
            options = available_rental_units(cursor, boarding["owner_id"], {
                "boarding_id": boarding_id, "preferred_room_id": values["room_id"], "preferred_room_type": None,
                "start_date": values['intended_start_date'],
            })
            if not options:
                raise JoinRequestConflict("The selected room is no longer available. Refresh and choose an available option.")
            if values["intended_start_date"] < local_today():
                raise StudentRequestValidationError({"intended_start_date": "Choose today or a future intended start date."})
            room_type = ("shared" if options[0]["kind"] == "bed" else "private") if values["room_id"] else None
            # Submission only joins the queue; the Owner decides the unit, final date and rent.
            cursor.execute("""INSERT INTO join_requests (student_id,boarding_id,preferred_room_id,
                preferred_room_type,intended_start_date,message,status,requested_at)
                VALUES (%s,%s,%s,%s,%s,%s,'requested',UTC_TIMESTAMP(6))""",
                (student_id, boarding_id, values["room_id"], room_type, values["intended_start_date"], values["message"]))
            request_id = cursor.lastrowid
            connection.commit()
            return request_id
        except Exception as error:
            connection.rollback()
            if isinstance(error, Error) and error.errno in (1062, 1205, 1213):
                raise JoinRequestConflict("Another request changed your status. Check My Join Requests before trying again.") from None
            raise


def decorate_student_request(row):
    row["status_label"] = REQUEST_STATUSES.get(row["status"], "Unknown")
    row["tenancy_phase"] = ("Ended" if row["tenancy_status"] == "ended" or row.get('end_date') is not None and row['end_date']<=local_today() else
                            "Scheduled" if row["start_date"] and row["start_date"] > local_today() else "Active agreement") if row["tenancy_id"] else None
    return row


def load_student_requests(student_id, page):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        try:
            cursor.execute("SELECT COUNT(*) AS total FROM join_requests WHERE student_id=%s", (student_id,))
            pages = max(1, math.ceil(int(cursor.fetchone()["total"]) / PAGE_SIZE))
            page = min(page, pages)
            cursor.execute("SELECT " + HISTORY_COLUMNS + " " + HISTORY_FROM
                           + " ORDER BY j.requested_at DESC,j.request_id DESC LIMIT %s OFFSET %s",
                           (student_id, PAGE_SIZE, (page - 1) * PAGE_SIZE))
            return {"rows": [decorate_student_request(row) for row in cursor.fetchall()], "page": page, "page_count": pages}
        finally:
            connection.rollback()


def load_student_request(student_id, request_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT " + HISTORY_COLUMNS + ", j.message, j.rejection_reason " + HISTORY_FROM
                       + " AND j.request_id=%s", (student_id, request_id))
        row = cursor.fetchone()
        if row is None:
            raise JoinRequestNotFound()
        return decorate_student_request(row)
