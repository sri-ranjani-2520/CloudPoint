"""Shared data validation for the local foundation."""

from dataclasses import dataclass
import re
import secrets


CATEGORIES = ("Hostel", "Academic", "Infrastructure", "Transport", "Cleanliness", "Other")
STATUSES = ("Submitted", "Under Review", "In Progress", "Resolved", "Rejected")
FIELD_LIMITS = {
    "student_name": 120,
    "registration_number": 64,
    "title": 160,
    "description": 5000,
    "location": 160,
    "rejection_reason": 1000,
}
COMPLAINT_ID_PATTERN = re.compile(r"^CP-[A-Za-z0-9_-]{16,64}$")


def generate_complaint_id() -> str:
    """Generate an unpredictable ID; the repository still enforces uniqueness."""
    return f"CP-{secrets.token_urlsafe(18)}"


class ValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("The supplied data is invalid")


@dataclass(frozen=True)
class ComplaintInput:
    student_name: str
    registration_number: str
    title: str
    category: str
    description: str
    location: str


def validate_complaint(data: object) -> ComplaintInput:
    if not isinstance(data, dict):
        raise ValidationError({"complaint": "Complaint data must be an object."})
    errors: dict[str, str] = {}
    cleaned: dict[str, str] = {}
    for field in ("student_name", "registration_number", "title", "description", "location"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors[field] = "This field is required."
            continue
        normalized = value.strip()
        if len(normalized) > FIELD_LIMITS[field]:
            errors[field] = f"Must be at most {FIELD_LIMITS[field]} characters."
        else:
            cleaned[field] = normalized

    category = data.get("category")
    if not isinstance(category, str) or category not in CATEGORIES:
        errors["category"] = "Select one of the approved complaint categories."
    else:
        cleaned["category"] = category
    if errors:
        raise ValidationError(errors)
    return ComplaintInput(**cleaned)


def validate_complaint_id(complaint_id: object) -> str:
    if not isinstance(complaint_id, str) or not COMPLAINT_ID_PATTERN.fullmatch(complaint_id):
        raise ValidationError({"complaint_id": "Complaint ID has an invalid format."})
    return complaint_id


def complaint_id_from_search(search: str | None) -> str | None:
    if not isinstance(search, str) or search[:3].casefold() != "cp-":
        return None
    candidate = "CP-" + search[3:]
    try:
        return validate_complaint_id(candidate)
    except ValidationError:
        return None


def validate_status(status: object, rejection_reason: object = None) -> tuple[str, str | None]:
    if not isinstance(status, str) or status not in STATUSES:
        raise ValidationError({"status": "Select one of the approved complaint statuses."})
    reason: str | None = None
    if status == "Rejected":
        if not isinstance(rejection_reason, str) or not rejection_reason.strip():
            raise ValidationError({"rejection_reason": "A reason is required when rejecting a complaint."})
        reason = rejection_reason.strip()
        if len(reason) > FIELD_LIMITS["rejection_reason"]:
            raise ValidationError({"rejection_reason": "Must be at most 1000 characters."})
    return status, reason


def validate_list_filters(
    category: object,
    status: object,
    search: object,
) -> tuple[str | None, str | None, str | None]:
    if category is not None and (not isinstance(category, str) or category not in CATEGORIES):
        raise ValidationError({"category": "Select one of the approved complaint categories."})
    if status is not None and (not isinstance(status, str) or status not in STATUSES):
        raise ValidationError({"status": "Select one of the approved complaint statuses."})
    if search is not None and not isinstance(search, str):
        raise ValidationError({"search": "Search text must be a string."})
    normalized = search.strip().casefold() if isinstance(search, str) else None
    if normalized and len(normalized) > FIELD_LIMITS["title"]:
        raise ValidationError({"search": "Search text must be at most 160 characters."})
    return category, status, normalized or None
