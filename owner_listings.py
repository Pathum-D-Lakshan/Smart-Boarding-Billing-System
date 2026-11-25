"""Read-only Owner Listings and inventory preview for the existing Boarding."""

from flask import Blueprint, abort, current_app, flash, g, make_response, redirect, render_template, url_for
from mysql.connector import Error

from auth_access import load_current_account
from listing_data import load_owner_listing, load_owner_preview
from owner_boarding import FACILITY_OPTIONS


owner_listings = Blueprint("owner_listings", __name__, url_prefix="/owner/listings")


def listings_response(*, listing=None, error=None, inventory=None, status=200, preview=False):
    search_live = "public_boardings.search" in current_app.view_functions
    if listing and listing.get('admin_hidden'):
        visibility = 'Hidden by Platform Admin. Editing or republishing does not remove this moderation block.'
    elif listing and listing["status"] == "published":
        visibility = "Visible in public search" if search_live else "Published · Public search is not available yet."
    else:
        visibility = "Draft · Only visible to you."
    return make_response(render_template(
        "owner/listing_preview.html" if preview else "owner/listings.html",
        owner_name=g.current_owner["full_name"] if g.get("current_owner") else "Owner",
        listing=listing, error=error, inventory=inventory,
        visibility=visibility, facility_icons=dict(FACILITY_OPTIONS),
        cover_url=url_for("owner_boarding.cover") if listing and listing["has_cover"] else None,
    ), status)


@owner_listings.before_request
def require_listing_owner():
    try:
        owner = load_current_account()
    except Error as error:
        current_app.logger.error("Listings account lookup failed (%s).", error.errno)
        return listings_response(error="Could not load your listing. Please try again.", status=500)
    if owner is None:
        return redirect(url_for("login"))
    if owner["role"] != "owner":
        abort(403)
    g.current_owner = owner


@owner_listings.after_request
def prevent_listing_caching(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def load_listing_page(*, preview=False):
    inventory = None
    try:
        # Resolve the Owner from the current account, never from query or form IDs.
        if preview:
            listing, inventory = load_owner_preview(g.current_owner["user_id"])
        else:
            listing = load_owner_listing(g.current_owner["user_id"])
    except Error as database_error:
        current_app.logger.error("Listing lookup failed (%s).", database_error.errno)
        return listings_response(error="Could not load your listing. Please try again.", status=500)
    except (ValueError, TypeError, OSError):
        current_app.logger.error("Listing contains invalid saved data or an unreadable cover.")
        return listings_response(error="Could not load your listing. Please check your profile and try again.", status=500)
    if preview and listing is None:
        flash("Create your Boarding Profile before previewing a listing.", "error")
        return redirect(url_for("owner_listings.overview"), code=303)
    return listings_response(listing=listing, preview=preview, inventory=inventory)


@owner_listings.get("")
def overview():
    return load_listing_page()


@owner_listings.get("/preview")
def preview():
    return load_listing_page(preview=True)
