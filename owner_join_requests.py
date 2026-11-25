"""Authenticated Owner request management and progressively enhanced details."""

from flask import Blueprint, abort, current_app, flash, g, jsonify, make_response, redirect, render_template, request, url_for
from mysql.connector import Error
from werkzeug.exceptions import HTTPException

from auth_access import load_current_account
from join_request_service import (
    JoinRequestConflict, JoinRequestNotFound, JoinRequestValidationError,
    RequestFilters, REQUEST_STATUSES, load_owner_requests, local_request_time, reject_owner_request,
)
from tenancy_service import (
    ApprovalValidationError, approve_owner_request, load_approval_context, load_owner_tenancy,
)


owner_join_requests = Blueprint("owner_join_requests", __name__, url_prefix="/owner/join-requests")
owner_join_requests.app_template_filter("join_request_datetime")(local_request_time)


def wants_dialog():
    # This selects presentation only; every request still passes Owner authentication.
    return request.endpoint == "owner_join_requests.dialog" or request.headers.get("X-Join-Request-Modal") == "1"


def page_response(*, data=None, filters=None, error=None, reason="", reason_error=None, status=200,
                  approval=None, tenancy=None, approval_values=None, approval_errors=None, notice=None):
    filters = filters or RequestFilters()
    data = data or {"boarding": None, "summary": None, "rows": [], "selected": None,
                    "filtered_total": 0, "page": 1, "page_count": 1, "first_row": 0, "last_row": 0}
    context = dict(**data, filters=filters,
        filter_params=filters.params(page=data["page"]), request_statuses=REQUEST_STATUSES,
        owner_name=g.current_owner["full_name"] if g.get("current_owner") else "Owner",
        join_requests_pending_count=data["summary"]["pending"] if data["summary"] is not None else None,
        error=error, reason=reason, reason_error=reason_error,
        approval=approval, tenancy=tenancy, approval_values=approval_values or {}, approval_errors=approval_errors or {},
        notice=notice,
    )
    if wants_dialog():
        # Render through Jinja so Student text remains escaped in fetched fragments.
        return jsonify(
            html=render_template("owner/_join_request_details.html", **context) if data["selected"] else None,
            results_html=render_template("owner/_join_request_results.html", **context) if data["boarding"] and data["summary"] is not None else None,
            summary=data["summary"], error=error, notice=notice,
        ), status
    return make_response(render_template("owner/join_requests.html", **context), status)


@owner_join_requests.before_request
def require_request_owner():
    try:
        owner = load_current_account()
    except Error as error:
        current_app.logger.error("Join Requests account lookup failed (%s).", error.errno)
        return page_response(error="Could not load Join Requests. Please try again.", status=500)
    if owner is None:
        if wants_dialog():
            return jsonify(error="Your session expired. Log in again to view this request.", login_url=url_for("login")), 401
        return redirect(url_for("login"))
    if owner["role"] != "owner":
        abort(403)
    g.current_owner = owner


@owner_join_requests.after_request
def prevent_request_caching(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.vary.add("X-Join-Request-Modal")
    return response


@owner_join_requests.errorhandler(HTTPException)
def dialog_http_error(error):
    if wants_dialog():
        messages = {400: "The form expired or contains invalid values. Refresh this request before trying again.",
                    403: "You do not have permission to view or change this request.",
                    404: "This request is not available to your account."}
        return jsonify(error=messages.get(error.code, "Could not complete this request.")), error.code
    return error


def load_page(selected_id=None, *, filters=None, error=None, reason="", reason_error=None, status=200,
              approval_values=None, approval_errors=None, notice=None):
    approval, tenancy = None, None
    try:
        filters = filters or RequestFilters.parse(request.args)
        data = load_owner_requests(g.current_owner["user_id"], filters, selected_id)
        if data["selected"]:
            if data["selected"]["status"] == "requested":
                approval = load_approval_context(g.current_owner["user_id"], selected_id)
                # A stale price must be reviewed with the newly saved rate before retry.
                if approval_values:
                    old_unit = approval_values.get("unit", "").split(":")
                    for option in approval["options"]:
                        if option["token"].split(":")[:2] == old_unit[:2]:
                            approval_values = {**approval_values, "unit": option["token"]}
                            break
            elif data["selected"]["status"] == "approved":
                tenancy = load_owner_tenancy(g.current_owner["user_id"], selected_id)
    except JoinRequestValidationError as invalid:
        return page_response(error=str(invalid), status=400)
    except JoinRequestNotFound:
        abort(404)
    except Error as database_error:
        current_app.logger.error("Join Requests lookup failed (%s).", database_error.errno)
        return page_response(filters=filters, error="Could not load Join Requests. Please try again.", status=500)
    return page_response(data=data, filters=filters, error=error, reason=reason, reason_error=reason_error, status=status,
                         approval=approval, tenancy=tenancy, approval_values=approval_values, approval_errors=approval_errors, notice=notice)


@owner_join_requests.get("")
def overview():
    return load_page()


@owner_join_requests.get("/<int:request_id>")
def details(request_id):
    return load_page(request_id)


@owner_join_requests.get("/<int:request_id>/dialog")
def dialog(request_id):
    return load_page(request_id)


@owner_join_requests.post("/<int:request_id>/reject")
def reject(request_id):
    try:
        filters = RequestFilters.parse(request.form)
    except JoinRequestValidationError as invalid:
        return page_response(error=str(invalid), status=400)
    reason = request.form.get("reason", "").strip()
    try:
        reject_owner_request(g.current_owner["user_id"], request_id, reason)
    except JoinRequestValidationError as invalid:
        return load_page(request_id, filters=filters, reason=reason[:500], reason_error=str(invalid), status=400)
    except JoinRequestNotFound:
        abort(404)
    except JoinRequestConflict as conflict:
        return load_page(request_id, filters=filters, error=str(conflict), status=409)
    except Error as database_error:
        current_app.logger.error("Join Request rejection failed (%s).", database_error.errno)
        return load_page(request_id, filters=filters, reason=reason[:500], error="Could not confirm this rejection. Refresh to check the current status before trying again.", status=500)
    message = "Join request rejected. The request and your reason have been saved."
    if wants_dialog():
        return load_page(request_id, filters=filters, notice=message)
    flash(message)
    return redirect(url_for("owner_join_requests.details", request_id=request_id, **filters.params()), code=303)


@owner_join_requests.post("/<int:request_id>/approve")
def approve(request_id):
    try:
        filters = RequestFilters.parse(request.form)
    except JoinRequestValidationError as invalid:
        return page_response(error=str(invalid), status=400)
    values = {name: request.form.get(name, "")[:50] for name in ("unit", "start_date")}
    try:
        # Browser-provided prices, Student IDs and status values are never authoritative.
        approve_owner_request(g.current_owner["user_id"], request_id, request.form)
    except ApprovalValidationError as invalid:
        return load_page(request_id, filters=filters, approval_values=values, approval_errors=invalid.errors, status=400)
    except JoinRequestNotFound:
        abort(404)
    except JoinRequestConflict as conflict:
        return load_page(request_id, filters=filters, error=str(conflict), approval_values=values,
                         approval_errors={"approval": str(conflict)}, status=409)
    except Error as database_error:
        current_app.logger.error("Join Request approval failed (%s).", database_error.errno)
        message = "Could not confirm approval. Refresh to check the request and tenancy before trying again."
        return load_page(request_id, filters=filters, error=message, approval_values=values, status=500)
    message = "Join request approved. The tenancy, start date and agreed monthly rent have been saved."
    if wants_dialog():
        return load_page(request_id, filters=filters, notice=message)
    flash(message)
    return redirect(url_for("owner_join_requests.details", request_id=request_id, **filters.params()), code=303)
