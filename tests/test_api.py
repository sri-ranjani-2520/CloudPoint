import base64
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from cloudpoint.app import create_app
from cloudpoint.config import PROJECT_ROOT, Settings
from cloudpoint import lambda_adapter
from cloudpoint.lambda_adapter import _read_session_secret, api_gateway_v2_adapter, create_lambda_handler
from cloudpoint.repository import Repository
from tools.create_admin import hash_password


VALID_COMPLAINT = {
    "student_name": "Example Student",
    "registration_number": "REG-1001",
    "title": "Broken light",
    "category": "Infrastructure",
    "description": "A corridor light is not working.",
    "location": "North Block",
}


class ComplaintApiTests(unittest.TestCase):
    def setUp(self):
        descriptor, database_path = tempfile.mkstemp(
            prefix=".test-cloudpoint-api-", suffix=".sqlite3", dir=PROJECT_ROOT
        )
        os.close(descriptor)
        self.database_path = Path(database_path)
        self.repository = Repository(self.database_path)
        self.repository.initialize()
        self.repository.add_administrator("admin", hash_password("correct horse battery"))
        self.application = create_app(
            Settings(self.database_path, session_secret="unit-test-session-secret-" + "x" * 32),
            repository=self.repository,
        )

    def tearDown(self):
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)

    def test_student_submit_and_track_contract_hides_student_identifiers(self):
        status, _, body = self.request("POST", "/api/complaints", VALID_COMPLAINT)
        self.assertEqual(status, "201 Created")
        confirmation = json.loads(body)
        self.assertEqual(confirmation["message"], "Complaint submitted successfully.")
        complaint_id = confirmation["complaint_id"]

        status, _, body = self.request("GET", f"/api/complaints/{complaint_id}")
        self.assertEqual(status, "200 OK")
        tracking = json.loads(body)
        self.assertEqual(tracking["complaint_id"], complaint_id)
        self.assertEqual(tracking["status"], "Submitted")
        self.assertEqual(tracking["title"], "Broken light")
        self.assertNotIn("student_name", tracking)
        self.assertNotIn("registration_number", tracking)

    def test_invalid_submission_unknown_complaint_and_invalid_tracking_id(self):
        status, _, body = self.request("POST", "/api/complaints", {**VALID_COMPLAINT, "category": "Unknown"})
        self.assertEqual(status, "400 Bad Request")
        error = json.loads(body)["error"]
        self.assertEqual(error["code"], "validation_error")
        self.assertNotIn("Unknown", body)
        self.assertEqual(self.repository.dashboard_counts()["total"], 0)

        status, _, body = self.request("GET", "/api/complaints/CP-abcdefghijklmnop")
        self.assertEqual(status, "404 Not Found")
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")
        status, _, _ = self.request("GET", "/api/complaints/bad")
        self.assertEqual(status, "400 Bad Request")

    def test_submission_content_type_json_shape_and_size_errors(self):
        status, _, _ = self.request("POST", "/api/complaints", VALID_COMPLAINT, content_type="text/plain")
        self.assertEqual(status, "415 Unsupported Media Type")
        status, _, _ = self.request("POST", "/api/complaints", body=b"[]")
        self.assertEqual(status, "400 Bad Request")
        status, _, _ = self.request("POST", "/api/complaints", body=b"{broken-json")
        self.assertEqual(status, "400 Bad Request")
        status, _, body = self.request("POST", "/api/complaints", body=b"x" * 16_385)
        self.assertTrue(status.startswith("413 "))
        self.assertNotIn(str(self.database_path.parent), body)

    def test_collection_method_contract(self):
        status, headers, _ = self.request("GET", "/api/complaints")
        self.assertEqual(status, "405 Method Not Allowed")
        self.assertIn(("Allow", "POST"), headers)

    def test_invalid_request_id_is_replaced_with_a_log_safe_identifier(self):
        status, headers, _ = self.request("GET", "/health", request_id="bad\r\nX-Injected: yes")
        self.assertEqual(status, "200 OK")
        request_id = dict(headers)["X-Request-Id"]
        self.assertRegex(request_id, re.compile(r"^[a-f0-9]{32}$"))

    def test_admin_routes_require_authentication(self):
        complaint_id = "CP-abcdefghijklmnop"
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        protected = [
            ("GET", "/api/admin/dashboard", None),
            ("GET", "/api/admin/complaints", None),
            ("GET", f"/api/admin/complaints/{complaint_id}", None),
            ("PATCH", f"/api/admin/complaints/{complaint_id}/status", {"status": "Resolved"}),
            ("POST", "/api/admin/logout", None),
        ]
        for method, path, data in protected:
            with self.subTest(method=method, path=path):
                status, _, body = self.request(method, path, data)
                self.assertEqual(status, "401 Unauthorized")
                self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")

    def test_direct_admin_api_rejects_forged_bearer_token_on_every_protected_route(self):
        complaint_id = "CP-abcdefghijklmnop"
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        forged_headers = {"Authorization": "Bearer " + "x" * 90}
        protected = [
            ("POST", "/api/admin/logout", None),
            ("GET", "/api/admin/dashboard", None),
            ("GET", "/api/admin/complaints", None),
            ("GET", f"/api/admin/complaints/{complaint_id}", None),
            ("PATCH", f"/api/admin/complaints/{complaint_id}/status", {"status": "Resolved"}),
        ]
        for method, path, data in protected:
            with self.subTest(method=method, path=path):
                status, headers, body = self.request(method, path, data, headers=forged_headers)
                self.assertEqual(status, "401 Unauthorized")
                self.assertIn(("WWW-Authenticate", "Bearer"), headers)
                self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")
        self.assertEqual(self.repository.get_complaint(complaint_id)["status"], "Submitted")

    def test_tracking_disclosure_is_limited_even_after_rejection(self):
        complaint_id = "CP-abcdefghijklmnop"
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        self.repository.update_complaint_status(complaint_id, "Rejected", "Not eligible for this process.")
        status, _, body = self.request("GET", f"/api/complaints/{complaint_id}")
        self.assertEqual(status, "200 OK")
        tracking = json.loads(body)
        self.assertEqual(
            set(tracking),
            {"complaint_id", "title", "category", "description", "location", "status", "created_at", "rejection_reason"},
        )
        self.assertNotIn("Example Student", body)
        self.assertNotIn("REG-1001", body)
        self.assertNotIn("modified_at", tracking)

    def test_dashboard_counts_current_statuses_and_returns_request_id(self):
        statuses = ("Submitted", "Under Review", "In Progress", "Resolved", "Rejected")
        ids = [f"CP-{number:016d}" for number in range(1, 6)]
        for complaint_id, status in zip(ids, statuses):
            self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
            if status == "Rejected":
                self.repository.update_complaint_status(complaint_id, status, "Reviewed and declined.")
            elif status != "Submitted":
                self.repository.update_complaint_status(complaint_id, status, None)

        token = self.login_token()
        request_id = "dashboard-request-2026-01"
        status, headers, body = self.request(
            "GET", "/api/admin/dashboard", headers={"Authorization": "Bearer " + token}, request_id=request_id
        )
        self.assertEqual(status, "200 OK")
        self.assertIn(("X-Request-Id", request_id), headers)
        counts = json.loads(body)
        self.assertEqual(counts["total"], 5)
        self.assertEqual([counts[current] for current in statuses], [1, 1, 1, 1, 1])
        self.assertEqual(counts["total"], sum(counts[current] for current in statuses))

    def test_local_acceptance_student_to_admin_to_student_lifecycle(self):
        status, submission_headers, body = self.request(
            "POST", "/api/complaints", VALID_COMPLAINT, request_id="acceptance-submit-01"
        )
        self.assertEqual(status, "201 Created")
        self.assertIn(("X-Request-Id", "acceptance-submit-01"), submission_headers)
        complaint_id = json.loads(body)["complaint_id"]
        self.assertEqual(self.repository.dashboard_counts()["total"], 1)

        status, _, body = self.request("GET", f"/api/complaints/{complaint_id}")
        self.assertEqual(status, "200 OK")
        tracking = json.loads(body)
        self.assertEqual(tracking["status"], "Submitted")
        self.assertNotIn("student_name", tracking)
        self.assertNotIn("registration_number", tracking)

        token = self.login_token()
        auth = {"Authorization": "Bearer " + token}
        status, _, body = self.request("GET", "/api/admin/dashboard", headers=auth)
        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body)["Submitted"], 1)
        status, _, body = self.request("GET", "/api/admin/complaints?status=Submitted&limit=1", headers=auth)
        self.assertEqual(status, "200 OK")
        page = json.loads(body)
        self.assertEqual([item["complaint_id"] for item in page["items"]], [complaint_id])
        status, _, body = self.request("GET", f"/api/admin/complaints/{complaint_id}", headers=auth)
        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body)["student_name"], "Example Student")

        status, update_headers, body = self.request(
            "PATCH", f"/api/admin/complaints/{complaint_id}/status",
            {"status": "Rejected", "rejection_reason": "Reviewed and declined."},
            headers=auth, request_id="acceptance-update-01",
        )
        self.assertEqual(status, "200 OK")
        self.assertIn(("X-Request-Id", "acceptance-update-01"), update_headers)
        self.assertEqual(json.loads(body)["status"], "Rejected")

        status, _, body = self.request("GET", "/api/admin/dashboard", headers=auth)
        counts = json.loads(body)
        self.assertEqual(status, "200 OK")
        self.assertEqual(counts["Rejected"], 1)
        self.assertEqual(counts["total"], sum(counts[key] for key in (
            "Submitted", "Under Review", "In Progress", "Resolved", "Rejected"
        )))
        status, _, body = self.request("GET", f"/api/complaints/{complaint_id}")
        tracking = json.loads(body)
        self.assertEqual(status, "200 OK")
        self.assertEqual(tracking["status"], "Rejected")
        self.assertEqual(tracking["rejection_reason"], "Reviewed and declined.")
        self.assertNotIn("student_name", tracking)
        self.assertNotIn("registration_number", tracking)

        status, _, _ = self.request("POST", "/api/admin/logout", headers=auth)
        self.assertEqual(status, "200 OK")
        status, _, _ = self.request("GET", "/api/admin/dashboard", headers=auth)
        self.assertEqual(status, "401 Unauthorized")

    def test_failure_logs_are_correlated_structured_and_do_not_include_submitted_data(self):
        request_id = "submission-failure-01"
        secret_marker = "student-private-details credential-token signing-secret"

        def fail_insert(complaint_id, values):
            raise RuntimeError(secret_marker)

        self.repository.create_complaint = fail_insert
        sensitive_payload = {**VALID_COMPLAINT, "student_name": secret_marker, "description": secret_marker}
        with self.assertLogs("cloudpoint", level="ERROR") as captured:
            status, headers, body = self.request(
                "POST", "/api/complaints", sensitive_payload, request_id=request_id
            )
        self.assertEqual(status, "500 Internal Server Error")
        self.assertIn(("X-Request-Id", request_id), headers)
        self.assertNotIn(secret_marker, body)
        self.assertEqual(len(captured.records), 1)
        event = {
            key: getattr(captured.records[0], key)
            for key in ("event", "request_id", "operation", "error_type")
        }
        self.assertEqual(event, {
            "event": "operation_failed",
            "request_id": request_id,
            "operation": "complaint_submission",
            "error_type": "RuntimeError",
        })

    def test_status_update_failure_log_contains_only_safe_correlation_metadata(self):
        complaint_id = "CP-abcdefghijklmnop"
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        token = self.login_token()
        secret_marker = "student-private-details bearer-secret rejection-text"

        def fail_update(*args, **kwargs):
            raise OSError(secret_marker)

        self.repository.update_complaint_status = fail_update
        request_id = "status-update-failure-02"
        with self.assertLogs("cloudpoint", level="ERROR") as captured:
            status, headers, body = self.request(
                "PATCH",
                f"/api/admin/complaints/{complaint_id}/status",
                {"status": "Resolved"},
                headers={"Authorization": "Bearer " + token},
                request_id=request_id,
            )
        self.assertEqual(status, "500 Internal Server Error")
        self.assertIn(("X-Request-Id", request_id), headers)
        self.assertNotIn(secret_marker, body)
        self.assertNotIn(secret_marker, "\n".join(captured.output))
        self.assertNotIn(token, "\n".join(captured.output))
        event = {
            key: getattr(captured.records[0], key)
            for key in ("event", "request_id", "operation", "error_type")
        }
        self.assertEqual(event["request_id"], request_id)
        self.assertEqual(event["operation"], "complaint_status_update")
        self.assertEqual(event["error_type"], "OSError")

    def test_unknown_admin_route_remains_not_found(self):
        status, _, body = self.request("GET", "/api/admin/complaints")
        self.assertEqual(status, "401 Unauthorized")
        status, _, body = self.request("GET", "/api/admin/not-a-route")
        self.assertEqual(status, "404 Not Found")
        self.assertEqual(json.loads(body)["error"]["code"], "not_found")

    def test_admin_login_rejects_invalid_credentials_and_logout_revokes_token(self):
        status, _, body = self.request("POST", "/api/admin/login", {"username": "admin", "password": "wrong"})
        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(json.loads(body)["error"]["code"], "authentication_failed")
        status, _, body = self.request("POST", "/api/admin/login", {"username": "admin", "password": "correct horse battery"})
        self.assertEqual(status, "200 OK")
        session = json.loads(body)
        token = session["access_token"]
        self.assertEqual(session["token_type"], "Bearer")
        self.assertNotIn("password_hash", body)
        self.assertNotIn("correct horse battery", body)
        with self.repository._connection() as connection:
            rows = connection.execute("SELECT token_digest FROM admin_sessions").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertNotEqual(rows[0]["token_digest"], token)
        headers = {"Authorization": "Bearer " + token}
        status, _, _ = self.request("POST", "/api/admin/logout", headers=headers)
        self.assertEqual(status, "200 OK")
        status, _, body = self.request("GET", "/api/admin/dashboard", headers=headers)
        self.assertEqual(status, "401 Unauthorized")
        self.assertEqual(json.loads(body)["error"]["code"], "unauthorized")
        status, _, _ = self.request("GET", "/api/admin/dashboard", headers={"Authorization": "Bearer " + token + "x"})
        self.assertEqual(status, "401 Unauthorized")

    def test_expired_admin_session_is_rejected_and_deleted(self):
        token = self.login_token()
        headers = {"Authorization": "Bearer " + token}
        with self.repository._connection() as connection:
            connection.execute("UPDATE admin_sessions SET expires_at = 1")
        status, _, _ = self.request("GET", "/api/admin/dashboard", headers=headers)
        self.assertEqual(status, "401 Unauthorized")
        with self.repository._connection() as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM admin_sessions").fetchone()[0], 0)

    def test_admin_listing_filters_pagination_details_and_status_updates(self):
        ids = ["CP-abcdefghijklmnop", "CP-qrstuvwxyzABCDEF", "CP-1234567890ABCDEF"]
        for index, complaint_id in enumerate(ids):
            values = {**VALID_COMPLAINT, "title": f"Broken light {index}", "registration_number": f"REG-{index}"}
            self.repository.create_complaint(complaint_id, values)
        token = self.login_token()
        headers = {"Authorization": "Bearer " + token}

        status, _, body = self.request("GET", "/api/admin/complaints?category=Infrastructure&status=Submitted&search=broken&limit=2", headers=headers)
        self.assertEqual(status, "200 OK")
        first_page = json.loads(body)
        self.assertEqual(len(first_page["items"]), 2)
        self.assertIsNotNone(first_page["next_cursor"])
        self.assertIn("registration_number", first_page["items"][0])
        self.assertNotIn("description", first_page["items"][0])
        cursor = first_page["next_cursor"]
        status, _, body = self.request("GET", "/api/admin/complaints?category=Infrastructure&status=Submitted&search=broken&limit=2&cursor=" + cursor, headers=headers)
        self.assertEqual(status, "200 OK")
        self.assertEqual(len(json.loads(body)["items"]), 1)

        complaint_id = ids[0]
        status, _, detail = self.request("GET", f"/api/admin/complaints/{complaint_id}", headers=headers)
        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(detail)["registration_number"], "REG-0")
        status, _, body = self.request("PATCH", f"/api/admin/complaints/{complaint_id}/status", {"status": "Rejected", "rejection_reason": "Reviewed and declined."}, headers=headers)
        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body)["status"], "Rejected")
        status, _, body = self.request("GET", "/api/admin/dashboard", headers=headers)
        counts = json.loads(body)
        self.assertEqual(counts["Rejected"], 1)
        self.assertEqual(counts["total"], sum(counts[key] for key in ("Submitted", "Under Review", "In Progress", "Resolved", "Rejected")))
        status, _, tracked = self.request("GET", f"/api/complaints/{complaint_id}")
        tracking = json.loads(tracked)
        self.assertEqual(tracking["status"], "Rejected")
        self.assertEqual(tracking["rejection_reason"], "Reviewed and declined.")
        self.assertNotIn("registration_number", tracking)
        self.assertNotIn("student_name", tracking)

    def test_admin_status_validation_and_unknown_complaint(self):
        complaint_id = "CP-abcdefghijklmnop"
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        headers = {"Authorization": "Bearer " + self.login_token()}
        for data in ({"status": "Rejected"}, {"status": "bad"}, {"status": "Resolved", "extra": True}):
            status, _, body = self.request("PATCH", f"/api/admin/complaints/{complaint_id}/status", data, headers=headers)
            self.assertEqual(status, "400 Bad Request")
            self.assertEqual(json.loads(body)["error"]["code"], "validation_error" if "extra" not in data else "invalid_request")
        self.assertEqual(self.repository.get_complaint(complaint_id)["status"], "Submitted")
        status, _, _ = self.request("GET", "/api/admin/complaints/CP-qrstuvwxyzABCDEF", headers=headers)
        self.assertEqual(status, "404 Not Found")

    def test_admin_storage_failure_is_a_generic_error(self):
        token = self.login_token()
        self.repository.dashboard_counts = lambda: (_ for _ in ()).throw(RuntimeError("private details"))
        status, _, body = self.request("GET", "/api/admin/dashboard", headers={"Authorization": "Bearer " + token})
        self.assertEqual(status, "500 Internal Server Error")
        self.assertNotIn("private details", body)

    def test_storage_exception_is_not_disclosed_in_api_response(self):
        def fail_create(complaint_id, values):
            raise RuntimeError("internal-path-and-student-data-must-not-leak")

        self.repository.create_complaint = fail_create
        status, _, body = self.request("POST", "/api/complaints", VALID_COMPLAINT)
        self.assertEqual(status, "500 Internal Server Error")
        self.assertEqual(json.loads(body)["error"]["code"], "internal_error")
        self.assertNotIn("internal-path-and-student-data-must-not-leak", body)
        self.assertNotIn(str(self.database_path.parent), body)

    def test_lambda_http_api_v2_adapter_translates_request_and_response(self):
        lambda_handler = create_lambda_handler(self.application)
        payload = json.dumps(VALID_COMPLAINT).encode("utf-8")
        event = self.gateway_event(
            "POST",
            "/api/complaints",
            body=base64.b64encode(payload).decode("ascii"),
            is_base64=True,
            headers={"content-type": "application/json"},
            request_id="gateway-request-456",
        )
        response = lambda_handler(event, object())
        self.assertEqual(response["statusCode"], 201)
        self.assertEqual(response["headers"]["x-request-id"], "gateway-request-456")
        self.assertFalse(response["isBase64Encoded"])
        complaint_id = json.loads(response["body"])["complaint_id"]
        tracked = api_gateway_v2_adapter(
            self.application,
            self.gateway_event("GET", f"/api/complaints/{complaint_id}"),
        )
        self.assertEqual(tracked["statusCode"], 200)
        self.assertEqual(json.loads(tracked["body"])["complaint_id"], complaint_id)

    def test_lambda_invocation_id_is_used_when_gateway_request_id_is_unavailable(self):
        handler = create_lambda_handler(self.application)
        event = self.gateway_event("GET", "/health")
        response = handler(event, type("Context", (), {"aws_request_id": "lambda-invocation-789"})())
        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["headers"]["x-request-id"], "lambda-invocation-789")

    def test_lambda_adapter_malformed_event_uses_consistent_error(self):
        response = api_gateway_v2_adapter(self.application, {"rawPath": "/health"})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"]["code"], "invalid_request")

    def test_lambda_base64_flag_is_strict_and_defaults_to_false(self):
        payload = json.dumps(VALID_COMPLAINT).encode("utf-8")
        encoded_event = self.gateway_event(
            "POST", "/api/complaints", body=base64.b64encode(payload).decode("ascii"), is_base64=True,
            headers={"content-type": "application/json"},
        )
        self.assertEqual(api_gateway_v2_adapter(self.application, encoded_event)["statusCode"], 201)
        raw_event = self.gateway_event(
            "POST", "/api/complaints", body=payload.decode("utf-8"), is_base64=False,
            headers={"content-type": "application/json"},
        )
        self.assertEqual(api_gateway_v2_adapter(self.application, raw_event)["statusCode"], 201)
        event = self.gateway_event(
            "POST", "/api/complaints", body=payload.decode("utf-8"),
            headers={"content-type": "application/json"},
        )
        event.pop("isBase64Encoded")
        self.assertEqual(api_gateway_v2_adapter(self.application, event)["statusCode"], 201)
        for value in ("false", "true", 0, 1, None):
            event = self.gateway_event("GET", "/health")
            event["isBase64Encoded"] = value
            response = api_gateway_v2_adapter(self.application, event)
            self.assertEqual(response["statusCode"], 400)
            self.assertEqual(json.loads(response["body"])["error"]["code"], "invalid_request")

    def test_lambda_reads_signing_secret_from_scoped_secret_client(self):
        signing_key = "test-only-signing-secret-value-1234567890"
        calls = []

        class FakeSecretsClient:
            def get_secret_value(self, **kwargs):
                calls.append(kwargs)
                return {"SecretString": signing_key}

        def client_factory(service_name, region_name=None):
            self.assertEqual(service_name, "secretsmanager")
            self.assertEqual(region_name, "ap-south-1")
            return FakeSecretsClient()

        actual = _read_session_secret("arn:aws:secretsmanager:ap-south-1:123456789012:secret:test", "ap-south-1", client_factory)
        self.assertEqual(actual, signing_key)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["SecretId"], "arn:aws:secretsmanager:ap-south-1:123456789012:secret:test")

    def test_lambda_secret_read_failure_is_generic_and_short_secret_rejected(self):
        class FailedSecretsClient:
            def get_secret_value(self, **kwargs):
                raise RuntimeError("secret content must not leak")

        def failed_factory(*args, **kwargs):
            return FailedSecretsClient()

        with self.assertRaisesRegex(RuntimeError, "could not be loaded") as caught:
            _read_session_secret("secret-arn", "ap-south-1", failed_factory)
        self.assertNotIn("secret content", str(caught.exception))

        class ShortSecretsClient:
            def get_secret_value(self, **kwargs):
                return {"SecretString": "too-short"}

        with self.assertRaisesRegex(RuntimeError, "is invalid"):
            _read_session_secret("secret-arn", "ap-south-1", lambda *args, **kwargs: ShortSecretsClient())

        for malformed in ({}, {"SecretString": None}, {"SecretString": 4}, {"SecretString": "too-short"}):
            with self.subTest(secret_response=malformed):
                class MalformedSecretsClient:
                    def get_secret_value(self, **kwargs):
                        return malformed

                with self.assertRaisesRegex(RuntimeError, "is invalid"):
                    _read_session_secret("secret-arn", "ap-south-1", lambda *args, **kwargs: MalformedSecretsClient())

    def test_lambda_secret_value_is_absent_from_initialization_response_and_logs(self):
        leaked_value = "private-secret-value-that-must-not-appear"

        class FailedSecretsClient:
            def get_secret_value(self, **kwargs):
                raise RuntimeError(leaked_value)

        previous = lambda_adapter._cached_handler
        lambda_adapter._cached_handler = None
        try:
            with patch.dict(os.environ, {
                "CLOUDPOINT_SESSION_SECRET_ARN": "arn:example:secret",
                "CLOUDPOINT_DYNAMODB_TABLE": "test-table",
                "CLOUDPOINT_AWS_REGION": "ap-south-1",
            }, clear=False):
                handler = create_lambda_handler(secrets_client_factory=lambda *args, **kwargs: FailedSecretsClient())
                with self.assertLogs("cloudpoint.lambda", level="ERROR") as captured:
                    response = handler(self.gateway_event("GET", "/health"), object())
            self.assertEqual(response["statusCode"], 500)
            self.assertNotIn(leaked_value, response["body"])
            self.assertNotIn(leaked_value, "\n".join(captured.output))
        finally:
            lambda_adapter._cached_handler = previous

    def test_rotated_signing_key_rejects_old_sessions_and_accepts_new_sessions(self):
        old_token = self.login_token()
        original_app = self.application
        self.application = create_app(
            Settings(self.database_path, session_secret="rotated-session-secret-" + "y" * 32),
            repository=self.repository,
        )
        try:
            status, _, _ = self.request("GET", "/api/admin/dashboard", headers={"Authorization": "Bearer " + old_token})
            self.assertEqual(status, "401 Unauthorized")
            new_token = self.login_token()
            status, _, _ = self.request("GET", "/api/admin/dashboard", headers={"Authorization": "Bearer " + new_token})
            self.assertEqual(status, "200 OK")
        finally:
            self.application = original_app

    def request(self, method, path, data=None, *, body=None, content_type="application/json", headers=None, request_id=None):
        if body is None:
            body = json.dumps(data).encode("utf-8") if data is not None else b""
        captured = {}
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path.split("?", 1)[0],
            "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        if request_id is not None:
            environ["cloudpoint.request_id"] = request_id
        environ.update({"HTTP_" + key.upper().replace("-", "_"): value for key, value in (headers or {}).items()})

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        response_body = b"".join(self.application(environ, start_response)).decode("utf-8")
        return captured["status"], captured["headers"], response_body

    def login_token(self):
        status, _, body = self.request("POST", "/api/admin/login", {"username": "admin", "password": "correct horse battery"})
        self.assertEqual(status, "200 OK")
        return json.loads(body)["access_token"]

    @staticmethod
    def gateway_event(method, path, *, body="", is_base64=False, headers=None, request_id=None):
        return {
            "version": "2.0",
            "rawPath": path,
            "rawQueryString": "",
            "headers": headers or {},
            "requestContext": {"requestId": request_id, "http": {"method": method}},
            "body": body,
            "isBase64Encoded": is_base64,
        }


if __name__ == "__main__":
    unittest.main()
