"""Read the existing Boarding and inventory as one listing; never invent rent."""

from decimal import Decimal, InvalidOperation
import json

from boarding_images import cover_image_path
from db import get_db_connection
from owner_boarding import visible_facilities
from admin_security import admin_enabled


OWNER_LISTING_SQL = """SELECT boarding_id, boarding_name, description, city, district,
                              facilities, status, cover_image_filename
                       FROM boardings WHERE owner_id = %s"""

# A default for a future bed is not a saved price on a registered bed.
OWNER_RENT_OPTIONS_SQL = """
    SELECT 'shared' AS room_type, br.monthly_rent
    FROM beds bed JOIN rooms r ON r.room_id = bed.room_id
    JOIN boardings bo ON bo.boarding_id = r.boarding_id
    JOIN bed_rent_rates br ON br.bed_id = bed.bed_id
    WHERE bo.boarding_id = %s AND bo.owner_id = %s
      AND r.room_type = 'shared' AND r.operational_status = 'ready'
      AND bed.operational_status = 'ready'
      AND br.effective_from = (
          SELECT MAX(latest.effective_from) FROM bed_rent_rates latest
          WHERE latest.bed_id = bed.bed_id AND latest.effective_from <= UTC_TIMESTAMP(6)
      )
    UNION
    SELECT 'private' AS room_type, rr.monthly_rent
    FROM rooms r JOIN boardings bo ON bo.boarding_id = r.boarding_id
    JOIN room_rent_rates rr ON rr.room_id = r.room_id
    WHERE bo.boarding_id = %s AND bo.owner_id = %s
      AND r.room_type = 'private' AND r.operational_status = 'ready'
      AND rr.effective_from = (
          SELECT MAX(latest.effective_from) FROM room_rent_rates latest
          WHERE latest.room_id = r.room_id AND latest.effective_from <= UTC_TIMESTAMP(6)
      )
    ORDER BY room_type, monthly_rent
"""


OWNER_PREVIEW_ROOMS_SQL = """SELECT r.room_id, r.room_number, r.room_type, r.floor,
       r.capacity, r.operational_status,
       CASE WHEN r.room_type = 'private' THEN
         (SELECT rr.monthly_rent FROM room_rent_rates rr WHERE rr.room_id = r.room_id
          AND rr.effective_from <= UTC_TIMESTAMP(6)
          ORDER BY rr.effective_from DESC LIMIT 1)
       ELSE NULL END AS monthly_rent
    FROM rooms r JOIN boardings bo ON bo.boarding_id = r.boarding_id
    WHERE bo.boarding_id = %s AND bo.owner_id = %s
    ORDER BY r.room_type, r.room_number, r.room_id"""

OWNER_PREVIEW_BEDS_SQL = """SELECT bed.bed_id, bed.room_id, bed.bed_label, bed.operational_status,
       CASE WHEN r.room_type = 'shared' THEN
         (SELECT br.monthly_rent FROM bed_rent_rates br WHERE br.bed_id = bed.bed_id
          AND br.effective_from <= UTC_TIMESTAMP(6)
          ORDER BY br.effective_from DESC LIMIT 1)
       ELSE NULL END AS monthly_rent
    FROM beds bed JOIN rooms r ON r.room_id = bed.room_id
    JOIN boardings bo ON bo.boarding_id = r.boarding_id
    WHERE bo.boarding_id = %s AND bo.owner_id = %s
    ORDER BY bed.bed_label, bed.bed_id"""


def saved_rent_amount(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or not Decimal("0") < amount <= Decimal("99999999.99") or amount != amount.quantize(Decimal("0.01")):
            raise ValueError("Invalid saved rent")
    except InvalidOperation:
        raise ValueError("Invalid saved rent") from None
    return amount


def build_listing(boarding, rent_rows):
    """Project only listing fields so account and contact data stay private."""
    facilities = boarding.get("facilities")
    if isinstance(facilities, (str, bytes, bytearray)):
        facilities = json.loads(facilities)
    if not isinstance(facilities, list) or not all(isinstance(value, str) for value in facilities):
        raise ValueError("Invalid saved facilities")
    if boarding["status"] not in ("draft", "published"):
        raise ValueError("Invalid saved publication status")
    listing = {name: boarding[name] for name in (
        "boarding_id", "boarding_name", "description", "city", "district", "status",
    )}
    listing["facilities"] = visible_facilities(facilities)
    listing['admin_hidden'] = bool(boarding.get('admin_hidden', False))
    cover = cover_image_path(boarding.get("cover_image_filename"))
    listing["has_cover"] = cover is not None and cover.is_file()
    options = {"shared": set(), "private": set()}
    for row in rent_rows:
        room_type = row["room_type"]
        if room_type not in options:
            raise ValueError("Invalid saved room type")
        options[room_type].add(saved_rent_amount(row["monthly_rent"]))
    listing["rent_options"] = {room_type: sorted(amounts) for room_type, amounts in options.items()}
    return listing


def load_owner_listing(owner_id):
    with get_db_connection() as connection:
        # Use one read-only snapshot so the profile and its prices agree on refresh.
        connection.start_transaction(readonly=True)
        try:
            with connection.cursor(dictionary=True) as cursor:
                sql = OWNER_LISTING_SQL.replace('facilities, status,', 'facilities, status, admin_hidden,') if admin_enabled() else OWNER_LISTING_SQL
                cursor.execute(sql, (owner_id,))
                boarding = cursor.fetchone()
                if boarding is None:
                    return None
                cursor.execute(OWNER_RENT_OPTIONS_SQL, (
                    boarding["boarding_id"], owner_id, boarding["boarding_id"], owner_id,
                ))
                return build_listing(boarding, cursor.fetchall())
        finally:
            connection.rollback()


def build_preview_inventory(room_rows, bed_rows):
    rooms = {}
    for row in room_rows:
        if row["room_type"] not in ("shared", "private") or row["operational_status"] not in ("ready", "maintenance") or row["room_id"] in rooms:
            raise ValueError("Invalid saved room inventory")
        room = {name: row[name] for name in (
            "room_id", "room_number", "room_type", "floor", "capacity", "operational_status",
        )}
        room["monthly_rent"] = saved_rent_amount(row["monthly_rent"]) if room["room_type"] == "private" and row["monthly_rent"] is not None else None
        room["beds"] = []
        rooms[room["room_id"]] = room
    for row in bed_rows:
        room = rooms.get(row["room_id"])
        if room is None or row["operational_status"] not in ("ready", "maintenance"):
            raise ValueError("Invalid saved bed inventory")
        bed = {name: row[name] for name in ("bed_id", "bed_label", "operational_status")}
        bed["monthly_rent"] = saved_rent_amount(row["monthly_rent"]) if room["room_type"] == "shared" and row["monthly_rent"] is not None else None
        room["beds"].append(bed)

    inventory = {"public": {"shared": [], "private": []}, "owner_only": {"shared": [], "private": []}}
    for room in rooms.values():
        room["bed_count"] = len(room["beds"])
        room_type = room["room_type"]
        if room["operational_status"] == "maintenance":
            room["visibility_note"] = "Room under maintenance"
            inventory["owner_only"][room_type].append(room)
        elif room_type == "private":
            if room["monthly_rent"] is None:
                room["visibility_note"] = "No current saved room rent"
                inventory["owner_only"][room_type].append(room)
            else:
                inventory["public"][room_type].append(room)
        else:
            shown = [bed for bed in room["beds"] if bed["operational_status"] == "ready" and bed["monthly_rent"] is not None]
            hidden = [bed for bed in room["beds"] if bed not in shown]
            if shown:
                inventory["public"][room_type].append({**room, "beds": shown})
            if hidden or not room["beds"]:
                # Keep excluded beds outside the public-facing preview component.
                inventory["owner_only"][room_type].append({
                    **room, "beds": hidden,
                    "visibility_note": "No registered beds yet" if not room["beds"] else "Beds under maintenance or without a current saved rent",
                })
    return inventory


def load_owner_preview(owner_id):
    with get_db_connection() as connection:
        connection.start_transaction(readonly=True)
        try:
            with connection.cursor(dictionary=True) as cursor:
                sql = OWNER_LISTING_SQL.replace('facilities, status,', 'facilities, status, admin_hidden,') if admin_enabled() else OWNER_LISTING_SQL
                cursor.execute(sql, (owner_id,))
                boarding = cursor.fetchone()
                if boarding is None:
                    return None, None
                scope = (boarding["boarding_id"], owner_id)
                cursor.execute(OWNER_PREVIEW_ROOMS_SQL, scope)
                rooms = cursor.fetchall()
                cursor.execute(OWNER_PREVIEW_BEDS_SQL, scope)
                beds = cursor.fetchall()
                # Do not collapse detailed inventory into distinct amounts.
                return build_listing(boarding, []), build_preview_inventory(rooms, beds)
        finally:
            connection.rollback()
