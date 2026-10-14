"""Shared opaque cursors and page-size rules for local and DynamoDB stores."""

import base64
import binascii
import json

from .validation import ValidationError, validate_complaint_id


DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_CURSOR_LENGTH = 512
DYNAMODB_KEY_MAX_LENGTH = 256


def normalize_page_size(value: object) -> int:
    if value is None:
        return DEFAULT_PAGE_SIZE
    if isinstance(value, bool):
        raise ValidationError({"limit": "Page size must be an integer from 1 to 100."})
    try:
        page_size = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"limit": "Page size must be an integer from 1 to 100."}) from exc
    if str(value).strip() != str(page_size) or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValidationError({"limit": "Page size must be an integer from 1 to 100."})
    return page_size


def encode_cursor(key: dict[str, object] | None) -> str | None:
    if not key:
        return None
    complaint_id = validate_complaint_id(key.get("complaint_id"))
    payload = json.dumps({"complaint_id": complaint_id}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(token: object) -> dict[str, str] | None:
    if token is None or token == "":
        return None
    if not isinstance(token, str) or len(token) > MAX_CURSOR_LENGTH:
        raise ValidationError({"cursor": "Pagination cursor is invalid."})
    try:
        padding = "=" * (-len(token) % 4)
        payload = base64.b64decode(token + padding, altchars=b"-_", validate=True)
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict) or set(value) != {"complaint_id"}:
            raise ValueError("Unexpected cursor shape")
        complaint_id = validate_complaint_id(value["complaint_id"])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise ValidationError({"cursor": "Pagination cursor is invalid."}) from exc
    return {"complaint_id": complaint_id}


def encode_dynamodb_cursor(key: dict[str, object] | None) -> str | None:
    """Encode a DynamoDB partition key, including reserved admin/session keys."""
    if not key:
        return None
    if not isinstance(key, dict) or set(key) != {"complaint_id"}:
        raise ValidationError({"cursor": "Pagination cursor is invalid."})
    partition_key = _validate_dynamodb_partition_key(key["complaint_id"])
    payload = json.dumps({"complaint_id": partition_key}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_dynamodb_cursor(token: object) -> dict[str, str] | None:
    """Decode a cursor without assuming every table key identifies a complaint."""
    if token is None or token == "":
        return None
    if not isinstance(token, str) or len(token) > MAX_CURSOR_LENGTH:
        raise ValidationError({"cursor": "Pagination cursor is invalid."})
    try:
        padding = "=" * (-len(token) % 4)
        payload = base64.b64decode(token + padding, altchars=b"-_", validate=True)
        value = json.loads(payload.decode("utf-8"))
        if not isinstance(value, dict) or set(value) != {"complaint_id"}:
            raise ValueError("Unexpected cursor shape")
        partition_key = _validate_dynamodb_partition_key(value["complaint_id"])
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise ValidationError({"cursor": "Pagination cursor is invalid."}) from exc
    return {"complaint_id": partition_key}


def _validate_dynamodb_partition_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= DYNAMODB_KEY_MAX_LENGTH
        or any(ord(character) < 32 or 0x7F <= ord(character) <= 0x9F for character in value)
    ):
        raise ValidationError({"cursor": "Pagination cursor is invalid."})
    return value
