"""Pure Decimal billing calculations; no browser amounts or database side effects."""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import hashlib
import json
import re

CENT=Decimal('0.01')
ZERO=Decimal('0.00')
MAX_TOTAL=Decimal('999999999999.99')


class BillingValidationError(ValueError):
    def __init__(self,message,field='billing'):
        self.errors={field:message}
        super().__init__(message)


def month_period(text):
    if not isinstance(text,str) or not re.fullmatch(r'(20[0-9]{2}|2100)-(0[1-9]|1[0-2])',text):
        raise BillingValidationError('Choose a billing month between 2000 and 2100.','month')
    year,month=map(int,text.split('-'))
    start=date(year,month,1)
    until=date(year+1,1,1) if month==12 else date(year,month+1,1)
    return start,until,monthrange(year,month)[1]


def input_amount(text,field='amount',percentage=False):
    if not isinstance(text,str) or not re.fullmatch(r'[0-9]{1,9}(\.[0-9]{1,2})?',text.strip()):
        raise BillingValidationError('Enter a non-negative amount with at most two decimal places. Use 0 to confirm no expense.',field)
    amount=Decimal(text.strip()).quantize(CENT)
    if percentage and amount>100:
        raise BillingValidationError('Percentage must be between 0 and 100.',field)
    return amount


def decimal_money(value):
    if isinstance(value,float): raise BillingValidationError('Currency must use Decimal, never floating point.')
    result=Decimal(value)
    if not result.is_finite() or result<0 or result>MAX_TOTAL or result!=result.quantize(CENT):
        raise BillingValidationError('The saved monetary amount is invalid.')
    return result.quantize(CENT)


def overlap_days(start,end,period_start,period_until):
    first=max(start,period_start)
    until=min(end or period_until,period_until)
    return first,until,max(0,(until-first).days)


def allocate_cents(total,weights):
    """Largest remainder in integer cents reconciles exactly; stable IDs break ties."""
    total=decimal_money(total)
    weights=[(int(key),int(days)) for key,days in weights if days>0]
    denominator=sum(days for _,days in weights)
    if not denominator: return {},total
    cents=int(total*100)
    whole={key:(cents*days)//denominator for key,days in weights}
    remainder=sorted(((cents*days)%denominator,key) for key,days in weights)
    order=sorted(remainder,key=lambda item:(-item[0],item[1]))
    for _,key in order[:cents-sum(whole.values())]: whole[key]+=1
    return {key:Decimal(value)/100 for key,value in whole.items()},ZERO


def json_value(value):
    if isinstance(value,Decimal): return format(value,'.2f')
    if isinstance(value,date): return value.isoformat()
    raise TypeError('Unsupported billing snapshot value')


def canonical(value):
    return json.dumps(value,default=json_value,sort_keys=True,separators=(',',':'),ensure_ascii=False)


def digest(value): return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def calculate_bills(month,tenancies,rules,electricity,water,*,shared_expenses=()):
    # Expense-backed rules use the existing exact-cent allocator and discount
    # calculation. Negative temporary IDs never become adjustment foreign keys.
    rules=list(rules)+[dict(adjustment_id=-source['expense_id'],kind='charge',name=source['expense_name'],
        value=source['amount'],apply_all=True,targets=[],application_method='shared_total',category='other',
        recurrence='once',expense_id=source['expense_id'],expense_revision=source['revision']) for source in shared_expenses]
    start,until,calendar_days=month_period(month)
    rows=[]; excluded=[]
    for tenancy in sorted(tenancies,key=lambda row:row['tenancy_id']):
        first,last,days=overlap_days(tenancy['start_date'],tenancy['end_date'],start,until)
        if not days:
            reason=('Starts after this billing month' if tenancy['start_date']>=until else
                    'Checkout is on/before this billing month' if tenancy['end_date'] and tenancy['end_date']<=start else 'No billable days')
            excluded.append({**tenancy,'reason':reason})
            continue
        rent=decimal_money(tenancy['agreed_monthly_rent'])
        if rent<=0: raise BillingValidationError('An eligible tenancy has no valid agreed rent.')
        with localcontext() as context:
            context.prec=40
            prorated=(rent*days/Decimal(calendar_days)).quantize(CENT,rounding=ROUND_HALF_UP)
        rows.append({**tenancy,'eligible_from':first,'eligible_until':last,'eligible_days':days,
            'calendar_days':calendar_days,'agreed_rent':rent,'rent_amount':prorated,
            'charge_amount':ZERO,'discount_amount':ZERO,'lines':[{'kind':'rent','description':'Prorated agreed rent',
                'amount':prorated,'adjustment_id':None,'details':{'agreed_rent':rent,'eligible_days':days,'calendar_days':calendar_days,
                'eligible_from':first,'eligible_until':last,'rent_unit':tenancy['rent_unit'],
                'bed_rate_id':tenancy.get('bed_rate_id'),'room_rate_id':tenancy.get('room_rate_id')}}]})
    weights=[(row['tenancy_id'],row['eligible_days']) for row in rows]
    total_days=sum(days for _,days in weights)
    electricity_shares,electricity_unallocated=allocate_cents(electricity,weights)
    water_shares,water_unallocated=allocate_cents(water,weights)
    for row in rows:
        row['total_tenant_days']=total_days
        for kind,shares,total in (('electricity',electricity_shares,electricity),('water',water_shares,water)):
            row[kind+'_share']=shares[row['tenancy_id']]
            row['lines'].append({'kind':kind,'description':kind.capitalize()+' - eligible tenant-days',
                'amount':shares[row['tenancy_id']],'adjustment_id':None,'details':{'utility_total':decimal_money(total),
                'eligible_days':row['eligible_days'],'total_tenant_days':total_days,'rounding':'largest_remainder_cents'}})
    unallocated_charges=[]
    for rule in sorted((rule for rule in rules if rule['kind']=='charge'),key=lambda rule:rule['adjustment_id']):
        amount=decimal_money(rule['value'])
        targets=[row for row in rows if rule['apply_all'] or row['tenancy_id'] in rule['targets']]
        if rule['application_method']=='shared_total':
            amounts,left=allocate_cents(amount,[(row['tenancy_id'],row['eligible_days']) for row in targets])
            if left: unallocated_charges.append({'name':rule['name'],'amount':left})
        else: amounts={row['tenancy_id']:amount for row in targets}
        for row in targets:
            applied=amounts[row['tenancy_id']]
            row['charge_amount']+=applied
            row['lines'].append({'kind':'charge','description':rule['name'],'amount':applied,'adjustment_id':None if rule.get('expense_id') else rule['adjustment_id'],
                'details':{'configured_amount':amount,'method':rule['application_method'],'category':rule['category'],
                'recurrence':rule['recurrence'],'eligible_days':row['eligible_days'],
                'target_tenant_days':sum(target['eligible_days'] for target in targets),
                **({'expense_id':rule['expense_id'],'expense_revision':rule['expense_revision'],'origin':'shared_expense'} if rule.get('expense_id') else {})}})
    for row in rows:
        applicable=[rule for rule in rules if rule['kind']=='discount' and (rule['apply_all'] or row['tenancy_id'] in rule['targets'])]
        if len(applicable)>1:
            raise BillingValidationError('Only one effective discount is allowed per tenancy. Remove the overlapping discount first.','discount')
        subtotal=row['rent_amount']+row['electricity_share']+row['water_share']+row['charge_amount']
        if applicable:
            rule=applicable[0]; value=decimal_money(rule['value'])
            base=row['rent_amount'] if rule['discount_scope']=='rent' else subtotal
            if rule['value_type']=='percentage':
                if value>100: raise BillingValidationError('Discount percentage cannot exceed 100.','discount')
                applied=(base*value/100).quantize(CENT,rounding=ROUND_HALF_UP)
            else: applied=value
            if applied>base:
                raise BillingValidationError('The discount exceeds an eligible tenancy\'s selected discount base.','discount')
            row['discount_amount']=applied
            row['lines'].append({'kind':'discount','description':rule['name'],'amount':-applied,'adjustment_id':rule['adjustment_id'],
                'details':{'discount_type':rule['value_type'],'value':value,'scope':rule['discount_scope'],'base':base,'reason':rule.get('description') or ''}})
        row['final_total']=subtotal-row['discount_amount']
        decimal_money(row['final_total'])
    # Only financially relevant overlap facts enter freshness checks; unrelated future
    # date edits or identity spelling changes do not rewrite an issued allocation.
    facts=[{key:row[key] for key in ('tenancy_id','student_id','room_id','bed_id','rent_unit','eligible_from','eligible_until',
        'eligible_days','agreed_rent','rent_amount','electricity_share','water_share','charge_amount','discount_amount','final_total','lines')} for row in rows]
    return {'rows':rows,'ineligible':excluded,'period_start':start,'period_until':until,'calendar_days':calendar_days,
        'total_tenant_days':total_days,'electricity_total':decimal_money(electricity),'water_total':decimal_money(water),
        'electricity_unallocated':electricity_unallocated,'water_unallocated':water_unallocated,
        'unallocated_charges':unallocated_charges,'source_digest':digest(facts),
        'eligible_student_count':len({row['student_id'] for row in rows}),
        'joining_count':len({row['student_id'] for row in rows if start<=row['start_date']<until}),
        'moving_count':len({row['student_id'] for row in rows if row['end_date'] and start<=row['end_date']<until}),
        'ineligible_student_count':len({row['student_id'] for row in excluded}-{row['student_id'] for row in rows})}


def selected_summary(calculation,selected_ids):
    chosen=set(selected_ids)
    valid={row['tenancy_id'] for row in calculation['rows']}
    if not chosen<=valid: raise BillingValidationError('Select only eligible tenancies from your boarding.','selected_ids')
    rows=[row for row in calculation['rows'] if row['tenancy_id'] in chosen]
    return {'bill_count':len(rows),'student_count':len({row['student_id'] for row in rows}),
        **{field:sum((row[field] for row in rows),ZERO) for field in
            ('rent_amount','electricity_share','water_share','charge_amount','discount_amount','final_total')}}
