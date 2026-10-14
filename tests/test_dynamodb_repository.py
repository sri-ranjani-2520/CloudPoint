import io
import json
import unittest
from pathlib import Path

from cloudpoint.app import create_app
from cloudpoint.config import Settings
from cloudpoint.dynamodb_repository import DynamoDBRepository
from cloudpoint.pagination import decode_cursor, decode_dynamodb_cursor, encode_dynamodb_cursor
from cloudpoint.repository import DuplicateComplaintError
from cloudpoint.validation import ValidationError, generate_complaint_id
from tools.create_admin import hash_password


VALID_COMPLAINT = {
    "student_name": "Example Student",
    "registration_number": "REG-1001",
    "title": "Broken corridor light",
    "category": "Infrastructure",
    "description": "A light in the north corridor is broken.",
    "location": "North Block",
}


class ConditionalFailure(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeDynamoTable:
    """Small in-memory stand-in for Table calls; no AWS SDK or credentials required."""

    def __init__(self):
        self.items = {}
        self.calls = []

    def put_item(self, Item, ConditionExpression):
        self.calls.append(("put_item", {"ConditionExpression": ConditionExpression}))
        if Item["complaint_id"] in self.items:
            raise ConditionalFailure()
        self.items[Item["complaint_id"]] = dict(Item)

    def get_item(self, Key, ConsistentRead):
        self.calls.append(("get_item", {"ConsistentRead": ConsistentRead}))
        item = self.items.get(Key["complaint_id"])
        return {"Item": dict(item)} if item else {}

    def delete_item(self, Key):
        self.calls.append(("delete_item", {"Key": Key}))
        self.items.pop(Key["complaint_id"], None)

    def update_item(self, **request):
        key = request["Key"]["complaint_id"]
        item = self.items.get(key)
        if item is None or item.get("modified_at") != request["ExpressionAttributeValues"][":previous"]:
            raise ConditionalFailure()
        values = request["ExpressionAttributeValues"]
        item.update({
            "status": values[":status"],
            "rejection_reason": values[":reason"],
            "modified_at": values[":modified"],
        })
        self.calls.append(("update_item", request))
        return {"Attributes": dict(item)}

    def scan(self, **request):
        self.calls.append(("scan", request))
        items = [self.items[key] for key in sorted(self.items)]
        start_key = request.get("ExclusiveStartKey")
        if start_key:
            items = [item for item in items if item["complaint_id"] > start_key["complaint_id"]]
        page_limit = request.get("Limit", 2)
        evaluated = items[:page_limit]
        has_more = len(items) > page_limit
        names = request.get("ExpressionAttributeNames", {})
        values = request.get("ExpressionAttributeValues", {})
        selected = [item for item in evaluated if self._matches(item, names, values)]
        response = {"Items": [dict(item) for item in selected]}
        if has_more and evaluated:
            response["LastEvaluatedKey"] = {"complaint_id": evaluated[-1]["complaint_id"]}
        projection = request.get("ProjectionExpression")
        if projection:
            keys = [names.get(part.strip(), part.strip()) for part in projection.split(",")]
            response["Items"] = [{key: item[key] for key in keys if key in item} for item in response["Items"]]
        return response

    @staticmethod
    def _matches(item, names, values):
        category = values.get(":category")
        status = values.get(":status")
        search = values.get(":search")
        return (
            item.get("record_type", "complaint") == "complaint"
            and
            (category is None or item["category"] == category)
            and (status is None or item["status"] == status)
            and (
                search is None
                or search in item.get("search_title", "")
                or search in item.get("search_registration_number", "")
            )
        )


class DynamoDBRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeDynamoTable()
        self.repository = DynamoDBRepository(self.table)

    def test_create_and_read_use_conditional_write_and_validated_consistent_get(self):
        complaint_id = generate_complaint_id()
        record = self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        self.assertEqual(record["status"], "Submitted")
        self.assertNotIn("search_title", self.repository.get_complaint(complaint_id))
        self.assertEqual(self.table.calls[0][1]["ConditionExpression"], "attribute_not_exists(complaint_id)")
        self.assertTrue(self.table.calls[1][1]["ConsistentRead"])
        self.assertIsNone(self.repository.get_complaint("CP-does-not-exist-000"))

    def test_invalid_read_and_write_ids_are_rejected_before_table_calls(self):
        for invalid_id in (None, "", "  ", "bad", "CP-invalid!"):
            with self.subTest(invalid_id=invalid_id):
                with self.assertRaises(ValidationError):
                    self.repository.get_complaint(invalid_id)
                with self.assertRaises(ValidationError):
                    self.repository.create_complaint(invalid_id, VALID_COMPLAINT)
        self.assertEqual(self.table.calls, [])

    def test_duplicate_conditional_write_is_a_controlled_error(self):
        complaint_id = generate_complaint_id()
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        with self.assertRaises(DuplicateComplaintError):
            self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        self.assertEqual(len(self.table.items), 1)

    def test_filtered_scan_paginates_and_returns_opaque_cursor(self):
        for number in range(1, 6):
            self.repository.create_complaint(f"CP-{number:016d}", VALID_COMPLAINT)
        first_page = self.repository.list_complaints(
            category="Infrastructure", status="Submitted", search="CORRIDOR", limit=2
        )
        self.assertEqual(len(first_page.items), 2)
        self.assertIsNotNone(first_page.next_cursor)
        self.assertIsNotNone(decode_cursor(first_page.next_cursor))
        scan_request = [call[1] for call in self.table.calls if call[0] == "scan"][0]
        self.assertEqual(scan_request["Limit"], 2)
        self.assertIn("category", scan_request["ExpressionAttributeNames"].values())
        second_page = self.repository.list_complaints(
            category="Infrastructure",
            status="Submitted",
            search="corridor",
            limit=2,
            cursor=first_page.next_cursor,
        )
        self.assertEqual(len(second_page.items), 2)
        self.assertNotEqual(first_page.items[0]["complaint_id"], second_page.items[0]["complaint_id"])

    def test_dynamodb_cursor_preserves_internal_partition_keys_between_scan_pages(self):
        self.repository.add_administrator("admin", hash_password("a valid test password"))
        self.repository.create_admin_session("a" * 64, "admin", 9_999_999_999)
        self.table.items["ZZZ#sentinel"] = {
            "complaint_id": "ZZZ#sentinel",
            "record_type": "internal",
        }
        for number in range(1, 3):
            self.repository.create_complaint(f"CP-{number:016d}", VALID_COMPLAINT)

        cursor = None
        complaint_ids = []
        cursors = []
        for _ in range(8):
            page = self.repository.list_complaints(limit=1, cursor=cursor)
            complaint_ids.extend(item["complaint_id"] for item in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break
            cursors.append(decode_dynamodb_cursor(cursor)["complaint_id"])

        self.assertEqual(complaint_ids, ["CP-0000000000000001", "CP-0000000000000002"])
        self.assertIn("ADMIN#admin", cursors)
        self.assertIn("SESSION#" + "a" * 64, cursors)
        self.assertIsNone(encode_dynamodb_cursor(None))

    def test_exact_id_search_uses_direct_read_and_filter_combinations(self):
        complaint_id = "CP-abcdefghijklmnop"
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        page = self.repository.list_complaints(
            search=complaint_id.lower(), category="Infrastructure", status="Submitted"
        )
        self.assertEqual([item["complaint_id"] for item in page.items], [complaint_id])
        self.assertEqual(self.table.calls[-1][0], "get_item")

    def test_search_text_is_passed_as_an_expression_value(self):
        search = "x' OR attribute_exists(complaint_id)"
        self.repository.list_complaints(search=search)
        request = [call[1] for call in self.table.calls if call[0] == "scan"][0]
        self.assertNotIn(search, request["FilterExpression"])
        self.assertEqual(request["ExpressionAttributeValues"][":search"], search.casefold())

    def test_dashboard_counts_scan_every_page(self):
        for number in range(1, 6):
            self.repository.create_complaint(f"CP-{number:016d}", VALID_COMPLAINT)
        counts = self.repository.dashboard_counts()
        self.assertEqual(counts["total"], 5)
        self.assertEqual(counts["Submitted"], 5)
        self.assertEqual(counts["total"], sum(counts[status] for status in (
            "Submitted", "Under Review", "In Progress", "Resolved", "Rejected"
        )))
        self.assertEqual(len([call for call in self.table.calls if call[0] == "scan"]), 3)

    def test_dashboard_counts_each_current_status_and_excludes_internal_records(self):
        statuses = ("Submitted", "Under Review", "In Progress", "Resolved", "Rejected")
        for number, status in enumerate(statuses, start=1):
            complaint_id = f"CP-{number:016d}"
            self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
            if status == "Rejected":
                self.repository.update_complaint_status(complaint_id, status, "Reviewed and declined.")
            elif status != "Submitted":
                self.repository.update_complaint_status(complaint_id, status, None)
        self.repository.add_administrator("admin", hash_password("a valid test password"))
        self.repository.create_admin_session("a" * 64, "admin", 9_999_999_999)
        self.table.calls.clear()

        counts = self.repository.dashboard_counts()

        self.assertEqual(counts["total"], 5)
        self.assertEqual([counts[status] for status in statuses], [1, 1, 1, 1, 1])
        self.assertEqual(counts["total"], sum(counts[status] for status in statuses))
        scans = [request for operation, request in self.table.calls if operation == "scan"]
        self.assertGreater(len(scans), 1)
        self.assertTrue(all(request["ConsistentRead"] is True for request in scans))

    def test_invalid_filters_cursor_and_page_sizes_fail_validation(self):
        for kwargs in (
            {"category": "not-a-category"},
            {"status": "not-a-status"},
            {"cursor": "invalid"},
            {"limit": 0},
            {"limit": 101},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError):
                    self.repository.list_complaints(**kwargs)

    def test_adapter_requires_an_explicit_table_name(self):
        with self.assertRaisesRegex(ValueError, "CLOUDPOINT_DYNAMODB_TABLE"):
            DynamoDBRepository.from_settings(Settings(Path("unused.sqlite3")))

    def test_admin_records_sessions_status_updates_and_counts_share_table_safely(self):
        self.repository.add_administrator("Admin", hash_password("secret"))
        self.assertEqual(self.repository.get_administrator("ADMIN")["username"], "admin")
        self.repository.create_admin_session("a" * 64, "admin", 9999999999)
        self.assertEqual(self.repository.get_admin_session("a" * 64)["username"], "admin")
        complaint_id = "CP-abcdefghijklmnop"
        created = self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        updated = self.repository.update_complaint_status(complaint_id, "Rejected", "Not in scope")
        self.assertEqual(updated["status"], "Rejected")
        self.assertEqual(updated["created_at"], created["created_at"])
        self.assertEqual(self.repository.dashboard_counts()["total"], 1)
        page = self.repository.list_complaints()
        self.assertEqual([item["complaint_id"] for item in page.items], [complaint_id])
        self.repository.delete_admin_session("a" * 64)
        self.assertIsNone(self.repository.get_admin_session("a" * 64))

    def test_admin_repository_rejects_plaintext_passwords_and_invalid_status_writes(self):
        with self.assertRaises(ValueError):
            self.repository.add_administrator("admin", "plain-text-password")
        self.repository.create_complaint("CP-abcdefghijklmnop", VALID_COMPLAINT)
        for status, reason in (("invalid", None), ("Rejected", " ")):
            with self.subTest(status=status, reason=reason):
                with self.assertRaises(ValidationError):
                    self.repository.update_complaint_status("CP-abcdefghijklmnop", status, reason)

    def test_protected_admin_http_workflow_uses_dynamodb_repository_contract(self):
        self.repository.add_administrator("admin", hash_password("a valid test password"))
        complaint_id = "CP-abcdefghijklmnop"
        self.repository.create_complaint(complaint_id, VALID_COMPLAINT)
        app = create_app(
            Settings(Path("unused.sqlite3"), session_secret="dynamodb-test-session-secret-" + "x" * 32),
            repository=self.repository,
        )
        status, _, body = self._request(app, "POST", "/api/admin/login", {
            "username": "admin", "password": "a valid test password"
        })
        self.assertEqual(status, "200 OK")
        token = json.loads(body)["access_token"]
        status, _, body = self._request(
            app, "PATCH", f"/api/admin/complaints/{complaint_id}/status",
            {"status": "In Progress"}, token=token,
        )
        self.assertEqual(status, "200 OK")
        status, _, body = self._request(
            app, "GET", f"/api/complaints/{complaint_id}"
        )
        self.assertEqual(status, "200 OK")
        self.assertEqual(json.loads(body)["status"], "In Progress")

    @staticmethod
    def _request(app, method, path, data=None, token=None):
        payload = json.dumps(data).encode("utf-8") if data is not None else b""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path,
            "QUERY_STRING": "",
            "CONTENT_TYPE": "application/json",
            "CONTENT_LENGTH": str(len(payload)),
            "wsgi.input": io.BytesIO(payload),
        }
        if token:
            environ["HTTP_AUTHORIZATION"] = "Bearer " + token
        captured = {}

        def start_response(status, headers):
            captured["status"] = status

        body = b"".join(app(environ, start_response)).decode("utf-8")
        return captured["status"], [], body


if __name__ == "__main__":
    unittest.main()
