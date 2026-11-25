"""Owner-scoped request reads and transactional decisions, shared with future UI."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math

from db import get_db_connection
from settings_service import student_contact_phone


REQUEST_STATUSES = {"requested": "Pending", "approved": "Approved", "rejected": "Rejected", "cancelled": "Cancelled"}
SORT_ORDERS = {"newest": "j.requested_at DESC, j.request_id DESC", "oldest": "j.requested_at ASC, j.request_id ASC"}
PAGE_SIZE = 10
SRI_LANKA_TIME = timezone(timedelta(hours=5, minutes=30))
SUMMARY_SQL = """SELECT COUNT(*) AS total,
    COALESCE(SUM(j.status = 'requested'), 0) AS pending,
    COALESCE(SUM(j.status = 'approved'), 0) AS approved,
    COALESCE(SUM(j.status = 'rejected'), 0) AS rejected,
    COALESCE(SUM(j.status = 'cancelled'), 0) AS cancelled
    FROM join_requests j JOIN boardings b ON b.boarding_id = j.boarding_id
    WHERE b.owner_id = %s"""
REQUEST_COLUMNS = """j.request_id, j.student_id, j.boarding_id, j.preferred_room_type,
    j.intended_start_date, j.status, j.requested_at, j.decided_at,
    u.full_name AS student_name, u.is_active AS student_active,
    b.boarding_name, b.status AS boarding_status, r.room_number AS preferred_room_number"""
REQUEST_JOINS = """FROM join_requests j
    JOIN boardings b ON b.boarding_id = j.boarding_id
    JOIN users u ON u.user_id = j.student_id
    LEFT JOIN rooms r ON r.room_id = j.preferred_room_id AND r.boarding_id = b.boarding_id"""


class JoinRequestValidationError(ValueError):
    pass


class JoinRequestNotFound(LookupError):
    pass


class JoinRequestConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class RequestFilters:
    search: str = ""
    status: str = ""
    sort: str = "newest"
    page: int = 1

    @classmethod
    def parse(cls, data):
        search = data.get("q", "").strip()
        status = data.get("status", "").strip()
        sort = data.get("sort", "newest")
        raw_page = data.get("page", "1")
        if len(search) > 150 or "\x00" in search:
            raise JoinRequestValidationError("Use no more than 150 characters to search for a student.")
        if status and status not in REQUEST_STATUSES:
            raise JoinRequestValidationError("Choose a request status from the list.")
        if sort not in SORT_ORDERS:
            raise JoinRequestValidationError("Choose Newest First or Oldest First.")
        if not isinstance(raw_page, str) or not raw_page.isascii() or not raw_page.isdecimal() or not 1 <= len(raw_page) <= 7:
            raise JoinRequestValidationError("Choose a valid page number.")
        page = int(raw_page)
        if not 1 <= page <= 1_000_000:
            raise JoinRequestValidationError("Choose a valid page number.")
        return cls(search, status, sort, page)

    def params(self, *, page=None):
        return {"q": self.search, "status": self.status, "sort": self.sort, "page": page or self.page}


def local_request_time(value):
    if not isinstance(value, datetime):
        return "Not available"
    return value.replace(tzinfo=timezone.utc).astimezone(SRI_LANKA_TIME).strftime("%d %b %Y · %I:%M %p")


def decorate_request(row):
    row["status_label"] = REQUEST_STATUSES.get(row["status"], "Unknown")
    parts = row["student_name"].split()
    row["initials"] = "".join(part[0] for part in (parts[:1] + parts[-1:] if len(parts) > 1 else parts)).upper() or "?"
    kind = row.get("preferred_room_type")
    number = row.get("preferred_room_number")
    row["preference"] = ("Room " + number + " · " + kind.capitalize()) if number and kind else (
        kind.capitalize() + " room" if kind else "Any suitable room")
    return row


def get_join_request_summary(owner_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute(SUMMARY_SQL, (owner_id,))
        return {key: int(value) for key, value in cursor.fetchone().items()}


def load_owner_requests(owner_id, filters, selected_id=None):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute("SELECT boarding_id, boarding_name, status FROM boardings WHERE owner_id = %s", (owner_id,))
        boarding = cursor.fetchone()
        cursor.execute(SUMMARY_SQL, (owner_id,))
        summary = {key: int(value) for key, value in cursor.fetchone().items()}
        where = " WHERE b.owner_id = %s"
        parameters = [owner_id]
        if filters.search:
            # LIKE wildcards in a student's name are literal search text.
            search = filters.search.replace("!", "!!").replace("%", "!%").replace("_", "!_")
            where += " AND u.full_name LIKE %s ESCAPE '!'"
            parameters.append("%" + search + "%")
        if filters.status:
            where += " AND j.status = %s"
            parameters.append(filters.status)
        cursor.execute("SELECT COUNT(*) AS filtered_total " + REQUEST_JOINS + where, tuple(parameters))
        total = int(cursor.fetchone()["filtered_total"])
        page_count = max(1, math.ceil(total / PAGE_SIZE))
        page = min(filters.page, page_count)
        # Only allowlisted sort fragments enter SQL; user values stay parameters.
        cursor.execute("SELECT " + REQUEST_COLUMNS + " " + REQUEST_JOINS + where
                       + " ORDER BY " + SORT_ORDERS[filters.sort] + " LIMIT %s OFFSET %s",
                       (*parameters, PAGE_SIZE, (page - 1) * PAGE_SIZE))
        rows = [decorate_request(row) for row in cursor.fetchall()]
        selected = None
        if selected_id is not None:
            cursor.execute("SELECT " + REQUEST_COLUMNS + ", u.email AS student_email, j.message, j.rejection_reason "
                           + REQUEST_JOINS + " WHERE j.request_id = %s AND b.owner_id = %s", (selected_id, owner_id))
            selected = cursor.fetchone()
            if selected is None:
                raise JoinRequestNotFound()
            selected = decorate_request(selected)
            selected['student_phone']=student_contact_phone(cursor,selected['student_id'])
        return {"boarding": boarding, "summary": summary, "rows": rows, "selected": selected,
                "filtered_total": total, "page": page, "page_count": page_count,
                "first_row": (page - 1) * PAGE_SIZE + 1 if total else 0,
                "last_row": min(page * PAGE_SIZE, total)}


def reject_owner_request(owner_id, request_id, reason):
    reason = reason.strip()
    if len(reason) > 500 or "\x00" in reason:
        raise JoinRequestValidationError("Use no more than 500 characters for the rejection reason.")
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction()
            # This nonlocking hint identifies the Student before taking locks in
            # Student -> Boarding -> Request order, shared with future decisions.
            cursor.execute("""SELECT j.student_id, j.boarding_id FROM join_requests j
                JOIN boardings b ON b.boarding_id = j.boarding_id
                WHERE j.request_id = %s AND b.owner_id = %s""", (request_id, owner_id))
            hint = cursor.fetchone()
            if hint is None:
                raise JoinRequestNotFound()
            cursor.execute("SELECT user_id FROM users WHERE user_id = %s FOR UPDATE", (hint["student_id"],))
            if cursor.fetchone() is None:
                raise JoinRequestNotFound()
            cursor.execute("SELECT boarding_id FROM boardings WHERE boarding_id = %s AND owner_id = %s FOR UPDATE",
                           (hint["boarding_id"], owner_id))
            if cursor.fetchone() is None:
                raise JoinRequestNotFound()
            cursor.execute("""SELECT request_id, status FROM join_requests
                WHERE request_id = %s AND student_id = %s AND boarding_id = %s FOR UPDATE""",
                           (request_id, hint["student_id"], hint["boarding_id"]))
            current = cursor.fetchone()
            if current is None:
                raise JoinRequestNotFound()
            if current["status"] != "requested":
                raise JoinRequestConflict("This request has already been decided or cancelled. Refresh to see its current status.")
            # Retain history; only this Owner's still-pending request can change.
            cursor.execute("""UPDATE join_requests j JOIN boardings b ON b.boarding_id = j.boarding_id
                SET j.status = 'rejected', j.decided_at = UTC_TIMESTAMP(6),
                    j.decided_by = %s, j.rejection_reason = %s
                WHERE j.request_id = %s AND b.owner_id = %s AND j.status = 'requested'""",
                           (owner_id, reason or None, request_id, owner_id))
            if cursor.rowcount != 1:
                raise JoinRequestConflict("The request changed. Refresh before trying again.")
            # A decision and its metadata succeed together, or nothing is saved.
            connection.commit()
        except Exception:
            connection.rollback()
            raise
