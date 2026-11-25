"""Issued-bill payments: private submissions and atomic manual Owner decisions."""
from contextlib import contextmanager
from datetime import date,datetime,timedelta
from decimal import Decimal
import json
import hashlib
import math
import re
import secrets
import uuid

from flask import current_app
from mysql.connector import Error

from auth_email import password_stamp
from admin_security import account_guard
from settings_service import student_bank_instructions
from billing_calculator import canonical,digest
from db import get_db_connection
from payment_files import evidence_path,store_slip,validate_slip
from tenancy_service import local_today

METHODS={'bank_transfer':'Bank Transfer','cash':'Cash','zero_balance':'No Payment Due'}
STATUSES={'submitted':'Pending Verification','verified':'Verified','rejected':'Rejected','withdrawn':'Withdrawn'}
# The existing inactive status releases the active-bill key. A self-decision
# identifies a Student withdrawal because an Owner decision uses a different actor.
WITHDRAWN_SQL = "(p.status='withdrawn' OR (p.status='rejected' AND p.decided_by=p.submitted_by))"
WITHDRAWAL_REASON = 'Withdrawn by the Student before Owner review.'
TABLES=('payments','payment_evidence','receipts','payment_events')
STUDENT_BILL_PAGE_SIZE=15
BILL_SELECT='''SELECT m.*,b.owner_id FROM monthly_bills m
    JOIN boardings b ON b.boarding_id=m.boarding_id'''
PAYMENT_SELECT='''SELECT p.*,m.bill_reference,m.period_start,m.final_total AS bill_amount,m.due_date,m.state AS bill_state,
    m.student_id,m.recipient_name,m.recipient_email,m.boarding_snapshot,m.unit_snapshot,b.owner_id,
    r.receipt_id,r.receipt_reference,e.evidence_id,e.stored_filename,e.media_type,e.byte_count,e.sha256,
    decider.full_name AS decider_name FROM payments p JOIN monthly_bills m ON m.bill_id=p.bill_id
    JOIN boardings b ON b.boarding_id=m.boarding_id
    LEFT JOIN receipts r ON r.payment_id=p.payment_id LEFT JOIN payment_evidence e ON e.payment_id=p.payment_id
    LEFT JOIN users decider ON decider.user_id=p.decided_by'''


class PaymentNotFound(LookupError): pass
class PaymentConflict(RuntimeError): pass
class PaymentValidationError(ValueError):
    def __init__(self,message,field='form'):
        super().__init__(message); self.errors={field:message}


def _json(value): return json.loads(value) if isinstance(value,(str,bytes,bytearray)) else value
def _was_withdrawn(payment):
    return payment['status']=='withdrawn' or (
        payment['status']=='rejected' and payment['decided_by']==payment['submitted_by'])


def _display_status(payment):
    if _was_withdrawn(payment):
        payment['status']='withdrawn'
    return payment


def _scope(actor,role):
    if role not in ('owner','student'): raise PaymentNotFound()
    return ('b.owner_id' if role=='owner' else 'm.student_id')+'=%s',(actor,)


def _bill(cursor,actor,role,bill_id,lock=False):
    where,args=_scope(actor,role)
    cursor.execute(BILL_SELECT+' WHERE m.bill_id=%s AND '+where+(' FOR UPDATE' if lock else ''),(bill_id,*args))
    row=cursor.fetchone()
    if row is None: raise PaymentNotFound()
    return row


@contextmanager
def _transaction(actor,role,bill_id,credential=None):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED')
            hint=_bill(cursor,actor,role,bill_id)
            # Match Student -> Boarding -> Cycle -> Owner lock order used by
            # billing/tenancy writers, then lock the authoritative issued bill.
            cursor.execute("SELECT user_id,is_active,role FROM users WHERE user_id=%s"+account_guard()+" FOR UPDATE",(hint['student_id'],))
            student=cursor.fetchone()
            if role=='student' and (not student or not student['is_active'] or student['role']!='student'):
                raise PaymentConflict('Your account changed. Log in again.')
            cursor.execute('SELECT owner_id FROM boardings WHERE boarding_id=%s FOR UPDATE',(hint['boarding_id'],))
            boarding=cursor.fetchone()
            if not boarding or boarding['owner_id']!=hint['owner_id']: raise PaymentConflict('Boarding ownership changed. Refresh and try again.')
            cursor.execute('SELECT cycle_id FROM billing_cycles WHERE cycle_id=%s FOR UPDATE',(hint['cycle_id'],)); cursor.fetchone()
            cursor.execute("SELECT user_id,full_name,password_hash FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard()+" FOR UPDATE",(hint['owner_id'],))
            owner=cursor.fetchone()
            if not owner: raise PaymentConflict('The boarding Owner account is unavailable. Try again later.')
            if role=='owner' and (not credential or not secrets.compare_digest(password_stamp(owner['password_hash']),credential)):
                raise PaymentConflict('Your account changed. Log in again and confirm your current password.')
            bill=_bill(cursor,actor,role,bill_id,True)
            yield cursor,bill,owner
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):
                raise PaymentConflict('Another request already changed this bill or payment. Refresh its history before trying again.') from None
            raise


def _issued(bill):
    if bill['state']!='issued': raise PaymentConflict('Only a current issued bill can be paid. This bill was voided or replaced.')


def _key(form):
    key=form.get('request_key','')
    if not re.fullmatch(r'[a-f0-9]{32}',key): raise PaymentValidationError('Refresh this form before submitting again.')
    return key


def _text(form,name,limit,required=False):
    value=form.get(name,'').strip()
    if required and not value or len(value)>limit or any(ord(c)<32 and c not in '\n\r\t' for c in value):
        raise PaymentValidationError('Enter '+name.replace('_',' ').title()+' using no more than '+str(limit)+' characters.',name)
    if name in ('transaction_reference','bank_name') and any(c in value for c in '\n\r\t'):
        raise PaymentValidationError('Use a single line for this field.',name)
    return value or None


def _date(form):
    value=form.get('payment_date','')
    try:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value): raise ValueError()
        result=date.fromisoformat(value)
        if not date(2000,1,1)<=result<=local_today(): raise ValueError()
        return result
    except (ValueError,TypeError): raise PaymentValidationError('Choose a valid payment date, today or earlier.','payment_date') from None


def _amount(form,bill):
    value=form.get('amount','')
    if not re.fullmatch(r'[0-9]{1,14}(?:\.[0-9]{1,2})?',value) or Decimal(value)!=bill['final_total']:
        raise PaymentValidationError('The full amount must exactly match the issued bill. Partial or excess payments are not supported.','amount')


def _active(cursor,bill_id):
    cursor.execute("SELECT * FROM payments WHERE bill_id=%s AND status IN ('submitted','verified') FOR UPDATE",(bill_id,))
    return cursor.fetchone()


def _same_request(cursor,actor,key,bill_id):
    cursor.execute('SELECT payment_id,bill_id,status,submitted_by,decided_by FROM payments WHERE submitted_by=%s AND request_key=%s',(actor,key))
    row=cursor.fetchone()
    if row and _was_withdrawn(row):
        raise PaymentConflict('This submission was withdrawn. Reopen the upload form to send a replacement.')
    if row and row['bill_id']!=bill_id: raise PaymentConflict('This form was already used for another bill. Open a fresh form.')
    return row


def _event(cursor,payment_id,actor,kind,details):
    cursor.execute('INSERT INTO payment_events(payment_id,actor_id,event_type,details,created_at) VALUES(%s,%s,%s,%s,UTC_TIMESTAMP(6))',
        (payment_id,actor,kind,canonical(details)))


def _new_payment(cursor,actor,bill,method,status,form,key):
    reference='PAY-'+local_today().strftime('%Y%m')+'-'+uuid.uuid4().hex[:16].upper()
    cursor.execute('''INSERT INTO payments(payment_reference,bill_id,amount,method,status,payment_date,bank_name,
        transaction_reference,note,submitted_by,submitted_at,request_key) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6),%s)''',
        (reference,bill['bill_id'],bill['final_total'],method,status,_date(form),
         _text(form,'bank_name',100) if method=='bank_transfer' else None,
         _text(form,'transaction_reference',100,True) if method=='bank_transfer' else None,_text(form,'note',500),actor,key))
    return cursor.lastrowid


def _cleanup_unreferenced(filename):
    if not filename: return
    try:
        # A lost COMMIT acknowledgement must never delete committed evidence.
        # If MySQL cannot confirm absence, retain the file for controlled review.
        with get_db_connection() as connection,connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM payment_evidence WHERE stored_filename=%s LIMIT 1',(filename,))
            if not cursor.fetchone(): evidence_path(filename).unlink(missing_ok=True)
    except (Error,OSError): current_app.logger.warning('Payment evidence cleanup needs a controlled review; no evidence was deleted blindly.')


def submit_bank_transfer(student_id,bill_id,form,upload,*,mobile_token=None):
    # Bank settings supply instructions for future transfers. Evidence for an
    # existing transfer goes to the Owner for independent verification.
    key=_key(form)
    # Check ownership before processing private content or using parser resources.
    detail=load_bill(student_id,'student',bill_id); _issued(detail); _amount(form,detail)
    if detail['final_total']==0: raise PaymentConflict('No transfer is needed for this zero-amount bill. The Owner must record a non-cash settlement.')
    _date(form); _text(form,'transaction_reference',100,True); _text(form,'bank_name',100); _text(form,'note',500)
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        existing=_same_request(cursor,student_id,key,bill_id)
        if existing and mobile_token is None: return existing['payment_id']
    if detail['active_payment']:
        raise PaymentConflict('A pending or verified payment already exists for this bill. Check My Payments.')
    slip=validate_slip(upload); filename=None
    if mobile_token:
        from payment_files import sanitize_mobile_slip
        slip=sanitize_mobile_slip(slip)
    try:
        with _transaction(student_id,'student',bill_id) as (cursor,bill,_):
            _issued(bill); _amount(form,bill)
            if mobile_token:
                from mobile_payment_service import validate_link,UploadLinkError
                capability=validate_link(cursor,mobile_token,lock=True)
                if capability['student_id']!=student_id or capability['bill_id']!=bill_id or capability['request_key']!=key:
                    raise UploadLinkError('This upload link does not match the invoice.')
            existing=_same_request(cursor,student_id,key,bill_id)
            if existing: return existing['payment_id']
            if _active(cursor,bill_id): raise PaymentConflict('A pending or verified payment already exists for this bill. Check My Payments.')
            payment_id=_new_payment(cursor,student_id,bill,'bank_transfer','submitted',form,key)
            filename=store_slip(slip)
            cursor.execute('INSERT INTO payment_evidence(payment_id,stored_filename,media_type,byte_count,sha256,created_at) VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))',
                (payment_id,filename,slip['media_type'],slip['byte_count'],slip['sha256']))
            _event(cursor,payment_id,student_id,'submitted',{'bill_id':bill_id,'amount':bill['final_total'],'evidence_sha256':slip['sha256']})
            if mobile_token:
                from mobile_payment_service import consume_link
                consume_link(cursor,mobile_token,bill,payment_id)
            if current_app.config.get('MOBILE_SLIP_ENABLED'):
                from payment_notifications import enqueue
                enqueue(cursor,payment_id,bill['owner_id'])
        return payment_id
    except Exception:
        _cleanup_unreferenced(filename); raise


def _receipt(cursor,payment,bill,owner):
    snapshot={'payment_reference':payment['payment_reference'],'bill_reference':bill['bill_reference'],
        'student_id':bill['student_id'],'student_name':bill['recipient_name'],'student_email':bill['recipient_email'],
        'boarding':_json(bill['boarding_snapshot']),'unit':_json(bill['unit_snapshot']),'billing_month':bill['period_start'].strftime('%B %Y'),
        'amount':format(payment['amount'],'.2f'),'method':payment['method'],'payment_date':payment['payment_date'].isoformat(),
        'verified_at':payment['decided_at'].isoformat(),'verified_by':owner['full_name'],'zero_balance':payment['method']=='zero_balance'}
    reference='RCT-'+local_today().strftime('%Y%m')+'-'+uuid.uuid4().hex[:16].upper()
    cursor.execute('INSERT INTO receipts(receipt_reference,payment_id,bill_id,snapshot,snapshot_sha256,issued_at) VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))',
        (reference,payment['payment_id'],bill['bill_id'],canonical(snapshot),digest(snapshot)))
    return cursor.lastrowid


def decide_payment(owner_id,payment_id,decision,form,credential):
    hint=load_payment(owner_id,'owner',payment_id)
    if decision not in ('verify','reject'): raise PaymentValidationError('Choose Verify or Reject.')
    reason=_text(form,'rejection_reason',500,True) if decision=='reject' else None
    if form.get('confirm_decision')!='yes': raise PaymentValidationError('Confirm the decision before saving.','confirm_decision')
    if decision=='verify' and form.get('confirm_received')!='yes': raise PaymentValidationError('Independently confirm the full transfer was received.','confirm_received')
    with _transaction(owner_id,'owner',hint['bill_id'],credential) as (cursor,bill,owner):
        _issued(bill)
        cursor.execute('SELECT * FROM payments WHERE payment_id=%s AND bill_id=%s FOR UPDATE',(payment_id,bill['bill_id']))
        payment=cursor.fetchone()
        target='verified' if decision=='verify' else 'rejected'
        if _was_withdrawn(payment):
            raise PaymentConflict('The Student withdrew this slip before review. Refresh your payment list.')
        if payment['status']==target:
            if target=='verified':
                cursor.execute('SELECT receipt_id FROM receipts WHERE payment_id=%s AND bill_id=%s',(payment_id,bill['bill_id']))
                if not cursor.fetchone() or payment['amount']!=bill['final_total']:
                    raise PaymentConflict('This verification needs a financial integrity review; no duplicate receipt was created.')
            return payment_id # Idempotent retry preserves the original decision/receipt.
        if payment['status']!='submitted' or payment['method']!='bank_transfer': raise PaymentConflict('This payment was already decided. Refresh its current details.')
        if str(payment['revision'])!=form.get('revision',''): raise PaymentConflict('This payment changed. Refresh before confirming again.')
        if payment['amount']!=bill['final_total'] or payment['amount']<=0: raise PaymentConflict('Payment amount does not match the issued bill. No decision was saved.')
        active=_active(cursor,bill['bill_id'])
        if not active or active['payment_id']!=payment_id: raise PaymentConflict('A conflicting payment already exists for this bill.')
        cursor.execute('SELECT * FROM payment_evidence WHERE payment_id=%s',(payment_id,))
        evidence=cursor.fetchone()
        if decision=='verify':
            if not evidence: raise PaymentConflict('Bank-slip evidence is unavailable. No verification was saved.')
            path=evidence_path(evidence['stored_filename'])
            try:
                if not path.is_file() or path.stat().st_size!=evidence['byte_count'] or hashlib.sha256(path.read_bytes()).hexdigest()!=evidence['sha256']:
                    raise PaymentConflict('Bank-slip evidence needs an integrity review. No decision was saved.')
            except OSError: raise PaymentConflict('Bank-slip evidence could not be read. No decision was saved.') from None
        cursor.execute('UPDATE payments SET status=%s,decided_by=%s,decided_at=UTC_TIMESTAMP(6),rejection_reason=%s,revision=revision+1 WHERE payment_id=%s',
            (target,owner_id,reason,payment_id))
        cursor.execute('SELECT * FROM payments WHERE payment_id=%s',(payment_id,)); saved=cursor.fetchone()
        receipt_id=_receipt(cursor,saved,bill,owner) if decision=='verify' else None
        _event(cursor,payment_id,owner_id,target,{'bill_id':bill['bill_id'],'amount':saved['amount'],'reason':reason,'receipt_id':receipt_id})
    return payment_id


def withdraw_payment(student_id, payment_id):
    hint = load_payment(student_id, 'student', payment_id)
    with _transaction(student_id, 'student', hint['bill_id']) as (cursor, bill, _):
        _issued(bill)
        # Owner decisions lock the same bill before checking the pending state.
        cursor.execute('''SELECT status, method, submitted_by, decided_by FROM payments
            WHERE payment_id=%s AND bill_id=%s FOR UPDATE''', (payment_id, bill['bill_id']))
        payment = cursor.fetchone()
        if not payment or payment['submitted_by'] != student_id or payment['method'] != 'bank_transfer':
            raise PaymentNotFound()
        if _was_withdrawn(payment):
            return bill['bill_id']
        if payment['status'] != 'submitted':
            raise PaymentConflict('The Owner has already reviewed this slip. It can no longer be deleted.')
        cursor.execute('''UPDATE payments SET status='rejected', decided_by=%s,
            rejection_reason=%s, decided_at=UTC_TIMESTAMP(6), revision=revision+1
            WHERE payment_id=%s''', (student_id, WITHDRAWAL_REASON, payment_id))
        _event(cursor, payment_id, student_id, 'rejected', {'bill_id': bill['bill_id'], 'action': 'student_withdrawal'})
    return hint['bill_id']


def record_cash(owner_id,bill_id,form,credential):
    key=_key(form)
    if form.get('confirm_received')!='yes': raise PaymentValidationError('Confirm the full cash was received, or explicitly confirm a zero-balance settlement.','confirm_received')
    with _transaction(owner_id,'owner',bill_id,credential) as (cursor,bill,owner):
        _issued(bill); _amount(form,bill); _date(form); _text(form,'note',500)
        existing=_same_request(cursor,owner_id,key,bill_id)
        if existing: return existing['payment_id']
        if _active(cursor,bill_id): raise PaymentConflict('A pending or verified payment exists. Review it first; cash cannot bypass an existing submission.')
        method='zero_balance' if bill['final_total']==0 else 'cash'
        if form.get('settlement_method')!=method: raise PaymentValidationError('Review the selected bill and confirm its actual settlement method.')
        # Insert a valid submitted bank record is not appropriate for cash. Create
        # the already-confirmed decision and receipt in one atomic transaction.
        reference='PAY-'+local_today().strftime('%Y%m')+'-'+uuid.uuid4().hex[:16].upper()
        cursor.execute('''INSERT INTO payments(payment_reference,bill_id,amount,method,status,payment_date,note,
            submitted_by,submitted_at,decided_by,decided_at,request_key) VALUES(%s,%s,%s,%s,'verified',%s,%s,%s,UTC_TIMESTAMP(6),%s,UTC_TIMESTAMP(6),%s)''',
            (reference,bill_id,bill['final_total'],method,_date(form),_text(form,'note',500),owner_id,owner_id,key))
        payment_id=cursor.lastrowid
        cursor.execute('SELECT * FROM payments WHERE payment_id=%s',(payment_id,)); payment=cursor.fetchone()
        receipt_id=_receipt(cursor,payment,bill,owner)
        _event(cursor,payment_id,owner_id,'zero_settled' if method=='zero_balance' else 'cash_recorded',
            {'bill_id':bill_id,'amount':bill['final_total'],'receipt_id':receipt_id,'no_money_collected':method=='zero_balance'})
    return payment_id


def _bill_state(bill,active):
    if bill['state']=='void': return 'Void'
    if active and active['status']=='verified' and not active.get('receipt_id'): return 'Verification Needs Review'
    if active and active['status']=='verified': return 'Settled — No Payment Due' if active['method']=='zero_balance' else 'Paid'
    if active: return 'Pending Verification'
    if bill['final_total']==0: return 'Awaiting Zero-Balance Settlement'
    return 'Overdue' if bill['due_date']<local_today() else 'Unpaid'


def student_bill_state(bill,active,rejected=False):
    """The debt can stay overdue while transfer evidence awaits verification."""
    settled=bool(active and active['status']=='verified' and active.get('receipt_id'))
    if bill['state']!='issued':label='Void'
    elif active and active['status']=='verified' and not settled:label='Verification Needs Review'
    elif bill['final_total']==0:label='No Payment Due'
    elif settled:label='Paid'
    else:label='Overdue' if bill['due_date']<local_today() else 'Unpaid'
    submission=('Payment Verification Pending' if active and active['status']=='submitted' else
        'Payment already verified.' if settled else 'Previous Payment Rejected' if rejected else '')
    return {'bill_status':label,'submission_status':submission,'bill_tone':
        'verified' if settled else 'rejected' if label=='Overdue' else 'submitted' if label=='Unpaid' else 'neutral'}


def load_bill(actor,role,bill_id):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        bill=_bill(cursor,actor,role,bill_id)
        for field in ('boarding_snapshot','unit_snapshot'): bill[field]=_json(bill[field])
        cursor.execute("SELECT p.payment_id,p.status,p.method,p.submitted_by,r.receipt_id FROM payments p LEFT JOIN receipts r ON r.payment_id=p.payment_id WHERE p.bill_id=%s AND p.status IN ('submitted','verified')",(bill_id,))
        active=cursor.fetchone(); bill['active_payment']=active; bill['payment_status']=_bill_state(bill,active)
        bill['can_submit']=bill['state']=='issued' and not active and bill['final_total']>0
        cursor.execute('SELECT * FROM bill_line_items WHERE bill_id=%s ORDER BY line_number',(bill_id,)); bill['lines']=cursor.fetchall()
        for line in bill['lines']:line['details']=_json(line['details'])
        cursor.execute('''SELECT payment_id,payment_reference,method,status,payment_date,submitted_at,
            decided_at,decided_by,submitted_by,rejection_reason FROM payments WHERE bill_id=%s
            ORDER BY payment_id DESC''',(bill_id,))
        bill['payments']=[_display_status(item) for item in cursor.fetchall() if role!='owner' or not _was_withdrawn(item)]
        bill['bank_instructions']=student_bank_instructions(cursor,actor,bill_id) if role=='student' and bill['can_submit'] else None
        bill['transfer_eligible']=bill['can_submit']
        bill.update(student_bill_state(bill,active,any(item['status']=='rejected' for item in bill['payments'])))
        cursor.execute('SELECT eligible_from,eligible_until,eligible_days,calendar_days,agreed_rent FROM billing_allocations WHERE allocation_id=%s AND tenancy_id=%s',(bill['allocation_id'],bill['tenancy_id']))
        bill['allocation']=cursor.fetchone()
        return bill


def load_payment(actor,role,payment_id):
    where,args=_scope(actor,role)
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute(PAYMENT_SELECT+' WHERE p.payment_id=%s AND '+where,(payment_id,*args)); row=cursor.fetchone()
        if row: _display_status(row)
        if not row or (role=='owner' and row['status']=='withdrawn'): raise PaymentNotFound()
        for field in ('boarding_snapshot','unit_snapshot'): row[field]=_json(row[field])
        cursor.execute('SELECT event_type,details,created_at FROM payment_events WHERE payment_id=%s ORDER BY event_id',(payment_id,))
        row['events']=cursor.fetchall()
        for event in row['events']:
            event['details']=_json(event['details'])
            if event['event_type']=='rejected' and event['details'].get('action')=='student_withdrawal':
                event['event_type']='withdrawn'
        return row


def load_receipt(actor,role,receipt_id):
    where,args=_scope(actor,role)
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        cursor.execute('''SELECT r.* FROM receipts r JOIN payments p ON p.payment_id=r.payment_id
            JOIN monthly_bills m ON m.bill_id=r.bill_id JOIN boardings b ON b.boarding_id=m.boarding_id
            WHERE r.receipt_id=%s AND p.status='verified' AND '''+where,(receipt_id,*args))
        row=cursor.fetchone()
        if not row: raise PaymentNotFound()
        row['snapshot']=_json(row['snapshot'])
        if digest(row['snapshot'])!=row['snapshot_sha256']: raise PaymentConflict('This receipt needs an integrity review. Contact the Owner.')
        row['verified_time']=datetime.fromisoformat(row['snapshot']['verified_at'])
        return row


def parse_filters(params,role):
    first=local_today().replace(day=1); next_month=(first.replace(day=28)+timedelta(days=4)).replace(day=1)
    status=params.get('status','submitted' if role=='owner' else '').strip()
    reporting_month=role=='owner' and status!='submitted'
    values={name:params.get(name,default).strip() for name,default in (
        ('q',''),('status',status),('method',''),('from',first.isoformat() if reporting_month else ''),
        ('to',(next_month-timedelta(days=1)).isoformat() if reporting_month else ''),('sort','newest'),('page','1'))}
    allowed_statuses = ('', 'submitted', 'verified', 'rejected') if role=='owner' else ('', *STATUSES)
    if (len(values['q'])>150 or any(ord(c)<32 for c in values['q']) or values['status'] not in allowed_statuses
        or values['method'] not in ('',*METHODS) or values['sort'] not in ('newest','oldest')
        or not re.fullmatch(r'[0-9]{1,6}',values['page']) or int(values['page'])<1): raise PaymentValidationError('Choose valid payment filters.')
    try:
        start=date.fromisoformat(values['from']) if values['from'] else None
        end=date.fromisoformat(values['to']) if values['to'] else None
        if start and end and start>end: raise ValueError()
    except ValueError: raise PaymentValidationError('Choose a valid reporting date range.') from None
    return values


def load_history(actor,role,params):
    values=parse_filters(params,role); where,args=_scope(actor,role); args=list(args)
    status=values['status']
    where+=(' AND ' if status=='withdrawn' else ' AND NOT ')+WITHDRAWN_SQL
    if values['from']: where+=' AND DATE(COALESCE(p.decided_at,p.submitted_at)+INTERVAL 330 MINUTE)>=%s'; args.append(values['from'])
    if values['to']: where+=' AND DATE(COALESCE(p.decided_at,p.submitted_at)+INTERVAL 330 MINUTE)<=%s'; args.append(values['to'])
    if values['method']: where+=' AND p.method=%s'; args.append(values['method'])
    joins=' FROM payments p JOIN monthly_bills m ON m.bill_id=p.bill_id JOIN boardings b ON b.boarding_id=m.boarding_id'
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute("SELECT SUM(p.status='submitted') AS pending,SUM(p.status='verified') AS verified,SUM(p.status='rejected' AND NOT "+WITHDRAWN_SQL+") AS rejected,COALESCE(SUM(CASE WHEN p.status='verified' THEN p.amount ELSE 0 END),0) AS collected"+joins+' WHERE '+where,tuple(args))
        summary=cursor.fetchone()
        for key in ('pending','verified','rejected'): summary[key]=int(summary[key] or 0)
        if status and status!='withdrawn': where+=' AND p.status=%s'; args.append(status)
        if values['q']:
            escaped=values['q'].replace('!','!!').replace('%','!%').replace('_','!_')
            where+=" AND (m.recipient_name LIKE %s ESCAPE '!' OR m.bill_reference LIKE %s ESCAPE '!' OR p.payment_reference LIKE %s ESCAPE '!' OR p.transaction_reference LIKE %s ESCAPE '!')"
            args+=['%'+escaped+'%']*4
        cursor.execute('SELECT COUNT(*) AS total'+joins+' WHERE '+where,tuple(args)); total=cursor.fetchone()['total']
        pages=max(1,math.ceil(total/15)); page=min(int(values['page']),pages)
        order=' DESC' if values['sort']=='newest' else ' ASC'
        cursor.execute(PAYMENT_SELECT+' WHERE '+where+' ORDER BY p.submitted_at'+order+',p.payment_id'+order+' LIMIT 15 OFFSET %s',(*args,(page-1)*15))
        rows=[_display_status(item) for item in cursor.fetchall()]
        approvals=recent_payment_approvals(cursor,actor) if role=='student' else []
        return dict(rows=rows,summary=summary,total=total,page=page,page_count=pages,filters=values,payment_approvals=approvals)


def recent_payment_approvals(cursor,student_id):
    """Read durable notices from committed Owner approvals and their receipts."""
    cursor.execute('''SELECT m.bill_reference,p.amount,p.decided_at,r.receipt_id
        FROM monthly_bills m
        JOIN payments p ON p.bill_id=m.bill_id
        JOIN receipts r ON r.payment_id=p.payment_id AND r.bill_id=m.bill_id
        WHERE m.student_id=%s AND m.state='issued' AND p.method='bank_transfer'
          AND p.status='verified' AND p.decided_at IS NOT NULL
        ORDER BY p.decided_at DESC,p.payment_id DESC LIMIT 5''',(student_id,))
    return cursor.fetchall()


def student_bill_filters(params):
    if isinstance(params,str):params={'page':params}
    values={key:params.get(key,default).strip() for key,default in (('q',''),('status',''),('sort','newest'),('page','1'))}
    if len(values['q'])>150 or any(ord(c)<32 for c in values['q']) or values['status'] not in ('','unpaid','overdue','paid','void','zero') or values['sort'] not in ('newest','oldest') or not re.fullmatch(r'[1-9][0-9]{0,5}',values['page']):
        raise PaymentValidationError('Choose valid bill search, status, order and page values.')
    return values


STUDENT_BILLS_FROM=""" FROM monthly_bills m
    JOIN boardings b ON b.boarding_id=m.boarding_id
    LEFT JOIN payments p ON p.bill_id=m.bill_id AND p.status IN ('submitted','verified')
    LEFT JOIN receipts r ON r.payment_id=p.payment_id"""
SETTLED="p.status='verified' AND r.receipt_id IS NOT NULL"
UNPAID_FOR_TRANSFER="m.state='issued' AND m.final_total>0 AND p.payment_id IS NULL"
OWNER_BANK_AVAILABLE="""EXISTS (SELECT 1 FROM owner_settings s WHERE s.owner_id=b.owner_id
        AND s.bank_boarding_id=b.boarding_id AND s.account_number IS NOT NULL)"""


def my_bills(student_id,page_value='1'):
    values=student_bill_filters(page_value);where=' WHERE m.student_id=%s';args=[student_id]
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute("SELECT COALESCE(SUM(m.state='issued'),0) AS total_issued,COALESCE(SUM(m.state='issued' AND "+SETTLED+"),0) AS paid,COALESCE(SUM(CASE WHEN m.state='issued' AND NOT ("+SETTLED+") THEN m.final_total ELSE 0 END),0) AS outstanding"+STUDENT_BILLS_FROM+where,tuple(args))
        summary=cursor.fetchone();summary['total_issued']=int(summary['total_issued']);summary['paid']=int(summary['paid'])
        if values['status']:
            conditions={'paid':"m.state='issued' AND "+SETTLED,'void':"m.state='void'",'zero':"m.state='issued' AND m.final_total=0",
                'unpaid':"m.state='issued' AND m.final_total>0 AND NOT ("+SETTLED+") AND m.due_date>=%s",
                'overdue':"m.state='issued' AND m.final_total>0 AND NOT ("+SETTLED+") AND m.due_date<%s"}
            where+=' AND '+conditions[values['status']]
            if values['status'] in ('unpaid','overdue'):args.append(local_today())
        if values['q']:
            needle='%'+values['q'].replace('!','!!').replace('%','!%').replace('_','!_')+'%'
            where+=" AND (m.bill_reference LIKE %s ESCAPE '!' OR DATE_FORMAT(m.period_start,'%M %Y') LIKE %s ESCAPE '!' OR DATE_FORMAT(m.period_start,'%Y-%m') LIKE %s ESCAPE '!')";args.extend([needle]*3)
        cursor.execute('SELECT COUNT(*) AS total'+STUDENT_BILLS_FROM+where,tuple(args));total=cursor.fetchone()['total']
        pages=max(1,math.ceil(total/STUDENT_BILL_PAGE_SIZE));page=min(int(values['page']),pages);direction=' DESC' if values['sort']=='newest' else ' ASC'
        cursor.execute('SELECT m.*,p.payment_id,p.status AS active_status,p.method AS active_method,r.receipt_id,('+UNPAID_FOR_TRANSFER+") AS can_transfer,EXISTS(SELECT 1 FROM payments rejected WHERE rejected.bill_id=m.bill_id AND rejected.status='rejected' AND rejected.decided_by<>rejected.submitted_by) AS had_rejection"+STUDENT_BILLS_FROM+where+' ORDER BY m.issued_at'+direction+',m.bill_id'+direction+' LIMIT %s OFFSET %s',(*args,STUDENT_BILL_PAGE_SIZE,(page-1)*STUDENT_BILL_PAGE_SIZE))
        rows=cursor.fetchall()
        for row in rows:
            for field in ('boarding_snapshot','unit_snapshot'): row[field]=_json(row[field])
            active={'status':row['active_status'],'method':row['active_method'],'receipt_id':row['receipt_id']} if row['active_status'] else None
            row['payment_status']=_bill_state(row,active);row['can_submit']=bool(row['can_transfer'])
            row.update(student_bill_state(row,active,row['had_rejection']))
        return dict(rows=rows,total=total,page=page,page_count=pages,filters=values,summary=summary)


def student_submission_options(student_id,page_value='1'):
    if not re.fullmatch(r'[1-9][0-9]{0,5}',page_value):raise PaymentValidationError('Choose a valid bill selection page.')
    scope=' WHERE m.student_id=%s AND '+UNPAID_FOR_TRANSFER
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute('SELECT COUNT(*) AS total'+STUDENT_BILLS_FROM+scope,(student_id,));total=int(cursor.fetchone()['total'])
        pages=max(1,math.ceil(total/STUDENT_BILL_PAGE_SIZE));page=min(int(page_value),pages)
        cursor.execute('SELECT m.bill_id,m.bill_reference,m.period_start,m.final_total,m.due_date,('+OWNER_BANK_AVAILABLE+') AS bank_ready'+STUDENT_BILLS_FROM+scope+' ORDER BY m.due_date,m.bill_id LIMIT %s OFFSET %s',(student_id,STUDENT_BILL_PAGE_SIZE,(page-1)*STUDENT_BILL_PAGE_SIZE))
        return {'rows':cursor.fetchall(),'total':total,'page':page,'page_count':pages}


def cash_options(owner_id,search=''):
    search=search.strip()
    if len(search)>150 or any(ord(c)<32 for c in search): raise PaymentValidationError('Use no more than 150 characters for bill search.')
    where=" WHERE b.owner_id=%s AND m.state='issued' AND NOT EXISTS (SELECT 1 FROM payments p WHERE p.bill_id=m.bill_id AND p.status IN ('submitted','verified'))"; args=[owner_id]
    if search:
        escaped=search.replace('!','!!').replace('%','!%').replace('_','!_'); where+=" AND (m.recipient_name LIKE %s ESCAPE '!' OR m.bill_reference LIKE %s ESCAPE '!')"; args+=['%'+escaped+'%']*2
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        cursor.execute(BILL_SELECT+where+' ORDER BY m.issued_at DESC,m.bill_id DESC LIMIT 200',tuple(args)); return cursor.fetchall()


def bill_payment_summary(cursor,bill):
    """Expose the one authoritative settlement state without a second Paid flag."""
    cursor.execute("SELECT 1 AS available FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='payments' LIMIT 1")
    if not cursor.fetchone(): return {'available':False,'label':'Unpaid','payment_id':None,'receipt_id':None}
    cursor.execute("SELECT p.payment_id,p.status,p.method,r.receipt_id FROM payments p LEFT JOIN receipts r ON r.payment_id=p.payment_id WHERE p.bill_id=%s AND p.status IN ('submitted','verified')",(bill['bill_id'],))
    active=cursor.fetchone()
    return {'available':True,'label':_bill_state(bill,active),'payment_id':active['payment_id'] if active else None,'receipt_id':active['receipt_id'] if active else None}
