"""Persistence contract shared by SQLite and DynamoDB adapters."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ComplaintPage:
    items: list[dict[str, Any]]
    next_cursor: str | None


class ComplaintRepository(Protocol):
    def create_complaint(self, complaint_id: str, values: dict[str, Any]) -> dict[str, Any]: ...

    def get_complaint(self, complaint_id: str) -> dict[str, Any] | None: ...

    def list_complaints(
        self,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
        cursor: str | None = None,
        limit: int | str | None = None,
    ) -> ComplaintPage: ...

    def dashboard_counts(self) -> dict[str, int]: ...

    def add_administrator(self, username: str, password_hash: str) -> None: ...

    def get_administrator(self, username: str) -> dict[str, str] | None: ...

    def create_admin_session(self, token_digest: str, username: str, expires_at: int) -> None: ...

    def get_admin_session(self, token_digest: str) -> dict[str, Any] | None: ...

    def delete_admin_session(self, token_digest: str) -> None: ...

    def update_complaint_status(
        self, complaint_id: str, status: str, rejection_reason: str | None
    ) -> dict[str, Any] | None: ...
