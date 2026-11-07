"""Authentication regression checks with database and email boundaries mocked."""

import time
import unittest
from unittest.mock import MagicMock, patch

from werkzeug.security import generate_password_hash

from app import app
from auth_email import password_stamp


class AuthRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password_hash = generate_password_hash("TestPassword!42")

    def setUp(self):
        original_config = dict(app.config)
        self.addCleanup(app.config.update, original_config)
        app.config.update(TESTING=True, SECRET_KEY="auth-test-key")
        self.client = app.test_client()
        self.user = {
            "user_id": 41, "full_name": "Test Owner", "role": "owner",
            "password_hash": self.password_hash, "is_active": True,
        }
        self.connection = MagicMock()
        self.connection.__enter__.return_value = self.connection
        self.cursor = self.connection.cursor.return_value.__enter__.return_value
        self.cursor.fetchone.side_effect = lambda: self.user.copy() if self.user else None
        self.start_patch("auth_access.get_db_connection", return_value=self.connection)
        for target in ("auth_email.get_db_connection", "owner_boarding.get_db_connection", "auth_email.send_code"):
            self.start_patch(target, side_effect=AssertionError("Unexpected live database or SMTP access"))

    def start_patch(self, target, **kwargs):
        patcher = patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def csrf(self):
        self.client.get("/login")
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def sign_in(self):
        with app.app_context():
            stamp = password_stamp(self.password_hash)
        with self.client.session_transaction() as session:
            session["user_id"] = 41
            session["password_stamp"] = stamp

    def test_public_auth_pages_render(self):
        for path in ("/", "/login", "/register", "/forgot-password"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_login_success_still_reaches_owner_dashboard(self):
        token = self.csrf()
        with patch("app.find_account", return_value=self.user):
            response = self.client.post("/login", data={"email": "owner@example.test", "password": "TestPassword!42", "csrf_token": token})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/dashboard/owner"))
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], 41)
            self.assertNotIn("csrf_token", session)
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_invalid_and_inactive_login_denied(self):
        token = self.csrf()
        for inactive in (False, True):
            with self.subTest(inactive=inactive), patch("app.find_account", return_value={**self.user, "is_active": not inactive}):
                response = self.client.post("/login", data={"email": "owner@example.test", "password": "TestPassword!42" if inactive else "wrong", "csrf_token": token})
                self.assertEqual(response.status_code, 400)

    def test_all_existing_auth_posts_block_missing_and_invalid_csrf(self):
        token = self.csrf()
        for path in ("/login", "/register", "/register/check-email", "/register/verify", "/forgot-password", "/reset-password", "/reset-password/new", "/logout"):
            for submitted in (None, "wrong"):
                with self.subTest(path=path, submitted=submitted):
                    data = {} if submitted is None else {"csrf_token": submitted}
                    self.assertEqual(self.client.post(path, data=data).status_code, 400)
        self.assertTrue(token)

    def test_logout_requires_post_and_csrf_then_clears_session(self):
        self.sign_in()
        token = self.csrf()
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.post("/logout").status_code, 400)
        with self.client.session_transaction() as session:
            self.assertEqual(session["user_id"], 41)
        response = self.client.post("/logout", data={"csrf_token": token})
        self.assertEqual(response.status_code, 303)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)
        self.assertEqual(self.client.get("/dashboard/owner").status_code, 302)

    def test_dashboard_guest_role_and_account_checks(self):
        self.assertEqual(self.client.get("/dashboard/owner").status_code, 302)
        self.sign_in()
        self.assertEqual(self.client.get("/dashboard/student").status_code, 403)
        self.assertTrue(self.client.get("/dashboard").location.endswith("/dashboard/owner"))
        for role in ("student", "admin"):
            self.user["role"] = role
            self.assertEqual(self.client.get(f"/dashboard/{role}").status_code, 200)
        self.user = None
        self.assertEqual(self.client.get("/dashboard/admin").status_code, 302)

    def test_dashboard_rejects_stale_password_stamp(self):
        self.sign_in()
        self.user["password_hash"] = "changed-hash"
        self.assertEqual(self.client.get("/dashboard/owner").status_code, 302)
        with self.client.session_transaction() as session:
            self.assertNotIn("user_id", session)

    def test_registration_starts_mocked_otp_flow(self):
        token = self.csrf()
        pending = {"email": "owner@gmail.com", "id": "test-challenge", "expires_at": int(time.time()) + 60}
        with patch("app.allow_request", return_value=True), patch("app.find_account", return_value=None), patch("app.mail_is_configured", return_value=True), patch("app.issue_code", return_value=pending):
            response = self.client.post("/register", data={
                "email": "owner@gmail.com", "full_name": "Test Owner", "role": "owner",
                "password": "TestPassword!42", "confirm_password": "TestPassword!42", "csrf_token": token,
            })
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/register/verify"))
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_registration_otp_completion_uses_existing_flow(self):
        token = self.csrf()
        with self.client.session_transaction() as session:
            session["pending_register"] = {"email": "owner@gmail.com", "id": "test-challenge", "expires_at": int(time.time()) + 60}
        with patch("app.allow_request", return_value=True), patch("app.verify_code", return_value="verified"):
            response = self.client.post("/register/verify", data={"csrf_token": token, "code": "12345678"})
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.location.endswith("/login"))

    def test_password_reset_request_otp_and_completion(self):
        token = self.csrf()
        pending = {"email": "owner@example.test", "id": "test-reset", "expires_at": int(time.time()) + 60}
        with patch("app.mail_is_configured", return_value=True), patch("app.allow_request", return_value=True), patch("app.begin_reset", return_value=pending):
            response = self.client.post("/forgot-password", data={"email": "owner@example.test", "csrf_token": token})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get("/reset-password").status_code, 200)
        with patch("app.allow_request", return_value=True), patch("app.verify_code", return_value="test-grant"):
            response = self.client.post("/reset-password", data={"code": "12345678", "csrf_token": token})
        self.assertEqual(response.status_code, 303)
        with patch("app.can_change_password", return_value=True), patch("app.change_password", return_value=True) as change:
            self.assertEqual(self.client.get("/reset-password/new").status_code, 200)
            response = self.client.post("/reset-password/new", data={"password": "NewPassword!42", "confirm_password": "NewPassword!42", "csrf_token": token})
        self.assertEqual(response.status_code, 303)
        change.assert_called_once()
        with self.client.session_transaction() as session:
            self.assertNotIn("verified_reset", session)
            self.assertNotIn("user_id", session)


if __name__ == "__main__":
    unittest.main()
