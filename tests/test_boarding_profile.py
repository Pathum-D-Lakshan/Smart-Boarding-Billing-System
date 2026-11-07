"""Profile view/create/edit tests. All account/profile data are disposable mocks."""

from copy import deepcopy
from datetime import datetime
from html.parser import HTMLParser
import unittest
from unittest.mock import MagicMock, patch
import json

from mysql.connector import Error
from werkzeug.security import generate_password_hash

from app import app
from auth_email import password_stamp


class NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.current_links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("aria-current") == "page":
            self.current_links.append(attrs["href"])


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.fields = {}
        self.forms = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.forms.append(attrs)
        if tag in ("input", "textarea") and "name" in attrs:
            self.fields.setdefault(attrs["name"], []).append(attrs)


class BoardingProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.edit_password = " TestEditPassword!42 "
        cls.edit_password_hash = generate_password_hash(cls.edit_password)

    def setUp(self):
        original_config = dict(app.config)
        self.addCleanup(app.config.update, original_config)
        app.config.update(TESTING=True, SECRET_KEY="boarding-test-key")
        self.client = app.test_client()
        self.owner = {"user_id": 41, "full_name": "Test Owner", "role": "owner", "password_hash": "test-hash"}
        self.boarding = {
            "boarding_id": 12, "owner_id": 41, "boarding_name": "Test Boarding",
            "description": "A quiet home.\nNear campus.", "address": "Example address",
            "city": "Example city", "district": "Example district",
            "contact_phone": "+94771234567", "contact_email": None,
            "facilities": '["Wi-Fi", "Kitchen"]', "house_rules": None, "status": "draft",
            "created_at": datetime(2026, 11, 1), "updated_at": datetime(2026, 11, 2),
        }
        self.account_connection, self.account_cursor = self.connection()
        self.boarding_connection, self.boarding_cursor = self.connection()
        self.account_cursor.fetchone.side_effect = lambda: deepcopy(self.owner)
        self.boarding_cursor.fetchone.side_effect = lambda: deepcopy(self.boarding)
        self.account_db = self.start_patch("auth_access.get_db_connection", return_value=self.account_connection)
        self.boarding_db = self.start_patch("owner_boarding.get_db_connection", return_value=self.boarding_connection)
        self.start_patch("auth_email.get_db_connection", side_effect=AssertionError("Unexpected live database access"))
        self.sign_in()

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    @staticmethod
    def connection():
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value.__enter__.return_value
        return connection, cursor

    def sign_in(self, user_id=41, password_hash="test-hash"):
        with app.app_context():
            stamp = password_stamp(password_hash)
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["password_stamp"] = stamp

    def test_empty_state(self):
        self.boarding = None
        response = self.client.get("/owner/boarding")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"No boarding profile yet", response.data)
        self.assertNotIn(b"Test Boarding", response.data)

    def test_saved_profile_and_optional_fields(self):
        response = self.client.get("/owner/boarding")
        self.assertEqual(response.status_code, 200)
        for text in ("Test Boarding", "A quiet home.", "Example address", "+94771234567", "Wi-Fi", "Kitchen", "Draft", "Not provided", "02 Nov 2026"):
            self.assertIn(text, response.text)
        self.assertNotIn("No boarding profile yet", response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_published_badge(self):
        self.boarding["status"] = "published"
        response = self.client.get("/owner/boarding")
        self.assertIn('class="boarding-status boarding-status-published"', response.text)
        self.assertIn("Published", response.text)

    def test_empty_facilities(self):
        self.boarding["facilities"] = "[]"
        self.assertIn("None selected", self.client.get("/owner/boarding").text)

    def test_facilities_already_decoded(self):
        self.boarding["facilities"] = ["Wi-Fi"]
        self.assertEqual(self.client.get("/owner/boarding").status_code, 200)

    def test_invalid_saved_facilities_has_safe_error(self):
        for facilities in ("invalid", "{}", '[{"bad": "value"}]', None):
            with self.subTest(facilities=facilities), self.assertLogs(app.logger, level="ERROR"):
                self.boarding["facilities"] = facilities
                response = self.client.get("/owner/boarding")
                self.assertEqual(response.status_code, 500)
                self.assertIn("Could not load your boarding profile", response.text)
                self.assertNotIn("No boarding profile yet", response.text)

    def test_saved_text_is_escaped(self):
        self.owner["full_name"] = '<script>alert("owner")</script>'
        self.boarding["boarding_name"] = '<script>alert("boarding")</script>'
        self.boarding["description"] = '<img src=x onerror="alert(1)">'
        self.boarding["facilities"] = '["<script>bad()</script>"]'
        response = self.client.get("/owner/boarding")
        self.assertNotIn("<script>", response.text)
        self.assertNotIn("<img src=x", response.text)
        self.assertIn("&lt;script&gt;", response.text)

    def test_submitted_ids_do_not_change_owner_scope(self):
        response = self.client.get("/owner/boarding?owner_id=99&boarding_id=99&status=published")
        self.assertEqual(response.status_code, 200)
        query, parameters = self.boarding_cursor.execute.call_args.args
        self.assertIn("WHERE owner_id = %s", query)
        self.assertEqual(parameters, (41,))
        self.assertIn("Draft", response.text)

    def test_second_owner_uses_own_account_id(self):
        self.owner["user_id"] = 99
        self.boarding = None
        self.sign_in(user_id=99)
        response = self.client.get("/owner/boarding")
        self.assertIn("No boarding profile yet", response.text)
        self.assertEqual(self.account_cursor.execute.call_args.args[1], (99,))
        self.assertEqual(self.boarding_cursor.execute.call_args.args[1], (99,))

    def test_active_account_query_is_parameterized(self):
        self.client.get("/owner/boarding")
        query, parameters = self.account_cursor.execute.call_args.args
        self.assertIn("WHERE user_id = %s AND is_active = TRUE", query)
        self.assertEqual(parameters, (41,))

    def test_guest_redirects_without_database_access(self):
        with self.client.session_transaction() as session:
            session.clear()
        response = self.client.get("/owner/boarding")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/login"))
        self.account_db.assert_not_called()
        self.boarding_db.assert_not_called()

    def test_student_and_admin_denied(self):
        for role in ("student", "admin"):
            with self.subTest(role=role):
                self.owner["role"] = role
                response = self.client.get("/owner/boarding")
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.boarding_db.assert_not_called()

    def test_inactive_or_removed_account_clears_session(self):
        self.owner = None
        response = self.client.get("/owner/boarding")
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
        self.boarding_db.assert_not_called()

    def test_changed_password_or_invalid_stamp_clears_session(self):
        for stamp in ("old-stamp", None, 42):
            with self.subTest(stamp=stamp):
                self.sign_in()
                with self.client.session_transaction() as session:
                    session["password_stamp"] = stamp
                self.assertEqual(self.client.get("/owner/boarding").status_code, 302)
                with self.client.session_transaction() as session:
                    self.assertNotIn("user_id", session)
        self.boarding_db.assert_not_called()

    def test_invalid_session_user_ids_rejected(self):
        for user_id in ("41", True, -1, 0, [41]):
            with self.subTest(user_id=user_id):
                with self.client.session_transaction() as session:
                    session["user_id"] = user_id
                self.assertEqual(self.client.get("/owner/boarding").status_code, 302)
        self.account_db.assert_not_called()

    def test_account_database_failure_is_safe(self):
        self.account_db.side_effect = Error("sensitive connection details", errno=2003)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.get("/owner/boarding")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("sensitive", response.text)
        self.boarding_db.assert_not_called()

    def test_boarding_database_failure_is_safe_and_keeps_layout(self):
        self.boarding_db.side_effect = Error("sensitive database details", errno=1142)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.get("/owner/boarding")
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("sensitive", response.text)
        self.assertIn('id="owner-sidebar"', response.text)
        self.assertIn("Try again", response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_shared_layout_and_active_link_on_both_pages(self):
        for path, active in (("/dashboard/owner", "/dashboard/owner"), ("/owner/boarding", "/owner/boarding")):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                parser = NavigationParser()
                parser.feed(response.text)
                self.assertEqual(parser.current_links, [active])
                for element_id in ("owner-sidebar", "sidebar-toggle", "sidebar-close", "sidebar-backdrop", "owner-page", "owner-logout"):
                    self.assertEqual(response.text.count(f'id="{element_id}"'), 1)
                self.assertIn('name="csrf_token"', response.text)
                self.assertIn('form="owner-logout"', response.text)
                self.assertEqual(response.text.count('<span class="nav-status">Coming soon</span>'), 10)
                self.assertIn('href="/owner/boarding"', response.text)

    def test_profile_styles_only_loaded_on_profile(self):
        self.assertIn("owner-boarding-profile.css", self.client.get("/owner/boarding").text)
        self.assertNotIn("owner-boarding-profile.css", self.client.get("/dashboard/owner").text)

    def test_read_only_view_does_not_commit_or_accept_post(self):
        self.client.get("/owner/boarding")
        self.assertEqual(self.client.post("/owner/boarding").status_code, 405)
        self.account_connection.commit.assert_not_called()
        self.boarding_connection.commit.assert_not_called()
        self.assertTrue(all(call.args[0].lstrip().startswith("SELECT") for call in self.boarding_cursor.execute.call_args_list))

    def create_payload(self, **changes):
        self.boarding = None
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-create-csrf"
        values = {
            "boarding_name": "Campus Boarding", "description": "A quiet place to stay.",
            "address": "Test address", "city": "Test city", "district": "Test district",
            "contact_phone": "077 123 4567", "contact_email": "", "house_rules": "",
            "csrf_token": "test-create-csrf",
        }
        values.update(changes)
        return values

    def insert_calls(self):
        return [call for call in self.boarding_cursor.execute.call_args_list if call.args[0].lstrip().startswith("INSERT")]

    def test_empty_state_has_live_create_action_only_without_profile(self):
        self.boarding = None
        self.assertIn('href="/owner/boarding/create"', self.client.get("/owner/boarding").text)
        self.boarding = {"boarding_id": 12, "owner_id": 41, "boarding_name": "Saved",
                         "description": "Saved details", "address": "Address", "city": "City", "district": "District",
                         "contact_phone": "+94771234567", "contact_email": None, "facilities": "[]", "house_rules": None,
                         "status": "draft", "created_at": datetime(2026, 11, 1), "updated_at": datetime(2026, 11, 1)}
        self.assertNotIn('href="/owner/boarding/create"', self.client.get("/owner/boarding").text)

    def test_create_form_native_validation_layout_and_cancel(self):
        self.boarding = None
        response = self.client.get("/owner/boarding/create")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        parser = FormParser()
        parser.feed(response.text)
        self.assertIn({"class": "boarding-form boarding-panel", "method": "post", "enctype": "multipart/form-data", "action": "/owner/boarding/create"}, parser.forms)
        for name in ("boarding_name", "description", "address", "city", "district", "contact_phone"):
            self.assertIn("required", parser.fields[name][0])
        for name in ("contact_email", "house_rules"):
            self.assertNotIn("required", parser.fields[name][0])
        for name, limit in (("boarding_name", 150), ("address", 255), ("city", 100), ("district", 100), ("contact_phone", 20), ("contact_email", 254)):
            self.assertEqual(parser.fields[name][0]["maxlength"], str(limit))
        self.assertEqual(parser.fields["contact_email"][0]["type"], "email")
        self.assertEqual(parser.fields["contact_phone"][0]["type"], "tel")
        self.assertIn("pattern", parser.fields["contact_phone"][0])
        self.assertEqual([field["value"] for field in parser.fields["facilities"]], ["Wi-Fi", "Parking", "Kitchen", "Laundry", "Study Area", "CCTV"])
        self.assertIn('href="/owner/boarding">Cancel</a>', response.text)
        self.assertIn("Save as Draft", response.text)
        nav = NavigationParser()
        nav.feed(response.text)
        self.assertEqual(nav.current_links, ["/owner/boarding"])
        for name in ("owner-sidebar", "owner-logout", "sidebar-toggle", "sidebar-backdrop"):
            self.assertIn(f'id="{name}"', response.text)
        self.boarding_connection.commit.assert_not_called()

    def test_create_draft_parameterized_insert_normalizes_and_ignores_ids_status(self):
        payload = self.create_payload(
            boarding_name="  Campus Boarding  ", contact_email=" OWNER@EXAMPLE.TEST ",
            facilities=["CCTV", "Wi-Fi", "Wi-Fi"], house_rules="  Keep shared areas clean.  ",
            owner_id="999", boarding_id="999", status="published",
        )
        response = self.client.post("/owner/boarding/create", data=payload)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/owner/boarding"))
        self.assertEqual(len(self.insert_calls()), 1)
        query, parameters = self.insert_calls()[0].args
        self.assertIn("'draft'", query)
        self.assertNotIn("published", query)
        self.assertEqual(parameters[:8], (41, "Campus Boarding", "A quiet place to stay.", "Test address", "Test city", "Test district", "+94771234567", "owner@example.test"))
        self.assertEqual(json.loads(parameters[8]), ["Wi-Fi", "CCTV"])
        self.assertEqual(parameters[9], "Keep shared areas clean.")
        self.boarding_connection.commit.assert_called_once()
        self.boarding_connection.rollback.assert_not_called()

    def test_empty_optional_values_store_null_and_json_array(self):
        response = self.client.post("/owner/boarding/create", data=self.create_payload())
        self.assertEqual(response.status_code, 303)
        parameters = self.insert_calls()[0].args[1]
        self.assertIsNone(parameters[7])
        self.assertEqual(parameters[8], "[]")
        self.assertIsNone(parameters[9])

    def test_success_redirect_shows_saved_values_and_flash_with_mocked_database(self):
        payload = self.create_payload()
        saved = {"boarding_id": 23, "owner_id": 41, "status": "draft", "facilities": "[]",
                 "created_at": datetime(2026, 11, 7), "updated_at": datetime(2026, 11, 7),
                 **{key: payload[key] for key in ("boarding_name", "description", "address", "city", "district")},
                 "contact_phone": "+94771234567", "contact_email": None, "house_rules": None}
        self.boarding_connection.commit.side_effect = lambda: setattr(self, "boarding", saved)
        response = self.client.post("/owner/boarding/create", data=payload, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Boarding saved as Draft!", response.text)
        self.assertIn("Campus Boarding", response.text)
        self.assertIn("+94771234567", response.text)
        self.assertIn('class="boarding-status boarding-status-draft"', response.text)
        self.assertNotIn('href="/owner/boarding/create"', response.text)
        self.assertIn("Campus Boarding", self.client.get("/owner/boarding").text)

    def test_blank_required_fields_block_insert_and_preserve_values(self):
        for field in ("boarding_name", "description", "address", "city", "district", "contact_phone"):
            with self.subTest(field=field):
                payload = self.create_payload(**{field: "   "})
                response = self.client.post("/owner/boarding/create", data=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn(f'id="{field}-error"', response.text)
                self.assertIn('role="alert"', response.text)
                self.assertIn('value="Test city"' if field != "city" else 'value="Test district"', response.text)
        self.assertEqual(self.insert_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_oversized_varchar_fields_block_insert(self):
        for field, limit in (("boarding_name", 150), ("address", 255), ("city", 100), ("district", 100), ("contact_phone", 20), ("contact_email", 254)):
            with self.subTest(field=field):
                response = self.client.post("/owner/boarding/create", data=self.create_payload(**{field: "x" * (limit + 1)}))
                self.assertEqual(response.status_code, 400)
                self.assertIn(f'id="{field}-error"', response.text)
        self.assertEqual(self.insert_calls(), [])

    def test_varchar_schema_boundaries_are_accepted(self):
        response = self.client.post("/owner/boarding/create", data=self.create_payload(
            boarding_name="x" * 150, address="x" * 255, city="x" * 100, district="x" * 100,
        ))
        self.assertEqual(response.status_code, 303)

    def test_multibyte_text_limit_rejects_by_bytes(self):
        for field in ("description", "house_rules"):
            with self.subTest(field=field):
                response = self.client.post("/owner/boarding/create", data=self.create_payload(**{field: "අ" * 21_846}))
                self.assertEqual(response.status_code, 400)
                self.assertIn(f'id="{field}-error"', response.text)
        self.assertEqual(self.insert_calls(), [])

    def test_multibyte_text_at_byte_limit_is_accepted(self):
        response = self.client.post("/owner/boarding/create", data=self.create_payload(description="අ" * 21_845, house_rules="අ" * 21_845))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(self.insert_calls()[0].args[1][2].encode("utf-8")), 65_535)

    def test_invalid_phone_formats_block_insert(self):
        for phone in ("123", "+940771234567", "0094771234567", "07712345678", "0001234567", "077abc4567", "077/123/4567", "+9477(1234567)", "077\t1234567"):
            with self.subTest(phone=phone):
                response = self.client.post("/owner/boarding/create", data=self.create_payload(contact_phone=phone))
                self.assertEqual(response.status_code, 400)
                self.assertIn('id="contact_phone-error"', response.text)
        self.assertEqual(self.insert_calls(), [])

    def test_local_and_international_phone_normalization(self):
        for phone, expected in (("0771234567", "+94771234567"), ("077-123-4567", "+94771234567"), ("+94 77 123 4567", "+94771234567"), ("011 234 5678", "+94112345678")):
            with self.subTest(phone=phone):
                response = self.client.post("/owner/boarding/create", data=self.create_payload(contact_phone=phone))
                self.assertEqual(response.status_code, 303)
                self.assertEqual(self.insert_calls()[-1].args[1][6], expected)

    def test_invalid_email_blocks_insert(self):
        for email in ("bad", "owner@", "owner@example", "owner @example.test"):
            with self.subTest(email=email):
                response = self.client.post("/owner/boarding/create", data=self.create_payload(contact_email=email))
                self.assertEqual(response.status_code, 400)
                self.assertIn('id="contact_email-error"', response.text)
        self.assertEqual(self.insert_calls(), [])

    def test_unknown_facilities_rejected_and_known_selection_retained(self):
        response = self.client.post("/owner/boarding/create", data=self.create_payload(facilities=["Wi-Fi", "Hot Water"]))
        self.assertEqual(response.status_code, 400)
        self.assertIn('id="facilities-error"', response.text)
        parser = FormParser()
        parser.feed(response.text)
        self.assertIn("checked", parser.fields["facilities"][0])
        self.assertEqual(self.insert_calls(), [])

    def test_existing_profile_blocks_direct_create_get_and_post(self):
        existing = deepcopy(self.boarding)
        payload = self.create_payload()
        self.boarding = existing
        for method in ("get", "post"):
            with self.subTest(method=method):
                response = getattr(self.client, method)("/owner/boarding/create", data=payload)
                self.assertEqual(response.status_code, 303)
                self.assertTrue(response.location.endswith("/owner/boarding"))
                self.assertIn("You already have a boarding profile", self.client.get(response.location).text)
        self.assertEqual(self.insert_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_concurrent_duplicate_rolls_back_and_redirects_friendly(self):
        payload = self.create_payload()
        def execute(query, parameters):
            if query.lstrip().startswith("INSERT"):
                raise Error("sensitive duplicate details", errno=1062)
        self.boarding_cursor.execute.side_effect = execute
        response = self.client.post("/owner/boarding/create", data=payload)
        self.assertEqual(response.status_code, 303)
        self.boarding_connection.rollback.assert_called_once()
        self.boarding_connection.commit.assert_not_called()
        self.assertIn("You already have a boarding profile", self.client.get(response.location).text)

    def test_insert_database_failure_rolls_back_and_preserves_form(self):
        payload = self.create_payload(facilities=["Parking"])
        def execute(query, parameters):
            if query.lstrip().startswith("INSERT"):
                raise Error("sensitive SQL details", errno=1142)
        self.boarding_cursor.execute.side_effect = execute
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/create", data=payload)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("sensitive", response.text)
        self.assertIn('value="Campus Boarding"', response.text)
        self.assertIn("Could not save", response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.boarding_connection.rollback.assert_called_once()
        self.boarding_connection.commit.assert_not_called()

    def test_commit_failure_rolls_back(self):
        payload = self.create_payload()
        self.boarding_connection.commit.side_effect = Error("private commit details", errno=1213)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/create", data=payload)
        self.assertEqual(response.status_code, 500)
        self.boarding_connection.rollback.assert_called_once()
        self.assertNotIn("private", response.text)

    def test_duplicate_precheck_failure_never_inserts(self):
        payload = self.create_payload()
        self.boarding_db.side_effect = Error("private connection details", errno=2003)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/create", data=payload)
        self.assertEqual(response.status_code, 500)
        self.assertIn('value="Campus Boarding"', response.text)
        self.assertEqual(self.insert_calls(), [])

    def test_missing_and_invalid_create_csrf_blocked_before_database(self):
        for token in (None, "wrong"):
            payload = self.create_payload()
            payload.pop("csrf_token")
            if token:
                payload["csrf_token"] = token
            with self.subTest(token=token):
                self.assertEqual(self.client.post("/owner/boarding/create", data=payload).status_code, 400)
        self.account_db.assert_not_called()
        self.boarding_db.assert_not_called()

    def test_guest_and_nonowner_cannot_create(self):
        payload = self.create_payload()
        with self.client.session_transaction() as session:
            session.pop("user_id")
        self.assertEqual(self.client.post("/owner/boarding/create", data=payload).status_code, 302)
        self.assertEqual(self.client.get("/owner/boarding/create").status_code, 302)
        self.sign_in()
        for role in ("student", "admin"):
            self.owner["role"] = role
            self.assertEqual(self.client.get("/owner/boarding/create").status_code, 403)
            self.assertEqual(self.client.post("/owner/boarding/create", data=payload).status_code, 403)
        self.boarding_db.assert_not_called()

    def test_second_owner_create_is_scoped_to_current_account(self):
        payload = self.create_payload(owner_id="41")
        self.owner["user_id"] = 99
        self.sign_in(user_id=99)
        response = self.client.post("/owner/boarding/create", data=payload)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.boarding_cursor.execute.call_args_list[0].args[1], (99,))
        self.assertEqual(self.insert_calls()[0].args[1][0], 99)

    def test_create_rejects_removed_account_and_stale_session(self):
        payload = self.create_payload()
        self.owner["password_hash"] = "changed-hash"
        self.assertEqual(self.client.post("/owner/boarding/create", data=payload).status_code, 302)
        self.sign_in()
        payload = self.create_payload()
        self.owner = None
        self.assertEqual(self.client.post("/owner/boarding/create", data=payload).status_code, 302)
        self.boarding_db.assert_not_called()

    def test_sql_shaped_name_stays_in_bound_parameters(self):
        name = "Owner's place'); DROP TABLE boardings; --"
        response = self.client.post("/owner/boarding/create", data=self.create_payload(boarding_name=name))
        self.assertEqual(response.status_code, 303)
        query, parameters = self.insert_calls()[0].args
        self.assertNotIn(name, query)
        self.assertEqual(parameters[1], name)

    def test_invalid_form_values_are_html_escaped(self):
        response = self.client.post("/owner/boarding/create", data=self.create_payload(boarding_name='<script>alert("x")</script>', description=""))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("<script>", response.text)
        self.assertIn("&lt;script&gt;", response.text)

    def test_later_batch_actions_not_added(self):
        for action in ("delete", "archive", "restore"):
            self.assertEqual(self.client.get(f"/owner/boarding/{action}").status_code, 404)

    def edit_payload(self, **changes):
        self.owner["password_hash"] = self.edit_password_hash
        self.sign_in(user_id=self.owner["user_id"], password_hash=self.edit_password_hash)
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-edit-csrf"
        values = {
            "boarding_name": "Updated Boarding", "description": "Updated description.",
            "address": "Updated address", "city": "Updated city", "district": "Updated district",
            "contact_phone": "077 123 4567", "contact_email": "", "house_rules": "",
            "current_password": self.edit_password, "csrf_token": "test-edit-csrf",
        }
        values.update(changes)
        return values

    def update_calls(self):
        return [call for call in self.boarding_cursor.execute.call_args_list if call.args[0].lstrip().startswith("UPDATE")]

    def test_edit_action_only_shown_for_saved_profile(self):
        self.assertIn('href="/owner/boarding/edit"', self.client.get("/owner/boarding").text)
        self.boarding = None
        self.assertNotIn('href="/owner/boarding/edit"', self.client.get("/owner/boarding").text)

    def test_edit_get_prefills_fields_and_keeps_shared_layout(self):
        response = self.client.get("/owner/boarding/edit")
        self.assertEqual(response.status_code, 200)
        parser = FormParser()
        parser.feed(response.text)
        for name in ("boarding_name", "address", "city", "district", "contact_phone"):
            self.assertEqual(parser.fields[name][0]["value"], self.boarding[name])
        self.assertIn(self.boarding["description"], response.text)
        self.assertEqual(parser.fields["contact_email"][0]["value"], "")
        selected = [field["value"] for field in parser.fields["facilities"] if "checked" in field]
        self.assertEqual(selected, ["Wi-Fi", "Kitchen"])
        password = parser.fields["current_password"][0]
        self.assertEqual(password["type"], "password")
        self.assertEqual(password["autocomplete"], "current-password")
        self.assertIn("required", password)
        self.assertNotIn("value", password)
        self.assertTrue(any(form.get("action") == "/owner/boarding/edit" for form in parser.forms))
        self.assertIn("Save Changes", response.text)
        self.assertNotIn("Save as Draft", response.text)
        self.assertIn('href="/owner/boarding">Cancel</a>', response.text)
        nav = NavigationParser()
        nav.feed(response.text)
        self.assertEqual(nav.current_links, ["/owner/boarding"])
        for element_id in ("owner-sidebar", "sidebar-toggle", "owner-logout", "sidebar-backdrop"):
            self.assertIn(f'id="{element_id}"', response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_create_form_does_not_require_edit_password(self):
        self.boarding = None
        response = self.client.get("/owner/boarding/create")
        self.assertNotIn('name="current_password"', response.text)
        self.assertIn("Save as Draft", response.text)

    def test_edit_confirmation_dialog_and_script_are_scoped_to_edit(self):
        response = self.client.get("/owner/boarding/edit")
        self.assertIn('id="boarding-password-dialog"', response.text)
        self.assertIn('aria-labelledby="password-dialog-title"', response.text)
        self.assertIn('id="boarding-confirm-save"', response.text)
        self.assertIn("owner-boarding-confirm.js", response.text)
        self.assertNotIn("boarding-password-section", response.text)
        self.assertNotIn("owner-boarding-confirm.js", self.client.get("/dashboard/owner").text)
        self.boarding = None
        self.assertNotIn("owner-boarding-confirm.js", self.client.get("/owner/boarding/create").text)

    def test_wrong_password_reopens_dialog_without_echoing_password(self):
        response = self.client.post("/owner/boarding/edit", data=self.edit_payload(current_password="wrong-password"))
        self.assertEqual(response.status_code, 400)
        self.assertIn('data-password-error="true"', response.text)
        parser = FormParser()
        parser.feed(response.text)
        self.assertNotIn("value", parser.fields["current_password"][0])
        response = self.client.post("/owner/boarding/edit", data=self.edit_payload(current_password="wrong-password", boarding_name=""))
        self.assertEqual(response.status_code, 400)
        self.assertIn('data-password-error="false"', response.text)
        self.assertEqual(self.update_calls(), [])

    def test_profile_photo_placeholder_and_saved_details_are_real(self):
        response = self.client.get("/owner/boarding")
        self.assertIn('class="boarding-profile-hero"', response.text)
        self.assertIn('aria-label="No cover photo added"', response.text)
        self.assertIn("Saved and unpublished", response.text)
        self.assertNotIn("Green Valley", response.text)
        self.assertIn(self.boarding["boarding_name"], response.text)
        self.assertIn(self.boarding["address"], response.text)
        self.assertIn("Created", response.text)
        self.assertIn("Last Updated", response.text)

    def test_edit_without_profile_redirects_without_writing(self):
        payload = self.edit_payload()
        self.boarding = None
        for method in ("get", "post"):
            response = getattr(self.client, method)("/owner/boarding/edit", data=payload)
            self.assertEqual(response.status_code, 303)
            self.assertTrue(response.location.endswith("/owner/boarding"))
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_edit_correct_password_updates_only_owned_details(self):
        payload = self.edit_payload(
            owner_id="999", boarding_id="999", status="published", created_at="2000-01-01",
            updated_at="2000-01-01", contact_email=" OWNER@EXAMPLE.TEST ",
            facilities=["Kitchen", "Wi-Fi"], house_rules="  Keep clean.  ",
        )
        response = self.client.post("/owner/boarding/edit", data=payload)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/owner/boarding"))
        self.assertEqual(len(self.update_calls()), 1)
        query, parameters = self.update_calls()[0].args
        self.assertIn("WHERE boarding_id = %s AND owner_id = %s", query)
        self.assertEqual(parameters, (
            "Updated Boarding", "Updated description.", "Updated address", "Updated city", "Updated district",
            "+94771234567", "owner@example.test", '["Wi-Fi", "Kitchen"]', "Keep clean.", 12, 41,
        ))
        assignments = query.split("WHERE")[0]
        for field in ("owner_id", "boarding_id", "created_at", "updated_at", "status", "password"):
            self.assertNotIn(field, assignments)
        lock_calls = [call for call in self.boarding_cursor.execute.call_args_list if "FOR UPDATE" in call.args[0]]
        self.assertEqual(len(lock_calls), 1)
        self.assertEqual(lock_calls[0].args[1], (12, 41))
        self.boarding_connection.commit.assert_called_once()
        self.boarding_connection.rollback.assert_not_called()
        self.assertEqual(self.insert_calls(), [])
        with self.client.session_transaction() as session:
            self.assertNotIn("current_password", session)
            self.assertNotIn(self.edit_password, str(dict(session)))

    def test_edit_missing_wrong_and_oversized_password_do_not_write(self):
        for password in (None, "wrong-password", "x" * 129):
            payload = self.edit_payload()
            if password is None:
                payload.pop("current_password")
            else:
                payload["current_password"] = password
            with self.subTest(password_case="missing" if password is None else "invalid"):
                response = self.client.post("/owner/boarding/edit", data=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn('id="current_password-error"', response.text)
                self.assertIn('value="Updated Boarding"', response.text)
                parser = FormParser()
                parser.feed(response.text)
                self.assertNotIn("value", parser.fields["current_password"][0])
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_edit_validation_reuses_create_rules_without_saving_password(self):
        cases = (
            {"boarding_name": " "}, {"description": ""}, {"address": ""}, {"city": ""}, {"district": ""},
            {"contact_phone": ""}, {"boarding_name": "x" * 151}, {"address": "x" * 256},
            {"city": "x" * 101}, {"district": "x" * 101}, {"contact_phone": "bad"},
            {"contact_email": "bad"}, {"facilities": ["Hot Water"]}, {"description": "අ" * 21_846},
            {"house_rules": "අ" * 21_846},
        )
        for fields in cases:
            with self.subTest(field=next(iter(fields))):
                response = self.client.post("/owner/boarding/edit", data=self.edit_payload(**fields))
                self.assertEqual(response.status_code, 400)
                self.assertIn(f'id="{next(iter(fields))}-error"', response.text)
                self.assertNotIn(self.edit_password, response.text)
                self.assertIn("Save Changes", response.text)
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_edit_empty_optionals_store_null_and_empty_json(self):
        response = self.client.post("/owner/boarding/edit", data=self.edit_payload())
        self.assertEqual(response.status_code, 303)
        parameters = self.update_calls()[0].args[1]
        self.assertIsNone(parameters[6])
        self.assertEqual(parameters[7], "[]")
        self.assertIsNone(parameters[8])

    def test_edit_published_status_stays_published(self):
        self.boarding["status"] = "published"
        self.assertIn('boarding-status-published', self.client.get("/owner/boarding/edit").text)
        response = self.client.post("/owner/boarding/edit", data=self.edit_payload(status="draft"))
        self.assertEqual(response.status_code, 303)
        self.assertNotIn("status", self.update_calls()[0].args[0])
        self.assertEqual(self.boarding["status"], "published")

    def test_edit_unchanged_row_is_successful(self):
        self.boarding_cursor.rowcount = 0
        response = self.client.post("/owner/boarding/edit", data=self.edit_payload())
        self.assertEqual(response.status_code, 303)
        self.boarding_connection.commit.assert_called_once()
        self.boarding_connection.rollback.assert_not_called()

    def test_edit_row_disappearing_before_update_rolls_back(self):
        payload = self.edit_payload()
        def fetchone():
            query = self.boarding_cursor.execute.call_args.args[0]
            return None if "FOR UPDATE" in query else deepcopy(self.boarding)
        self.boarding_cursor.fetchone.side_effect = fetchone
        response = self.client.post("/owner/boarding/edit", data=payload)
        self.assertEqual(response.status_code, 303)
        self.assertIn("no longer available", self.client.get(response.location).text)
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.rollback.assert_called_once()
        self.boarding_connection.commit.assert_not_called()

    def test_edit_update_error_rolls_back_and_preserves_safe_form(self):
        payload = self.edit_payload(facilities=["Parking"])
        def execute(query, parameters):
            if query.lstrip().startswith("UPDATE"):
                raise Error("private SQL details", errno=1142)
        self.boarding_cursor.execute.side_effect = execute
        with self.assertLogs(app.logger, level="ERROR") as logs:
            response = self.client.post("/owner/boarding/edit", data=payload)
        self.assertEqual(response.status_code, 500)
        self.assertIn('value="Updated Boarding"', response.text)
        self.assertIn("Could not save your boarding changes", response.text)
        self.assertNotIn("private SQL", response.text)
        self.assertNotIn(self.edit_password, response.text)
        self.assertNotIn(self.edit_password, str(logs.output))
        self.assertNotIn(self.edit_password_hash, str(logs.output))
        parser = FormParser()
        parser.feed(response.text)
        self.assertNotIn("value", parser.fields["current_password"][0])
        self.assertEqual([item["value"] for item in parser.fields["facilities"] if "checked" in item], ["Parking"])
        self.boarding_connection.rollback.assert_called_once()
        self.boarding_connection.commit.assert_not_called()

    def test_edit_commit_failure_rolls_back(self):
        payload = self.edit_payload()
        self.boarding_connection.commit.side_effect = Error("private commit details", errno=1213)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/edit", data=payload)
        self.assertEqual(response.status_code, 500)
        self.boarding_connection.rollback.assert_called_once()
        self.assertNotIn(self.edit_password, response.text)

    def test_edit_read_error_preserves_submitted_values_without_password(self):
        payload = self.edit_payload()
        self.boarding_db.side_effect = Error("private connection details", errno=2003)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/edit", data=payload)
        self.assertEqual(response.status_code, 500)
        self.assertIn('value="Updated Boarding"', response.text)
        self.assertNotIn(self.edit_password, response.text)
        self.assertEqual(self.update_calls(), [])

    def test_edit_missing_and_invalid_csrf_block_before_account_lookup(self):
        for token in (None, "wrong"):
            payload = self.edit_payload()
            payload.pop("csrf_token")
            if token:
                payload["csrf_token"] = token
            self.assertEqual(self.client.post("/owner/boarding/edit", data=payload).status_code, 400)
        self.account_db.assert_not_called()
        self.boarding_db.assert_not_called()

    def test_edit_guest_student_and_admin_denied(self):
        payload = self.edit_payload()
        with self.client.session_transaction() as session:
            session.pop("user_id")
        self.assertEqual(self.client.get("/owner/boarding/edit").status_code, 302)
        self.assertEqual(self.client.post("/owner/boarding/edit", data=payload).status_code, 302)
        self.sign_in(password_hash=self.edit_password_hash)
        for role in ("student", "admin"):
            self.owner["role"] = role
            self.assertEqual(self.client.get("/owner/boarding/edit").status_code, 403)
            self.assertEqual(self.client.post("/owner/boarding/edit", data=payload).status_code, 403)
        self.boarding_db.assert_not_called()

    def test_edit_rechecks_account_activation_and_password_stamp(self):
        payload = self.edit_payload()
        self.owner["password_hash"] = "changed-hash"
        self.assertEqual(self.client.post("/owner/boarding/edit", data=payload).status_code, 302)
        payload = self.edit_payload()
        self.owner = None
        self.assertEqual(self.client.post("/owner/boarding/edit", data=payload).status_code, 302)
        self.boarding_db.assert_not_called()

    def test_edit_owner_b_can_only_update_owner_b_record(self):
        self.owner["user_id"] = 99
        self.boarding["owner_id"] = 99
        self.boarding["boarding_id"] = 24
        payload = self.edit_payload(owner_id="41", boarding_id="12")
        response = self.client.post("/owner/boarding/edit", data=payload)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.boarding_cursor.execute.call_args_list[0].args[1], (99,))
        self.assertEqual(self.update_calls()[0].args[1][-2:], (24, 99))

    def test_edit_sql_like_and_html_values_remain_bound_and_escaped(self):
        name = "Owner's place'); DROP TABLE boardings; --"
        response = self.client.post("/owner/boarding/edit", data=self.edit_payload(boarding_name=name))
        self.assertEqual(response.status_code, 303)
        self.assertNotIn(name, self.update_calls()[0].args[0])
        self.assertEqual(self.update_calls()[0].args[1][0], name)
        response = self.client.post("/owner/boarding/edit", data=self.edit_payload(boarding_name="<script>bad()</script>", description=""))
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("<script>", response.text)
        self.assertIn("&lt;script&gt;", response.text)

    def test_edit_success_redirect_and_refresh_after_relogin_with_mocked_database(self):
        payload = self.edit_payload()
        created_at = self.boarding["created_at"]
        def commit_saved_values():
            parameters = self.update_calls()[0].args[1]
            self.boarding.update(boarding_name=parameters[0], description=parameters[1],
                                 contact_phone=parameters[5], facilities=parameters[7],
                                 updated_at=datetime(2026, 11, 7))
        self.boarding_connection.commit.side_effect = commit_saved_values
        response = self.client.post("/owner/boarding/edit", data=payload, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Boarding profile updated successfully.", response.text)
        self.assertIn("Updated Boarding", response.text)
        self.assertEqual(self.boarding["created_at"], created_at)
        self.assertIn("01 Nov 2026", response.text)
        self.assertIn("07 Nov 2026", response.text)
        self.client.post("/logout", data={"csrf_token": payload["csrf_token"]})
        with patch("app.find_account", return_value={**self.owner, "is_active": True}):
            self.client.get("/login")
            with self.client.session_transaction() as session:
                token = session["csrf_token"]
            response = self.client.post("/login", data={"email": "owner@example.test", "password": self.edit_password, "csrf_token": token})
        self.assertEqual(response.status_code, 303)
        self.assertIn("Updated Boarding", self.client.get("/owner/boarding").text)
        self.assertIn('value="Updated Boarding"', self.client.get("/owner/boarding/edit").text)

    def status_payload(self, **changes):
        with self.client.session_transaction() as session:
            session["csrf_token"] = "test-status-csrf"
        return {"csrf_token": "test-status-csrf", **changes}

    def test_status_actions_match_saved_status_and_include_csrf(self):
        response = self.client.get("/owner/boarding")
        parser = FormParser()
        parser.feed(response.text)
        self.assertTrue(any(form.get("action") == "/owner/boarding/publish" and form.get("method") == "post" for form in parser.forms))
        self.assertNotIn('action="/owner/boarding/unpublish"', response.text)
        self.assertTrue(all(field.get("value") for field in parser.fields["csrf_token"]))
        self.boarding["status"] = "published"
        response = self.client.get("/owner/boarding")
        self.assertIn('action="/owner/boarding/unpublish"', response.text)
        self.assertNotIn('action="/owner/boarding/publish"', response.text)
        self.boarding = None
        response = self.client.get("/owner/boarding")
        self.assertNotIn('action="/owner/boarding/publish"', response.text)
        self.assertNotIn('action="/owner/boarding/unpublish"', response.text)

    def test_publish_validates_locked_saved_record_and_updates_only_status(self):
        response = self.client.post("/owner/boarding/publish", data=self.status_payload(
            owner_id="99", boarding_id="99", status="draft", boarding_name="Untrusted value",
        ))
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/owner/boarding"))
        lock, update = self.boarding_cursor.execute.call_args_list
        self.assertIn("WHERE owner_id = %s FOR UPDATE", lock.args[0])
        self.assertEqual(lock.args[1], (41,))
        self.assertIn("SET status = %s, updated_at = CURRENT_TIMESTAMP", update.args[0])
        self.assertIn("WHERE boarding_id = %s AND owner_id = %s AND status = %s", update.args[0])
        self.assertEqual(update.args[1], ("published", 12, 41, "draft"))
        assignments = update.args[0].split("WHERE")[0]
        for field in ("boarding_name", "created_at", "owner_id", "boarding_id", "cover_image_filename"):
            self.assertNotIn(field, assignments)
        self.boarding_connection.commit.assert_called_once()
        self.boarding_connection.rollback.assert_not_called()

    def test_publish_does_not_require_optional_cover_or_facilities(self):
        self.boarding["facilities"] = "[]"
        self.boarding["cover_image_filename"] = None
        response = self.client.post("/owner/boarding/publish", data=self.status_payload())
        self.assertEqual(response.status_code, 303)
        self.boarding_connection.commit.assert_called_once()

    def test_publish_rejects_invalid_saved_details_even_with_valid_submitted_values(self):
        original = deepcopy(self.boarding)
        cases = (
            ("boarding_name", " "), ("description", ""), ("address", ""), ("city", ""),
            ("district", ""), ("contact_phone", ""), ("boarding_name", "x" * 151),
            ("contact_phone", "bad"), ("contact_email", "invalid"),
            ("facilities", '["Unknown"]'), ("description", "අ" * 21_846),
        )
        for field, value in cases:
            with self.subTest(field=field):
                self.boarding = {**original, field: value}
                response = self.client.post("/owner/boarding/publish", data=self.status_payload(
                    boarding_name="Valid submitted name", description="Valid submitted description",
                    address="Valid address", city="Valid city", district="Valid district", contact_phone="0771234567",
                ))
                self.assertEqual(response.status_code, 400)
                self.assertIn("Update these details before publishing", response.text)
                self.assertIn('href="/owner/boarding/edit"', response.text)
                self.assertIn('role="alert"', response.text)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_publish_invalid_saved_facilities_has_safe_feedback(self):
        for facilities in ("invalid", "{}", None, '[{"bad":"value"}]'):
            with self.subTest(facilities=facilities):
                self.boarding["facilities"] = facilities
                response = self.client.post("/owner/boarding/publish", data=self.status_payload())
                self.assertEqual(response.status_code, 400)
                self.assertIn("choose facilities", response.text)
                self.assertNotIn("Traceback", response.text)
        self.assertEqual(self.update_calls(), [])

    def test_unpublish_sets_draft_without_requiring_valid_publish_details(self):
        self.boarding.update(status="published", description="", facilities="invalid")
        response = self.client.post("/owner/boarding/unpublish", data=self.status_payload(status="published"))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.update_calls()[0].args[1], ("draft", 12, 41, "published"))
        self.boarding_connection.commit.assert_called_once()

    def test_repeated_status_action_is_idempotent_and_does_not_touch_timestamps(self):
        for action, status in (("publish", "published"), ("unpublish", "draft")):
            with self.subTest(action=action):
                self.boarding["status"] = status
                response = self.client.post("/owner/boarding/" + action, data=self.status_payload())
                self.assertEqual(response.status_code, 303)
                self.assertIn("already", self.client.get(response.location).text)
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_status_actions_without_profile_do_not_write(self):
        self.boarding = None
        for action in ("publish", "unpublish"):
            response = self.client.post("/owner/boarding/" + action, data=self.status_payload())
            self.assertEqual(response.status_code, 303)
            self.assertIn("Create a boarding profile before", self.client.get(response.location).text)
        self.assertEqual(self.update_calls(), [])
        self.boarding_connection.commit.assert_not_called()

    def test_status_actions_require_post(self):
        for action in ("publish", "unpublish"):
            self.assertEqual(self.client.get("/owner/boarding/" + action).status_code, 405)
        self.boarding_db.assert_not_called()

    def test_status_actions_reject_missing_and_invalid_csrf_before_database(self):
        for action in ("publish", "unpublish"):
            for token in (None, "wrong"):
                data = self.status_payload()
                data.pop("csrf_token")
                if token:
                    data["csrf_token"] = token
                self.assertEqual(self.client.post("/owner/boarding/" + action, data=data).status_code, 400)
        self.account_db.assert_not_called()
        self.boarding_db.assert_not_called()

    def test_status_actions_deny_guest_student_admin(self):
        for action in ("publish", "unpublish"):
            self.owner["role"] = "owner"
            data = self.status_payload()
            with self.client.session_transaction() as session:
                session.pop("user_id", None)
            self.assertEqual(self.client.post("/owner/boarding/" + action, data=data).status_code, 302)
            self.sign_in()
            for role in ("student", "admin"):
                self.owner["role"] = role
                self.assertEqual(self.client.post("/owner/boarding/" + action, data=data).status_code, 403)
        self.boarding_db.assert_not_called()

    def test_status_actions_recheck_account_activation_and_password_stamp(self):
        original = deepcopy(self.owner)
        for action in ("publish", "unpublish"):
            self.owner = deepcopy(original)
            self.sign_in()
            data = self.status_payload()
            self.owner["password_hash"] = "changed"
            self.assertEqual(self.client.post("/owner/boarding/" + action, data=data).status_code, 302)
            self.owner = deepcopy(original)
            self.sign_in()
            data = self.status_payload()
            self.owner = None
            self.assertEqual(self.client.post("/owner/boarding/" + action, data=data).status_code, 302)
        self.boarding_db.assert_not_called()

    def test_owner_b_status_update_ignores_owner_a_ids(self):
        self.owner["user_id"] = 99
        self.boarding.update(owner_id=99, boarding_id=24)
        self.sign_in(user_id=99)
        response = self.client.post("/owner/boarding/publish", data=self.status_payload(owner_id="41", boarding_id="12"))
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.boarding_cursor.execute.call_args_list[0].args[1], (99,))
        self.assertEqual(self.update_calls()[0].args[1], ("published", 24, 99, "draft"))

    def test_status_update_failure_rolls_back_with_safe_feedback(self):
        def execute(query, parameters):
            if query.lstrip().startswith("UPDATE"):
                raise Error("private SQL details", errno=1142)
        self.boarding_cursor.execute.side_effect = execute
        with self.assertLogs(app.logger, level="ERROR") as logs:
            response = self.client.post("/owner/boarding/publish", data=self.status_payload())
        self.assertEqual(response.status_code, 500)
        self.assertIn("Could not change your boarding status", response.text)
        self.assertNotIn("private SQL", response.text)
        self.assertNotIn("private SQL", str(logs.output))
        self.boarding_connection.rollback.assert_called_once()
        self.boarding_connection.commit.assert_not_called()

    def test_status_commit_failure_rolls_back(self):
        self.boarding_connection.commit.side_effect = Error("private commit details", errno=1213)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/publish", data=self.status_payload())
        self.assertEqual(response.status_code, 500)
        self.boarding_connection.rollback.assert_called_once()

    def test_status_lookup_failure_is_safe(self):
        self.boarding_db.side_effect = Error("private connection details", errno=2003)
        with self.assertLogs(app.logger, level="ERROR"):
            response = self.client.post("/owner/boarding/publish", data=self.status_payload())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.update_calls(), [])
        self.assertNotIn("private connection", response.text)

    def test_status_actions_do_not_modify_cover_files(self):
        self.boarding["cover_image_filename"] = "a" * 32 + ".webp"
        with patch("owner_boarding.remove_cover_image") as remove, patch("owner_boarding.save_cover_image") as save:
            self.assertEqual(self.client.post("/owner/boarding/publish", data=self.status_payload()).status_code, 303)
            self.boarding["status"] = "published"
            self.assertEqual(self.client.post("/owner/boarding/unpublish", data=self.status_payload()).status_code, 303)
        remove.assert_not_called()
        save.assert_not_called()

    def test_publish_then_unpublish_renders_saved_badges_with_mocked_database(self):
        created_at = self.boarding["created_at"]
        def commit_status():
            self.boarding["status"] = self.update_calls()[-1].args[1][0]
            self.boarding["updated_at"] = datetime(2026, 11, 7)
        self.boarding_connection.commit.side_effect = commit_status
        response = self.client.post("/owner/boarding/publish", data=self.status_payload(), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Boarding published successfully.", response.text)
        self.assertIn('boarding-status-published', response.text)
        self.assertIn('action="/owner/boarding/unpublish"', response.text)
        self.assertIn("Published", self.client.get("/owner/boarding").text)
        response = self.client.post("/owner/boarding/unpublish", data=self.status_payload(), follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Boarding unpublished", response.text)
        self.assertIn('boarding-status-draft', response.text)
        self.assertIn('action="/owner/boarding/publish"', response.text)
        self.assertEqual(self.boarding["created_at"], created_at)


if __name__ == "__main__":
    unittest.main()
