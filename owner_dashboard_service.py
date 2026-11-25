"""Read-only dashboard queries for the authenticated Owner's boarding."""

from boarding_images import has_cover_image
from db import get_db_connection
from finance_service import period
from join_request_service import REQUEST_COLUMNS, REQUEST_JOINS, SUMMARY_SQL, decorate_request
from maintenance_service import STATUSES as MAINTENANCE_STATUSES
from payment_service import SETTLED, STUDENT_BILLS_FROM as BILLS_WITH_ACTIVE_PAYMENT
from reports_service import shift_month
from tenancy_service import local_today, rental_unit_queries


def occupancy(cursor, owner_id, boarding_id, today):
    # Start from the same ready, correctly priced inventory as Join Request approval.
    # A Private room is one unit, regardless of how many physical beds it holds.
    queries = rental_unit_queries({"boarding_id": boarding_id}, owner_id, include_held=True)
    cursor.execute("WITH rentable AS (" + " UNION ALL ".join(sql for sql, _ in queries) + """),
        held AS (
            SELECT unit.kind, unit.unit_id, MAX(t.start_date <= %s) AS occupied
            FROM rentable unit JOIN tenancies t ON t.room_id=unit.room_id
            WHERE t.tenancy_status='open' AND (t.end_date IS NULL OR t.end_date>%s)
              AND (t.rent_unit='room' OR (unit.kind='bed' AND t.bed_id=unit.unit_id))
            GROUP BY unit.kind, unit.unit_id
        )
        SELECT rentable.kind, COUNT(*) AS total,
            COALESCE(SUM(held.occupied=1),0) AS occupied,
            COALESCE(SUM(held.occupied=0),0) AS reserved
        FROM rentable LEFT JOIN held USING(kind,unit_id) GROUP BY rentable.kind
        """, (*[value for _, params in queries for value in params], today, today))
    result = {"bed": {"total": 0, "occupied": 0, "reserved": 0}, "room": {"total": 0, "occupied": 0, "reserved": 0}}
    for row in cursor.fetchall():
        result[row["kind"]] = {key: int(row[key]) for key in ("total", "occupied", "reserved")}
    total = {key: sum(row[key] for row in result.values()) for key in ("total", "occupied", "reserved")}
    for row in (*result.values(), total):
        row["available"] = row["total"] - row["occupied"] - row["reserved"]
    total["percent"] = round(100 * total["occupied"] / total["total"]) if total["total"] else None
    return {"units": total, "by_kind": result}


def billing_overview(cursor, boarding_id, month):
    months = [shift_month(month, offset) for offset in range(-5, 1)]
    first, _, start_utc, _ = period(months[0])
    _, until, _, until_utc = period(month)
    cursor.execute("""SELECT DATE_FORMAT(period_start,'%Y-%m') AS month, SUM(final_total) AS billed
        FROM monthly_bills WHERE boarding_id=%s AND state='issued' AND period_start>=%s AND period_start<%s
        GROUP BY month""", (boarding_id, first, until))
    billed = {row["month"]: row["billed"] for row in cursor.fetchall()}
    # Match Finance: cash basis, by Colombo decision date, verified transfers and cash only.
    cursor.execute("""SELECT DATE_FORMAT(CONVERT_TZ(p.decided_at,'+00:00','+05:30'),'%Y-%m') AS month,
           SUM(p.amount) AS received FROM payments p JOIN monthly_bills m ON m.bill_id=p.bill_id
        WHERE m.boarding_id=%s AND p.status='verified' AND p.method IN ('bank_transfer','cash')
          AND p.decided_at>=%s AND p.decided_at<%s GROUP BY month""", (boarding_id, start_utc, until_utc))
    received = {row["month"]: row["received"] for row in cursor.fetchall()}
    cursor.execute("""SELECT COUNT(*) AS due_count, MIN(m.due_date) AS next_due,
        COALESCE(SUM(CASE WHEN m.period_start=%s THEN m.final_total ELSE 0 END),0) AS outstanding,
        COALESCE(SUM(p.status='submitted'),0) AS slips""" + BILLS_WITH_ACTIVE_PAYMENT + """
        WHERE m.boarding_id=%s AND m.state='issued' AND m.final_total>0 AND NOT (""" + SETTLED + ")",
        (period(month)[0], boarding_id))
    overview = cursor.fetchone()
    overview["months"] = [
        {"label": period(key)[0].strftime("%b"), "month": period(key)[0], "billed": billed.get(key, 0), "received": received.get(key, 0)}
        for key in months
    ]
    overview.update(billed=billed.get(month, 0), received=received.get(month, 0))
    overview["scale"] = max(1, *(max(row["billed"], row["received"]) for row in overview["months"]))
    return overview


def load_owner_dashboard(owner_id):
    today = local_today()
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute("""SELECT boarding_id,boarding_name,city,district,status,cover_image_filename
            FROM boardings WHERE owner_id=%s""", (owner_id,))
        boarding = cursor.fetchone()
        data = {"month": today, "boarding": boarding, "rooms": 0, "beds": 0, "active": 0, "former": 0, "pending": 0}
        if not boarding:
            return data

        boarding["has_cover"] = has_cover_image(boarding.pop("cover_image_filename"))
        boarding_id = boarding["boarding_id"]
        cursor.execute("""SELECT COUNT(*) AS rooms,
            COALESCE(SUM((SELECT COUNT(*) FROM beds WHERE room_id=r.room_id)),0) AS beds
            FROM rooms r WHERE r.boarding_id=%s""", (boarding_id,))
        data.update(cursor.fetchone())
        cursor.execute("""SELECT COUNT(DISTINCT CASE WHEN t.tenancy_status='open' AND t.start_date<=%s
            AND (t.end_date IS NULL OR t.end_date>%s) THEN t.student_id END) AS active,
            COUNT(DISTINCT CASE WHEN (t.tenancy_status='ended' OR t.end_date<=%s)
              AND NOT EXISTS (SELECT 1 FROM tenancies other WHERE other.boarding_id=t.boarding_id
                AND other.student_id=t.student_id AND other.tenancy_status='open'
                AND (other.end_date IS NULL OR other.end_date>%s)) THEN t.student_id END) AS former
            FROM tenancies t WHERE t.boarding_id=%s""", (today, today, today, today, boarding_id))
        data.update(cursor.fetchone())
        cursor.execute(SUMMARY_SQL, (owner_id,))
        data["pending"] = int(cursor.fetchone()["pending"])
        cursor.execute("SELECT " + REQUEST_COLUMNS + " " + REQUEST_JOINS + """
           WHERE b.owner_id=%s ORDER BY j.requested_at DESC,j.request_id DESC LIMIT 4""", (owner_id,))
        data["requests"] = [decorate_request(row) for row in cursor.fetchall()]
        cursor.execute("""SELECT maintenance_id, issue_title, room_label, status, created_at
            FROM maintenance_requests WHERE boarding_id=%s ORDER BY created_at DESC,maintenance_id DESC LIMIT 4""", (boarding_id,))
        data["maintenance"] = [row | {"label": MAINTENANCE_STATUSES[row["status"]]} for row in cursor.fetchall()]
        cursor.execute("""SELECT COUNT(*) AS total FROM maintenance_requests
            WHERE boarding_id=%s AND status IN ('pending','in_progress')""", (boarding_id,))
        data["open_maintenance"] = cursor.fetchone()["total"]
        data["occupancy"] = occupancy(cursor, owner_id, boarding_id, today)
        data["billing"] = billing_overview(cursor, boarding_id, today.strftime("%Y-%m"))
        return data
