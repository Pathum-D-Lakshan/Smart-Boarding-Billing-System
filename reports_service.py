"""Read-only Owner financial reports; Finance remains the calculation authority."""
from datetime import datetime,timezone
from decimal import Decimal,ROUND_HALF_UP
import re

from db import get_db_connection
from finance_service import FinanceValidationError,accounting_period_available,expense_month_scope,period,reporting_summary
from tenancy_service import SRI_LANKA_TIME,local_today

MAX_MONTHS=12
MAX_DETAIL_ROWS=5000
METHODS={'bank_transfer':'Bank Transfer','cash':'Cash'}


class ReportValidationError(ValueError):pass
class ReportTooLarge(ValueError):pass


def month_value(value):
    if not isinstance(value,str) or not re.fullmatch(r'20[0-9]{2}-(?:0[1-9]|1[0-2])',value):
        raise ReportValidationError('Choose a valid month between January 2000 and December 2099.')
    try:period(value)
    except FinanceValidationError:raise ReportValidationError('Choose a valid reporting month.') from None
    return value


def shift_month(month,offset):
    year,number=map(int,month.split('-'));index=year*12+number-1+offset
    return f'{index//12:04d}-{index%12+1:02d}'


def month_label(month):return datetime.strptime(month,'%Y-%m').strftime('%B %Y')
def money(value):return f'{value:,.2f}'


def filters(params):
    tab=params.get('tab','monthly');trend=params.get('trend','income')
    if tab not in ('monthly','analysis') or trend not in ('income','balance'):
        raise ReportValidationError('Choose Monthly Report or Multi-Month Analysis and a valid trend.')
    month=month_value(params.get('month') or local_today().strftime('%Y-%m'))
    start=month_value(params.get('start') or max('2000-01',shift_month(month,-5)))
    end=month_value(params.get('end') or month)
    months=[];current=start
    if start>end:raise ReportValidationError('Start Month must be on or before End Month.')
    while current<=end:
        months.append(current)
        if len(months)>MAX_MONTHS:raise ReportValidationError('Choose a reporting interval of no more than 12 months.')
        current=shift_month(current,1)
    return dict(tab=tab,month=month,start=start,end=end,trend=trend),months


def expense_breakdown(rows,total):
    # Free-text expense names are never converted to invented categories.
    groups={}
    for row in rows:
        label=' '.join(row['expense_name'].split());key=label.casefold()
        group=groups.setdefault(key,{'label':label,'amount':Decimal('0')});group['amount']+=row['amount']
    ranked=sorted(groups.values(),key=lambda item:(-item['amount'],item['label'].casefold()))
    if len(ranked)>8:
        ranked=ranked[:7]+[dict(label='Other recorded names',amount=sum((r['amount'] for r in ranked[7:]),Decimal('0')))]
    for row in ranked:
        row['percentage']=(row['amount']*100/total).quantize(Decimal('.1'),rounding=ROUND_HALF_UP) if total else Decimal('0')
    return ranked


def _details(cursor,boarding_id,month,allocated):
    first,until,start,end=period(month)
    cursor.execute('''SELECT p.payment_reference,p.decided_at,p.method,p.amount FROM payments p
        JOIN monthly_bills m ON m.bill_id=p.bill_id WHERE m.boarding_id=%s
        AND p.status='verified' AND p.method IN ('bank_transfer','cash')
        AND p.decided_at>=%s AND p.decided_at<%s ORDER BY p.decided_at,p.payment_id LIMIT %s''',
        (boarding_id,start,end,MAX_DETAIL_ROWS+1))
    income=cursor.fetchall()
    clause,dates=expense_month_scope(first,until,allocated)
    cursor.execute('''SELECT expense_name,expense_date,amount FROM expenses
        WHERE boarding_id=%s AND archived_at IS NULL AND '''+clause+
        ' ORDER BY expense_date,expense_id LIMIT %s',(boarding_id,*dates,MAX_DETAIL_ROWS+1))
    expenses=cursor.fetchall()
    if len(income)>MAX_DETAIL_ROWS or len(expenses)>MAX_DETAIL_ROWS:
        raise ReportTooLarge('This month exceeds the 5,000-record limit per detail table. No partial report was exported. Contact support for a larger export.')
    for row in income:
        row['collection_date']=row['decided_at'].replace(tzinfo=timezone.utc).astimezone(SRI_LANKA_TIME).date()
        row['method_label']=METHODS[row['method']]
        row.pop('method');row.pop('decided_at')
    return income,expenses


def load_report(owner,params):
    view,months=filters(params)
    with get_db_connection() as connection,connection.cursor(dictionary=True) as cursor:
        # Summary/detail/series share one snapshot, including during PDF generation.
        connection.start_transaction(isolation_level='REPEATABLE READ',readonly=True,consistent_snapshot=True)
        cursor.execute('SELECT boarding_id,boarding_name FROM boardings WHERE owner_id=%s',(owner,));boarding=cursor.fetchone()
        result=dict(boarding=boarding,view=view,month_label=month_label(view['month']),summary=None,income=[],expenses=[],breakdown=[],months=[],period_totals=None,
            generated_at=datetime.now(SRI_LANKA_TIME))
        if not boarding:return result
        allocated=accounting_period_available(cursor)
        if view['tab']=='monthly':
            summary=reporting_summary(cursor,boarding['boarding_id'],view['month'],allocated)
            income,expenses=_details(cursor,boarding['boarding_id'],view['month'],allocated)
            if sum((r['amount'] for r in income),Decimal('0'))!=summary['income'] or sum((r['amount'] for r in expenses),Decimal('0'))!=summary['expenses']:
                raise ReportValidationError('The report details could not be reconciled with Finance. No inconsistent report was produced.')
            result.update(summary=summary,income=income,expenses=expenses,breakdown=expense_breakdown(expenses,summary['expenses']))
        else:
            series=[dict(month=m,label=month_label(m),**reporting_summary(cursor,boarding['boarding_id'],m,allocated)) for m in months]
            totals={key:sum((r[key] for r in series),Decimal('0')) for key in ('income','expenses','balance')}
            result.update(months=series,period_totals=totals)
        return result


def chart_data(report):
    return [dict(label=row['label'],**{key:str(row[key]) for key in ('income','expenses','balance')},
        **{key+'_formatted':money(row[key]) for key in ('income','expenses','balance')}) for row in report['months']]
