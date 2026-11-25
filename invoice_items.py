"""Student-specific invoice items; shared utility allocations stay immutable."""
from copy import deepcopy
from decimal import Decimal,ROUND_HALF_UP
from datetime import datetime,timezone
import json,re

from billing_calculator import BillingValidationError,CENT,ZERO,decimal_money

MAX_ITEMS=20


def amount_value(value,*,zero=False):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,12}(?:\.[0-9]{1,2})?',value.strip()):
        raise BillingValidationError('Enter a valid LKR amount with no more than two decimal places.','items')
    amount=decimal_money(Decimal(value.strip()))
    if not zero and amount==0:raise BillingValidationError('Enter a positive charge amount.','items')
    return amount


def parse_items(raw,*,allow_legacy=True):
    if not isinstance(raw,list) or len(raw)>MAX_ITEMS:
        raise BillingValidationError('Add no more than 20 custom charges.','items')
    result=[]
    for index,item in enumerate(raw,1):
        if not isinstance(item,dict) or (set(item)!={'description','amount'} and not (allow_legacy and set(item)=={'description','quantity','unit_price'})):
            raise BillingValidationError('Custom charges accept only Description and Amount.','items')
        name=item['description']
        if not isinstance(name,str) or not 1<=len(name.strip())<=150 or any(ord(c)<32 for c in name):
            raise BillingValidationError('Item '+str(index)+': enter a description using 1–150 characters.','items')
        if 'amount' in item:
            result.append(dict(description=name.strip(),amount=format(amount_value(item['amount']),'.2f')))
            continue
        quantity=item['quantity'];price=item['unit_price']
        if isinstance(quantity,bool) or not isinstance(quantity,(str,int)) or not re.fullmatch(r'[1-9][0-9]{0,2}',str(quantity)):
            raise BillingValidationError('Item '+str(index)+': Quantity must be a whole number from 1 to 999.','items')
        if not isinstance(price,str) or not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,2})?',price.strip()) or Decimal(price)<=0:
            raise BillingValidationError('Item '+str(index)+': enter a positive Unit Price with at most two decimals.','items')
        result.append(dict(description=name.strip(),quantity=int(quantity),unit_price=format(Decimal(price).quantize(CENT),'.2f')))
    return result


def line_key(line):
    if line.get('kind') in ('electricity','water'):return line['kind']
    if line.get('kind')=='charge':
        if line['details'].get('expense_id'):return 'expense:'+str(line['details']['expense_id'])
        if line.get('adjustment_id'):return 'adjustment:'+str(line['adjustment_id'])
    return None


def parse_overrides(raw):
    if not isinstance(raw,list) or len(raw)>50:raise BillingValidationError('Adjust no more than 50 optional charges.')
    result=[];seen=set()
    for item in raw:
        if not isinstance(item,dict) or not {'key','amount'}<=set(item) or not set(item)<={'key','amount','reason','description'}:
            raise BillingValidationError('A charge adjustment requires its original charge and amount.')
        key=item['key'];reason=item.get('reason','')
        if not isinstance(key,str) or not re.fullmatch(r'(electricity|water|(?:expense|adjustment):[1-9][0-9]{0,9})',key) or key in seen:
            raise BillingValidationError('Choose each valid optional charge only once; rent cannot be adjusted.')
        if not isinstance(reason,str) or len(reason.strip())>200 or any(ord(c)<32 for c in reason):
            raise BillingValidationError('Choose a valid draft adjustment.')
        entry=dict(key=key,amount=format(amount_value(item['amount'],zero=True),'.2f'),reason=reason.strip())
        if 'description' in item:
            name=item['description']
            if not isinstance(name,str) or not 1<=len(name.strip())<=150 or any(ord(c)<32 for c in name):raise BillingValidationError('Enter a charge description using 1–150 characters.')
            entry['description']=name.strip()
        seen.add(key);result.append(entry)
    return sorted(result,key=lambda item:item['key'])


def parse_discount(raw):
    if raw is None:return None
    if not isinstance(raw,dict) or set(raw)!={'description','amount'}:
        raise BillingValidationError('Enter a discount description and amount.','discount')
    name=raw['description']
    if not isinstance(name,str) or not 1<=len(name.strip())<=150 or any(ord(c)<32 for c in name):
        raise BillingValidationError('Enter a discount description using 1–150 characters.','discount')
    return dict(description=name.strip(),amount=format(amount_value(raw['amount']),'.2f'))


def compose_invoice(allocation,items,overrides=None,discount=None):
    """Recompute manual extensions and subtotal discounts, never change allocations."""
    items=parse_items(items);row=deepcopy(allocation)
    adjustments=parse_overrides(overrides or [])
    available={line_key(line):line for line in row['lines'] if line_key(line)}
    for override in adjustments:
        line=available.get(override['key'])
        if line is None:raise BillingValidationError('This optional charge is not part of the selected Student invoice. Reload charges.')
        original=line['amount'];final=Decimal(override['amount']);kind=line['kind']
        original_description=line['description']
        if override.get('description'):line['description']=override['description']
        line['details'].update(original_amount=format(original,'.2f'),charged_amount=override['amount'],
            adjustment_reason=override['reason'],original_description=original_description,waived=final==0,override_key=override['key'],adjustment_origin='owner_draft_edit')
        line['amount']=final
        row[kind+'_share' if kind in ('electricity','water') else 'charge_amount']+=final-original
    custom=[];extra=ZERO
    for item in items:
        amount=Decimal(item['amount']) if 'amount' in item else decimal_money(Decimal(item['unit_price'])*item['quantity']);extra+=amount
        custom.append(dict(kind='charge',description=item['description'],amount=amount,adjustment_id=None,
            details={'method':'student_specific','origin':'invoice_builder',
                **({'entered_amount':item['amount']} if 'amount' in item else {'quantity':item['quantity'],'unit_price':item['unit_price']})}))
    row['lines']=[line for line in row['lines'] if line['kind']!='discount']+custom+[line for line in row['lines'] if line['kind']=='discount']
    for line in row['lines']:
        if line['kind'] in ('rent','electricity','water'):
            if not line['details'].get('override_key') or not next((o.get('description') for o in adjustments if o['key']==line_key(line)),None):
                line['description']={'rent':'Boarding Rent','electricity':'Electricity Share','water':'Water Share'}[line['kind']]
    row['charge_amount']+=extra
    for line in row['lines']:
        if line['kind']!='discount':continue
        details=line['details']
        if details.get('scope')=='subtotal':
            base=row['rent_amount']+row['electricity_share']+row['water_share']+row['charge_amount']
            configured_discount=(base*Decimal(str(details['value']))/100).quantize(CENT,rounding=ROUND_HALF_UP) if details['discount_type']=='percentage' else Decimal(str(details['value']))
            if configured_discount>base:raise BillingValidationError('The saved discount exceeds this invoice subtotal.')
            line['amount']=-configured_discount;details['base']=base;row['discount_amount']=configured_discount
    row['final_total']=decimal_money(row['rent_amount']+row['electricity_share']+row['water_share']+row['charge_amount']-row['discount_amount'])
    discount=parse_discount(discount)
    if discount is not None:
        value=Decimal(discount['amount'])
        if value>row['final_total']:raise BillingValidationError('Discount cannot exceed the remaining invoice total.','discount')
        row['lines'].append(dict(kind='discount',description=discount['description'],amount=-value,adjustment_id=None,
            details=dict(origin='invoice_builder_discount',method='student_specific',discount_type='fixed',value=discount['amount'],
                scope='subtotal',base=row['final_total'],reason='')))
        row['discount_amount']+=value;row['final_total']-=value
    if sum((line['amount'] for line in row['lines']),ZERO)!=row['final_total']:
        raise BillingValidationError('Invoice items do not reconcile. Reload the charges.')
    row['manual_items']=items
    row['invoice_overrides']=adjustments
    row['invoice_discount']=discount
    return row


def display_lines(lines):
    rows=[]
    for line in lines:
        details=line.get('details') or {}
        if isinstance(details,(str,bytes)):details=json.loads(details)
        quantity=details.get('quantity',1) if details.get('origin')=='invoice_builder' else 1
        unit=Decimal(str(details['unit_price'])) if details.get('origin')=='invoice_builder' and 'unit_price' in details else line['amount']
        rows.append({**line,'details':details,'quantity':quantity,'unit_price':unit,'manual':details.get('origin')=='invoice_builder',
            'key':line_key({**line,'details':details}),'waived':bool(details.get('waived')),'adjusted':details.get('original_amount') is not None,
            'manual_discount':details.get('origin')=='invoice_builder_discount'})
    return rows


def totals(lines):
    subtotal=sum((line['amount'] for line in lines if line['kind']!='discount'),ZERO)
    discount=-sum((line['amount'] for line in lines if line['kind']=='discount'),ZERO)
    return dict(subtotal=subtotal,discount=discount,total=subtotal-discount)


def issue_time(value):
    from join_request_service import SRI_LANKA_TIME
    if not isinstance(value,datetime):return 'Set when sent'
    if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
    return value.astimezone(SRI_LANKA_TIME).strftime('%d %B %Y, %I:%M %p')+' (UTC+05:30)'
