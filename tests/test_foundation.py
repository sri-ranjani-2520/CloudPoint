import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from cloudpoint.app import _QuietWSGIRequestHandler, create_app
from cloudpoint.config import DEFAULT_DATABASE_PATH, PROJECT_ROOT, Settings
from cloudpoint.repository import DuplicateComplaintError, Repository, SchemaMigrationError
from cloudpoint.validation import ValidationError, generate_complaint_id, validate_complaint, validate_complaint_id, validate_status
from tools.create_admin import hash_password


VALID_COMPLAINT = {
    "student_name": "  Example Student ",
    "registration_number": "REG-1001",
    "title": "Broken light",
    "category": "Infrastructure",
    "description": "A corridor light is not working.",
    "location": "North Block",
}


class FoundationTests(unittest.TestCase):
    def setUp(self):
        descriptor, database_path = tempfile.mkstemp(
            prefix=".test-cloudpoint-foundation-", suffix=".sqlite3", dir=PROJECT_ROOT
        )
        os.close(descriptor)
        self.database_path = Path(database_path)
        self.repository = Repository(self.database_path)
        self.repository.initialize()

    def tearDown(self):
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_configuration_loads_and_validates(self):
        settings = Settings.from_env({"CLOUDPOINT_DB_PATH": "tmp/test.sqlite3", "CLOUDPOINT_PORT": "8081"})
        self.assertEqual(settings.database_path, (PROJECT_ROOT / "tmp/test.sqlite3").resolve())
        self.assertEqual(settings.port, 8081)
        with self.assertRaises(ValueError):
            Settings.from_env({"CLOUDPOINT_PORT": "70000"})

    def test_session_secret_is_not_exposed_by_settings_repr(self):
        secret = "private-session-secret-value" * 2
        self.assertNotIn(secret, repr(Settings(self.database_path, session_secret=secret)))

    def test_configuration_paths_and_precedence_are_independent_of_working_directory(self):
        original_cwd = Path.cwd()
        dotenv_values = {
            "CLOUDPOINT_DB_PATH": "dotenv/db.sqlite3",
            "CLOUDPOINT_PORT": "8123",
            "CLOUDPOINT_DYNAMODB_TABLE": "from-dotenv",
            "CLOUDPOINT_AWS_REGION": "ap-south-1",
        }
        try:
            for working_directory in (PROJECT_ROOT, PROJECT_ROOT / "frontend"):
                os.chdir(working_directory)
                with patch("cloudpoint.config._read_dotenv", return_value=dotenv_values) as read_dotenv:
                    settings = Settings.from_env({
                        "CLOUDPOINT_DB_PATH": "override/local.sqlite3",
                        "CLOUDPOINT_DYNAMODB_TABLE": "from-environment",
                    })
                read_dotenv.assert_called_once_with(PROJECT_ROOT / ".env")
                self.assertEqual(settings.database_path, (PROJECT_ROOT / "override/local.sqlite3").resolve())
                self.assertEqual(settings.port, 8123)
                self.assertEqual(settings.dynamodb_table, "from-environment")
                self.assertEqual(settings.aws_region, "ap-south-1")
            with patch("cloudpoint.config._read_dotenv", return_value={}):
                self.assertEqual(Settings.from_env({}).database_path, DEFAULT_DATABASE_PATH)
        finally:
            os.chdir(original_cwd)

    def test_application_health_and_consistent_error_response(self):
        app = create_app(Settings(self.database_path))
        status, _, body = self.request(app, "/")
        self.assertEqual(status, "200 OK")
        self.assertIn("Submit a complaint", body)
        status, _, body = self.request(app, "/health")
        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body), {"status": "ok"})
        status, _, body = self.request(app, "/missing")
        self.assertEqual(status, "404 Not Found")
        payload = json.loads(body)
        self.assertEqual(payload["error"]["code"], "not_found")
        self.assertIn("message", payload["error"])

    def test_local_wsgi_access_log_suppresses_request_paths(self):
        handler = object.__new__(_QuietWSGIRequestHandler)
        with self.assertNoLogs("wsgiref", level="INFO"):
            handler.log_message('"GET /api/complaints/CP-sensitive-id HTTP/1.1" 200 -')

    def test_method_handling_and_allow_header(self):
        app = create_app(Settings(self.database_path))
        status, headers, _ = self.request(app, "/health", method="POST")
        self.assertEqual(status, "405 Method Not Allowed")
        self.assertIn(("Allow", "GET"), headers)
        status, _, body = self.request(app, "/not-a-route", method="POST")
        self.assertEqual(status, "404 Not Found")
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")
        status, _, _ = self.request(app, "/static/missing.css", method="POST")
        self.assertEqual(status, "404 Not Found")

    def test_admin_frontend_is_served_without_weakening_api_authorization(self):
        app = create_app(Settings(self.database_path, session_secret="foundation-test-session-secret-" + "s" * 32))
        status, _, body = self.request(app, "/admin.html")
        self.assertEqual(status, "200 OK")
        self.assertIn("Administrator sign in", body)
        self.assertIn('href="/admin.html"', self.request(app, "/")[2])
        status, _, script = self.request(app, "/static/admin.js")
        self.assertEqual(status, "200 OK")
        self.assertIn("Authorization", script)
        status, headers, _ = self.request(app, "/admin.html", method="POST")
        self.assertEqual(status, "405 Method Not Allowed")
        self.assertIn(("Allow", "GET"), headers)
        status, _, body = self.request(app, "/api/admin/dashboard")
        self.assertEqual(status, "401 Unauthorized")

    def test_malformed_wsgi_environment_returns_controlled_error(self):
        app = create_app(Settings(self.database_path))
        for environ in (
            {"PATH_INFO": "/health"},
            {"REQUEST_METHOD": "GET"},
            {"REQUEST_METHOD": None, "PATH_INFO": "/health"},
            {"REQUEST_METHOD": "GET\n", "PATH_INFO": "/health"},
            {"REQUEST_METHOD": "GET", "PATH_INFO": None},
            {"REQUEST_METHOD": "GET", "PATH_INFO": []},
            {"REQUEST_METHOD": "GET", "PATH_INFO": "health"},
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/bad\x00path"},
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/bad\ud800path"},
        ):
            with self.subTest(environ=environ):
                status, _, body = self.request_environ(app, environ)
                self.assertEqual(status, "400 Bad Request")
                self.assertEqual(json.loads(body)["error"]["code"], "invalid_request")
        status, _, body = self.request_environ(app, [])
        self.assertEqual(status, "400 Bad Request")
        self.assertNotIn(str(PROJECT_ROOT), body)

    def test_static_route_rejects_path_traversal(self):
        app = create_app(Settings(self.database_path))
        status, _, body = self.request(app, "/static/styles.css")
        self.assertEqual(status, "200 OK")
        self.assertIn("color-scheme", body)
        status, headers, body = self.request(app, "/static/app.js")
        self.assertEqual(status, "200 OK")
        self.assertIn(("Content-Type", "text/javascript; charset=utf-8"), headers)
        self.assertIn("credentials: \"omit\"", body)
        status, _, body = self.request(app, "/static/../../../README.md")
        self.assertEqual(status, "404 Not Found")
        self.assertNotIn("Campus Complaint Management System", body)

    def test_database_initializes_and_persists_records(self):
        complaint = validate_complaint(VALID_COMPLAINT)
        complaint_id = generate_complaint_id()
        self.repository.create_complaint(complaint_id, complaint.__dict__)
        self.repository.initialize()
        reopened = Repository(self.database_path)
        self.assertEqual(reopened.get_complaint(complaint_id)["student_name"], "Example Student")

    def test_repository_rejects_null_empty_whitespace_and_malformed_ids(self):
        values = validate_complaint(VALID_COMPLAINT).__dict__
        for complaint_id in (None, "", "   ", "malformed", "CP-abcdefghijklmn!"):
            with self.subTest(complaint_id=complaint_id):
                with self.assertRaises(ValidationError):
                    self.repository.create_complaint(complaint_id, values)
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM complaints").fetchone()[0], 0)

    def test_database_independently_rejects_invalid_ids(self):
        for index, complaint_id in enumerate((None, "", "   ", "malformed", "CP-abcdefghijklmn!")):
            with self.subTest(complaint_id=complaint_id):
                connection = sqlite3.connect(self.database_path)
                try:
                    with self.assertRaises(sqlite3.IntegrityError):
                        self._raw_insert(connection, complaint_id, f"REG-{index}")
                finally:
                    connection.close()

    def test_duplicate_identifier_is_rejected(self):
        values = validate_complaint(VALID_COMPLAINT).__dict__
        self.repository.create_complaint("CP-abcdefghijklmnop", values)
        with self.assertRaises(DuplicateComplaintError):
            self.repository.create_complaint("CP-abcdefghijklmnop", values)
        self.assertIsNotNone(self.repository.get_complaint("CP-abcdefghijklmnop"))
        with closing(sqlite3.connect(self.database_path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM complaints").fetchone()[0], 1)

    def test_sqlite_listing_filters_and_paginates_without_duplicates(self):
        values = validate_complaint(VALID_COMPLAINT).__dict__
        ids = [f"CP-{suffix:016d}" for suffix in range(1, 4)]
        for complaint_id in ids:
            self.repository.create_complaint(complaint_id, values)
        first_page = self.repository.list_complaints(category="Infrastructure", status="Submitted", limit=2)
        self.assertEqual([item["complaint_id"] for item in first_page.items], ids[:2])
        self.assertIsNotNone(first_page.next_cursor)
        second_page = self.repository.list_complaints(
            category="Infrastructure", status="Submitted", limit=2, cursor=first_page.next_cursor
        )
        self.assertEqual([item["complaint_id"] for item in second_page.items], ids[2:])
        self.assertIsNone(second_page.next_cursor)
        found = self.repository.list_complaints(search="broken LIGHT")
        self.assertEqual(len(found.items), 3)
        exact = self.repository.list_complaints(search=ids[0].lower())
        self.assertEqual([item["complaint_id"] for item in exact.items], [ids[0]])
        self.assertEqual(self.repository.dashboard_counts()["total"], 3)

    def test_sqlite_substring_search_uses_unicode_casefold(self):
        values = {**VALID_COMPLAINT, "title": "Straße lighting"}
        self.repository.create_complaint("CP-abcdefghijklmnop", values)
        page = self.repository.list_complaints(search="STRASSE")
        self.assertEqual([item["complaint_id"] for item in page.items], ["CP-abcdefghijklmnop"])

    def test_invalid_read_id_and_cursor_are_rejected(self):
        for complaint_id in (None, "", " bad ", "malformed"):
            with self.subTest(complaint_id=complaint_id):
                with self.assertRaises(ValidationError):
                    self.repository.get_complaint(complaint_id)
        with self.assertRaises(ValidationError):
            self.repository.list_complaints(cursor="not-a-valid-cursor")

    def test_rejection_reason_constraint_is_enforced_by_database(self):
        connection = sqlite3.connect(self.database_path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert(connection, "CP-abcdefghijklmnop", "REG-1", status="Rejected")
            with self.assertRaises(sqlite3.IntegrityError):
                self._raw_insert(
                    connection,
                    "CP-qrstuvwxyzABCDEF",
                    "REG-2",
                    status="Rejected",
                    rejection_reason="   ",
                )
        finally:
            connection.close()
        self.assertIsNone(self.repository.get_complaint("CP-abcdefghijklmnop"))

    def test_legacy_schema_migrates_valid_records_without_data_loss(self):
        self._replace_with_legacy_database(("CP-abcdefghijklmnop",))
        migrated = Repository(self.database_path)
        migrated.initialize()
        self.assertEqual(migrated.get_complaint("CP-abcdefghijklmnop")["title"], "Legacy title")
        migrated.initialize()
        self.assertEqual(migrated.get_complaint("CP-abcdefghijklmnop")["status"], "Submitted")

    def test_legacy_schema_with_null_id_is_refused_without_data_loss(self):
        self._replace_with_legacy_database((None,))
        with self.assertRaises(SchemaMigrationError):
            Repository(self.database_path).initialize()
        connection = sqlite3.connect(self.database_path)
        try:
            self.assertEqual(connection.execute("SELECT count(*) FROM complaints").fetchone()[0], 1)
            self.assertIsNone(connection.execute("SELECT complaint_id FROM complaints").fetchone()[0])
            self.assertEqual(connection.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='complaints_migration'"
            ).fetchone()[0], 0)
        finally:
            connection.close()

    def test_repository_connections_are_closed(self):
        self.repository.get_complaint("CP-abcdefghijklmnop")
        self.database_path.unlink()
        self.assertFalse(self.database_path.exists())

    def test_database_enforces_category_status_and_required_values(self):
        invalid_records = [
            ("CP-abcdefghijklmnop", "Other", "Unknown"),
            ("CP-qrstuvwxyzABCDEF", "Not a category", "Submitted"),
        ]
        for complaint_id, category, status in invalid_records:
            with self.subTest(category=category, status=status):
                with self.assertRaises(sqlite3.IntegrityError):
                    connection = sqlite3.connect(self.database_path)
                    try:
                        connection.execute(
                            """INSERT INTO complaints (complaint_id, student_name, registration_number,
                            title, category, description, location, status, created_at, modified_at)
                            VALUES (?, 'Name', 'Reg', 'Title', ?, 'Description', 'Location', ?, 'now', 'now')""",
                            (complaint_id, category, status),
                        )
                    finally:
                        connection.close()

    def test_required_fields_category_and_lengths_are_validated(self):
        with self.assertRaises(ValidationError) as caught:
            validate_complaint({**VALID_COMPLAINT, "student_name": " ", "category": "invalid"})
        self.assertEqual(set(caught.exception.errors), {"student_name", "category"})
        with self.assertRaises(ValidationError):
            validate_complaint({**VALID_COMPLAINT, "title": "x" * 161})

    def test_identifier_and_status_validation(self):
        generated = {generate_complaint_id() for _ in range(100)}
        self.assertEqual(len(generated), 100)
        for complaint_id in generated:
            validate_complaint_id(complaint_id)
        self.assertEqual(validate_complaint_id("CP-abcdefghijklmnop"), "CP-abcdefghijklmnop")
        with self.assertRaises(ValidationError):
            validate_complaint_id("bad")
        self.assertEqual(validate_status("Rejected", "Reviewed and declined"), ("Rejected", "Reviewed and declined"))
        with self.assertRaises(ValidationError):
            validate_status("Rejected", "  ")

    def test_administrator_password_hash_does_not_expose_password(self):
        password = "sample-password-not-for-storage"
        encoded = hash_password(password)
        self.assertTrue(encoded.startswith("scrypt$"))
        self.assertNotIn(password, encoded)
        _, salt_hex, digest_hex = encoded.split("$")
        self.assertEqual(hash_password(password, bytes.fromhex(salt_hex)), encoded)
        self.assertNotEqual(hash_password("different-password", bytes.fromhex(salt_hex)), encoded)

    @staticmethod
    def request(application, path, method="GET"):
        return FoundationTests.request_environ(application, {"REQUEST_METHOD": method, "PATH_INFO": path})

    @staticmethod
    def request_environ(application, environ_overrides):
        captured = {}
        if isinstance(environ_overrides, dict):
            environ = {"SERVER_NAME": "localhost", "SERVER_PORT": "8000",
                       "wsgi.url_scheme": "http", "wsgi.input": None, **environ_overrides}
        else:
            environ = environ_overrides
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers
        body = b"".join(application(environ, start_response)).decode("utf-8")
        return captured["status"], captured["headers"], body

    @staticmethod
    def _raw_insert(
        connection,
        complaint_id,
        registration_number,
        status="Submitted",
        rejection_reason=None,
    ):
        connection.execute(
            """INSERT INTO complaints (complaint_id, student_name, registration_number,
            title, category, description, location, status, rejection_reason, created_at, modified_at)
            VALUES (?, 'Student', ?, 'Title', 'Other', 'Description', 'Location', ?, ?, 'now', 'now')""",
            (complaint_id, registration_number, status, rejection_reason),
        )

    def _replace_with_legacy_database(self, complaint_ids):
        self.database_path.unlink(missing_ok=True)
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute(
                """CREATE TABLE complaints (
                    complaint_id TEXT PRIMARY KEY,
                    student_name TEXT NOT NULL,
                    registration_number TEXT NOT NULL,
                    title TEXT NOT NULL,
                    category TEXT NOT NULL,
                    description TEXT NOT NULL,
                    location TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rejection_reason TEXT,
                    created_at TEXT NOT NULL,
                    modified_at TEXT NOT NULL
                )"""
            )
            for index, complaint_id in enumerate(complaint_ids):
                connection.execute(
                    """INSERT INTO complaints VALUES (?, 'Legacy Student', 'REG-OLD', 'Legacy title',
                    'Other', 'Legacy description', 'Library', 'Submitted', NULL, '2025-01-01T00:00:00+00:00',
                    '2025-01-01T00:00:00+00:00')""",
                    (complaint_id,),
                )
            connection.commit()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
