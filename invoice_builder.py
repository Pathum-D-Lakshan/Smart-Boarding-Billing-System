"""Student-first invoice drafts using the existing billing engine and snapshots."""
from copy import deepcopy
from billing_calculator import BillingValidationError,month_period,overlap_days,canonical
import billing_service as billing
from invoice_items import parse_items,parse_overrides,parse_discount,compose_invoice,display_lines,totals
from invoice_expenses import parse_selection,expense_choices,selected_sources,apply_selection


def choices(owner,month):
    first,until,_=month_period(month);today=billing.local_today()
    with billing.get_db_connection() as c,c.cursor(dictionary=True) as q:
        c.start_transaction(readonly=True)
        q.execute('SELECT '+billing.BOARDING_COLUMNS+' FROM boardings WHERE owner_id=%s',(owner,));boarding=q.fetchone()
        if not boarding:return dict(boarding=None,students=[],month=month,default_due=billing.default_due_date(first).isoformat())
        q.execute(billing.TENANT_SQL,(boarding['boarding_id'],));students=q.fetchall()
    for row in students:
        row['tenancy_label']='Scheduled' if row['start_date']>today else 'Moved Out' if row['end_date'] and row['end_date']<=today else 'Active'
        row['eligible_days']=overlap_days(row['start_date'],row['end_date'],first,until)[2]
    return dict(boarding=boarding,students=students,month=month,default_due=billing.default_due_date(first).isoformat())


def preview(owner,payload):
    month=payload.get('month','');first,until,_=month_period(month)
    due=billing.due_date(payload.get('due_date',''),first)
    tenancy_id=billing.identifier(payload.get('tenancy_id',''),'tenancy')
    items=parse_items(payload.get('items',[]),allow_legacy=False)
    overrides=parse_overrides(payload.get('overrides',[]))
    selection=parse_selection(payload.get('selected_expenses',[]))
    discount=parse_discount(payload.get('discount'))
    data=choices(owner,month)
    selected=next((row for row in data['students'] if row['tenancy_id']==tenancy_id),None)
    if selected is None:raise billing.BillingNotFound()
    result=dict(boarding=data['boarding'],student=selected,month=month,due_date=due,items=items,
        cycle_id=None,token=None,ready=False,invoice=None,lines=[],messages=[],eligible=bool(selected['eligible_days']),issued_bill=None,overrides=overrides,selected_expenses=selection,expenses=[],discount=discount)
    if not result['eligible']:
        reason=('tenancy begins '+selected['start_date'].strftime('%d %B %Y') if selected['start_date']>=until
            else 'tenancy ended '+selected['end_date'].strftime('%d %B %Y') if selected['end_date'] else 'no approved tenancy days overlap this month')
        result['messages'].append('Not eligible for '+first.strftime('%B %Y')+' — '+reason+'.')
        return result
    current=billing.load_billing(owner,month)
    existing=next(row for row in current['rows'] if row['tenancy_id']==tenancy_id)
    if existing.get('issued_bill'):
        result['issued_bill']=existing['issued_bill'];result['messages'].append('An invoice is already issued for this tenancy and month. View the saved invoice.');return result
    # A locked common allocation remains immutable. Each new invoice can have its
    # own due date; it never rewrites another Student's due date or allocation.
    cycle=current.get('cycle')
    if not cycle or cycle['state']=='draft':
        cycle_id=billing.prepare_expense_preview(owner,month,due.isoformat())
    else:cycle_id=cycle['cycle_id']
    base=billing.preview_billing(owner,cycle_id,[tenancy_id])
    row=next(row for row in base['rows'] if row['tenancy_id']==tenancy_id)
    with billing.get_db_connection() as c,c.cursor(dictionary=True) as q:
        candidates=expense_choices(q,data['boarding']['boarding_id'],first,base,tenancy_id,selection)
    sources=selected_sources(candidates,selection)
    result['expenses']=candidates
    row=apply_selection(row,sources)
    legacy_costs=base['cycle']['state']=='locked' and base['cycle'].get('utility_source')=='manual_legacy'
    pending=set() if legacy_costs else {kind for kind in ('electricity','water') if base['utility_sources']['totals'][kind] is None}
    if any(override['key'] in pending for override in overrides):raise BillingValidationError('Record the actual utility expense before adjusting its calculated share.')
    invoice=compose_invoice(row,items,overrides,discount)
    ready=bool(base['preview_token']);costs_ready=base['costs_ready']
    messages=result['messages']
    if not base['period_started']:messages.append('Preview available — this billing month has not started. Issue from '+first.strftime('%d %B %Y')+'.')
    if not costs_ready:
        for kind in ('electricity','water'):
            if base['utility_sources']['totals'][kind] is None:messages.append(kind.title()+' expense not recorded for this month.')
    if base['stale']:messages.append('Tenancy data changed after this period was issued. Use the audited correction workflow.')
    if base['sources_changed']:messages.append('Saved costs changed. Reload Rent & Utility Charges before sending.')
    if base['validation_error']:messages.append(base['validation_error'])
    token=None
    if ready:
        signed=billing._token_data(base['cycle'],base,[tenancy_id])
        signed.update(invoice_items=items,invoice_due=due.isoformat(),invoice_overrides=overrides,invoice_expenses=billing._json(canonical(sources)))
        if discount is not None:signed['invoice_discount']=discount
        token=billing._signer().dumps(signed)
    lines=display_lines(invoice['lines'])
    for line in lines:
        line['pending']=line['kind'] in pending
        line['editable']=bool(line['key']) and not line['pending']
    paper=dict(boarding_snapshot=data['boarding'],recipient_name=row['student_name'],recipient_email=row['student_email'],
        unit_snapshot={'room_number':row['room_number'],'bed_label':row['bed_label'],'rent_unit':row['rent_unit']},
        period_start=first,due_date=due,bill_reference=None,issued_at=None,state='draft',final_total=invoice['final_total'],
        lines=lines,draft=True,costs_ready=costs_ready,**totals(invoice['lines']))
    result.update(cycle_id=cycle_id,token=token,ready=ready,invoice=paper,lines=lines,
        costs_ready=costs_ready,current_month=base['period_started'] and not base['month_complete'],eligible_days=row['eligible_days'],calendar_days=row['calendar_days'],total_tenant_days=row['total_tenant_days'])
    return result


def issue(owner,payload):
    if payload.get('confirm_send')!='yes':raise BillingValidationError('Confirm the reviewed invoice before sending.')
    first,_,_=month_period(payload.get('month',''))
    due=billing.due_date(payload.get('due_date',''),first)
    tenancy=billing.identifier(payload.get('tenancy_id',''),'tenancy')
    cycle_id=billing.identifier(str(payload.get('cycle_id','')),'cycle')
    # Rechecking the period on the owned cycle also prevents a changed UI month
    # from reusing a valid token belonging to a different entitlement.
    with billing.get_db_connection() as c,c.cursor(dictionary=True) as q:
        cycle=billing._cycle(q,owner,cycle_id)
        if cycle['period_start']!=first:raise billing.BillingConflict('Billing month changed. Reload charges and review again.')
    return billing.generate_bills(owner,cycle_id,[tenancy],payload.get('preview_token',''),
        invoice_items=parse_items(payload.get('items',[]),allow_legacy=False),invoice_due=due.isoformat(),
        invoice_overrides=parse_overrides(payload.get('overrides',[])),invoice_expenses=parse_selection(payload.get('selected_expenses',[])),
        invoice_discount=parse_discount(payload.get('discount')))


def paper_from_bill(bill):
    paper=deepcopy(bill);paper['lines']=display_lines(bill['lines'])
    paper.update(totals(bill['lines']),draft=False,costs_ready=True)
    return paper
