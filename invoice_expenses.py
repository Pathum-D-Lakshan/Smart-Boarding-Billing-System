"""Per-invoice saved-expense selection using the existing tenant-day allocator."""
from copy import deepcopy
import re
from billing_calculator import BillingValidationError,allocate_cents,month_period,ZERO
from finance_service import accounting_period_available,expense_month_scope


def parse_selection(raw):
    if not isinstance(raw,list) or len(raw)>50:raise BillingValidationError('Select no more than 50 saved expenses.')
    ids=[]
    for value in raw:
        if isinstance(value,bool) or not isinstance(value,(str,int)) or not re.fullmatch(r'[1-9][0-9]{0,9}',str(value)):
            raise BillingValidationError('Choose valid saved expenses.')
        ids.append(int(value))
    if len(set(ids))!=len(ids):raise BillingValidationError('An expense can only be selected once.')
    return sorted(ids)


def expense_choices(cursor,boarding_id,period,calculation,tenancy_id,selected=()):
    first,until,_=month_period(period.strftime('%Y-%m'))
    clause,dates=expense_month_scope(first,until,accounting_period_available(cursor))
    cursor.execute('''SELECT expense_id,revision,expense_name,category,amount,expense_date,utility_period,
        archived_at,charge_to_tenants FROM expenses WHERE boarding_id=%s AND archived_at IS NULL AND
        (utility_period=%s OR (utility_period IS NULL AND '''+clause+'''))
        ORDER BY expense_date DESC,expense_id DESC''',(boarding_id,first,*dates))
    sources=cursor.fetchall();weights=[(row['tenancy_id'],row['eligible_days']) for row in calculation['rows']]
    result=[]
    for source in sources:
        shares,_=allocate_cents(source['amount'],weights)
        available=not source['archived_at'] and source['category']=='other' and tenancy_id in shares
        state=('Not Applicable' if source['archived_at'] or tenancy_id not in shares else
            'Already Included' if source['category'] in ('electricity','water') or source['expense_id'] in selected else 'Available to Add')
        result.append({**source,'share':shares.get(tenancy_id,ZERO),'available':available,'state':state})
    return result


def selected_sources(choices,ids):
    lookup={row['expense_id']:row for row in choices}
    if any(key not in lookup or not lookup[key]['available'] for key in ids):
        raise BillingValidationError('A selected expense is unavailable, archived, outside this month or belongs to another Boarding. Reload expenses.')
    # Sign source revision and monetary facts, not browser-supplied shares.
    return [{key:lookup[expense_id][key] for key in ('expense_id','revision','expense_name','category','amount','expense_date','utility_period','charge_to_tenants','share')} for expense_id in ids]


def apply_selection(allocation,sources):
    row=deepcopy(allocation)
    # Explicit selection replaces automatic/legacy extra-charge rows for this
    # invoice only. The shared allocation and other Students remain immutable.
    row['lines']=[line for line in row['lines'] if line['kind']!='charge']
    row['charge_amount']=ZERO
    for source in sources:
        row['charge_amount']+=source['share']
        row['lines'].append(dict(kind='charge',description=source['expense_name'],amount=source['share'],adjustment_id=None,
            details=dict(origin='selected_expense',method='shared_total',expense_id=source['expense_id'],expense_revision=source['revision'],
                configured_amount=source['amount'],original_calculated_share=source['share'],category=source['category'],
                eligible_days=row['eligible_days'],target_tenant_days=row['total_tenant_days'],explicit_selection=True)))
    return row
