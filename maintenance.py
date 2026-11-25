"""Shared maintenance lifecycle with scoped Owner and Student workspaces."""
import uuid
from datetime import timezone,timedelta
from flask import Blueprint,abort,current_app,flash,g,jsonify,redirect,render_template,request,send_file,url_for
from io import BytesIO
import hashlib
import secrets
from mysql.connector import Error
from werkzeug.exceptions import HTTPException,NotFound
from auth_access import load_current_account
from owner_confirmation import PasswordConfirmationError,confirm_owner_password
from maintenance_service import (STATUSES,PRIORITIES,MaintenanceConflict,MaintenanceNotFound,MaintenanceValidationError,
    create_request,current_tenancy,filters,student_filters,load_request,load_requests,load_photo,update_request)
from maintenance_photos import InvalidMaintenancePhoto,MAX_PHOTO_BYTES,photo_enabled,photo_path,validate_photo

owner_maintenance=Blueprint('owner_maintenance',__name__,url_prefix='/owner/maintenance')
student_maintenance=Blueprint('student_maintenance',__name__,url_prefix='/student/maintenance')


@owner_maintenance.app_context_processor
def available():return {'maintenance_navigation_enabled':True}


@owner_maintenance.app_template_filter('maintenance_datetime')
def maintenance_datetime(value):
    return value.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=5,minutes=30))).strftime('%d %b %Y, %I:%M %p') if value else 'Not set'


def wants_modal():return request.headers.get('X-Maintenance-Modal')=='1'


def require(role):
    account=load_current_account()
    if not account:
        if wants_modal():return jsonify(error='Your session expired. Log in again.',login_url=url_for('login')),401
        return redirect(url_for('login'))
    if account['role']!=role:abort(403)
    g.maintenance_account=account


owner_maintenance.before_request(lambda:require('owner'))
student_maintenance.before_request(lambda:require('student'))


def private(response):
    response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff';response.vary.add('X-Maintenance-Modal');return response


def context(**values):
    account=g.get('maintenance_account',{})
    # CSRF/body-size errors can occur before the Blueprint's account loader.
    role=account.get('role','student' if request.blueprint=='student_maintenance' else 'owner')
    return dict(owner_name=account.get('full_name','Owner'),student_name=account.get('full_name','Student'),
        maintenance_role=role,maintenance_layout='student/base.html' if role=='student' else 'owner/base.html',
        statuses=STATUSES,priorities=PRIORITIES,maintenance_photos_enabled=photo_enabled(),**values)


def error_response(message,status):
    if wants_modal():return jsonify(error=message),status
    return render_template('maintenance/error.html',**context(error=message)),status


def http_error(error):return error_response({400:'The form expired or contains invalid data. Refresh and try again.',403:'You do not have access to this maintenance action.',404:'This maintenance request is not available.',413:'The form is too large. Choose one photo up to 5 MB.'}.get(error.code,'Could not complete this request.'),error.code)


def db_error(error):
    current_app.logger.error('Maintenance database operation failed (%s).',error.errno)
    return error_response('Maintenance database setup is unavailable.' if error.errno==1146 else
        'Could not confirm this save. Read the saved requests before retrying; do not repeat an uncertain action blindly.',503 if error.errno==1146 else 500)


for blueprint in (owner_maintenance,student_maintenance):
    blueprint.after_request(private)
    blueprint.register_error_handler(HTTPException,http_error)
    blueprint.register_error_handler(Error,db_error)
    blueprint.register_error_handler(MaintenanceNotFound,lambda error:http_error(NotFound()))
    blueprint.register_error_handler(MaintenanceValidationError,lambda error:error_response(str(error),getattr(error,'status',400)))
    blueprint.register_error_handler(MaintenanceConflict,lambda error:error_response(str(error),409))


def preserved():return {key:request.form.get(key,'')[:1000] for key in ('issue_title','description','priority','location','owner_note','resolution_note','expense_id','request_key')}


def submitted_view():
    parser=student_filters if request.blueprint=='student_maintenance' else filters
    return parser({**request.form.to_dict(),'status':request.form.get('view_status','')})


def display(*,selected=None,mode='view',view=None,errors=None,values=None,status=200):
    account=g.maintenance_account;role=account['role']
    view=(student_filters if role=='student' else filters)(view or request.args)
    item=load_request(account['user_id'],role,selected) if selected is not None else None
    if role=='student' and mode not in ('view','create'):abort(403)
    tenancy=current_tenancy(account['user_id']) if role=='student' and mode=='create' else None
    data=context(item=item,mode=mode,tenancy=tenancy,view=view,errors=errors or {},values=values or {},request_key=uuid.uuid4().hex)
    if wants_modal():return jsonify(html=render_template('maintenance/_form.html' if mode=='create' else 'maintenance/_details.html',**data),
        title='Report a Maintenance Issue' if mode=='create' else 'Maintenance Request Details'),status
    data['data']=load_requests(account['user_id'],role,view)
    return render_template('student/maintenance.html' if role=='student' else 'maintenance/index.html',**data),status


@owner_maintenance.get('')
def overview():return display()


@owner_maintenance.route('/create',methods=['GET','POST'])
def submission_not_allowed():
    # Retired links/direct submissions cannot bypass the Student-only workflow.
    return error_response('Only Students with a current active tenancy can submit maintenance requests.',403)


@owner_maintenance.get('/<int:maintenance_id>')
def details(maintenance_id):
    mode=request.args.get('mode','view')
    if mode not in ('view','start','resolve'):abort(404)
    return display(selected=maintenance_id,mode=mode)


@owner_maintenance.post('/<int:maintenance_id>/<action>')
def update(maintenance_id,action):
    if action not in ('start','resolve'):abort(404)
    owner=g.maintenance_account['user_id'];view=submitted_view()
    load_request(owner,'owner',maintenance_id)
    try:
        credential=confirm_owner_password(owner,request.form.get('current_password','')) if action!='start' else None
        update_request(owner,maintenance_id,action,request.form,credential)
    except (MaintenanceValidationError,MaintenanceConflict,PasswordConfirmationError) as invalid:
        return display(selected=maintenance_id,mode=action,view=view,errors=getattr(invalid,'errors',{'current_password' if isinstance(invalid,PasswordConfirmationError) else 'form':str(invalid)}),
            values=preserved(),status=getattr(invalid,'status',400 if isinstance(invalid,(MaintenanceValidationError,PasswordConfirmationError)) else 409))
    flash({'start':'Work started. The Student can now see In Progress.','resolve':'Maintenance resolved. Resolution details and history are saved.'}[action])
    return redirect(url_for('owner_maintenance.details',maintenance_id=maintenance_id,**view),code=303)


@student_maintenance.get('')
def history():return display()


@student_maintenance.get('/create')
def new_student():return display(mode='create')


@student_maintenance.get('/<int:maintenance_id>')
def student_details(maintenance_id):return display(selected=maintenance_id)


@student_maintenance.post('/create')
def create_student():
    view=submitted_view()
    try:
        uploaded=[(name,file) for name,file in request.files.items(multi=True) if file.filename]
        uploads=[file for _,file in uploaded]
        if len(uploads)>1 or uploads and (not photo_enabled() or any(name!='photo' for name,_ in uploaded)):
            raise MaintenanceValidationError('Choose at most one optional JPG, JPEG or PNG photo.','photo' if photo_enabled() else 'form')
        photo=validate_photo(uploads[0]) if uploads else None
        maintenance_id=create_request(g.maintenance_account['user_id'],'student',request.form,photo)
    except InvalidMaintenancePhoto as invalid:
        return display(mode='create',view=view,errors={'photo':str(invalid)},values=preserved(),status=400)
    except OSError:
        return display(mode='create',view=view,errors={'photo':'The photo could not be stored. Reselect it and try again, or submit without a photo.'},values=preserved(),status=503)
    except (MaintenanceValidationError,MaintenanceConflict) as invalid:
        return display(mode='create',view=view,errors=getattr(invalid,'errors',{'form':str(invalid)}),values=preserved(),status=getattr(invalid,'status',400 if isinstance(invalid,MaintenanceValidationError) else 409))
    flash('Maintenance Request Submitted Successfully. Saved as Pending; your Owner can now review it.')
    return redirect(url_for('student_maintenance.student_details',maintenance_id=maintenance_id),code=303)


@owner_maintenance.get('/<int:maintenance_id>/photo')
@student_maintenance.get('/<int:maintenance_id>/photo')
def request_photo(maintenance_id):
    account=g.maintenance_account;photo=load_photo(account['user_id'],account['role'],maintenance_id)
    try:
        with photo_path(photo['stored_filename']).open('rb') as source:data=source.read(MAX_PHOTO_BYTES+1)
        if len(data)!=photo['byte_count'] or not secrets.compare_digest(hashlib.sha256(data).hexdigest(),photo['sha256']):abort(404)
    except (InvalidMaintenancePhoto,OSError):abort(404)
    response=send_file(BytesIO(data),mimetype='image/webp',download_name='maintenance-issue.webp',
        as_attachment=request.args.get('download')=='1',max_age=0)
    response.headers['Content-Security-Policy']="default-src 'none'; sandbox"
    response.headers['Cross-Origin-Resource-Policy']='same-origin'
    response.headers['Referrer-Policy']='no-referrer'
    return response
