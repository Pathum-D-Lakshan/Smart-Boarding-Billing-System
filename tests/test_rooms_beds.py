"""Rooms overview/create/details tests with database calls fully mocked."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import unittest
from unittest.mock import MagicMock, patch

from mysql.connector import Error

from app import app
from auth_email import password_stamp


class RoomsTests(unittest.TestCase):
    def setUp(self):
        override = patch.dict(app.config, TESTING=True, SECRET_KEY="rooms-test-key")
        override.start()
        self.addCleanup(override.stop)
        self.client = app.test_client()
        self.owner = {"user_id": 41, "full_name": "Test Owner", "role": "owner", "password_hash": "test-hash"}
        self.boarding = {"boarding_id": 12, "boarding_name": "Test Boarding", "status": "draft"}
        self.room = {
            "room_id": 23, "boarding_id": 12, "room_number": "A101", "room_type": "shared",
            "capacity": 4, "default_bed_rent": Decimal("12000.00"), "room_rent": None,
            "floor": "1", "description": "A quiet room.", "operational_status": "ready", "bed_count": 0,
            "created_at": datetime(2026, 11, 7), "updated_at": datetime(2026, 11, 7),
        }
        self.rooms = [self.room]
        self.beds = []
        self.summary = {"total_rooms": 1, "total_beds": 0, "shared_rooms": 1, "private_rooms": 0}
        self.duplicate = False
        self.parent_available = True
        account_connection = MagicMock()
        account_connection.__enter__.return_value = account_connection
        account_cursor = account_connection.cursor.return_value.__enter__.return_value
        account_cursor.fetchone.side_effect = lambda: deepcopy(self.owner)
        self.account_db = self.start_patch("auth_access.get_db_connection", return_value=account_connection)
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.lastrowid = 23
        self.cursor.fetchone.side_effect = self.fetchone
        self.cursor.fetchall.side_effect = self.fetchall
        self.rooms_db = self.start_patch("owner_rooms.get_db_connection", return_value=self.connection)
        self.start_patch("owner_boarding.get_db_connection", side_effect=AssertionError("Unexpected live database access"))
        self.start_patch("auth_email.get_db_connection", side_effect=AssertionError("Unexpected live database access"))
        self.sign_in()

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def fetchone(self):
        query = self.cursor.execute.call_args.args[0]
        if "AS total_rooms" in query:
            return deepcopy(self.summary)
        if query.startswith("SELECT room_id FROM rooms"):
            return {"room_id": 23} if self.duplicate else None
        if "FROM boardings WHERE boarding_id" in query:
            return {"boarding_id": 12} if self.parent_available else None
        if "FROM boardings WHERE owner_id" in query:
            return deepcopy(self.boarding)
        if "FROM rooms r JOIN boardings" in query:
            return deepcopy(self.room)
        raise AssertionError("Unexpected mocked SELECT")

    def fetchall(self):
        query = self.cursor.execute.call_args.args[0]
        return deepcopy(self.beds if "FROM beds b JOIN rooms" in query else self.rooms)

    def sign_in(self, user_id=41):
        with app.app_context():
            stamp = password_stamp("test-hash")
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["password_stamp"] = stamp
            session["csrf_token"] = "rooms-test-csrf"

    def payload(self, **changes):
        return {
            "room_number": "a101", "room_type": "shared", "capacity": "4", "monthly_rent": "12000",
            "floor": "1", "description": "A quiet room.", "operational_status": "ready",
            "csrf_token": "rooms-test-csrf", **changes,
        }

    def inserts(self):
        return [call.args for call in self.cursor.execute.call_args_list if call.args[0].lstrip().startswith("INSERT")]

    def test_sidebar_live_link_and_real_overview(self):
        response = self.client.get("/owner/rooms")
        self.assertEqual(response.status_code, 200)
        for text in ("Rooms &amp; Beds", "Registered Beds", "Shared Rooms", "Private Rooms", "A101", "12,000.00", "Default for new beds", "Not yet tracked"):
            self.assertIn(text, response.text)
        self.assertIn('href="/owner/rooms"', response.text)
        self.assertIn('aria-current="page" title="Rooms &amp; Beds"', response.text)
        self.assertIn('href="/owner/rooms/23"', response.text)
        self.assertIn('href="/owner/rooms/create"', response.text)
        self.assertEqual(response.text.count('<span class="nav-status">Coming soon</span>'), 9)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn("Occupied", response.text)

    def test_no_boarding_shows_create_boarding_action(self):
        self.boarding = None
        self.summary = {key: 0 for key in self.summary}
        response = self.client.get("/owner/rooms")
        self.assertIn("Create your boarding first", response.text)
        self.assertIn('href="/owner/boarding/create"', response.text)
        self.assertNotIn('href="/owner/rooms/create"', response.text)

    def test_empty_room_list_has_real_add_action(self):
        self.rooms = []
        self.summary = {key: 0 for key in self.summary}
        response = self.client.get("/owner/rooms")
        self.assertIn("No rooms registered yet", response.text)
        self.assertIn('href="/owner/rooms/create"', response.text)

    def test_search_and_filter_use_bound_literal_parameters(self):
        response = self.client.get("/owner/rooms", query_string={"q": "a%_='", "room_type": "private", "owner_id": "999"})
        self.assertEqual(response.status_code, 200)
        query, parameters = self.cursor.execute.call_args.args
        self.assertIn("bo.owner_id = %s", query)
        self.assertIn("LIKE %s ESCAPE '='", query)
        self.assertEqual(parameters, (41, "%a=%=_=='%", "private"))
        self.assertIn("Clear Search", response.text)

    def test_invalid_filters_have_safe_feedback(self):
        for query in ({"q": "x" * 51}, {"room_type": "other"}):
            self.assertEqual(self.client.get("/owner/rooms", query_string=query).status_code, 400)

    def test_empty_search_results(self):
        self.rooms = []
        response = self.client.get("/owner/rooms?q=none")
        self.assertIn("No matching rooms", response.text)

    def test_create_form_has_required_fields_limits_and_csrf(self):
        response = self.client.get("/owner/rooms/create")
        self.assertEqual(response.status_code, 200)
        for text in ('name="csrf_token"', 'name="room_number"', 'name="room_type"', 'name="monthly_rent"', 'name="capacity"', 'max="65535"', 'step="0.01"', "Save Room", "Monthly Rent per Bed", 'href="/owner/rooms">Cancel</a>'):
            self.assertIn(text, response.text)
        self.assertNotIn("Occupied", response.text)
        self.assertIn("owner-rooms-beds.js", response.text)
        self.assertEqual(self.inserts(), [])

    def test_create_shared_room_stores_bed_default_not_private_rate(self):
        response = self.client.post("/owner/rooms/create", data=self.payload(boarding_id="999", owner_id="999", room_id="999"))
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/owner/rooms/23"))
        inserts = self.inserts()
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0][1], (12, "A101", "shared", 4, Decimal("12000.00"), "1", "A quiet room.", "ready"))
        lock = next(call.args for call in self.cursor.execute.call_args_list if "FOR UPDATE" in call.args[0])
        self.assertEqual(lock[1], (12, 41))
        self.connection.commit.assert_called_once()
        self.connection.rollback.assert_not_called()

    def test_create_private_room_atomically_stores_per_room_rate(self):
        response = self.client.post("/owner/rooms/create", data=self.payload(room_type="private", monthly_rent="35000.50"))
        self.assertEqual(response.status_code, 303)
        inserts = self.inserts()
        self.assertEqual(len(inserts), 2)
        self.assertIsNone(inserts[0][1][4])
        self.assertIn("INSERT INTO room_rent_rates", inserts[1][0])
        self.assertIn("UTC_TIMESTAMP(6)", inserts[1][0])
        self.assertEqual(inserts[1][1], (23, Decimal("35000.50")))
        self.assertFalse(any("INSERT INTO beds" in query for query, parameters in inserts))
        self.connection.commit.assert_called_once()

    def test_duplicate_precheck_rolls_back_without_insert(self):
        self.duplicate = True
        response = self.client.post("/owner/rooms/create", data=self.payload())
        self.assertEqual(response.status_code, 409)
        self.assertIn('id="room_number-error"', response.text)
        self.assertEqual(self.inserts(), [])
        self.connection.rollback.assert_called_once()

    def test_unique_constraint_duplicate_is_friendly(self):
        def execute(query, parameters):
            if query.startswith("INSERT INTO rooms"):
                raise Error("private duplicate details", errno=1062)
        self.cursor.execute.side_effect = execute
        response = self.client.post("/owner/rooms/create", data=self.payload())
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("private duplicate", response.text)
        self.connection.rollback.assert_called_once()

    def test_boarding_disappearing_before_insert_is_safe(self):
        self.parent_available = False
        self.assertEqual(self.client.post("/owner/rooms/create", data=self.payload()).status_code, 303)
        self.assertEqual(self.inserts(), [])
        self.connection.rollback.assert_called_once()

    def test_private_rate_failure_rolls_back_room_creation(self):
        def execute(query, parameters):
            if "INSERT INTO room_rent_rates" in query:
                raise Error("private SQL details", errno=1142)
        self.cursor.execute.side_effect = execute
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/rooms/create", data=self.payload(room_type="private"))
        self.assertEqual(response.status_code, 500)
        self.assertIn('value="A101"', response.text)
        self.assertIn("Monthly Rent per Room", response.text)
        self.assertNotIn("private SQL", response.text)
        self.connection.rollback.assert_called_once()
        self.connection.commit.assert_not_called()

    def test_commit_failure_rolls_back(self):
        self.connection.commit.side_effect = Error("test commit error", errno=1213)
        with self.assertLogs(app.logger, level="ERROR"):
            self.assertEqual(self.client.post("/owner/rooms/create", data=self.payload()).status_code, 500)
        self.connection.rollback.assert_called_once()

    def test_required_and_oversized_fields_rejected(self):
        for field, value in (("room_number", " "), ("room_number", "x" * 51), ("floor", "x" * 51), ("room_type", "other"), ("operational_status", "occupied"), ("description", "අ" * 21846)):
            with self.subTest(field=field):
                response = self.client.post("/owner/rooms/create", data=self.payload(**{field: value}))
                self.assertEqual(response.status_code, 400)
                self.assertIn(f'id="{field}-error"', response.text)
        self.assertEqual(self.inserts(), [])

    def test_capacity_must_be_a_valid_positive_integer(self):
        for capacity in ("", "0", "-1", "1.5", "1e2", "65536", "abc"):
            with self.subTest(capacity=capacity):
                response = self.client.post("/owner/rooms/create", data=self.payload(capacity=capacity))
                self.assertEqual(response.status_code, 400)
                self.assertIn('id="capacity-error"', response.text)
        self.assertEqual(self.inserts(), [])

    def test_rent_must_be_positive_finite_and_within_decimal_precision(self):
        for rent in ("", "0", "-1", "NaN", "Infinity", "1e3", "1.001", "100000000", "abc"):
            with self.subTest(rent=rent):
                response = self.client.post("/owner/rooms/create", data=self.payload(monthly_rent=rent))
                self.assertEqual(response.status_code, 400)
                self.assertIn('id="monthly_rent-error"', response.text)
        self.assertEqual(self.inserts(), [])

    def test_optional_fields_and_schema_boundaries(self):
        response = self.client.post("/owner/rooms/create", data=self.payload(
            room_number="x" * 50, capacity="65535", monthly_rent="99999999.99", floor="", description="",
        ))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.inserts()[0][1][5:7], (None, None))

    def test_create_without_boarding_redirects(self):
        self.boarding = None
        self.assertEqual(self.client.get("/owner/rooms/create").status_code, 303)
        self.assertEqual(self.client.post("/owner/rooms/create", data=self.payload()).status_code, 303)
        self.assertEqual(self.inserts(), [])

    def test_room_details_load_owned_room_and_beds(self):
        self.room["bed_count"] = 1
        self.beds = [{"bed_id": 32, "bed_label": "B1", "operational_status": "ready", "monthly_rent": Decimal("12500.00")}]
        response = self.client.get("/owner/rooms/23")
        self.assertEqual(response.status_code, 200)
        self.assertIn("A101", response.text)
        self.assertIn("B1", response.text)
        self.assertIn("12,500.00", response.text)
        self.assertIn("Not yet tracked", response.text)
        self.assertEqual(self.cursor.execute.call_args.args[1], (23, 41))
        self.assertIn("bo.owner_id = %s", self.cursor.execute.call_args.args[0])

    def test_private_physical_beds_are_not_shown_as_individually_rentable(self):
        self.room.update(room_type="private", default_bed_rent=None, room_rent=Decimal("35000.00"), bed_count=1)
        self.beds = [{"bed_id": 32, "bed_label": "B1", "operational_status": "ready", "monthly_rent": Decimal("12500.00")}]
        response = self.client.get("/owner/rooms/23")
        self.assertIn("35,000.00", response.text)
        self.assertIn("Included in room rent", response.text)
        self.assertIn("not individually rentable", response.text)
        self.assertNotIn("12,500.00", response.text)

    def test_empty_bed_list(self):
        response = self.client.get("/owner/rooms/23")
        self.assertIn("No beds registered yet", response.text)

    def test_unowned_or_missing_room_returns_404_before_beds_query(self):
        self.room = None
        response = self.client.get("/owner/rooms/999?owner_id=99")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(any("FROM beds b JOIN rooms" in call.args[0] for call in self.cursor.execute.call_args_list))
        self.assertEqual(self.cursor.execute.call_args.args[1], (41, 999))

    def test_guests_and_nonowners_denied(self):
        with self.client.session_transaction() as session:
            session.pop("user_id")
        self.assertEqual(self.client.get("/owner/rooms").status_code, 302)
        self.rooms_db.assert_not_called()
        self.sign_in()
        for role in ("student", "admin"):
            self.owner["role"] = role
            for path in ("/owner/rooms", "/owner/rooms/create", "/owner/rooms/23"):
                self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post("/owner/rooms/create", data=self.payload()).status_code, 403)
        self.rooms_db.assert_not_called()

    def test_csrf_failures_block_before_database(self):
        for token in (None, "wrong"):
            payload = self.payload()
            payload.pop("csrf_token")
            if token:
                payload["csrf_token"] = token
            self.assertEqual(self.client.post("/owner/rooms/create", data=payload).status_code, 400)
        self.account_db.assert_not_called()
        self.rooms_db.assert_not_called()

    def test_inactive_account_and_stale_session_rejected(self):
        self.owner["password_hash"] = "changed-hash"
        self.assertEqual(self.client.get("/owner/rooms").status_code, 302)
        self.sign_in()
        self.owner = None
        self.assertEqual(self.client.get("/owner/rooms").status_code, 302)
        self.rooms_db.assert_not_called()

    def test_owner_b_queries_own_scope_despite_submitted_owner_and_boarding(self):
        self.owner["user_id"] = 99
        self.boarding["boarding_id"] = 24
        self.sign_in(user_id=99)
        self.client.post("/owner/rooms/create", data=self.payload(owner_id="41", boarding_id="12"))
        self.assertEqual(self.inserts()[0][1][0], 24)
        lock = next(call.args for call in self.cursor.execute.call_args_list if "FOR UPDATE" in call.args[0])
        self.assertEqual(lock[1], (24, 99))

    def test_database_errors_are_safe_and_preserve_owner_layout(self):
        self.rooms_db.side_effect = Error("private database details", errno=2003)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.get("/owner/rooms")
        self.assertEqual(response.status_code, 500)
        self.assertIn('id="owner-sidebar"', response.text)
        self.assertNotIn("private database details", response.text)

    def test_room_identifiers_and_description_are_html_escaped(self):
        self.room["room_number"] = "<script>bad()</script>"
        self.room["description"] = "<script>bad()</script>"
        response = self.client.get("/owner/rooms/23")
        self.assertNotIn("<script>", response.text)
        self.assertIn("&lt;script&gt;", response.text)

    def test_dashboard_room_count_uses_real_summary_and_preserves_other_placeholders(self):
        self.summary["total_rooms"] = 7
        response = self.client.get("/dashboard/owner")
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="metric-value">7</p>', response.text)
        self.assertIn("Occupied Beds", response.text)
        self.assertIn('href="/owner/rooms"', response.text)


if __name__ == "__main__":
    unittest.main()
