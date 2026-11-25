"""UC31–33: minimal platform data and audited, transactional Admin decisions."""
import calendar
from datetime import datetime
import math
import secrets

from flask import current_app
from mysql.connector import Error

from auth_email import password_stamp
from auth_sessions import credential_digest, token_digest
from boarding_images import cover_image_path
from db import get_db_connection
from owner_boarding import visible_facilities
from owner_confirmation import confirm_account_password
from tenancy_service import local_today
from admin_security import reactivation_enabled, normal_scope_guard

PAGE_SIZE = 15
USER_FIELDS = 'u.user_id,u.full_name,u.email,u.role,u.created_at,u.is_active,u.admin_suspended,u.admin_revision'
LISTING_FIELDS = '''b.boarding_id,b.boarding_name,b.city,b.district,b.status,b.admin_hidden,
    b.admin_revision,b.created_at,owner.full_name AS owner_name,owner.is_active AS owner_active'''
LISTING_FROM = " FROM boardings b JOIN users owner ON owner.user_id=b.owner_id AND owner.role='owner'"
VISIBLE = "b.status='published' AND b.admin_hidden=FALSE AND owner.is_active=TRUE"


class AdminValidationError(ValueError):
    def __init__(self, errors, status=400):
        self.errors, self.status = errors, status
        super().__init__('Please check the highlighted fields.')


class AdminNotFound(LookupError):
    pass


class AdminConflict(ValueError):
    pass


def identifier(value):
    text = str(value)
    if not text.isascii() or not text.isdigit() or not 0 < int(text) <= 4294967295:
        raise AdminNotFound()
    return int(text)


def parse_filters(args, kind):
    values = {name: args.get(name, '').strip() for name in ('search', 'role', 'status', 'location', 'sort')}
    values['sort'] = values['sort'] or 'newest'
    if len(values['search']) > 200 or len(values['location']) > 100 or any('\x00' in x for x in values.values()):
        raise AdminValidationError({'filters': 'Use a shorter search or location.'})
    if (values['sort'] not in ('newest', 'oldest') or
            values['role'] not in ('', 'student', 'owner') or
            values['status'] not in (('', 'active', 'suspended') if kind == 'users' else ('', 'visible', 'hidden'))):
        raise AdminValidationError({'filters': 'Choose an available filter.'})
    page = args.get('page', '1')
    if not str(page).isascii() or not str(page).isdigit() or not 1 <= int(page) <= 1000000:
        raise AdminValidationError({'page': 'Choose a valid page.'})
    values['page'] = int(page)
    return values


def user_status(row):
    return 'Suspended' if row['admin_suspended'] else 'Active' if row['is_active'] else 'Inactive'


def listing_status(row):
    return 'Admin-hidden' if row['admin_hidden'] else 'Draft' if row['status'] == 'draft' else 'Visible' if row['owner_active'] else 'Unavailable'


def load_records(kind, filters):
    params = []
    if kind == 'users':
        base = " FROM users u WHERE u.role IN ('student','owner')"
        if filters['search']:
            base += ' AND (u.full_name LIKE %s OR u.email LIKE %s)'
            params += ['%' + filters['search'] + '%'] * 2
        if filters['role']:
            base += ' AND u.role=%s'; params.append(filters['role'])
        if filters['status'] == 'suspended': base += ' AND u.admin_suspended=TRUE'
        if filters['status'] == 'active': base += ' AND u.admin_suspended=FALSE AND u.is_active=TRUE'
        fields, ordering = USER_FIELDS, 'u.created_at,u.user_id'
    else:
        base = LISTING_FROM + ' WHERE TRUE'
        if filters['search']:
            base += ' AND (b.boarding_name LIKE %s OR owner.full_name LIKE %s)'
            params += ['%' + filters['search'] + '%'] * 2
        if filters['location']:
            base += ' AND (b.city LIKE %s OR b.district LIKE %s)'
            params += ['%' + filters['location'] + '%'] * 2
        if filters['status'] == 'visible': base += ' AND ' + VISIBLE
        if filters['status'] == 'hidden': base += ' AND b.admin_hidden=TRUE'
        fields, ordering = LISTING_FIELDS, 'b.created_at,b.boarding_id'
    direction = ' DESC' if filters['sort'] == 'newest' else ' ASC'
    order = ','.join(part + direction for part in ordering.split(','))
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        try:
            cursor.execute('SELECT COUNT(*) AS total' + base, tuple(params))
            total = int(cursor.fetchone()['total']); pages = max(1, math.ceil(total / PAGE_SIZE))
            page = min(filters['page'], pages)
            cursor.execute('SELECT ' + fields + base + ' ORDER BY ' + order + ' LIMIT %s OFFSET %s',
                           tuple(params) + (PAGE_SIZE, (page - 1) * PAGE_SIZE))
            rows = cursor.fetchall()
            for row in rows: row['status_label'] = user_status(row) if kind == 'users' else listing_status(row)
            return {'rows': rows, 'total': total, 'page': page, 'pages': pages}
        finally:
            connection.rollback()


def load_record(kind, target_id):
    target_id = identifier(target_id)
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        if kind == 'users':
            cursor.execute('SELECT ' + USER_FIELDS + " FROM users u WHERE u.user_id=%s AND u.role IN ('student','owner')", (target_id,))
        else:
            cursor.execute('SELECT ' + LISTING_FIELDS + ',b.description,b.facilities,b.cover_image_filename' + LISTING_FROM + ' WHERE b.boarding_id=%s', (target_id,))
        row = cursor.fetchone()
        if row is None: raise AdminNotFound()
        field = 'target_user_id' if kind == 'users' else 'boarding_id'
        cursor.execute('SELECT action,reason,created_at FROM admin_events WHERE ' + field + '=%s ORDER BY revision DESC LIMIT 1', (target_id,))
        row['last_decision'] = cursor.fetchone()
        row['status_label'] = user_status(row) if kind == 'users' else listing_status(row)
        if kind == 'listings':
            import json
            facilities = row.pop('facilities')
            if isinstance(facilities, (str, bytes, bytearray)): facilities = json.loads(facilities)
            if not isinstance(facilities, list) or not all(isinstance(x, str) for x in facilities): raise ValueError('Invalid facilities')
            row['facilities'] = visible_facilities(facilities)
            filename = row.pop('cover_image_filename')
            cover = cover_image_path(filename) if row['status'] == 'published' else None
            row['has_cover'] = bool(cover and cover.is_file())
        return row


def load_cover(target_id):
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute("SELECT cover_image_filename FROM boardings WHERE boarding_id=%s AND status='published'", (identifier(target_id),))
        row = cursor.fetchone()
    path = cover_image_path(row['cover_image_filename']) if row else None
    if not path or not path.is_file(): raise AdminNotFound()
    return path


def parse_decision(form, action):
    errors = {}
    revision = form.get('revision', '')
    if not revision.isascii() or not revision.isdigit() or not 0 <= int(revision) < 4294967295:
        errors['revision'] = 'Reload these details before confirming.'
    reason = form.get('reason', '').strip()
    if action in ('suspend', 'hide') and not reason: errors['reason'] = 'Enter a reason for this decision.'
    if len(reason) > 500 or '\x00' in reason: errors['reason'] = 'Use no more than 500 characters without control characters.'
    if form.get('confirm') != '1': errors['confirm'] = 'Confirm that you reviewed this action.'
    if errors: raise AdminValidationError(errors)
    return int(revision), reason or ('Account reactivated.' if action == 'reactivate' else 'Moderation block removed.')


def _check_actor(cursor, admin_id, stamp, session_token):
    # Serialize with password resets/suspension and verify the current session inside the write transaction.
    cursor.execute('SELECT user_id,role,password_hash,is_active,admin_suspended FROM users WHERE user_id=%s FOR UPDATE', (admin_id,))
    actor = cursor.fetchone()
    if not actor or actor['role'] != 'admin' or not actor['is_active'] or actor['admin_suspended'] or not secrets.compare_digest(password_stamp(actor['password_hash']), stamp):
        raise AdminConflict('Your account changed. Log in again before confirming.')
    if current_app.config.get('AUTH_SESSION_STORE_ENABLED'):
        cursor.execute('''SELECT user_id FROM auth_sessions WHERE token_digest=%s AND user_id=%s
            AND credential_stamp=%s AND revoked_at IS NULL AND expires_at>UTC_TIMESTAMP(6)'''+normal_scope_guard()+''' FOR UPDATE''',
            (token_digest(session_token), admin_id, credential_digest(actor['password_hash'])))
        if cursor.fetchone() is None: raise AdminConflict('Your login expired. Log in again.')


def decide(admin_id, kind, target_id, action, form, session_token):
    target_id = identifier(target_id)
    if action not in (('suspend','reactivate') if kind == 'users' else ('hide','restore')): raise AdminNotFound()
    revision, reason = parse_decision(form, action)
    stamp = confirm_account_password(admin_id, form.get('current_password', ''), 'admin')
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED')
            _check_actor(cursor, admin_id, stamp, session_token)
            if kind == 'users':
                cursor.execute('SELECT user_id,role,is_active,admin_suspended,admin_revision FROM users WHERE user_id=%s FOR UPDATE', (target_id,))
                target = cursor.fetchone()
                if not target or target['role'] not in ('student','owner') or target_id == admin_id: raise AdminNotFound()
                previous = bool(target['admin_suspended']); new = action == 'suspend'
                if target['admin_revision'] != revision or previous == new:
                    raise AdminConflict('This account changed or the action was already completed. Reload the details.')
                cursor.execute('UPDATE users SET admin_suspended=%s,admin_revision=admin_revision+1 WHERE user_id=%s AND admin_revision=%s',
                               (new, target_id, revision))
                if new:
                    cursor.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE user_id=%s AND revoked_at IS NULL', (target_id,))
                    # Outstanding reset grants must not create a session/password bypass after suspension.
                    from auth_email import _clear_challenge
                    cursor.execute('SELECT email FROM users WHERE user_id=%s', (target_id,))
                    _clear_challenge(cursor, 'reset', cursor.fetchone()['email'])
                user_id, boarding_id = target_id, None
                if not new and reactivation_enabled():
                    from reactivation_service import resolve_pending_manual
                    resolve_pending_manual(cursor,target,admin_id)
                    cursor.execute('UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP(6) WHERE user_id=%s AND revoked_at IS NULL',(target_id,))
                event = 'user_suspended' if new else 'user_reactivated'
                previous_state, new_state = ('suspended' if previous else 'clear'), ('suspended' if new else 'clear')
            else:
                cursor.execute('SELECT boarding_id,status,admin_hidden,admin_revision FROM boardings WHERE boarding_id=%s FOR UPDATE', (target_id,))
                target = cursor.fetchone()
                if not target: raise AdminNotFound()
                previous = bool(target['admin_hidden']); new = action == 'hide'
                if target['admin_revision'] != revision or previous == new or new and target['status'] != 'published':
                    raise AdminConflict('This listing changed or cannot accept this action. Reload the details.')
                cursor.execute('UPDATE boardings SET admin_hidden=%s,admin_revision=admin_revision+1,updated_at=updated_at WHERE boarding_id=%s AND admin_revision=%s',
                               (new, target_id, revision))
                user_id, boarding_id = None, target_id
                event = 'listing_hidden' if new else 'listing_restored'
                previous_state, new_state = ('hidden' if previous else 'clear'), ('hidden' if new else 'clear')
            public_column=',user_visible_reason' if reactivation_enabled() else ''
            public_value=',%s' if reactivation_enabled() else ''
            params=(admin_id,user_id,boarding_id,event,previous_state,new_state,revision+1,reason)
            if reactivation_enabled(): params += (reason if event=='user_suspended' else None,)
            cursor.execute('''INSERT INTO admin_events(actor_id,target_user_id,boarding_id,action,previous_state,new_state,revision,reason,created_at'''+public_column+''')
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6)'''+public_value+')',params)
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error, Error) and error.errno in (1062, 1205, 1213):
                raise AdminConflict('Another action changed this record. Reload and try again.') from None
            raise


def month_window(months, today):
    index = today.year * 12 + today.month - months
    year, month = divmod(index, 12)
    start = datetime(year, month + 1, 1)
    labels = []
    for step in range(months):
        y, m = divmod(index + step, 12)
        labels.append({'key': f'{y:04d}-{m+1:02d}', 'label': calendar.month_abbr[m+1] + ' ' + str(y), 'student': 0, 'owner': 0})
    # users.created_at is TIMESTAMP; use explicit UTC session + local month boundaries.
    from datetime import timedelta
    end_year, end_month = divmod(index + months, 12)
    return start - timedelta(hours=5, minutes=30), datetime(end_year, end_month + 1, 1) - timedelta(hours=5, minutes=30), labels


def load_summary(months=6):
    if months not in (3,6,12): raise AdminValidationError({'period': 'Choose 3, 6 or 12 months.'})
    start, end, trend = month_window(months, local_today())
    with get_db_connection() as connection, connection.cursor(dictionary=True) as cursor:
        cursor.execute("SET SESSION time_zone='+00:00'")
        connection.start_transaction(readonly=True)
        try:
            cursor.execute('''SELECT COUNT(CASE WHEN role='student' THEN 1 END) AS students,
                COUNT(CASE WHEN role='owner' THEN 1 END) AS owners,
                COUNT(CASE WHEN is_active=TRUE AND admin_suspended=FALSE THEN 1 END) AS active,
                COUNT(CASE WHEN admin_suspended=TRUE THEN 1 END) AS suspended
                FROM users WHERE role IN ('student','owner')''')
            counts = cursor.fetchone()
            cursor.execute('''SELECT COUNT(*) AS listings,
                COUNT(CASE WHEN ''' + VISIBLE + ''' THEN 1 END) AS published,
                COUNT(CASE WHEN b.admin_hidden=TRUE THEN 1 END) AS hidden,
                COUNT(CASE WHEN b.status='draft' AND b.admin_hidden=FALSE THEN 1 END) AS drafts,
                COUNT(CASE WHEN b.status='published' AND b.admin_hidden=FALSE AND owner.is_active=FALSE THEN 1 END) AS unavailable'''+LISTING_FROM)
            counts.update(cursor.fetchone())
            cursor.execute('SELECT ' + USER_FIELDS + " FROM users u WHERE u.role IN ('student','owner') ORDER BY u.created_at DESC,u.user_id DESC LIMIT 5")
            recent = cursor.fetchall()
            for row in recent: row['status_label'] = user_status(row)
            cursor.execute('''SELECT e.action,e.created_at,b.boarding_name FROM admin_events e
                JOIN boardings b ON b.boarding_id=e.boarding_id
                WHERE e.action IN ('listing_hidden','listing_restored') ORDER BY e.created_at DESC,e.event_id DESC LIMIT 5''')
            events = cursor.fetchall()
            cursor.execute("""SELECT DATE_FORMAT(CONVERT_TZ(created_at,'+00:00','+05:30'),'%Y-%m') AS month,role,COUNT(*) AS total
                FROM users WHERE role IN ('student','owner') AND created_at>=%s AND created_at<%s
                GROUP BY month,role ORDER BY month,role""", (start, end))
            by_month = {row['key']: row for row in trend}
            for row in cursor.fetchall():
                if row['month'] in by_month: by_month[row['month']][row['role']] = int(row['total'])
            return {'counts': counts, 'recent': recent, 'events': events, 'trend': trend, 'months': months}
        finally:
            connection.rollback()
