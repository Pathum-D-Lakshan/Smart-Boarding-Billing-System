"""Read-only issued-bill balances at one Owner's boarding; no estimated final bill."""
from decimal import Decimal

from billing_calculator import digest
from payment_service import student_bill_state


def load_settlement(cursor, owner_id, boarding_id, student_id):
    # Include earlier stays at this boarding, never another Owner's financial records.
    cursor.execute('''SELECT m.bill_id,m.bill_reference,m.tenancy_id,m.period_start,m.due_date,
        m.final_total,m.state,m.revision,p.payment_id,p.status AS payment_status,p.amount AS payment_amount,
        p.method,p.revision AS payment_revision,r.receipt_id
        FROM monthly_bills m JOIN boardings b ON b.boarding_id=m.boarding_id
        LEFT JOIN payments p ON p.bill_id=m.bill_id AND p.status IN ('submitted','verified')
        LEFT JOIN receipts r ON r.payment_id=p.payment_id AND r.bill_id=m.bill_id
        WHERE b.owner_id=%s AND m.boarding_id=%s AND m.student_id=%s AND m.state='issued'
        ORDER BY m.period_start DESC,m.bill_id DESC''',(owner_id,boarding_id,student_id))
    rows=cursor.fetchall()
    version=digest({'boarding_id':boarding_id,'student_id':student_id,'bills':rows})
    total=paid=outstanding=pending=Decimal('0.00')
    paid_count=review_count=0
    for bill in rows:
        active={'status':bill['payment_status'],'receipt_id':bill['receipt_id'],'method':bill['method']} if bill['payment_id'] else None
        # Match Payments: submitted slips are not money received, and verified needs a receipt.
        settled=bool(active and active['status']=='verified' and active['receipt_id'] and bill['payment_amount']==bill['final_total'])
        bill['payment_label']=student_bill_state(bill,active)['bill_status']
        if active and active['status']=='submitted':bill['payment_label']='Pending Verification'
        if active and active['status']=='verified' and not settled:
            bill['payment_label']='Verification Needs Review';review_count+=1
        bill['outstanding']=Decimal('0.00') if settled else bill['final_total']
        total+=bill['final_total'];outstanding+=bill['outstanding']
        if settled:paid+=bill['final_total'];paid_count+=1
        if active and active['status']=='submitted':pending+=bill['final_total']
    label=('No Bills Issued' if not rows else 'Outstanding Balance' if outstanding else
           'Verification Needs Review' if review_count else 'No Payment Due — Issued Bills' if not total else
           'Paid in Full — Issued Bills' if paid_count==len(rows) else 'No Payment Due — Issued Bills')
    return dict(total=total,paid=paid,outstanding=outstanding,pending=pending,bill_count=len(rows),
                paid_count=paid_count,review_count=review_count,label=label,token=version,rows=rows[:12])
