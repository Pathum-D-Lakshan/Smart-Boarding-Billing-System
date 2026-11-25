"""The public marketplace shares availability and publication rules with Student discovery."""

from flask import Blueprint, abort, current_app, render_template, request, send_file
from mysql.connector import Error

from boarding_images import cover_image_path
from join_request_service import JoinRequestNotFound
from student_request_service import (
    StudentRequestValidationError, load_published_boardings, load_student_boarding,
    load_student_cover, parse_discovery_filters, parse_page,
)


public_boardings = Blueprint("public_boardings", __name__, url_prefix="/boardings")


@public_boardings.after_request
def keep_visibility_current(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@public_boardings.errorhandler(JoinRequestNotFound)
def missing_listing(_error):
    return render_template("public/message.html", message="This boarding is no longer available."), 404


@public_boardings.errorhandler(Error)
@public_boardings.errorhandler(OSError)
@public_boardings.errorhandler(TypeError)
def listings_unavailable(error):
    current_app.logger.error("Public listings unavailable (%s).", getattr(error, "errno", type(error).__name__))
    return render_template("public/message.html", message="Boardings are temporarily unavailable. Please try again."), 503


def homepage():
    try:
        results = load_published_boardings(1, include_address=False)
    except (Error, OSError, ValueError, TypeError) as error:
        current_app.logger.error("Public homepage listings unavailable (%s).", getattr(error, "errno", type(error).__name__))
        return render_template("home.html", listings=[], unavailable=True), 503
    return render_template("home.html", listings=results["listings"][:4])


@public_boardings.get("")
def search():
    query = request.args.get("q", "").strip()
    try:
        page = parse_page(request.args.get("page", "1"))
        filters = parse_discovery_filters({"location": query})
    except (StudentRequestValidationError, ValueError):
        return render_template("public/search.html", q=query[:150], listings=[], page=1, page_count=1, total=0,
                               error="Enter a boarding name or location up to 150 characters and a valid page."), 400

    try:
        results = load_published_boardings(page, filters, include_address=False)
    except ValueError as error:
        return listings_unavailable(error)
    return render_template("public/search.html", q=query, **results)


@public_boardings.get("/<int:boarding_id>")
def details(boarding_id):
    try:
        data = load_student_boarding(None, boarding_id)
    except ValueError as error:
        return listings_unavailable(error)
    return render_template("public/boarding.html", **data)


@public_boardings.get("/<int:boarding_id>/cover")
def cover(boarding_id):
    path = cover_image_path(load_student_cover(boarding_id))
    if path is None or not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/webp", conditional=False, max_age=0)
