"""Read-only Student agreements and tenant-authorized Boarding profile projection."""
import json
import math
import re
from boarding_images import cover_image_path
from db import get_db_connection
from join_request_service import JoinRequestNotFound
from owner_boarding import visible_facilities
from student_portal_service import TENANCY_FIELDS,TENANCY_JOINS,TENANCY_SUMMARY,load_dashboard_snapshot,valid_agreement
from tenancy_lifecycle import PHASES,phase
from tenancy_service import local_today

HISTORY_SIZE = 10
TABS = {'overview':'Overview','room':'Room & Rent','facilities':'Facilities','tenancy':'Tenancy'}
DETAIL_SQL = 'SELECT ' + TENANCY_FIELDS + """, r.floor, b.status AS publication_status,
    b.description,b.address,b.contact_phone,b.contact_email,b.facilities,b.cover_image_filename,
    owner.full_name AS owner_name,owner.role AS owner_role,owner.is_active AS owner_active,
    j.decided_at AS approved_at""" + TENANCY_JOINS + " LEFT JOIN users owner ON owner.user_id=b.owner_id WHERE t.student_id=%s AND t.tenancy_id=%s"


def parse_tenancy_id(value):
    if value is None:
        return None
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,9}',value) or int(value)>4294967295:
        raise ValueError('Choose an agreement from My Boarding.')
    return int(value)


def profile_details(row):
    """Unpublishing hides mutable draft details, while the saved agreement stays readable."""
    if row['publication_status'] != 'published' or row['owner_role'] != 'owner' or not row['owner_active']:
        return None
    facilities = row['facilities']
    if isinstance(facilities,(str,bytes,bytearray)):
        facilities=json.loads(facilities)
    if not isinstance(facilities,list) or not all(isinstance(value,str) for value in facilities):
        raise ValueError('Invalid saved facilities')
    cover=cover_image_path(row['cover_image_filename'])
    return {key:row[key] for key in ('description','address','city','district','contact_phone','contact_email','owner_name')} | {
        'facilities':visible_facilities(facilities),
        'has_cover':cover is not None and cover.is_file()}


def agreement_details(row,today):
    state=phase(row,today)
    # Only the public contract projection reaches Jinja; never return storage filenames.
    keys=('tenancy_id','request_id','boarding_name','room_number','room_type','bed_label','rent_unit',
          'agreed_monthly_rent','start_date','end_date','floor','approved_at')
    return {key:row[key] for key in keys} | {'phase':state,'status_label':PHASES[state], 'profile':profile_details(row)}


def load_my_boarding(student_id,selected_id=None,history_page=1):
    today=local_today()
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        try:
            state=load_dashboard_snapshot(cursor,student_id,today)
            cursor.execute('SELECT COUNT(*) AS total FROM tenancies WHERE student_id=%s',(student_id,))
            total=int(cursor.fetchone()['total']);pages=max(1,math.ceil(total/HISTORY_SIZE));history_page=min(history_page,pages)
            cursor.execute(TENANCY_SUMMARY+' ORDER BY t.start_date DESC,t.tenancy_id DESC LIMIT %s OFFSET %s',
                (student_id,HISTORY_SIZE,(history_page-1)*HISTORY_SIZE))
            history=[{key:row[key] for key in ('tenancy_id','boarding_name','start_date','end_date')} |
                {'status_label':PHASES[phase(row,today)]} for row in cursor.fetchall() if valid_agreement(row)]
            default=state['tenancy']
            target=selected_id or (default['tenancy_id'] if default else None)
            selected=None
            if target is not None:
                # An arbitrary ID never removes the authenticated Student ownership predicate.
                cursor.execute(DETAIL_SQL,(student_id,target));row=cursor.fetchone()
                if row is None:raise JoinRequestNotFound()
                if valid_agreement(row):selected=agreement_details(row,today)
                else:state['state']='review'
            return {'state':state,'selected':selected,'history':history,'history_total':total,
                'history_page':history_page,'history_pages':pages,
                'can_report':selected is not None and selected['phase']=='active' and state['state']=='active'
                    and state['tenancy']['tenancy_id']==selected['tenancy_id']}
        finally:
            connection.rollback()


def load_my_boarding_cover(student_id,tenancy_id):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        cursor.execute(DETAIL_SQL,(student_id,tenancy_id));row=cursor.fetchone()
        if row is None or not valid_agreement(row):raise JoinRequestNotFound()
        if row['publication_status']!='published' or row['owner_role']!='owner' or not row['owner_active']:
            raise JoinRequestNotFound()
        return row['cover_image_filename']
