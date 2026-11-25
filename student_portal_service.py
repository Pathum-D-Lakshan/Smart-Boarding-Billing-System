"""Read-only, Student-scoped dashboard summaries over existing agreements."""
from admin_security import account_guard, listing_guard
from boarding_images import has_cover_image
from db import get_db_connection
from join_request_service import REQUEST_STATUSES
from maintenance_service import STATUSES as MAINTENANCE_STATUSES
from payment_service import SETTLED, STUDENT_BILLS_FROM, UNPAID_FOR_TRANSFER, WITHDRAWN_SQL, _bill_state, recent_payment_approvals
from tenancy_service import local_today


TENANCY_FIELDS = """t.tenancy_id,t.source_request_id AS request_id,t.start_date,t.end_date,
    t.tenancy_status,t.rent_unit,t.agreed_monthly_rent,b.boarding_name,b.city,b.district,
    r.room_number,r.room_type,bed.bed_label,j.status AS request_status,
    (b.boarding_id=t.boarding_id AND r.boarding_id=t.boarding_id AND j.boarding_id=t.boarding_id
        AND j.student_id=t.student_id AND (t.rent_unit='room' AND t.bed_id IS NULL AND r.room_type='private'
            OR t.rent_unit='bed' AND r.room_type='shared' AND bed.room_id=t.room_id)) AS valid_assignment"""
TENANCY_JOINS = """ FROM tenancies t LEFT JOIN boardings b ON b.boarding_id=t.boarding_id
    LEFT JOIN rooms r ON r.room_id=t.room_id LEFT JOIN beds bed ON bed.bed_id=t.bed_id
    LEFT JOIN join_requests j ON j.request_id=t.source_request_id"""
TENANCY_SUMMARY = 'SELECT ' + TENANCY_FIELDS + TENANCY_JOINS + ' WHERE t.student_id=%s'


def valid_agreement(row):
    return bool(row['valid_assignment'] and row['request_status'] == 'approved'
        and row['agreed_monthly_rent'] > 0 and (row['end_date'] is None or row['end_date'] >= row['start_date']))


def dashboard_state(agreements, pending, previous, recent, today):
    """Use half-open effective dates; historical agreements never imply occupancy."""
    valid = all(valid_agreement(row) for row in agreements)
    overlap = any(a['end_date'] is None or a['end_date'] > b['start_date'] for a, b in zip(agreements, agreements[1:]))
    request_conflict = pending and any(row['end_date'] is None or row['end_date'] > pending[0]['intended_start_date'] for row in agreements)
    missing_approval = recent and recent['status'] == 'approved' and not agreements and not previous
    if not valid or overlap or len(agreements) > 100 or len(pending) > 1 or request_conflict or missing_approval:
        return {'state': 'review', 'tenancy': None, 'pending_request': None, 'recent_request': recent}
    tenancy = agreements[0] if agreements else None
    state = ('scheduled' if tenancy['start_date'] > today else 'active') if tenancy else 'pending' if pending else 'previous' if previous else 'new'
    if state == 'previous':
        if not previous['valid_assignment'] or previous['request_status'] != 'approved':
            state, previous = 'review', None
        tenancy = previous
    return {'state': state, 'tenancy': tenancy, 'pending_request': pending[0] if pending else None, 'recent_request': recent}


def load_dashboard_snapshot(cursor, student_id, today):
    """Keep Dashboard and My Boarding selection in one authoritative snapshot."""
    cursor.execute(TENANCY_SUMMARY + " AND t.tenancy_status='open' AND (t.end_date IS NULL OR t.end_date>%s) ORDER BY t.start_date,t.tenancy_id LIMIT 101", (student_id, today))
    agreements = cursor.fetchall()
    cursor.execute(TENANCY_SUMMARY + " AND (t.tenancy_status='ended' OR t.end_date<=%s) ORDER BY COALESCE(t.end_date,t.start_date) DESC,t.tenancy_id DESC LIMIT 1", (student_id, today))
    previous = cursor.fetchone()
    request_sql = """SELECT j.request_id,j.boarding_id,j.status,j.requested_at,j.intended_start_date,b.boarding_name,b.city,b.district
        FROM join_requests j JOIN boardings b ON b.boarding_id=j.boarding_id WHERE j.student_id=%s"""
    cursor.execute(request_sql + " AND j.status='requested' ORDER BY j.requested_at DESC,j.request_id DESC LIMIT 2", (student_id,))
    pending = cursor.fetchall()
    cursor.execute(request_sql + ' ORDER BY j.requested_at DESC,j.request_id DESC LIMIT 1', (student_id,))
    recent = cursor.fetchone()
    for row in pending + ([recent] if recent else []):
        row['status_label'] = REQUEST_STATUSES.get(row['status'], 'Unknown')
    return dashboard_state(agreements, pending, previous, recent, today)


def load_student_dashboard(student_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        try:
            data = load_dashboard_snapshot(cursor, student_id, local_today())
            data.update(student_finances(cursor, student_id, data["tenancy"]))
            data["requests"] = recent_requests(cursor, student_id)
            data["updates"] = recent_updates(cursor, student_id)
            if data["tenancy"]:
                cursor.execute("""SELECT b.cover_image_filename FROM tenancies t
                    JOIN boardings b ON b.boarding_id=t.boarding_id JOIN users owner ON owner.user_id=b.owner_id
                    WHERE t.student_id=%s AND t.tenancy_id=%s
                      AND b.status='published' AND owner.role='owner' AND owner.is_active=TRUE"""
                    + listing_guard() + account_guard("owner"), (student_id, data["tenancy"]["tenancy_id"]))
                cover = cursor.fetchone()
                data["tenancy"]["has_cover"] = bool(cover and has_cover_image(cover["cover_image_filename"]))
            data['payment_approvals'] = recent_payment_approvals(cursor, student_id)[:1]
            return data
        finally:
            connection.rollback()


def student_finances(cursor, student_id, tenancy):
    cursor.execute("""SELECT COUNT(*) AS unpaid FROM monthly_bills m
        LEFT JOIN payments p ON p.bill_id=m.bill_id AND p.status='verified'
        LEFT JOIN receipts r ON r.payment_id=p.payment_id
        WHERE m.student_id=%s AND m.state='issued' AND m.final_total>0 AND NOT (""" + SETTLED + ")",
        (student_id,))
    data = cursor.fetchone()
    cursor.execute("""SELECT COALESCE(SUM(p.amount),0) AS verified FROM payments p
        JOIN monthly_bills m ON m.bill_id=p.bill_id WHERE m.student_id=%s
        AND p.status='verified' AND p.method IN ('bank_transfer','cash')""", (student_id,))
    data.update(cursor.fetchone())
    cursor.execute("SELECT COUNT(*) AS pending FROM join_requests WHERE student_id=%s AND status='requested'", (student_id,))
    data.update(cursor.fetchone())
    cursor.execute("""SELECT m.bill_id,m.bill_reference,m.state,m.period_start,m.final_total,m.due_date,
        p.status AS active_status,p.method,r.receipt_id,(""" + UNPAID_FOR_TRANSFER + """) AS can_submit"""
        + STUDENT_BILLS_FROM + """ WHERE m.student_id=%s AND m.state='issued'
        ORDER BY (m.tenancy_id=%s) DESC,m.period_start DESC,m.issued_at DESC,m.bill_id DESC LIMIT 1""",
        (student_id, tenancy["tenancy_id"] if tenancy else 0))
    bill = cursor.fetchone()
    if bill:
        active = {"status": bill["active_status"], "method": bill["method"], "receipt_id": bill["receipt_id"]} if bill["active_status"] else None
        bill["payment_status"] = _bill_state(bill, active)
    data["bill"] = bill
    return data


def recent_requests(cursor, student_id):
    cursor.execute("""SELECT j.request_id,j.boarding_id,j.requested_at,j.status,b.boarding_name,b.city,b.district,
        CASE WHEN b.status='published' AND owner.role='owner' AND owner.is_active=TRUE"""
        + listing_guard() + account_guard("owner") + """ THEN b.cover_image_filename END AS cover_image_filename
        FROM join_requests j JOIN boardings b ON b.boarding_id=j.boarding_id JOIN users owner ON owner.user_id=b.owner_id
        WHERE j.student_id=%s ORDER BY j.requested_at DESC,j.request_id DESC LIMIT 4""", (student_id,))
    rows = cursor.fetchall()
    for row in rows:
        row["status_label"] = REQUEST_STATUSES[row["status"]]
        row["has_cover"] = has_cover_image(row.pop("cover_image_filename"))
    return rows


def recent_updates(cursor, student_id):
    # Only read status, display labels and timestamps. Each link rechecks Student access.
    cursor.execute("""SELECT 'bill' AS kind,bill_id AS item_id,bill_reference AS label,
             'issued' AS status,issued_at AS event_at
        FROM monthly_bills WHERE student_id=%s AND state='issued'
        UNION ALL
        SELECT 'payment',p.payment_id,m.bill_reference,p.status,p.decided_at
        FROM payments p JOIN monthly_bills m ON m.bill_id=p.bill_id
        WHERE m.student_id=%s AND p.status IN ('verified','rejected') AND NOT """ + WITHDRAWN_SQL + """
        UNION ALL
        SELECT 'request',j.request_id,b.boarding_name,j.status,COALESCE(j.decided_at,j.requested_at)
        FROM join_requests j JOIN boardings b ON b.boarding_id=j.boarding_id WHERE j.student_id=%s
        UNION ALL
        SELECT 'maintenance',maintenance_id,issue_title,status,status_changed_at
        FROM maintenance_requests WHERE reported_by_user_id=%s AND reporter_role='student'
        ORDER BY event_at DESC,kind,item_id DESC LIMIT 5""", (student_id,) * 4)
    return [row | {"status_label": (REQUEST_STATUSES if row["kind"] == "request" else MAINTENANCE_STATUSES).get(
        row["status"], row["status"].capitalize())} for row in cursor.fetchall()]
