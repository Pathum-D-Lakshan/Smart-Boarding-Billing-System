"""Private vector invoice PDFs generated only from a saved financial snapshot."""
from html import escape
from io import BytesIO
from decimal import Decimal
import json,re
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER,TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,LongTable,Table,TableStyle,KeepTogether
from reports_pdf import _fonts
from invoice_items import display_lines,issue_time


def filename(bill):return 'Invoice-'+re.sub(r'[^A-Za-z0-9_-]','-',bill['bill_reference'])[:90]+'.pdf'


def invoice_pdf(bill):
    _fonts();buffer=BytesIO()
    def unpack(value):return json.loads(value) if isinstance(value,(str,bytes)) else value
    boarding=unpack(bill['boarding_snapshot']);unit=unpack(bill['unit_snapshot']);lines=display_lines(bill['lines'])
    total=Decimal(str(bill['final_total']))
    if sum((Decimal(str(line['amount'])) for line in lines),Decimal('0'))!=total:raise ValueError('Invoice lines do not reconcile.')
    ink=colors.HexColor('#16324e');cyan=colors.HexColor('#087f96');pale=colors.HexColor('#eaf8fc')
    body=ParagraphStyle('InvoiceBody',fontName='ReportsSans',fontSize=10,leading=15,textColor=ink,spaceAfter=5,splitLongWords=True)
    bold=ParagraphStyle('InvoiceBold',parent=body,fontName='ReportsBold')
    title=ParagraphStyle('InvoiceTitle',parent=bold,fontSize=20,leading=26,alignment=TA_CENTER,spaceAfter=10)
    center=ParagraphStyle('InvoiceCenter',parent=body,alignment=TA_CENTER)
    right=ParagraphStyle('InvoiceRight',parent=bold,alignment=TA_RIGHT)
    def p(value,style=body):return Paragraph(escape(str(value)).replace('\n','<br/>'),style)
    doc=SimpleDocTemplate(buffer,pagesize=A4,leftMargin=42,rightMargin=42,topMargin=40,bottomMargin=48,
        title='Invoice '+bill['bill_reference'],author='Smart Boarding & Billing System',pageCompression=1)
    story=[p('SMART BOARDING & BILLING SYSTEM',center),p('MONTHLY RENT INVOICE',title),p(boarding['boarding_name'],ParagraphStyle('BoardingName',parent=bold,alignment=TA_CENTER,fontSize=13,leading=19))]
    if bill.get('state')=='void':story.append(p('VOID INVOICE - retained for financial history. Do not pay.',ParagraphStyle('VoidInvoice',parent=bold,textColor=colors.HexColor('#9f263d'),alignment=TA_CENTER)))
    if boarding.get('address'):story.append(p(boarding['address']+(', '+boarding['city'] if boarding.get('city') else ''),center))
    if boarding.get('contact_phone'):story.append(p(boarding['contact_phone'],center))
    story.append(Spacer(1,15))
    metadata=[['Invoice Number',bill['bill_reference']],['Student',bill['recipient_name']],
        ['Room / Bed',str(unit['room_number'])+(' / '+str(unit['bed_label']) if unit.get('bed_label') else ' / Entire Private Room')],
        ['Billing Month',bill['period_start'].strftime('%B %Y')],['Issued At (Sri Lanka)',issue_time(bill.get('issued_at'))],
        ['Payment Due Date',bill['due_date'].strftime('%d %B %Y')]]
    table=Table([[p(label,bold),p(value)] for label,value in metadata],colWidths=[165,346],hAlign='LEFT')
    table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('BACKGROUND',(0,0),(-1,-1),pale),('LEFTPADDING',(0,0),(-1,-1),10),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
    story.extend([table,Spacer(1,18)])
    rows=[[p('Description',bold),p('Amount (LKR)',right)]]
    for line in lines:
        if line['waived']:continue
        rows.append([p(line['description']),p(format(Decimal(str(line['amount'])),',.2f'),right)])
    charges=LongTable(rows,colWidths=[365,146],hAlign='LEFT',repeatRows=1)
    charges.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),pale),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),1,cyan),
        ('LINEBELOW',(0,1),(-1,-1),.35,colors.HexColor('#d7e4ec')),('TOPPADDING',(0,0),(-1,-1),9),('BOTTOMPADDING',(0,0),(-1,-1),9),('LEFTPADDING',(0,0),(-1,-1),9),('RIGHTPADDING',(0,0),(-1,-1),9)]))
    story.append(charges)
    total_table=Table([[p('TOTAL AMOUNT DUE',bold),p('LKR '+format(total,',.2f'),ParagraphStyle('InvoiceTotal',parent=right,fontSize=16,leading=22,textColor=cyan))]],colWidths=[300,211])
    total_table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),pale),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('TOPPADDING',(0,0),(-1,-1),15),('BOTTOMPADDING',(0,0),(-1,-1),15)]))
    story.append(KeepTogether([Spacer(1,14),total_table,Spacer(1,16),p('Please complete your payment by the due date.',center),p('This invoice is not a paid receipt.',center),p('Thank you!',center)]))
    if any(line['waived'] for line in lines):story.append(p('Waived charges: '+', '.join(line['description'] for line in lines if line['waived'])))
    def footer(canvas,document):
        canvas.saveState();canvas.setStrokeColor(cyan);canvas.line(42,35,A4[0]-42,35);canvas.setFont('ReportsSans',8);canvas.setFillColor(ink)
        canvas.drawString(42,23,bill['bill_reference']);canvas.drawRightString(A4[0]-42,23,'Page '+str(document.page));canvas.restoreState()
    def stable_canvas(*args,**kwargs):kwargs['invariant']=1;return Canvas(*args,**kwargs)
    doc.build(story,onFirstPage=footer,onLaterPages=footer,canvasmaker=stable_canvas)
    return buffer.getvalue()
