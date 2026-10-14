"""Application use cases independent of WSGI, Lambda, and storage technology."""

from typing import Any

from .repository import DuplicateComplaintError
from .repository_interface import ComplaintRepository
from .validation import ComplaintInput, generate_complaint_id, validate_complaint, validate_complaint_id


class ComplaintService:
    def __init__(self, repository: ComplaintRepository):
        self.repository = repository

    def submit(self, data: object) -> str:
        validated: ComplaintInput = validate_complaint(data)
        for _ in range(3):
            complaint_id = generate_complaint_id()
            try:
                self.repository.create_complaint(complaint_id, validated.__dict__)
                return complaint_id
            except DuplicateComplaintError:
                continue
        raise RuntimeError("Could not allocate a unique complaint identifier")

    def track(self, complaint_id: object) -> dict[str, Any] | None:
        complaint_id = validate_complaint_id(complaint_id)
        record = self.repository.get_complaint(complaint_id)
        if record is None:
            return None
        allowed = (
            "complaint_id",
            "title",
            "category",
            "description",
            "location",
            "status",
            "created_at",
        )
        student_record = {key: record[key] for key in allowed}
        if record["status"] == "Rejected" and record.get("rejection_reason"):
            student_record["rejection_reason"] = record["rejection_reason"]
        return student_record
