"""Owner-scoped billing snapshots, atomic issuance and audited corrections."""
from contextlib import contextmanager
from datetime import date,timedelta
from decimal import Decimal
import json
import math
import re
import secrets
import uuid

from flask import current_app
from itsdangerous import BadSignature,SignatureExpired,URLSafeTimedSerializer
from mysql.connector import Error

from auth_email import password_stamp
from billing_calculator import BillingValidationError,ZERO,calculate_bills,canonical,digest,input_amount,month_period,selected_summary
from db import get_db_connection
from payment_service import bill_payment_summary
from admin_security import account_guard
from billing_sources import enabled,utility_sources,sync_sources,assert_sources,current_sources,snapshot_sources
from tenancy_service import local_today

TABLES=('billing_cycles','billing_adjustments','billing_adjustment_targets','billing_allocations','monthly_bills','bill_line_items','billing_audit_events')
BOARDING_COLUMNS='boarding_id,boarding_name,address,city,district,contact_phone,contact_email'
TENANT_SQL='''SELECT t.tenancy_id,t.student_id,t.boarding_id,t.room_id,t.bed_id,t.start_date,t.end_date,
    t.tenancy_status,t.rent_unit,t.agreed_monthly_rent,t.bed_rate_id,t.room_rate_id,
    u.full_name AS student_name,u.email AS student_email,r.room_number,bed.bed_label
    FROM tenancies t JOIN users u ON u.user_id=t.student_id
    JOIN rooms r ON r.room_id=t.room_id AND r.boarding_id=t.boarding_id
    LEFT JOIN beds bed ON bed.bed_id=t.bed_id AND bed.room_id=t.room_id
    JOIN join_requests j ON j.request_id=t.source_request_id AND j.student_id=t.student_id
        AND j.boarding_id=t.boarding_id AND j.status='approved' WHERE t.boarding_id=%s'''


class BillingConflict(RuntimeError): pass
class BillingNotFound(LookupError): pass


def identifier(value,field='record'):
    if not isinstance(value,str) or not re.fullmatch(r'[1-9][0-9]{0,9}',value) or int(value)>4294967295:
        raise BillingValidationError('Choose a valid '+field+'.',field)
    return int(value)


def selected_ids(values):
    if len(values)>500: raise BillingValidationError('Generate no more than 500 bills in one operation.','selected_ids')
    return sorted({identifier(value,'tenancy') for value in values})


def due_date(value,period):
    try:
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value): raise ValueError()
        result=date.fromisoformat(value)
        if result<period: raise ValueError()
        return result
    except (ValueError,TypeError): raise BillingValidationError('Due Date must be a valid date on/after the billing month starts.','due_date') from None


def default_due_date(period):
    """Issue during the month; payment defaults to that month's final day."""
    return month_period(period.strftime('%Y-%m'))[1]-timedelta(days=1)


def _json(value): return json.loads(value) if isinstance(value,(str,bytes,bytearray)) else value


def _audit(cursor,cycle_id,owner_id,kind,details,reason=None,bill_id=None):
    cursor.execute('''INSERT INTO billing_audit_events(cycle_id,bill_id,actor_id,event_type,reason,details,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(cycle_id,bill_id,owner_id,kind,reason,canonical(details)))


def _cycle(cursor,owner_id,cycle_id,lock=False):
    cursor.execute('''SELECT c.* FROM billing_cycles c JOIN boardings b ON b.boarding_id=c.boarding_id
        WHERE c.cycle_id=%s AND b.owner_id=%s'''+(' FOR UPDATE' if lock else ''),(cycle_id,owner_id))
    row=cursor.fetchone()
    if row is None: raise BillingNotFound()
    return row


@contextmanager
def _transaction(owner_id,cycle_id=None,students=False,credential=None):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED')
            cursor.execute('SELECT '+BOARDING_COLUMNS+' FROM boardings WHERE owner_id=%s',(owner_id,))
            hint=cursor.fetchone()
            if hint is None: raise BillingValidationError('Create your Boarding Profile before configuring monthly bills.')
            locked_students=set()
            if students:
                # Bill/student FKs must not reverse Student -> Boarding locks used by
                # approval/lifecycle. Lock all existing Student parents in ID order.
                cursor.execute('SELECT DISTINCT student_id FROM tenancies WHERE boarding_id=%s ORDER BY student_id',(hint['boarding_id'],))
                locked_students={row['student_id'] for row in cursor.fetchall()}
                if locked_students:
                    marks=','.join(['%s']*len(locked_students))
                    cursor.execute('SELECT user_id FROM users WHERE user_id IN ('+marks+') ORDER BY user_id FOR UPDATE',tuple(sorted(locked_students)))
                    cursor.fetchall()
            cursor.execute('SELECT '+BOARDING_COLUMNS+' FROM boardings WHERE owner_id=%s FOR UPDATE',(owner_id,))
            boarding=cursor.fetchone()
            if boarding is None: raise BillingNotFound()
            if students:
                cursor.execute('SELECT DISTINCT student_id FROM tenancies WHERE boarding_id=%s',(boarding['boarding_id'],))
                if not {row['student_id'] for row in cursor.fetchall()}<=locked_students:
                    raise BillingConflict('The tenancy list changed. Recalculate before trying again.')
            cycle=_cycle(cursor,owner_id,cycle_id,True) if cycle_id else None
            cursor.execute("SELECT password_hash FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard()+" FOR UPDATE",(owner_id,))
            account=cursor.fetchone()
            if not account or credential is not None and not secrets.compare_digest(password_stamp(account['password_hash']),credential):
                raise BillingConflict('Your account changed. Log in again and confirm the action.')
            yield cursor,boarding,cycle
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):
                raise BillingConflict('Another operation changed this billing period or a bill already exists. Refresh before trying again.') from None
            raise


def _version(cycle,value):
    if not re.fullmatch(r'[0-9]{1,10}',str(value)) or int(value)!=cycle['version']:
        raise BillingConflict('This billing period changed. Recalculate using its current inputs.')


def _draft(cycle):
    if cycle['state']!='draft':
        raise BillingConflict('Issued billing inputs are locked. Use the password-confirmed Correct Cycle flow.')


def _rules(cursor,cycle):
    cursor.execute('''SELECT * FROM billing_adjustments WHERE boarding_id=%s AND enabled=TRUE
        AND effective_from<=%s AND effective_to>=%s AND (recurrence='monthly' OR origin_cycle_id=%s)
        ORDER BY adjustment_id''',(cycle['boarding_id'],cycle['period_start'],cycle['period_start'],cycle['cycle_id']))
    rows=cursor.fetchall()
    for row in rows:
        cursor.execute('SELECT tenancy_id FROM billing_adjustment_targets WHERE adjustment_id=%s ORDER BY tenancy_id',(row['adjustment_id'],))
        row['targets']=[item['tenancy_id'] for item in cursor.fetchall()]
    return rows


def _calculate(cursor,cycle):
    cursor.execute(TENANT_SQL,(cycle['boarding_id'],))
    tenants=cursor.fetchall()
    rules=_rules(cursor,cycle)
    electricity=cycle['electricity_total'] if cycle['electricity_total'] is not None else ZERO
    water=cycle['water_total'] if cycle['water_total'] is not None else ZERO
    snapshot=snapshot_sources(cycle) if enabled() else {}
    shared=snapshot.get('shared_expenses',[]) if snapshot.get('allocation_policy')=='shared_other_v1' else []
    if cycle['state']=='draft' and snapshot.get('totals'):
        electricity=Decimal(str(snapshot['totals']['electricity'])) if snapshot['totals']['electricity'] is not None else ZERO
        water=Decimal(str(snapshot['totals']['water'])) if snapshot['totals']['water'] is not None else ZERO
    validation_error=None
    try:
        from shared_expense_policy import reject_duplicate_sources
        reject_duplicate_sources(shared,rules)
        result=calculate_bills(cycle['period_start'].strftime('%Y-%m'),tenants,rules,electricity,water,shared_expenses=shared)
    except BillingValidationError as invalid:
        # Keep invalid draft rules visible/removable, but never offer an issuable
        # total or signed token for a calculation that did not validate.
        validation_error=str(invalid)
        result=calculate_bills(cycle['period_start'].strftime('%Y-%m'),tenants,[],electricity,water,shared_expenses=shared)
    result['validation_error']=validation_error
    result['rules']=rules
    result['stale']=cycle['state']=='locked' and result['source_digest']!=cycle['source_digest']
    cursor.execute("SELECT bill_id,bill_reference,tenancy_id,final_total FROM monthly_bills WHERE cycle_id=%s AND state='issued'",(cycle['cycle_id'],))
    issued={row['tenancy_id']:row for row in cursor.fetchall()}
    if cycle['state']=='locked':
        cursor.execute('SELECT * FROM billing_allocations WHERE cycle_id=%s',(cycle['cycle_id'],))
        allocations={row['tenancy_id']:row for row in cursor.fetchall()}
        for row in result['rows']:
            stored=allocations.get(row['tenancy_id'])
            if stored:
                for field in ('allocation_id','eligible_from','eligible_until','eligible_days','calendar_days','total_tenant_days',
                    'agreed_rent','rent_amount','electricity_share','water_share','charge_amount','discount_amount','final_total'):
                    row[field]=stored[field]
                row['lines']=_json(stored['calculation'])['lines']
                for line in row['lines']: line['amount']=Decimal(line['amount'])
    saved_lines={}
    if issued:
        cursor.execute("""SELECT l.* FROM bill_line_items l JOIN monthly_bills m ON m.bill_id=l.bill_id
            WHERE m.cycle_id=%s AND m.state='issued' ORDER BY l.bill_id,l.line_number""",(cycle['cycle_id'],))
        for line in cursor.fetchall():
            line['details']=_json(line['details']);saved_lines.setdefault(line['bill_id'],[]).append(line)
    for row in result['rows']:
        row['issued_bill']=issued.get(row['tenancy_id'])
        if row['issued_bill']:
            # Issued display uses invoice lines including custom items. Freshness
            # still compares the original common allocation digest computed above.
            row['lines']=saved_lines[row['issued_bill']['bill_id']]
            row['final_total']=row['issued_bill']['final_total']
            for kind in ('rent','electricity','water'):
                row[kind+'_amount' if kind=='rent' else kind+'_share']=sum((line['amount'] for line in row['lines'] if line['kind']==kind),ZERO)
            row['charge_amount']=sum((line['amount'] for line in row['lines'] if line['kind']=='charge'),ZERO)
            row['discount_amount']=-sum((line['amount'] for line in row['lines'] if line['kind']=='discount'),ZERO)
    return result


def _signer(): return URLSafeTimedSerializer(current_app.config['SECRET_KEY'],salt='monthly-bill-preview-v1')


def _token_data(cycle,result,chosen):
    return {'cycle_id':cycle['cycle_id'],'version':cycle['version'],'digest':result['source_digest'],
        **({'utility_digest':cycle.get('utility_expense_digest')} if enabled() else {}),
        'due_date':cycle['due_date'].isoformat(),'selected_ids':sorted(chosen)}


def _preview(cursor,cycle,chosen=None):
    result=_calculate(cursor,cycle)
    available=[row['tenancy_id'] for row in result['rows'] if not row['issued_bill']]
    chosen=available if chosen is None else chosen
    summary=selected_summary(result,chosen)
    if set(chosen)-set(available): raise BillingValidationError('An already-issued tenancy cannot be selected again.','selected_ids')
    token=None
    if enabled():
        sources=current_sources(cursor,cycle)
        result.update(utility_sources=sources,month_complete=local_today()>=result['period_until'],period_started=local_today()>=result['period_start'])
        result['sources_changed']=cycle.get('utility_source')=='expenses' and sources['digest']!=cycle.get('utility_expense_digest')
        result['costs_ready']=cycle['electricity_total'] is not None and cycle['water_total'] is not None and (
            cycle.get('utility_source')=='expenses' and sources['ready'] or cycle['state']=='locked' and cycle.get('utility_source')=='manual_legacy')
    if chosen and not result['stale'] and not result['validation_error'] and cycle['electricity_total'] is not None and cycle['state']!='void' and (not enabled() or (result['period_started'] and result['costs_ready'] and not result['sources_changed'])):
        token=_signer().dumps(_token_data(cycle,result,chosen))
    return {**result,'cycle':cycle,'selected_ids':chosen,'selected_summary':summary,'preview_token':token,
        'issued_count':sum(1 for row in result['rows'] if row['issued_bill']),
        'eligible_student_count':len({row['student_id'] for row in result['rows']}),
        'joining_count':len({row['student_id'] for row in result['rows'] if cycle['period_start']<=row['start_date']<result['period_until']}),
        'moving_count':len({row['student_id'] for row in result['rows'] if row['end_date'] and cycle['period_start']<=row['end_date']<result['period_until']}),
        'ineligible_student_count':len({row['student_id'] for row in result['ineligible']}-{row['student_id'] for row in result['rows']})}


def load_billing(owner_id,month,chosen=None):
    start,until,_=month_period(month)
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        cursor.execute('SELECT '+BOARDING_COLUMNS+' FROM boardings WHERE owner_id=%s',(owner_id,))
        boarding=cursor.fetchone()
        if not boarding: return {'boarding':None,'cycle':None,'month':month}
        cursor.execute("SELECT * FROM billing_cycles WHERE boarding_id=%s AND period_start=%s AND state<>'void'",(boarding['boarding_id'],start))
        cycle=cursor.fetchone()
        if not cycle:
            cursor.execute(TENANT_SQL,(boarding['boarding_id'],))
            calculation=calculate_bills(month,cursor.fetchall(),[],ZERO,ZERO)
            return {**calculation,'boarding':boarding,'cycle':None,'month':month,'default_due':default_due_date(start).isoformat(),
                **({'utility_sources':utility_sources(cursor,boarding['boarding_id'],start),'month_complete':local_today()>=until,'period_started':local_today()>=start} if enabled() else {})}
        return {**_preview(cursor,cycle,chosen),'boarding':boarding,'month':month}


def preview_billing(owner_id,cycle_id,chosen):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        return _preview(cursor,_cycle(cursor,owner_id,cycle_id),chosen)


def prepare_expense_preview(owner_id,month,raw_due):
    """Save draft inputs only. Issuance always requires a separate signed POST."""
    cycle_id=open_cycle(owner_id,month,raw_due)
    with _transaction(owner_id,cycle_id) as (cursor,_,cycle):
        sync_sources(cursor,cycle,owner_id,_audit)
    return cycle_id


def open_cycle(owner_id,month,raw_due):
    start,_,_=month_period(month); due=due_date(raw_due,start)
    with _transaction(owner_id) as (cursor,boarding,_):
        cursor.execute("SELECT * FROM billing_cycles WHERE boarding_id=%s AND period_start=%s AND state<>'void' FOR UPDATE",(boarding['boarding_id'],start))
        cycle=cursor.fetchone()
        if cycle:
            if cycle['due_date']!=due:
                _draft(cycle)
                cursor.execute('UPDATE billing_cycles SET due_date=%s,version=version+1 WHERE cycle_id=%s',(due,cycle['cycle_id']))
                _audit(cursor,cycle['cycle_id'],owner_id,'draft_due_date_saved',{'old':cycle['due_date'],'new':due})
            return cycle['cycle_id']
        cursor.execute('SELECT COALESCE(MAX(cycle_number),0)+1 AS number FROM billing_cycles WHERE boarding_id=%s AND period_start=%s',(boarding['boarding_id'],start))
        number=cursor.fetchone()['number']
        cursor.execute('''INSERT INTO billing_cycles(boarding_id,period_start,cycle_number,due_date,created_by,created_at)
            VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(boarding['boarding_id'],start,number,due,owner_id))
        cycle_id=cursor.lastrowid
        _audit(cursor,cycle_id,owner_id,'cycle_opened',{'month':month,'due_date':due})
        return cycle_id


def save_utilities(owner_id,cycle_id,form):
    if enabled():raise BillingValidationError('Record actual Electricity and Water under Income & Expenses, then Generate Bills.')
    electricity=input_amount(form.get('electricity_total',''),'electricity_total')
    water=input_amount(form.get('water_total',''),'water_total')
    with _transaction(owner_id,cycle_id) as (cursor,_,cycle):
        _draft(cycle); _version(cycle,form.get('version',''))
        cursor.execute('UPDATE billing_cycles SET electricity_total=%s,water_total=%s,version=version+1 WHERE cycle_id=%s',(electricity,water,cycle_id))
        _audit(cursor,cycle_id,owner_id,'utilities_saved',{'old_electricity':cycle['electricity_total'],'new_electricity':electricity,'old_water':cycle['water_total'],'new_water':water})


def parse_adjustment(form,month):
    kind=form.get('kind',''); name=form.get('name','').strip(); category=form.get('category','other')
    if kind not in ('charge','discount'): raise BillingValidationError('Choose Charge or Discount.','kind')
    if kind=='discount': name='Discount'; category='discount'
    if not name or len(name)>100 or '\x00' in name: raise BillingValidationError('Enter a charge name up to 100 characters.','name')
    if category not in ('internet','cleaning','parking','gas','other','discount'): raise BillingValidationError('Choose a valid category.','category')
    value_type=form.get('value_type','fixed') if kind=='discount' else 'fixed'
    method=form.get('application_method','per_tenant') if kind=='charge' else 'per_tenant'
    scope=form.get('discount_scope','rent')
    if value_type not in ('fixed','percentage') or method not in ('per_tenant','shared_total') or scope not in ('rent','subtotal'):
        raise BillingValidationError('Choose valid application and discount settings.')
    value=input_amount(form.get('value',''),'value',value_type=='percentage')
    apply_all=form.get('apply_to','all')=='all'
    if form.get('apply_to','all') not in ('all','selected'): raise BillingValidationError('Choose All or Selected eligible tenancies.','apply_to')
    targets=[] if apply_all else selected_ids(form.getlist('targets'))
    if not apply_all and not targets: raise BillingValidationError('Select at least one eligible tenancy.','targets')
    recurrence=form.get('recurrence','once') if kind=='charge' else 'once'
    if recurrence not in ('once','monthly'): raise BillingValidationError('Choose One-Time or Monthly recurrence.','recurrence')
    first,_,_=month_period(month)
    end=month_period(form.get('effective_to',''))[0] if recurrence=='monthly' else first
    if end<first: raise BillingValidationError('The recurrence end month cannot precede its start.','effective_to')
    description=form.get('description','').strip()
    if len(description)>500 or '\x00' in description: raise BillingValidationError('Use no more than 500 characters.','description')
    key=form.get('request_key','')
    if not re.fullmatch(r'[a-f0-9]{32}',key): raise BillingValidationError('Refresh the form before adding an adjustment.')
    return dict(kind=kind,name=name,category=category,value=value,value_type=value_type,application_method=method,
        discount_scope=scope,apply_all=apply_all,targets=targets,recurrence=recurrence,effective_from=first,effective_to=end,
        description=description or None,request_key=key)


def add_adjustment(owner_id,cycle_id,form):
    with _transaction(owner_id,cycle_id) as (cursor,_,cycle):
        _draft(cycle)
        values=parse_adjustment(form,cycle['period_start'].strftime('%Y-%m'))
        cursor.execute('SELECT adjustment_id FROM billing_adjustments WHERE boarding_id=%s AND request_key=%s',(cycle['boarding_id'],values['request_key']))
        if cursor.fetchone(): return
        _version(cycle,form.get('version',''))
        cursor.execute(TENANT_SQL,(cycle['boarding_id'],))
        eligible=calculate_bills(cycle['period_start'].strftime('%Y-%m'),cursor.fetchall(),[],ZERO,ZERO)
        if not set(values['targets'])<={row['tenancy_id'] for row in eligible['rows']}:
            raise BillingValidationError('Choose only eligible tenancies from your own boarding.','targets')
        if values['recurrence']=='monthly':
            cursor.execute("SELECT cycle_id FROM billing_cycles WHERE boarding_id=%s AND state='locked' AND period_start BETWEEN %s AND %s LIMIT 1",(cycle['boarding_id'],values['effective_from'],values['effective_to']))
            if cursor.fetchone(): raise BillingConflict('This recurring charge would change an issued cycle. Choose a range without issued periods.')
        identity={key:value for key,value in values.items() if key!='request_key'}
        if values['recurrence']=='once': identity['origin_cycle_id']=cycle_id
        fingerprint=digest(identity)
        cursor.execute('SELECT adjustment_id FROM billing_adjustments WHERE boarding_id=%s AND active_fingerprint=%s',(cycle['boarding_id'],fingerprint))
        if cursor.fetchone(): raise BillingConflict('This adjustment is already configured; it was not added again.')
        cursor.execute('''INSERT INTO billing_adjustments(boarding_id,origin_cycle_id,kind,name,category,value,value_type,
            application_method,discount_scope,apply_all,recurrence,effective_from,effective_to,description,request_key,fingerprint)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
            (cycle['boarding_id'],cycle_id,*(values[key] for key in ('kind','name','category','value','value_type','application_method',
                'discount_scope','apply_all','recurrence','effective_from','effective_to','description','request_key')),fingerprint))
        rule_id=cursor.lastrowid
        for target in values['targets']:
            cursor.execute('INSERT INTO billing_adjustment_targets(adjustment_id,tenancy_id) VALUES(%s,%s)',(rule_id,target))
        calculation=_calculate(cursor,cycle)
        if calculation['validation_error']: raise BillingValidationError(calculation['validation_error'],'value')
        cursor.execute('UPDATE billing_cycles SET version=version+1 WHERE cycle_id=%s',(cycle_id,))
        _audit(cursor,cycle_id,owner_id,'adjustment_added',{'adjustment_id':rule_id,**identity})


def remove_adjustment(owner_id,cycle_id,rule_id,form):
    with _transaction(owner_id,cycle_id) as (cursor,_,cycle):
        _draft(cycle); _version(cycle,form.get('version',''))
        cursor.execute('SELECT * FROM billing_adjustments WHERE adjustment_id=%s AND boarding_id=%s AND enabled=TRUE',(rule_id,cycle['boarding_id']))
        rule=cursor.fetchone()
        if rule is None: raise BillingNotFound()
        if rule['recurrence']=='once' and rule['origin_cycle_id']!=cycle_id: raise BillingNotFound()
        if not rule['effective_from']<=cycle['period_start']<=rule['effective_to']: raise BillingNotFound()
        cursor.execute("SELECT cycle_id FROM billing_cycles WHERE boarding_id=%s AND state='locked' AND period_start BETWEEN %s AND %s LIMIT 1",(cycle['boarding_id'],cycle['period_start'],rule['effective_to']))
        if cursor.fetchone(): raise BillingConflict('This change would alter an issued allocation. Correct that billing cycle first.')
        if rule['recurrence']=='monthly' and rule['effective_from']<cycle['period_start']:
            previous_month=(cycle['period_start']-timedelta(days=1)).replace(day=1)
            cursor.execute('UPDATE billing_adjustments SET effective_to=%s WHERE adjustment_id=%s',(previous_month,rule_id))
        else: cursor.execute('UPDATE billing_adjustments SET enabled=FALSE WHERE adjustment_id=%s',(rule_id,))
        cursor.execute('UPDATE billing_cycles SET version=version+1 WHERE cycle_id=%s',(cycle_id,))
        _audit(cursor,cycle_id,owner_id,'adjustment_stopped',{'adjustment_id':rule_id,'from_period':cycle['period_start']})


def generate_bills(owner_id,cycle_id,chosen,token,*,invoice_items=None,invoice_due=None,invoice_overrides=None,invoice_expenses=None,invoice_discount=None):
    if not chosen: raise BillingValidationError('Select at least one eligible tenancy.','selected_ids')
    try: signed=_signer().loads(token,max_age=900)
    except (BadSignature,SignatureExpired,TypeError): raise BillingConflict('The preview expired or is invalid. Recalculate before generating.') from None
    references=[]
    if invoice_items is not None:
        from invoice_items import parse_items
        invoice_items=parse_items(invoice_items)
        if len(chosen)!=1:raise BillingValidationError('Create a custom invoice for one tenancy at a time.')
    if invoice_overrides is not None:
        from invoice_items import parse_overrides
        invoice_overrides=parse_overrides(invoice_overrides)
        if invoice_items is None:raise BillingValidationError('Optional charge adjustments require a reviewed individual invoice.')
    if invoice_discount is not None:
        from invoice_items import parse_discount
        invoice_discount=parse_discount(invoice_discount)
        if invoice_items is None or len(chosen)!=1:raise BillingValidationError('Apply a discount to one reviewed invoice at a time.')
    with _transaction(owner_id,cycle_id,students=True) as (cursor,boarding,cycle):
        if cycle['state']=='void': raise BillingConflict('This cycle was replaced. Open its current billing period.')
        if enabled():
            if local_today()<cycle['period_start']:
                raise BillingValidationError('This billing month has not started. Issue this invoice from '+cycle['period_start'].strftime('%d %B %Y')+'.')
            assert_sources(cursor,cycle)
        preview=_preview(cursor,cycle,chosen)
        if preview['validation_error']: raise BillingValidationError(preview['validation_error'])
        expected=_token_data(cycle,preview,chosen)
        if invoice_discount is not None:expected['invoice_discount']=invoice_discount
        selected_sources=[]
        if invoice_expenses is not None:
            from invoice_expenses import parse_selection,expense_choices,selected_sources as validate_sources
            if invoice_items is None or len(chosen)!=1:raise BillingValidationError('Select expenses for one reviewed invoice at a time.')
            ids=parse_selection(invoice_expenses)
            selected_sources=validate_sources(expense_choices(cursor,boarding['boarding_id'],cycle['period_start'],preview,chosen[0],ids),ids)
            expected['invoice_expenses']=_json(canonical(selected_sources))
        final_due=cycle['due_date']
        if invoice_items is not None:
            final_due=due_date(invoice_due,cycle['period_start'])
            expected.update(invoice_items=invoice_items,invoice_due=final_due.isoformat())
            if invoice_overrides is not None:expected['invoice_overrides']=invoice_overrides
        if preview['stale'] or signed!=expected:
            raise BillingConflict('Source data changed after preview. Recalculate; no bills were generated.')
        if cycle['electricity_total'] is None: raise BillingValidationError('Save actual utility totals first, including confirmed zeros.')
        if cycle['state']=='draft':
            # Freeze ALL eligible allocations, not just the selection; later partial
            # issuance consumes the same original shares and cannot reallocate costs.
            for row in preview['rows']:
                cursor.execute('''INSERT INTO billing_allocations(cycle_id,tenancy_id,eligible_from,eligible_until,eligible_days,
                    calendar_days,total_tenant_days,agreed_rent,rent_amount,electricity_share,water_share,charge_amount,discount_amount,final_total,calculation)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                    (cycle_id,*(row[key] for key in ('tenancy_id','eligible_from','eligible_until','eligible_days','calendar_days','total_tenant_days',
                    'agreed_rent','rent_amount','electricity_share','water_share','charge_amount','discount_amount','final_total')),canonical({'lines':row['lines']})))
                row['allocation_id']=cursor.lastrowid
            cursor.execute("UPDATE billing_cycles SET state='locked',source_digest=%s,locked_at=UTC_TIMESTAMP(6),electricity_unallocated=%s,water_unallocated=%s,version=version+1 WHERE cycle_id=%s",
                (preview['source_digest'],preview['electricity_unallocated'],preview['water_unallocated'],cycle_id))
        issued_summary=dict(preview['selected_summary'])
        for row in preview['rows']:
            if row['tenancy_id'] not in chosen: continue
            if invoice_items is not None:
                from invoice_items import compose_invoice
                if invoice_expenses is not None:
                    from invoice_expenses import apply_selection
                    row=apply_selection(row,selected_sources)
                # Allocations are the frozen common calculation. Invoice-specific
                # charges live only in this invoice's immutable final lines/total.
                row=compose_invoice(row,invoice_items,invoice_overrides,invoice_discount)
                issued_summary.update({key:row[key] for key in ('rent_amount','electricity_share','water_share','charge_amount','discount_amount','final_total')})
            reference='BILL-'+cycle['period_start'].strftime('%Y%m')+'-'+uuid.uuid4().hex[:12].upper()
            cursor.execute('''INSERT INTO monthly_bills(bill_reference,cycle_id,allocation_id,boarding_id,tenancy_id,student_id,
                period_start,recipient_name,recipient_email,boarding_snapshot,unit_snapshot,final_total,original_due_date,due_date,issued_by,issued_at)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',
                (reference,cycle_id,row['allocation_id'],cycle['boarding_id'],row['tenancy_id'],row['student_id'],cycle['period_start'],
                 row['student_name'],row['student_email'],canonical(boarding),canonical({'room_number':row['room_number'],'bed_label':row['bed_label'],'rent_unit':row['rent_unit']}),
                 row['final_total'],final_due,final_due,owner_id))
            bill_id=cursor.lastrowid
            if enabled():
                from bill_delivery import enqueue_bill
                enqueue_bill(cursor,bill_id)
            for number,line in enumerate(row['lines'],1):
                cursor.execute('INSERT INTO bill_line_items(bill_id,line_number,kind,description,amount,adjustment_id,details) VALUES(%s,%s,%s,%s,%s,%s,%s)',
                    (bill_id,number,line['kind'],line['description'],line['amount'],line['adjustment_id'],canonical(line['details'])))
            references.append(reference)
        if cycle['state']=='locked': cursor.execute('UPDATE billing_cycles SET version=version+1 WHERE cycle_id=%s',(cycle_id,))
        _audit(cursor,cycle_id,owner_id,'bills_issued',{'references':references,'selected_ids':chosen,'summary':issued_summary,
            'allocation_digest':preview['source_digest'],'invoice_items':invoice_items,'invoice_due':final_due,'invoice_overrides':invoice_overrides,'invoice_expenses':selected_sources,'invoice_discount':invoice_discount})
    return references


def load_bill(owner_id,bill_id):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        cursor.execute('''SELECT m.*,a.eligible_from,a.eligible_until,a.eligible_days,a.calendar_days,a.total_tenant_days,
            a.agreed_rent,a.rent_amount,a.electricity_share,a.water_share,a.charge_amount,a.discount_amount
            FROM monthly_bills m JOIN boardings b ON b.boarding_id=m.boarding_id JOIN billing_allocations a ON a.allocation_id=m.allocation_id
            WHERE m.bill_id=%s AND b.owner_id=%s''',(bill_id,owner_id))
        bill=cursor.fetchone()
        if bill is None: raise BillingNotFound()
        for field in ('boarding_snapshot','unit_snapshot'): bill[field]=_json(bill[field])
        cursor.execute('SELECT * FROM bill_line_items WHERE bill_id=%s ORDER BY line_number',(bill_id,))
        bill['lines']=cursor.fetchall()
        for line in bill['lines']: line['details']=_json(line['details'])
        # Final invoice lines include Student-specific waivers; the common
        # allocation is historical input, not the amount this Student now owes.
        for kind in ('rent','electricity','water'):
            bill[kind+'_amount' if kind=='rent' else kind+'_share']=sum((line['amount'] for line in bill['lines'] if line['kind']==kind),ZERO)
        bill['charge_amount']=sum((line['amount'] for line in bill['lines'] if line['kind']=='charge'),ZERO)
        bill['discount_amount']=-sum((line['amount'] for line in bill['lines'] if line['kind']=='discount'),ZERO)
        cursor.execute('SELECT event_type,reason,details,created_at FROM billing_audit_events WHERE bill_id=%s ORDER BY event_id',(bill_id,))
        bill['events']=cursor.fetchall()
        for event in bill['events']: event['details']=_json(event['details'])
        bill['payment_state']=bill_payment_summary(cursor,bill)
        return bill


def load_history(owner_id,params):
    search=params.get('q','').strip(); status=params.get('status',''); month=params.get('month',''); page=params.get('page','1')
    if len(search)>150 or '\x00' in search or status not in ('','issued','void') or not re.fullmatch(r'[0-9]{1,7}',page) or not 1<=int(page)<=1000000:
        raise BillingValidationError('Choose valid bill history filters.')
    where=' WHERE b.owner_id=%s'; values=[owner_id]
    if month: where+=' AND m.period_start=%s'; values.append(month_period(month)[0])
    if status: where+=' AND m.state=%s'; values.append(status)
    if search:
        escaped=search.replace('!','!!').replace('%','!%').replace('_','!_')
        where+=" AND (m.recipient_name LIKE %s ESCAPE '!' OR m.bill_reference LIKE %s ESCAPE '!')"; values+=['%'+escaped+'%']*2
    joins=' FROM monthly_bills m JOIN boardings b ON b.boarding_id=m.boarding_id'
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        cursor.execute('SELECT COUNT(*) AS total'+joins+where,tuple(values)); total=cursor.fetchone()['total']
        pages=max(1,math.ceil(total/15)); number=min(int(page),pages)
        cursor.execute('SELECT m.bill_id,m.bill_reference,m.recipient_name,m.period_start,m.final_total,m.due_date,m.issued_at,m.state'+joins+where+' ORDER BY m.issued_at DESC,m.bill_id DESC LIMIT 15 OFFSET %s',(*values,(number-1)*15))
        rows=cursor.fetchall()
        for row in rows:
            row['payment_state']=bill_payment_summary(cursor,row)
            if enabled():
                cursor.execute('SELECT status,error_code,attempt_count,sent_at FROM bill_email_deliveries WHERE bill_id=%s',(row['bill_id'],))
                row['delivery']=cursor.fetchone()
        return dict(rows=rows,total=total,page=number,page_count=pages,filters=dict(q=search,status=status,month=month))


def _no_external_financial_links(cursor,bill_ids):
    if not bill_ids: return
    cursor.execute("""SELECT TABLE_NAME,COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE
        WHERE REFERENCED_TABLE_SCHEMA=DATABASE() AND REFERENCED_TABLE_NAME='monthly_bills'
        AND TABLE_NAME NOT IN ('bill_line_items','billing_audit_events','bill_email_deliveries')""")
    for item in cursor.fetchall():
        table,column=item['TABLE_NAME'],item['COLUMN_NAME']
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',table) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',column):
            raise BillingConflict('A financial integration needs review before correction.')
        cursor.execute('SELECT 1 AS linked FROM `'+table+'` WHERE `'+column+'` IN ('+','.join(['%s']*len(bill_ids))+') LIMIT 1',tuple(bill_ids))
        if cursor.fetchone(): raise BillingConflict('This bill has linked financial records. Its payment/reversal policy must be completed before correction.')


def correction_reason(form):
    reason=form.get('reason','').strip()
    if not reason or len(reason)>500 or '\x00' in reason: raise BillingValidationError('Enter a correction reason up to 500 characters.','reason')
    return reason


def correct_due_date(owner_id,bill_id,form,credential):
    hint=load_bill(owner_id,bill_id); reason=correction_reason(form)
    new_due=due_date(form.get('due_date',''),hint['period_start'])
    with _transaction(owner_id,hint['cycle_id'],students=True,credential=credential) as (cursor,_,cycle):
        cursor.execute('SELECT due_date,revision,state FROM monthly_bills WHERE bill_id=%s AND cycle_id=%s FOR UPDATE',(bill_id,cycle['cycle_id']))
        bill=cursor.fetchone()
        if not bill or bill['state']!='issued' or str(bill['revision'])!=form.get('revision',''):
            raise BillingConflict('This bill changed or was voided. Refresh its current details.')
        if new_due==bill['due_date']: raise BillingValidationError('Choose a different due date.','due_date')
        _no_external_financial_links(cursor,[bill_id])
        cursor.execute('UPDATE monthly_bills SET due_date=%s,revision=revision+1 WHERE bill_id=%s',(new_due,bill_id))
        _audit(cursor,cycle['cycle_id'],owner_id,'due_date_corrected',{'old_due':bill['due_date'],'new_due':new_due},reason,bill_id)


def replace_cycle(owner_id,cycle_id,form,credential):
    reason=correction_reason(form)
    with _transaction(owner_id,cycle_id,students=True,credential=credential) as (cursor,boarding,cycle):
        if cycle['state']=='void':
            cursor.execute('SELECT cycle_id FROM billing_cycles WHERE replaces_cycle_id=%s ORDER BY cycle_id DESC LIMIT 1',(cycle_id,))
            replacement=cursor.fetchone()
            if replacement: return replacement['cycle_id']
            raise BillingConflict('This cycle was voided. Open the current billing period.')
        if cycle['state']!='locked': raise BillingConflict('Only an issued cycle needs financial correction.')
        _version(cycle,form.get('version',''))
        cursor.execute("SELECT bill_id,bill_reference FROM monthly_bills WHERE cycle_id=%s AND state='issued' FOR UPDATE",(cycle_id,))
        bills=cursor.fetchall(); _no_external_financial_links(cursor,[row['bill_id'] for row in bills])
        cursor.execute("UPDATE monthly_bills SET state='void',revision=revision+1 WHERE cycle_id=%s AND state='issued'",(cycle_id,))
        cursor.execute("UPDATE billing_cycles SET state='void',version=version+1 WHERE cycle_id=%s",(cycle_id,))
        cursor.execute('''INSERT INTO billing_cycles(boarding_id,period_start,cycle_number,replaces_cycle_id,due_date,
            electricity_total,water_total,created_by,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',
            (boarding['boarding_id'],cycle['period_start'],cycle['cycle_number']+1,cycle_id,cycle['due_date'],cycle['electricity_total'],cycle['water_total'],owner_id))
        replacement_id=cursor.lastrowid
        for bill in bills:
            _audit(cursor,cycle_id,owner_id,'bill_voided',{'reference':bill['bill_reference'],'replacement_cycle_id':replacement_id},reason,bill['bill_id'])
        # One-time definitions are copied; old snapshots/rules remain untouched.
        cursor.execute("SELECT * FROM billing_adjustments WHERE origin_cycle_id=%s AND recurrence='once' AND enabled=TRUE",(cycle_id,))
        for rule in cursor.fetchall():
            cursor.execute('SELECT tenancy_id FROM billing_adjustment_targets WHERE adjustment_id=%s ORDER BY tenancy_id',(rule['adjustment_id'],))
            targets=[item['tenancy_id'] for item in cursor.fetchall()]
            identity={key:rule[key] for key in ('kind','name','category','value','value_type','application_method','discount_scope',
                'recurrence','effective_from','effective_to','description')}
            identity.update(apply_all=bool(rule['apply_all']),targets=targets,origin_cycle_id=replacement_id)
            cursor.execute('''INSERT INTO billing_adjustments(boarding_id,origin_cycle_id,kind,name,category,value,value_type,
                application_method,discount_scope,apply_all,recurrence,effective_from,effective_to,description,request_key,fingerprint)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'once',%s,%s,%s,%s,%s)''',
                (boarding['boarding_id'],replacement_id,*(rule[key] for key in ('kind','name','category','value','value_type','application_method','discount_scope','apply_all')),
                 rule['effective_from'],rule['effective_to'],rule['description'],uuid.uuid4().hex,digest(identity)))
            new_rule=cursor.lastrowid
            cursor.execute('INSERT INTO billing_adjustment_targets(adjustment_id,tenancy_id) SELECT %s,tenancy_id FROM billing_adjustment_targets WHERE adjustment_id=%s',(new_rule,rule['adjustment_id']))
        _audit(cursor,cycle_id,owner_id,'cycle_replaced',{'replacement_cycle_id':replacement_id,'voided_bills':bills},reason)
        _audit(cursor,replacement_id,owner_id,'correction_draft_created',{'original_cycle_id':cycle_id},reason)
        return replacement_id
