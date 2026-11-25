"""Private vector/text PDFs from the same authoritative report result as HTML."""
from html import escape
from io import BytesIO
from pathlib import Path
import threading

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,TableStyle,KeepTogether,CondPageBreak
from reports_service import month_label,money

FONT_LOCK=threading.Lock()


def _fonts():
    with FONT_LOCK:
        if 'ReportsSans' not in pdfmetrics.getRegisteredFontNames():
            folder=Path(reportlab.__file__).parent/'fonts'
            pdfmetrics.registerFont(TTFont('ReportsSans',str(folder/'Vera.ttf')))
            pdfmetrics.registerFont(TTFont('ReportsBold',str(folder/'VeraBd.ttf')))


def financial_pdf(data):
    _fonts();buffer=BytesIO()
    title='Monthly Financial Report' if data['view']['tab']=='monthly' else 'Multi-Month Financial Analysis'
    doc=SimpleDocTemplate(buffer,pagesize=A4,rightMargin=38,leftMargin=38,topMargin=48,bottomMargin=48,
        title=title,author='Smart Boarding & Billing System',pageCompression=1)
    body=ParagraphStyle('Body',fontName='ReportsSans',fontSize=9,leading=13,textColor=colors.HexColor('#172f4b'),spaceAfter=6,splitLongWords=True)
    heading=ParagraphStyle('Heading',parent=body,fontName='ReportsBold',fontSize=16,leading=21,spaceAfter=12)
    subheading=ParagraphStyle('Subheading',parent=body,fontName='ReportsBold',fontSize=11,leading=16,spaceBefore=12,spaceAfter=8)
    right=ParagraphStyle('Money',parent=body,alignment=TA_RIGHT)
    header_style=ParagraphStyle('TableHeader',parent=body,fontName='ReportsBold',textColor=colors.white)
    def p(value,style=body):
        # Plain database text must never become ReportLab markup or external content.
        return Paragraph(escape(str(value)).replace('\n','<br/>'),style)
    story=[p('Smart Boarding & Billing System',heading),p(title,subheading),p(data['boarding']['boarding_name'],subheading)]
    view=data['view']
    period=data['month_label'] if view['tab']=='monthly' else month_label(view['start'])+' to '+month_label(view['end'])
    story.extend([p(period),p('Generated '+data['generated_at'].strftime('%d %b %Y, %I:%M %p')+' (Sri Lanka, UTC+05:30)'),p('Read-only operational collections report. Net Balance is collected income less actual recorded expenses, not an accrual accounting net profit.'),Spacer(1,6)])
    def table(headers,rows,widths,number_columns=()):
        cells=[[p(h,header_style) for h in headers]]
        cells.extend([[p(value,right if index in number_columns else body) for index,value in enumerate(row)] for row in rows])
        if not rows:cells.append([p('No records for this period.')]+[p('') for _ in headers[1:]])
        result=LongTable(cells,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1)
        result.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#173d58')),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#f2f6fa')]),
            ('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),
            ('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#173d58')),('LINEBELOW',(0,1),(-1,-1),.35,colors.HexColor('#d4e0e9'))]))
        return result
    total=data['summary'] if view['tab']=='monthly' else data['period_totals']
    summary_rows=[['Total Collected Income','LKR '+money(total['income'])],['Total Actual Expenses','LKR '+money(total['expenses'])],['Net Balance','LKR '+money(total['balance'])]]
    story.append(table(['Financial Summary','Amount (LKR)'],summary_rows,[310,209],(1,)))
    if view['tab']=='monthly':
        story.extend([CondPageBreak(100),p('Verified Income Details',subheading)])
        story.append(table(['Payment Reference','Collection Date','Method','Amount (LKR)'],
            [[r['payment_reference'],r['collection_date'].strftime('%d %b %Y'),r['method_label'],money(r['amount'])] for r in data['income']],
            [190,90,110,129],(3,)))
        story.extend([CondPageBreak(100),p('Actual Expense Details',subheading)])
        story.append(table(['Expense Name','Paid Date','Amount (LKR)'],
            [[r['expense_name'],r['expense_date'].strftime('%d %b %Y'),money(r['amount'])] for r in data['expenses']],
            [300,90,129],(2,)))
    else:
        story.extend([CondPageBreak(100),p('Monthly Comparison',subheading)])
        story.append(table(['Month','Income (LKR)','Expenses (LKR)','Net Balance (LKR)'],
            [[r['label'],money(r['income']),money(r['expenses']),money(r['balance'])] for r in data['months']],
            [150,123,123,123],(1,2,3)))
    story.append(KeepTogether([p('Final Summary',subheading),table(['Period Totals','Amount (LKR)'],summary_rows,[310,209],(1,)),
        p('Collections use the verification date, including confirmed cash. Pending/rejected payments, unpaid bills and archived expenses are excluded. No additional bill utility allocation or maintenance cost is added.')]))
    def footer(canvas,document):
        canvas.saveState();canvas.setStrokeColor(colors.HexColor('#d4e0e9'));canvas.line(38,35,A4[0]-38,35)
        canvas.setFont('ReportsSans',8);canvas.setFillColor(colors.HexColor('#53697c'))
        canvas.drawString(38,23,'Smart Boarding & Billing System | Private Owner Report')
        canvas.drawRightString(A4[0]-38,23,'Page '+str(document.page));canvas.restoreState()
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return buffer.getvalue()
