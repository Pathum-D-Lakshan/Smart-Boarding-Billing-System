"""Approve Owner requests atomically, preserving the agreed rental unit and price."""

from datetime import date, datetime, timezone
from decimal import Decimal
import re

from mysql.connector import Error, errorcode

from db import get_db_connection
import billing_guard
from join_request_service import JoinRequestConflict, JoinRequestNotFound, SRI_LANKA_TIME


class ApprovalValidationError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__("Check the highlighted approval fields.")


def local_today():
    return datetime.now(timezone.utc).astimezone(SRI_LANKA_TIME).date()


def parse_approval(form):
    unit = form.get("unit", "").strip()
    raw_date = form.get("start_date", "").strip()
    errors = {}
    match = re.fullmatch(r"(bed|room):([1-9][0-9]{0,9}):([1-9][0-9]{0,9})", unit)
    if not match or any(int(number) > 4_294_967_295 for number in match.groups()[1:]):
        errors["unit"] = "Choose an available Shared Bed or Private Room."
    try:
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date):
            raise ValueError()
        start = date.fromisoformat(raw_date)
        if start < local_today():
            raise ValueError()
    except ValueError:
        errors["start_date"] = "Choose today or a future Tenancy Start Date."
    if errors:
        raise ApprovalValidationError(errors)
    return {"kind": match[1], "unit_id": int(match[2]), "rate_id": int(match[3]), "start_date": start}


def rental_unit_queries(source, owner_id=None, *, published=False, include_held=False):
    """One availability predicate serves approval, submission and paginated discovery."""
    if owner_id is None and not published:
        raise ValueError('Rental inventory requires an Owner or published-listing scope.')
    queries = []
    start_date = source.get('start_date') or local_today()
    for kind in ("bed", "room"):
        shared = kind == "bed"
        unit_table = "beds unit" if shared else "rooms unit"
        room_join = "JOIN rooms r ON r.room_id = unit.room_id"
        rate_table, rate_key, id_key = ("bed_rent_rates", "bed_rate_id", "bed_id") if shared else ("room_rent_rates", "room_rate_id", "room_id")
        label = "unit.bed_label" if shared else "NULL"
        # Identifiers and query fragments come only from these two fixed branches.
        hold_condition = "t.rent_unit = 'room' OR t.bed_id = unit.bed_id" if shared else "TRUE"
        sql = f"""SELECT '{kind}' AS kind, unit.{id_key} AS unit_id, r.room_id, r.room_number,
            {label} AS bed_label, rate.{rate_key} AS rate_id, rate.monthly_rent, b.boarding_id
            FROM {unit_table} {room_join}
            JOIN boardings b ON b.boarding_id = r.boarding_id
            JOIN {rate_table} rate ON rate.{id_key} = unit.{id_key}
              AND rate.effective_from = (SELECT MAX(h.effective_from) FROM {rate_table} h
                  WHERE h.{id_key} = unit.{id_key} AND h.effective_from <= UTC_TIMESTAMP(6))
            WHERE r.room_type = %s
              AND r.operational_status = 'ready' AND unit.operational_status = 'ready'
              AND r.capacity > 0 AND rate.monthly_rent > 0
              AND (SELECT COUNT(*) FROM beds physical WHERE physical.room_id = r.room_id) <= r.capacity"""
        params = ["shared" if shared else "private"]
        if not include_held:
            sql += f""" AND NOT EXISTS (SELECT 1 FROM tenancies t WHERE t.room_id = r.room_id AND t.tenancy_status = 'open'
                  AND (t.end_date IS NULL OR t.end_date > %s)
                  AND ({hold_condition}))"""
            params.append(start_date)
        if owner_id is not None:
            sql += ' AND b.owner_id=%s'
            params.append(owner_id)
        if source.get('boarding_id') is not None:
            sql += ' AND b.boarding_id=%s'
            params.append(source['boarding_id'])
        if published:
            sql += " AND b.status='published' AND EXISTS (SELECT 1 FROM users owner WHERE owner.user_id=b.owner_id AND owner.role='owner' AND owner.is_active=TRUE)"
        if source.get("preferred_room_id") is not None:
            sql += " AND r.room_id = %s"
            params.append(source["preferred_room_id"])
        if source.get("preferred_room_type") is not None:
            sql += " AND r.room_type = %s"
            params.append(source["preferred_room_type"])
        queries.append((sql, tuple(params)))
    return queries


def available_rental_units(cursor, owner_id, source):
    """Share the same saved-rate and open-hold checks with Student submission."""
    options = []
    for sql, params in rental_unit_queries(source, owner_id):
        cursor.execute(sql + ' ORDER BY r.room_number, unit_id', params)
        for row in cursor.fetchall():
            kind = row['kind']
            shared = kind == 'bed'
            row["token"] = f"{kind}:{row['unit_id']}:{row['rate_id']}"
            row["rent_label"] = f"LKR {row['monthly_rent']:,.2f} / {'bed' if shared else 'room'} / month"
            row["unit_label"] = "Room " + row["room_number"] + (" · Bed " + row["bed_label"] if shared else " · Entire Room")
            options.append(row)
    return options


def load_approval_context(owner_id, request_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute("""SELECT j.boarding_id, j.student_id, j.preferred_room_id, j.preferred_room_type,
            j.intended_start_date, j.status, b.status AS boarding_status, u.role, u.is_active
            FROM join_requests j JOIN boardings b ON b.boarding_id=j.boarding_id
            JOIN users u ON u.user_id=j.student_id WHERE j.request_id=%s AND b.owner_id=%s""", (request_id, owner_id))
        source = cursor.fetchone()
        if source is None:
            raise JoinRequestNotFound()
        blocked = None
        if source["status"] != "requested":
            blocked = "This request has already been decided or cancelled."
        elif source["boarding_status"] != "published":
            blocked = "Publish your boarding before approving this request."
        elif source["role"] != "student" or not source["is_active"]:
            blocked = "Approval requires an active Student account."
        else:
            cursor.execute("SELECT tenancy_id FROM tenancies WHERE held_student_id=%s AND (end_date IS NULL OR end_date>%s) LIMIT 1", (source["student_id"],max(local_today(),source['intended_start_date'])))
            if cursor.fetchone():
                blocked = "This student already has an active or scheduled tenancy."
        source['start_date'] = max(local_today(),source['intended_start_date'])
        options = available_rental_units(cursor, owner_id, source) if not blocked else []
        if not blocked and not options:
            blocked = "No available rental units match this request. Shared rooms need a registered Ready Bed with a current saved rent."
        today = local_today()
        return {"options": options, "blocked": blocked, "today": today.isoformat(),
                "default_start": max(today, source["intended_start_date"]).isoformat()}


def load_owner_tenancy(owner_id, request_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute("""SELECT t.tenancy_id, t.start_date, t.end_date, t.tenancy_status, t.rent_unit,
            t.agreed_monthly_rent, r.room_number, bed.bed_label
            FROM tenancies t JOIN join_requests j ON j.request_id=t.source_request_id
            JOIN boardings b ON b.boarding_id=t.boarding_id AND b.boarding_id=j.boarding_id
            JOIN rooms r ON r.room_id=t.room_id AND r.boarding_id=b.boarding_id
            LEFT JOIN beds bed ON bed.bed_id=t.bed_id AND bed.room_id=r.room_id
            WHERE j.request_id=%s AND b.owner_id=%s AND t.student_id=j.student_id""", (request_id, owner_id))
        tenancy = cursor.fetchone()
        if tenancy:
            tenancy["phase"] = ("Ended" if tenancy["tenancy_status"] == "ended" or tenancy['end_date'] is not None and tenancy['end_date']<=local_today() else
                                "Scheduled" if tenancy["start_date"] > local_today() else "Active agreement")
        return tenancy


def approve_owner_request(owner_id, request_id, form):
    selection = parse_approval(form)
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            # Current reads after locks avoid a stale snapshot when approvals compete.
            connection.start_transaction(isolation_level="READ COMMITTED")
            cursor.execute("""SELECT j.student_id, j.boarding_id FROM join_requests j
                JOIN boardings b ON b.boarding_id=j.boarding_id WHERE j.request_id=%s AND b.owner_id=%s""",
                (request_id, owner_id))
            hint = cursor.fetchone()
            if hint is None:
                raise JoinRequestNotFound()
            # Keep the same Student -> Boarding -> Request -> Room -> Bed order as decisions.
            cursor.execute("SELECT user_id, role, is_active FROM users WHERE user_id=%s FOR UPDATE", (hint["student_id"],))
            student = cursor.fetchone()
            if student is None or student["role"] != "student" or not student["is_active"]:
                raise JoinRequestConflict("Approval requires an active Student account.")
            cursor.execute("SELECT boarding_id, status FROM boardings WHERE boarding_id=%s AND owner_id=%s FOR UPDATE",
                           (hint["boarding_id"], owner_id))
            boarding = cursor.fetchone()
            if boarding is None:
                raise JoinRequestNotFound()
            if boarding["status"] != "published":
                raise JoinRequestConflict("Publish your boarding before approving this request.")
            cursor.execute("""SELECT request_id, status, preferred_room_id, preferred_room_type, requested_at
                FROM join_requests WHERE request_id=%s AND student_id=%s AND boarding_id=%s FOR UPDATE""",
                           (request_id, hint["student_id"], hint["boarding_id"]))
            source = cursor.fetchone()
            if source is None:
                raise JoinRequestNotFound()
            if source["status"] != "requested":
                raise JoinRequestConflict("This request has already been decided or cancelled.")
            # Parent locks serialize inserts; history needs SELECT, not UPDATE grants.
            cursor.execute("SELECT tenancy_id FROM tenancies WHERE held_student_id=%s AND (end_date IS NULL OR end_date>%s) LIMIT 1", (hint["student_id"],selection['start_date']))
            if cursor.fetchone():
                raise JoinRequestConflict("This student already has an active or scheduled tenancy.")
            room_id = selection["unit_id"]
            if selection["kind"] == "bed":
                cursor.execute("""SELECT bed.room_id FROM beds bed JOIN rooms r ON r.room_id=bed.room_id
                    WHERE bed.bed_id=%s AND r.boarding_id=%s""", (selection["unit_id"], hint["boarding_id"]))
                bed_hint = cursor.fetchone()
                if bed_hint is None:
                    raise JoinRequestConflict("The selected Bed is not available in your boarding.")
                room_id = bed_hint["room_id"]
            cursor.execute("SELECT room_id, room_type, capacity, operational_status FROM rooms WHERE room_id=%s AND boarding_id=%s FOR UPDATE",
                           (room_id, hint["boarding_id"]))
            room = cursor.fetchone()
            if room is None:
                raise JoinRequestConflict("The selected Room is not available in your boarding.")
            shared = selection["kind"] == "bed"
            if room["operational_status"] != "ready" or room["room_type"] != ("shared" if shared else "private"):
                raise JoinRequestConflict("Select a Ready Shared Bed or an entire Ready Private Room.")
            if ((source["preferred_room_id"] is not None and source["preferred_room_id"] != room_id)
                    or (source["preferred_room_type"] is not None and source["preferred_room_type"] != room["room_type"])):
                raise JoinRequestConflict("The selected rental unit does not match this student's room preference.")
            if shared:
                cursor.execute("SELECT bed_id, operational_status FROM beds WHERE bed_id=%s AND room_id=%s FOR UPDATE",
                               (selection["unit_id"], room_id))
                bed = cursor.fetchone()
                if bed is None or bed["operational_status"] != "ready":
                    raise JoinRequestConflict("The selected Bed is no longer Ready. Choose another available unit.")
            cursor.execute("SELECT COUNT(*) AS registered FROM beds WHERE room_id=%s", (room_id,))
            registered = cursor.fetchone()["registered"]
            cursor.execute("SELECT tenancy_id, bed_id, rent_unit FROM tenancies WHERE room_id=%s AND tenancy_status='open' AND (end_date IS NULL OR end_date>%s)", (room_id,selection['start_date']))
            holds = cursor.fetchall()
            if (room["capacity"] <= 0 or registered > room["capacity"] or
                    (shared and any(h["rent_unit"] == "room" or h["bed_id"] == selection["unit_id"] for h in holds))
                    or (not shared and holds)):
                raise JoinRequestConflict("This rental unit is already assigned or has no valid capacity. Refresh availability.")
            # A Room lock covers both private holds and its individual Bed holds.
            cursor.execute("SELECT UTC_TIMESTAMP(6) AS decision_time")
            decision_time = cursor.fetchone()["decision_time"]
            if selection["start_date"] < decision_time.replace(tzinfo=timezone.utc).astimezone(SRI_LANKA_TIME).date():
                raise ApprovalValidationError({"start_date": "Choose today or a future Tenancy Start Date."})
            table, key, unit_key = (("bed_rent_rates", "bed_rate_id", "bed_id") if shared else ("room_rent_rates", "room_rate_id", "room_id"))
            cursor.execute(f"SELECT {key} AS rate_id, monthly_rent FROM {table} WHERE {unit_key}=%s AND effective_from<=%s ORDER BY effective_from DESC LIMIT 1",
                           (selection["unit_id"], decision_time))
            rate = cursor.fetchone()
            if rate is None or Decimal(rate["monthly_rent"]) <= 0:
                raise JoinRequestConflict("A current saved rent is required for this rental unit.")
            if rate["rate_id"] != selection["rate_id"]:
                raise JoinRequestConflict("The rent changed. Review the latest monthly rent and confirm again.")
            # Earlier compatible, eligible requests take precedence; no reservation table.
            cursor.execute("""SELECT j.request_id FROM join_requests j JOIN users u ON u.user_id=j.student_id
                WHERE j.boarding_id=%s AND j.status='requested' AND u.role='student' AND u.is_active=TRUE
                AND (j.requested_at<%s OR (j.requested_at=%s AND j.request_id<%s))
                AND (j.preferred_room_id IS NULL OR j.preferred_room_id=%s)
                AND (j.preferred_room_type IS NULL OR j.preferred_room_type=%s)
                AND NOT EXISTS (SELECT 1 FROM tenancies t WHERE t.held_student_id=j.student_id
                    AND (t.end_date IS NULL OR t.end_date>GREATEST(j.intended_start_date,%s)))
                ORDER BY j.requested_at, j.request_id LIMIT 1""",
                (hint["boarding_id"], source["requested_at"], source["requested_at"], request_id, room_id, room["room_type"],local_today()))
            if cursor.fetchone():
                raise JoinRequestConflict("An earlier eligible request matches this Room. Review the oldest matching request first.")
            billing_guard.guard_new_agreement(cursor,hint['boarding_id'],selection['start_date'])
            cursor.execute("""INSERT INTO tenancies (source_request_id, student_id, boarding_id, room_id, bed_id,
                start_date, rent_unit, agreed_monthly_rent, bed_rate_id, room_rate_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (request_id, hint["student_id"], hint["boarding_id"], room_id,
                 selection["unit_id"] if shared else None, selection["start_date"], selection["kind"],
                 rate["monthly_rent"], rate["rate_id"] if shared else None, None if shared else rate["rate_id"]))
            tenancy_id = cursor.lastrowid
            cursor.execute("""UPDATE join_requests SET status='approved', decided_at=%s, decided_by=%s, rejection_reason=NULL
                WHERE request_id=%s AND boarding_id=%s AND student_id=%s AND status='requested'""",
                (decision_time, owner_id, request_id, hint["boarding_id"], hint["student_id"]))
            if cursor.rowcount != 1:
                raise JoinRequestConflict("This request changed. Refresh before trying again.")
            # A failed second write or commit also rolls back the tenancy INSERT.
            connection.commit()
            return tenancy_id
        except Error as database_error:
            connection.rollback()
            if database_error.errno in (errorcode.ER_DUP_ENTRY, 1205, 1213):
                raise JoinRequestConflict("The request or rental unit changed during approval. Refresh availability before trying again.") from None
            raise
        except Exception:
            connection.rollback()
            raise
