"""Owner-only GET reports and private in-memory PDF downloads."""
from io import BytesIO
from flask import Blueprint,abort,current_app,g,redirect,render_template,request,send_file,url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException
from auth_access import load_current_account
from reports_service import ReportValidationError,ReportTooLarge,chart_data,load_report,month_label,shift_month

owner_reports=Blueprint('owner_reports',__name__,url_prefix='/owner/reports')


@owner_reports.app_context_processor
def reports_available():return {'reports_navigation_enabled':True}


@owner_reports.before_request
def require_owner():
    owner=load_current_account()
    if not owner:return redirect(url_for('login'))
    if owner['role']!='owner':abort(403)
    g.reports_owner=owner


@owner_reports.after_request
def private(response):
    response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';return response


def failure(message,status):return render_template('owner/reports.html',error=message,data=None,owner_name=g.reports_owner['full_name'] if g.get('reports_owner') else 'Owner'),status


@owner_reports.errorhandler(HTTPException)
def http_error(error):return failure('Owner access is required.' if error.code==403 else 'This report action is unavailable.',error.code)


@owner_reports.errorhandler(ReportValidationError)
def invalid(error):return failure(str(error),400)


@owner_reports.errorhandler(ReportTooLarge)
def too_large(error):return failure(str(error),422)


@owner_reports.errorhandler(Error)
def unavailable(error):
    current_app.logger.error('Reports read failed (%s).',error.errno)
    return failure('Reports could not be loaded. Please try again later.',503)


@owner_reports.get('')
def overview():
    data=load_report(g.reports_owner['user_id'],request.args)
    view=data['view']
    presets=[dict(label=f'Last {count} Months',start=max('2000-01',shift_month(view['month'],1-count)),end=view['month']) for count in (3,6,12)]
    return render_template('owner/reports.html',data=data,view=view,chart=chart_data(data),presets=presets,month_label=month_label,owner_name=g.reports_owner['full_name'])


def export(tab):
    params={**request.args.to_dict(),'tab':tab};data=load_report(g.reports_owner['user_id'],params)
    if not data['boarding']:return failure('Create a Boarding Profile before exporting a report.',404)
    try:
        from reports_pdf import financial_pdf
        content=financial_pdf(data)
    except ImportError:
        return failure('PDF export is not installed yet. The report remains available on screen.',503)
    view=data['view'];suffix=view['month'] if tab=='monthly' else view['start']+'-to-'+view['end']
    return send_file(BytesIO(content),mimetype='application/pdf',as_attachment=True,
        download_name=('boarding-financial-report-' if tab=='monthly' else 'boarding-analysis-')+suffix+'.pdf',max_age=0)


@owner_reports.get('/monthly.pdf')
def monthly_pdf():return export('monthly')


@owner_reports.get('/analysis.pdf')
def analysis_pdf():return export('analysis')
