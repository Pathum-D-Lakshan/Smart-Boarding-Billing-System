"""Owner monthly summaries and audited allocation of actual paid expenses."""
from contextlib import contextmanager
from datetime import date,datetime,time,timedelta,timezone
from decimal import Decimal
import json
import math
import re

from mysql.connector import Error
from billing_calculator import canonical,month_period
from db import get_db_connection
from tenancy_service import SRI_LANKA_TIME,local_today
from admin_security import account_guard
from billing_sources import enabled,shared_enabled,protect_expense_period


class FinanceNotFound(LookupError):pass
class FinanceConflict(RuntimeError):pass
class FinanceValidationError(ValueError):
    def __init__(self,message,field='form'):
        super().__init__(message);self.errors={field:message}


def period(month):
    try:first,until,days=month_period(month)
    except ValueError:raise FinanceValidationError('Choose a valid billing month.','month') from None
    start_utc=datetime.combine(first,time.min,SRI_LANKA_TIME).astimezone(timezone.utc).replace(tzinfo=None)
    until_utc=datetime.combine(until,time.min,SRI_LANKA_TIME).astimezone(timezone.utc).replace(tzinfo=None)
    return first,until,start_utc,until_utc


def filters(params):
    month=params.get('month') or params.get('view_month') or local_today().strftime('%Y-%m')
    period(month)
    q=params.get('q','').strip();page=str(params.get('page','1'))
    if len(q)>150 or any(ord(c)<32 for c in q):raise FinanceValidationError('Search using no more than 150 characters.','q')
    if not re.fullmatch(r'[0-9]{1,6}',page) or int(page)<1:raise FinanceValidationError('Choose a valid records page.','page')
    return dict(month=month,q=q,page=int(page))


def accounting_period_available(cursor):
    cursor.execute("""SELECT EXISTS(SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='expenses' AND COLUMN_NAME='accounting_period') AS available""")
    return bool(cursor.fetchone()['available'])


def has_expense_accounting():
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        return accounting_period_available(cursor)


def expense_month_scope(first,until,allocated):
    paid='expense_date>=%s AND expense_date<%s'
    if not allocated:
        return paid,(first,until)
    return f'(accounting_period=%s OR (accounting_period IS NULL AND {paid}))',(first,first,until)


def effective_expense_period(row):
    return row.get('accounting_period') or row['expense_date'].replace(day=1)


def parse_accounting_period(value):
    try:return month_period(value)[0]
    except ValueError:raise FinanceValidationError('Choose a valid Accounting Month.','accounting_period') from None


def expense_date_window(month,allocated=False):
    first,until,_,_=period(month)
    today=local_today()
    if allocated:
        return date(2000,1,1),today,first if today>=until else today
    last=min(until-timedelta(days=1),today)
    default=(today if first<=today<until else first) if first<=last else None
    return first,last,default


def parse_expense(form,*,accounting_month=None):
    category=form.get('category','other')
    if category not in ('electricity','water','other'):
        raise FinanceValidationError('Choose Electricity, Water or Other.','category')
    name=form.get('expense_name','').strip()
    if not name or len(name)>150 or any(ord(c)<32 for c in name):
        raise FinanceValidationError('Enter an Expense Name using 1–150 characters.','expense_name')
    raw=form.get('amount','').strip()
    if not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,2})?',raw) or Decimal(raw)<0 or (Decimal(raw)==0 and (category=='other' or not enabled())):
        raise FinanceValidationError('Enter a positive amount up to 999,999,999,999.99 with no more than two decimal places.','amount')
    value=form.get('expense_date','')
    try:
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}',value):raise ValueError()
        paid=date.fromisoformat(value)
        if not date(2000,1,1)<=paid<=local_today():raise ValueError()
    except (TypeError,ValueError):raise FinanceValidationError('Choose the actual paid expense date, today or earlier.','expense_date') from None
    result=dict(expense_name=name,amount=Decimal(raw).quantize(Decimal('.01')),expense_date=paid)
    if accounting_month is not None:
        result['accounting_period']=parse_accounting_period(accounting_month)
    if enabled():
        share=False
        if shared_enabled() and category=='other':
            raw_share=form.get('charge_to_tenants','0')
            if raw_share not in ('0','1',0,1):raise FinanceValidationError('Choose Owner Expense Only or Share Across Eligible Tenants.','charge_to_tenants')
            share=raw_share in ('1',1)
        utility=None
        if category!='other' or share:
            try:utility=month_period(form.get('utility_period',''))[0]
            except (ValueError,TypeError):raise FinanceValidationError('Choose the month this utility cost belongs to.','utility_period') from None
        notes=form.get('notes','').strip()
        if len(notes)>500 or any(ord(c)<32 and c not in '\n\r\t' for c in notes):
            raise FinanceValidationError('Use no more than 500 characters for Notes.','notes')
        result.update(category=category,utility_period=utility,notes=notes or None)
        if shared_enabled():result['charge_to_tenants']=share
    return result


def _boarding(cursor,owner,lock=False):
    cursor.execute('SELECT boarding_id,boarding_name FROM boardings WHERE owner_id=%s'+(' FOR UPDATE' if lock else ''),(owner,))
    return cursor.fetchone()


def _expense(cursor,owner,expense_id,lock=False):
    cursor.execute('''SELECT e.* FROM expenses e JOIN boardings b ON b.boarding_id=e.boarding_id
        WHERE e.expense_id=%s AND b.owner_id=%s'''+(' FOR UPDATE' if lock else ''),(expense_id,owner))
    row=cursor.fetchone()
    if row is None:raise FinanceNotFound()
    return row


def _summary(cursor,boarding_id,month,allocated):
    first,until,start_utc,until_utc=period(month)
    # Verification/decision date matches Payments reporting. Bills owed, receipts
    # and utility allocations are not additional sources of collected income.
    cursor.execute('''SELECT COALESCE(SUM(p.amount),0) AS income FROM payments p
        JOIN monthly_bills m ON m.bill_id=p.bill_id WHERE m.boarding_id=%s
        AND p.status='verified' AND p.method IN ('bank_transfer','cash')
        AND p.decided_at>=%s AND p.decided_at<%s''',(boarding_id,start_utc,until_utc))
    income=Decimal(cursor.fetchone()['income'])
    clause,dates=expense_month_scope(first,until,allocated)
    cursor.execute('''SELECT COALESCE(SUM(amount),0) AS expenses FROM expenses
        WHERE boarding_id=%s AND archived_at IS NULL AND '''+clause,(boarding_id,*dates))
    expenses=Decimal(cursor.fetchone()['expenses'])
    return dict(income=income,expenses=expenses,balance=income-expenses)


def monthly_summary(owner_id,month):
    """Reusable by future Reports/Dashboard without a second finance calculation."""
    period(month)
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        boarding=_boarding(cursor,owner_id)
        return dict(boarding=boarding,summary=_summary(cursor,boarding['boarding_id'],month,accounting_period_available(cursor)) if boarding else None)


def reporting_summary(cursor,boarding_id,month,allocated):
    """Reuse Finance rules inside a caller's consistent read-only report snapshot."""
    return _summary(cursor,boarding_id,month,allocated)


def load_finance(owner_id,params,attempt_key=None):
    view=filters(params);first,until,_,_=period(view['month'])
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        boarding=_boarding(cursor,owner_id)
        result=dict(boarding=boarding,summary=None,rows=[],total=0,page=1,page_count=1,filters=view,recovered=False)
        if not boarding:return result
        allocated=accounting_period_available(cursor)
        result['accounting_available']=allocated
        result['summary']=_summary(cursor,boarding['boarding_id'],view['month'],allocated)
        clause,dates=expense_month_scope(first,until,allocated)
        where='boarding_id=%s AND archived_at IS NULL AND '+clause
        args=[boarding['boarding_id'],*dates]
        if enabled():
            cursor.execute('SELECT category,COALESCE(SUM(amount),0) AS amount FROM expenses WHERE '+where+' GROUP BY category',tuple(args))
            result['categories']={r['category']:r['amount'] for r in cursor.fetchall()}
        if view['q']:
            escaped=view['q'].replace('!','!!').replace('%','!%').replace('_','!_')
            where+=" AND expense_name LIKE %s ESCAPE '!'";args.append('%'+escaped+'%')
        cursor.execute('SELECT COUNT(*) AS total FROM expenses WHERE '+where,tuple(args));total=cursor.fetchone()['total']
        pages=max(1,math.ceil(total/15));page=min(view['page'],pages)
        cursor.execute('SELECT * FROM expenses WHERE '+where+' ORDER BY expense_date DESC,expense_id DESC LIMIT 15 OFFSET %s',(*args,(page-1)*15))
        result.update(rows=cursor.fetchall(),total=total,page=page,page_count=pages)
        if attempt_key and re.fullmatch(r'[a-f0-9]{32}',attempt_key):
            cursor.execute('SELECT expense_id FROM expenses WHERE boarding_id=%s AND request_key=%s',(boarding['boarding_id'],attempt_key))
            result['recovered']=cursor.fetchone() is not None
        return result


def load_expense(owner_id,expense_id):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        connection.start_transaction(readonly=True)
        row=_expense(cursor,owner_id,expense_id)
        cursor.execute('''SELECT event_type,before_values,after_values,created_at FROM expense_events
            WHERE expense_id=%s ORDER BY revision DESC LIMIT 10''',(expense_id,))
        row['events']=cursor.fetchall()
        for event in row['events']:
            for key in ('before_values','after_values'):
                if isinstance(event[key],(str,bytes)):event[key]=json.loads(event[key])
        return row


@contextmanager
def _write(owner,expense_id=None,credential=None):
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        try:
            connection.start_transaction(isolation_level='READ COMMITTED')
            # Serialize this Owner's expense mutations; no payment/tenancy rows are
            # changed and no lock is taken ahead of the shared Boarding parent.
            boarding=_boarding(cursor,owner,True)
            if not boarding:raise FinanceValidationError('Create a Boarding Profile before recording expenses.')
            cursor.execute("SELECT password_hash FROM users WHERE user_id=%s AND role='owner' AND is_active=TRUE"+account_guard()+" FOR UPDATE",(owner,))
            account=cursor.fetchone()
            if not account:
                raise FinanceConflict('Your account is unavailable. Log in again.')
            expense=_expense(cursor,owner,expense_id,True) if expense_id else None
            yield cursor,boarding,expense
            connection.commit()
        except Exception as error:
            connection.rollback()
            if isinstance(error,Error) and error.errno in (1062,1205,1213):
                raise FinanceConflict('Another operation changed this expense. Refresh the saved records before trying again.') from None
            raise


def _snapshot(row):
    return {key:row[key] for key in ('expense_name','amount','expense_date','accounting_period','archived_at','archived_by','category','utility_period','notes','charge_to_tenants') if key in row}


def _event(cursor,row,owner,kind,before):
    cursor.execute('''INSERT INTO expense_events(expense_id,revision,actor_id,event_type,before_values,after_values,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))''',(row['expense_id'],row['revision'],owner,kind,
            canonical(before) if before is not None else None,canonical(_snapshot(row))))


def add_expense(owner,form,*,accounting_month=None):
    values=parse_expense(form,accounting_month=accounting_month);key=form.get('request_key','')
    if not re.fullmatch(r'[a-f0-9]{32}',key):raise FinanceValidationError('Refresh this form before saving another expense.')
    with _write(owner) as (cursor,boarding,_):
        # Keep old paid-month grouping until the additive migration is available.
        if accounting_month is not None and not accounting_period_available(cursor):
            if values.pop('accounting_period')!=values['expense_date'].replace(day=1):
                raise FinanceValidationError('This database requires the accounting allocation update to use a different month.','expense_date')
        cursor.execute('SELECT * FROM expenses WHERE boarding_id=%s AND request_key=%s',(boarding['boarding_id'],key))
        old=cursor.fetchone()
        if old:
            # A retry after migration can match an older row with an implicit paid month.
            if any((effective_expense_period(old) if field=='accounting_period' else old[field])!=value
                   for field,value in values.items()):
                raise FinanceConflict('This form already saved a different expense. Refresh the records before adding another.')
            return old
        if enabled():protect_expense_period(cursor,boarding['boarding_id'],values)
        extra=',category,utility_period,notes' if enabled() else ''
        args=(boarding['boarding_id'],values['expense_name'],values['amount'],values['expense_date'],key,owner)
        if enabled():args+=(values['category'],values['utility_period'],values['notes'])
        if shared_enabled():extra+=',charge_to_tenants';args+=(values['charge_to_tenants'],)
        if 'accounting_period' in values:extra+=',accounting_period';args+=(values['accounting_period'],)
        cursor.execute('INSERT INTO expenses(boarding_id,expense_name,amount,expense_date,request_key,created_by'+extra+
            ',created_at,updated_at) VALUES('+','.join(['%s']*len(args))+',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))',args)
        row=_expense(cursor,owner,cursor.lastrowid);_event(cursor,row,owner,'created',None)
    return row


def change_expense(owner,expense_id,action,form,credential=None):
    if action not in ('edit','archive'):raise FinanceValidationError('Choose Edit or Archive.')
    values=parse_expense(form) if action=='edit' else None
    if action=='archive' and form.get('confirm_archive')!='yes':raise FinanceValidationError('Confirm that this expense will be excluded from active totals.','confirm_archive')
    with _write(owner,expense_id,credential) as (cursor,_,row):
        if row['archived_at']:
            if action=='archive':return row # A repeated confirmation never duplicates audit.
            raise FinanceConflict('Archived expenses cannot be edited.')
        if str(row['revision'])!=form.get('revision',''):raise FinanceConflict('This expense changed after you opened it. Refresh its saved values before confirming again.')
        before=_snapshot(row)
        if enabled():
            protect_expense_period(cursor,row['boarding_id'],row)
            if values:protect_expense_period(cursor,row['boarding_id'],values)
        if action=='edit':
            if 'accounting_period' in row and 'accounting_period' in form:
                selected=form['accounting_period']
                values['accounting_period']=parse_accounting_period(selected) if selected else None
            if all(row[field]==value for field,value in values.items()):return row
            extra=',category=%s,utility_period=%s,notes=%s' if enabled() else ''
            args=(values['expense_name'],values['amount'],values['expense_date'])
            if enabled():args+=(values['category'],values['utility_period'],values['notes'])
            if shared_enabled():extra+=',charge_to_tenants=%s';args+=(values['charge_to_tenants'],)
            if 'accounting_period' in values:extra+=',accounting_period=%s';args+=(values['accounting_period'],)
            cursor.execute('UPDATE expenses SET expense_name=%s,amount=%s,expense_date=%s'+extra+
                ',revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE expense_id=%s AND boarding_id=%s',(*args,expense_id,row['boarding_id']))
        else:
            cursor.execute('''UPDATE expenses SET archived_at=UTC_TIMESTAMP(6),archived_by=%s,
                revision=revision+1,updated_at=UTC_TIMESTAMP(6) WHERE expense_id=%s AND boarding_id=%s''',(owner,expense_id,row['boarding_id']))
        saved=_expense(cursor,owner,expense_id);_event(cursor,saved,owner,'edited' if action=='edit' else 'archived',before)
    return saved
