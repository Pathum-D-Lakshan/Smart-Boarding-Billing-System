"""Protect frozen billing periods from changes through existing tenancy writers."""
from billing_calculator import month_period,overlap_days
from join_request_service import JoinRequestConflict


def schema_present(cursor):
    cursor.execute("SELECT 1 AS ready FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='billing_cycles' LIMIT 1")
    return cursor.fetchone() is not None


def guard_new_agreement(cursor,boarding_id,start,end=None):
    if not schema_present(cursor): return
    cursor.execute('''SELECT cycle_id FROM billing_cycles WHERE boarding_id=%s AND state='locked'
        AND DATE_ADD(period_start,INTERVAL 1 MONTH)>%s AND (%s IS NULL OR period_start<%s) LIMIT 1''',(boarding_id,start,end,end))
    if cursor.fetchone():
        raise JoinRequestConflict('This agreement would change an issued billing period. Correct that billing cycle before approving the new tenancy.')


def guard_period_change(cursor,old,start,end):
    if not schema_present(cursor): return
    cursor.execute("SELECT period_start FROM billing_cycles WHERE boarding_id=%s AND state='locked'",(old['boarding_id'],))
    for cycle in cursor.fetchall():
        first,until,_=month_period(cycle['period_start'].strftime('%Y-%m'))
        previous=overlap_days(old['start_date'],old['end_date'],first,until)
        proposed=overlap_days(start,end,first,until)
        if previous!=proposed and (previous[2] or proposed[2]):
            raise JoinRequestConflict('These dates affect a frozen billing allocation. Correct that Monthly Bills cycle first; issued amounts cannot change silently.')
