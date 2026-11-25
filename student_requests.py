"""Small Student request portal using the main application's authentication."""

from flask import Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, request, send_file, url_for
from mysql.connector import Error
from datetime import date

from auth_access import load_current_account
from boarding_images import cover_image_path
from join_request_service import JoinRequestConflict, JoinRequestNotFound
from owner_boarding import FACILITY_OPTIONS
from student_request_service import (
    StudentRequestValidationError, load_published_boardings, load_student_boarding,
    load_student_cover, load_student_request, load_student_requests, parse_page, submit_student_request, parse_discovery_filters,
)
from tenancy_service import local_today
from student_boarding_service import TABS,load_my_boarding,load_my_boarding_cover,parse_tenancy_id


student_requests = Blueprint("student_requests", __name__, url_prefix="/student")


def student_response(template="student/error.html", *, status=200, **context):
    return make_response(render_template(template,
        student_name=g.current_student["full_name"] if g.get("current_student") else "Student",
        facility_icons=dict(FACILITY_OPTIONS), **context), status)


@student_requests.before_request
def require_student():
    try:
        account = load_current_account()
    except Error as error:
        current_app.logger.error("Student account lookup failed (%s).", error.errno)
        return student_response(error="Could not check your account. Please try again.", status=500)
    if account is None:
        return redirect(url_for("login"))
    if account["role"] != "student":
        abort(403)
    g.current_student = account


@student_requests.after_request
def prevent_student_caching(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@student_requests.errorhandler(Error)
def student_database_error(error):
    current_app.logger.error("Student request database operation failed (%s).", error.errno)
    return student_response(error="Could not confirm this operation. Check My Join Requests before trying again.", status=500)


@student_requests.errorhandler(JoinRequestNotFound)
def student_record_not_found(error):
    return student_response(error="This boarding or request is not available.", status=404)


@student_requests.errorhandler(ValueError)
@student_requests.errorhandler(TypeError)
@student_requests.errorhandler(OSError)
def student_saved_data_error(error):
    current_app.logger.error("Student listing contains invalid saved data or an unreadable cover.")
    return student_response(error="Could not load this boarding. Please try again later.", status=500)


@student_requests.get("/boardings")
def boardings():
    try:
        page = parse_page(request.args.get("page", "1"))
        filters = parse_discovery_filters(request.args)
    except StudentRequestValidationError as invalid:
        return student_response('student/boardings.html', listings=[], page=1, page_count=1, total=0,
            filters={'location': request.args.get('location','')[:150], 'budget':request.args.get('budget','')[:25],
                'room_type':request.args.get('room_type',''), 'sort':request.args.get('sort','relevant'),
                'facilities':request.args.getlist('facility')}, errors=invalid.errors, status=400)
    except ValueError as error:
        return student_response(error=str(error), status=400)
    return student_response("student/boardings.html", **load_published_boardings(page, filters), errors={})


@student_requests.get('/my-boarding')
def my_boarding():
    try:
        selected=parse_tenancy_id(request.args.get('tenancy_id'))
        page=parse_page(request.args.get('history_page','1'))
        tab=request.args.get('tab','overview')
        if tab not in TABS:raise ValueError('Choose Overview, Room & Rent, Facilities or Tenancy.')
    except ValueError as invalid:
        return student_response(error=str(invalid),status=400)
    return student_response('student/my_boarding.html',data=load_my_boarding(g.current_student['user_id'],selected,page),tab=tab,tabs=TABS)


@student_requests.get('/my-boarding/<int:tenancy_id>/cover')
def my_boarding_cover(tenancy_id):
    path=cover_image_path(load_my_boarding_cover(g.current_student['user_id'],tenancy_id))
    if path is None or not path.is_file():abort(404)
    return send_file(path,mimetype='image/webp',conditional=False,max_age=0)


def boarding_page(boarding_id, *, values=None, errors=None, error=None, status=200):
    availability=local_today()
    raw_date=(values or {}).get('intended_start_date') or request.args.get('availability_date','')
    if raw_date:
        try:
            parsed=date.fromisoformat(raw_date)
            if parsed<local_today(): raise ValueError()
            availability=parsed
        except ValueError:
            if request.method=='GET': return student_response(error='Choose today or a future availability date.',status=400)
    try:
        data = load_student_boarding(g.current_student["user_id"], boarding_id,availability)
    except (ValueError, TypeError, OSError):
        current_app.logger.error("Student listing contains invalid saved data or an unreadable cover.")
        return student_response(error="Could not load this boarding. Please try again later.", status=500)
    try:
        search = parse_discovery_filters(request.args)
        back_url = url_for('student_requests.boardings',location=search['location'],budget=search['budget'],
            room_type=search['room_type'],sort=search['sort'],facility=search['facilities'],page=parse_page(request.args.get('page','1')))
    except (StudentRequestValidationError, ValueError):
        back_url = url_for('student_requests.boardings')
    return student_response("student/boarding.html", **data, back_url=back_url,
        values=values or {'intended_start_date':availability.isoformat()}, errors=errors or {}, error=error,
        today=local_today().isoformat(),availability_date=availability.isoformat(),status=status)


@student_requests.get("/boardings/<int:boarding_id>")
def boarding(boarding_id):
    return boarding_page(boarding_id)


@student_requests.get("/boardings/<int:boarding_id>/cover")
def cover(boarding_id):
    path = cover_image_path(load_student_cover(boarding_id))
    if path is None or not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/webp", conditional=False, max_age=0)


@student_requests.post("/boardings/<int:boarding_id>/request")
def submit(boarding_id):
    values = {name: request.form.get(name, "")[:limit] for name, limit in (
        ("preferred_room_id", 20), ("intended_start_date", 20), ("message", 1000),
    )}
    try:
        request_id = submit_student_request(g.current_student["user_id"], boarding_id, request.form)
    except StudentRequestValidationError as invalid:
        return boarding_page(boarding_id, values=values, errors=invalid.errors, status=400)
    except JoinRequestConflict as conflict:
        return boarding_page(boarding_id, values=values, error=str(conflict), status=409)
    flash("Your join request was sent to the Owner. No room or bed is reserved until approval.")
    return redirect(url_for("student_requests.details", request_id=request_id), code=303)


@student_requests.get("/requests")
def history():
    try:
        page = parse_page(request.args.get("page", "1"))
    except ValueError as error:
        return student_response(error=str(error), status=400)
    return student_response("student/requests.html", **load_student_requests(g.current_student["user_id"], page))


@student_requests.get("/requests/<int:request_id>")
def details(request_id):
    return student_response("student/request_details.html", item=load_student_request(g.current_student["user_id"], request_id))
