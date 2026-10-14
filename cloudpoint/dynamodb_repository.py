"""DynamoDB persistence adapter. It never creates or changes AWS resources."""

from datetime import datetime, timezone
from typing import Any

from .auth import is_password_hash
from .config import Settings
from .pagination import decode_dynamodb_cursor, encode_dynamodb_cursor, normalize_page_size
from .repository import DuplicateAdministratorError, DuplicateComplaintError
from .repository_interface import ComplaintPage
from .validation import (
    STATUSES,
    complaint_id_from_search,
    validate_complaint,
    validate_complaint_id,
    validate_list_filters,
    validate_status,
)


class DynamoDBRepository:
    """Adapter for a pre-existing table with string partition key ``complaint_id``."""

    SEARCH_TITLE_ATTRIBUTE = "search_title"
    SEARCH_REGISTRATION_ATTRIBUTE = "search_registration_number"

    def __init__(self, table: Any):
        self.table = table

    @classmethod
    def from_settings(cls, settings: Settings) -> "DynamoDBRepository":
        if not settings.dynamodb_table:
            raise ValueError("CLOUDPOINT_DYNAMODB_TABLE must be configured for the DynamoDB adapter")
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("Install the optional AWS dependencies to use DynamoDB") from exc
        resource = boto3.resource("dynamodb", region_name=settings.aws_region)
        return cls(resource.Table(settings.dynamodb_table))

    def create_complaint(self, complaint_id: str, values: dict[str, Any]) -> dict[str, Any]:
        complaint_id = validate_complaint_id(complaint_id)
        validated = validate_complaint(values)
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "complaint_id": complaint_id,
            "record_type": "complaint",
            **validated.__dict__,
            "status": "Submitted",
            "rejection_reason": None,
            "created_at": now,
            "modified_at": now,
            self.SEARCH_TITLE_ATTRIBUTE: validated.title.casefold(),
            self.SEARCH_REGISTRATION_ATTRIBUTE: validated.registration_number.casefold(),
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(complaint_id)",
            )
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") == "ConditionalCheckFailedException":
                raise DuplicateComplaintError(complaint_id) from exc
            raise
        return _without_search_fields(item)

    def get_complaint(self, complaint_id: str) -> dict[str, Any] | None:
        complaint_id = validate_complaint_id(complaint_id)
        response = self.table.get_item(
            Key={"complaint_id": complaint_id},
            ConsistentRead=True,
        )
        item = response.get("Item")
        if item is None or item.get("record_type", "complaint") != "complaint":
            return None
        return _without_search_fields(dict(item))

    def list_complaints(
        self,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
        cursor: str | None = None,
        limit: int | str | None = None,
    ) -> ComplaintPage:
        page_size = normalize_page_size(limit)
        exact_id = complaint_id_from_search(search.strip()) if isinstance(search, str) else None
        category, status, normalized_search = validate_list_filters(category, status, search)
        start_key = decode_dynamodb_cursor(cursor)

        if exact_id is not None:
            item = self.get_complaint(exact_id)
            matches = item is not None and _matches(item, category, status)
            return ComplaintPage([_without_search_fields(item)] if matches else [], None)

        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        predicates: list[str] = []
        if category is not None:
            names["#category"] = "category"
            values[":category"] = category
            predicates.append("#category = :category")
        if status is not None:
            names["#status"] = "status"
            values[":status"] = status
            predicates.append("#status = :status")
        if normalized_search:
            names["#title_search"] = self.SEARCH_TITLE_ATTRIBUTE
            names["#registration_search"] = self.SEARCH_REGISTRATION_ATTRIBUTE
            values[":search"] = normalized_search
            predicates.append("(contains(#title_search, :search) OR contains(#registration_search, :search))")
        names["#record_type"] = "record_type"
        values[":complaint_record"] = "complaint"
        predicates.append("(attribute_not_exists(#record_type) OR #record_type = :complaint_record)")

        request: dict[str, Any] = {"Limit": page_size}
        if start_key is not None:
            request["ExclusiveStartKey"] = start_key
        if predicates:
            request["FilterExpression"] = " AND ".join(predicates)
            request["ExpressionAttributeNames"] = names
            request["ExpressionAttributeValues"] = values
        response = self.table.scan(**request)
        items = [_without_search_fields(item) for item in response.get("Items", [])]
        next_cursor = encode_dynamodb_cursor(response.get("LastEvaluatedKey"))
        return ComplaintPage(items, next_cursor)

    def dashboard_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        total = 0
        start_key: dict[str, Any] | None = None
        while True:
            request: dict[str, Any] = {
                "ConsistentRead": True,
                "ProjectionExpression": "#complaint_id, #status, #record_type",
                "ExpressionAttributeNames": {
                    "#complaint_id": "complaint_id", "#status": "status", "#record_type": "record_type"
                },
                "FilterExpression": "(attribute_not_exists(#record_type) OR #record_type = :complaint_record)",
                "ExpressionAttributeValues": {":complaint_record": "complaint"},
            }
            if start_key is not None:
                request["ExclusiveStartKey"] = start_key
            response = self.table.scan(**request)
            for item in response.get("Items", []):
                if item.get("record_type", "complaint") != "complaint":
                    continue
                status = item.get("status")
                if status not in counts:
                    raise RuntimeError("DynamoDB contains a complaint with an unsupported status")
                total += 1
                counts[status] += 1
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        return {"total": total, **counts}

    def add_administrator(self, username: str, password_hash: str) -> None:
        username = _normalize_username(username)
        if not is_password_hash(password_hash):
            raise ValueError("Administrator password must be stored as a supported password hash")
        item = {
            "complaint_id": "ADMIN#" + username,
            "record_type": "administrator",
            "username": username,
            "password_hash": password_hash,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(complaint_id)")
        except Exception as exc:
            error = getattr(exc, "response", {}).get("Error", {})
            if error.get("Code") == "ConditionalCheckFailedException":
                raise DuplicateAdministratorError(username) from exc
            raise

    def get_administrator(self, username: str) -> dict[str, str] | None:
        username = _normalize_username(username)
        response = self.table.get_item(Key={"complaint_id": "ADMIN#" + username}, ConsistentRead=True)
        item = response.get("Item")
        if item is None or item.get("record_type") != "administrator":
            return None
        return {"username": item["username"], "password_hash": item["password_hash"]}

    def create_admin_session(self, token_digest: str, username: str, expires_at: int) -> None:
        self.table.put_item(Item={
            "complaint_id": "SESSION#" + token_digest,
            "record_type": "admin_session",
            "username": _normalize_username(username),
            "expires_at": expires_at,
        }, ConditionExpression="attribute_not_exists(complaint_id)")

    def get_admin_session(self, token_digest: str) -> dict[str, Any] | None:
        key = "SESSION#" + token_digest
        response = self.table.get_item(Key={"complaint_id": key}, ConsistentRead=True)
        item = response.get("Item")
        if item is None or item.get("record_type") != "admin_session":
            return None
        return {"username": item["username"], "expires_at": int(item["expires_at"])}

    def delete_admin_session(self, token_digest: str) -> None:
        self.table.delete_item(Key={"complaint_id": "SESSION#" + token_digest})

    def update_complaint_status(
        self, complaint_id: str, status: str, rejection_reason: str | None
    ) -> dict[str, Any] | None:
        complaint_id = validate_complaint_id(complaint_id)
        status, rejection_reason = validate_status(status, rejection_reason)
        record = self.get_complaint(complaint_id)
        if record is None:
            return None
        now = datetime.now(timezone.utc).isoformat()
        try:
            request: dict[str, Any] = {
                "Key": {"complaint_id": complaint_id},
                "UpdateExpression": "SET #status = :status, rejection_reason = :reason, modified_at = :modified",
                "ConditionExpression": "attribute_exists(complaint_id) AND modified_at = :previous",
                "ExpressionAttributeNames": {"#status": "status"},
                "ExpressionAttributeValues": {
                    ":status": status,
                    ":reason": rejection_reason,
                    ":modified": now,
                    ":previous": record["modified_at"],
                },
                "ReturnValues": "ALL_NEW",
            }
            response = self.table.update_item(**request)
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise RuntimeError("Complaint changed during update") from exc
            raise
        item = response.get("Attributes")
        return _without_search_fields(dict(item)) if item is not None else None


def _matches(item: dict[str, Any], category: str | None, status: str | None) -> bool:
    return (category is None or item.get("category") == category) and (
        status is None or item.get("status") == status
    )


def _without_search_fields(item: dict[str, Any] | None) -> dict[str, Any]:
    if item is None:
        return {}
    return {
        key: value
        for key, value in item.items()
        if key not in {
            DynamoDBRepository.SEARCH_TITLE_ATTRIBUTE,
            DynamoDBRepository.SEARCH_REGISTRATION_ATTRIBUTE,
            "record_type",
        }
    }


def _normalize_username(username: str) -> str:
    if not isinstance(username, str) or not username.strip() or len(username.strip()) > 120:
        raise ValueError("Administrator username must contain 1 to 120 characters")
    return username.strip().casefold()
