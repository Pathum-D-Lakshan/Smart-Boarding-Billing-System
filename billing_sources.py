"""Saved actual utility expenses, distinct from tenant charges and cash income."""
from flask import current_app,has_app_context
from billing_calculator import digest,canonical,ZERO,BillingValidationError
from decimal import Decimal


def enabled():
    return has_app_context() and current_app.config.get('BILLING_REDESIGN_ENABLED',False)


def shared_enabled():
    return enabled() and current_app.config.get('SHARED_EXPENSE_BILLING_ENABLED',False)


def utility_sources(cursor,boarding_id,period,include_shared=None):
    include_shared=shared_enabled() if include_shared is None else include_shared
    extra=',expense_name,charge_to_tenants' if include_shared else ''
    where="(category IN ('electricity','water') OR (category='other' AND charge_to_tenants=TRUE))" if include_shared else "category IN ('electricity','water')"
    cursor.execute('SELECT expense_id,revision,category,amount,utility_period'+extra+''' FROM expenses
        WHERE boarding_id=%s AND utility_period=%s AND archived_at IS NULL AND '''+where+' ORDER BY expense_id',(boarding_id,period))
    rows=cursor.fetchall()
    totals={kind:sum((r['amount'] for r in rows if r['category']==kind),ZERO)
        if any(r['category']==kind for r in rows) else None for kind in ('electricity','water')}
    return dict(rows=rows,totals=totals,digest=digest(rows),ready=all(v is not None for v in totals.values()),
        **({'allocation_policy':'shared_other_v1','shared_expenses':[r for r in rows if r['category']=='other']} if include_shared else {}))


def snapshot_sources(cycle):
    import json
    value=cycle.get('utility_snapshot') or {}
    return json.loads(value) if isinstance(value,(str,bytes)) else value


def current_sources(cursor,cycle):
    # Locked 020 snapshots retain their original digest and allocation policy.
    include=shared_enabled() and (cycle['state']=='draft' or snapshot_sources(cycle).get('allocation_policy')=='shared_other_v1')
    return utility_sources(cursor,cycle['boarding_id'],cycle['period_start'],include_shared=include)


def sync_sources(cursor,cycle,owner,audit):
    if cycle['state']!='draft':return
    sources=current_sources(cursor,cycle)
    if cycle.get('utility_source')=='expenses' and cycle.get('utility_expense_digest')==sources['digest']:return
    totals=sources['totals'];electricity=totals['electricity'] if sources['ready'] else None
    water=totals['water'] if sources['ready'] else None
    if any(value is not None and value>Decimal('999999999999.99') for value in totals.values()):
        raise BillingValidationError('Combined utility expenses exceed the supported billing total. Review the source records.')
    audit(cursor,cycle['cycle_id'],owner,'expense_sources_loaded',{
        'previous_source':cycle.get('utility_source'),'previous_electricity':cycle['electricity_total'],
        'previous_water':cycle['water_total'],'sources':sources})
    cursor.execute('''UPDATE billing_cycles SET utility_source='expenses',utility_expense_digest=%s,
        utility_snapshot=%s,electricity_total=%s,water_total=%s,version=version+1 WHERE cycle_id=%s''',
        (sources['digest'],canonical(sources),electricity,water,cycle['cycle_id']))


def assert_sources(cursor,cycle):
    # Legacy issued cycles retain frozen manual costs; never reinterpret history.
    if cycle['state']=='locked' and cycle.get('utility_source')=='manual_legacy':return
    if cycle.get('utility_source')!='expenses':
        raise BillingValidationError('Generate a new preview using saved Electricity and Water expenses first.')
    sources=current_sources(cursor,cycle)
    if not sources['ready']:raise BillingValidationError('Record Electricity and Water for this utility month, including explicit zeros.')
    if sources['digest']!=cycle['utility_expense_digest']:
        raise BillingValidationError('Saved utility expenses changed. Generate Bills again before sending.')


def protect_expense_period(cursor,boarding_id,values):
    if values.get('expense_id'):
        # Explicit per-invoice selections can reference Owner-only Other costs.
        # The shared Boarding lock serializes this guard with invoice issuance.
        cursor.execute('''SELECT 1 FROM bill_line_items l JOIN monthly_bills m ON m.bill_id=l.bill_id
            WHERE m.boarding_id=%s AND m.state='issued' AND
            JSON_UNQUOTE(JSON_EXTRACT(l.details,'$.expense_id'))=%s LIMIT 1''',(boarding_id,str(values['expense_id'])))
        if cursor.fetchone():
            from finance_service import FinanceConflict
            raise FinanceConflict('This expense is linked to an issued invoice. Its financial source cannot be changed or archived.')
    if values.get('category') not in ('electricity','water') and not (shared_enabled() and values.get('category')=='other' and values.get('charge_to_tenants')):return
    cursor.execute('''SELECT cycle_id FROM billing_cycles WHERE boarding_id=%s AND period_start=%s
        AND state='locked' AND utility_source='expenses' LIMIT 1''',(boarding_id,values['utility_period']))
    if cursor.fetchone():
        # Parent Boarding lock serializes this check with issuance and corrections.
        from finance_service import FinanceConflict
        raise FinanceConflict('These utility costs belong to issued bills. Use the password-confirmed Correct Cycle action before changing this month.')
