"""SQLite persistence boundary; business rules should not depend on SQL."""

from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Any

from .auth import is_password_hash
from .validation import (
    CATEGORIES,
    STATUSES,
    ValidationError,
    complaint_id_from_search,
    validate_complaint,
    validate_complaint_id,
    validate_status,
)
from .pagination import decode_cursor, encode_cursor, normalize_page_size
from .repository_interface import ComplaintPage
from .validation import validate_list_filters


class DuplicateComplaintError(Exception):
    """Raised when an identifier already exists."""


class DuplicateAdministratorError(Exception):
    """Raised when an administrator username already exists."""


class SchemaMigrationError(RuntimeError):
    """Raised when legacy data cannot safely satisfy the current schema."""


class RepositoryIntegrityError(RuntimeError):
    """Raised when persistence cannot return a successfully inserted record."""


class Repository:
    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.create_function(
            "casefold",
            1,
            lambda value: value.casefold() if isinstance(value, str) else "",
        )
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'complaints'"
            ).fetchone()
            if existing is None:
                connection.execute(_complaints_table_sql("complaints"))
            elif not _complaint_schema_is_current(connection, existing["sql"]):
                _migrate_complaints(connection)
            connection.execute(
                """CREATE TABLE IF NOT EXISTS administrators (
                    username TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_digest TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                )"""
            )

    def create_complaint(self, complaint_id: str, values: dict[str, Any]) -> dict[str, Any]:
        complaint_id = validate_complaint_id(complaint_id)
        validated_values = validate_complaint(values)
        values = validated_values.__dict__
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connection() as connection:
                connection.execute(
                    """INSERT INTO complaints (
                        complaint_id, student_name, registration_number, title, category,
                        description, location, status, rejection_reason, created_at, modified_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'Submitted', NULL, ?, ?)""",
                    (complaint_id, values["student_name"], values["registration_number"],
                     values["title"], values["category"], values["description"],
                     values["location"], now, now),
                )
                row = connection.execute(
                    "SELECT * FROM complaints WHERE complaint_id = ?", (complaint_id,)
                ).fetchone()
                if row is None:
                    raise RepositoryIntegrityError("Inserted complaint could not be retrieved")
        except sqlite3.IntegrityError as exc:
            if "UNIQUE constraint failed: complaints.complaint_id" in str(exc):
                raise DuplicateComplaintError(complaint_id) from exc
            raise RepositoryIntegrityError("Complaint record violates storage constraints") from exc
        return dict(row)

    def get_complaint(self, complaint_id: str) -> dict[str, Any] | None:
        complaint_id = validate_complaint_id(complaint_id)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?", (complaint_id,)
            ).fetchone()
        return dict(row) if row else None

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
        start_key = decode_cursor(cursor)
        if normalized_search:
            if exact_id is not None:
                record = self.get_complaint(exact_id)
                if record is not None and (category is None or category == record["category"]) and (
                    status is None or status == record["status"]
                ):
                    return ComplaintPage([record], None)
                return ComplaintPage([], None)

        clauses: list[str] = []
        parameters: list[Any] = []
        if category is not None:
            clauses.append("category = ?")
            parameters.append(category)
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if normalized_search:
            clauses.append("(instr(casefold(title), ?) > 0 OR instr(casefold(registration_number), ?) > 0)")
            parameters.extend((normalized_search, normalized_search))
        if start_key is not None:
            clauses.append("complaint_id > ?")
            parameters.append(start_key["complaint_id"])
        query = "SELECT * FROM complaints"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY complaint_id LIMIT ?"
        parameters.append(page_size + 1)
        with self._connection() as connection:
            rows = [dict(row) for row in connection.execute(query, parameters).fetchall()]
        has_more = len(rows) > page_size
        items = rows[:page_size]
        next_cursor = encode_cursor({"complaint_id": items[-1]["complaint_id"]}) if has_more else None
        return ComplaintPage(items, next_cursor)

    def dashboard_counts(self) -> dict[str, int]:
        counts = {status: 0 for status in STATUSES}
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT status, count(*) AS total FROM complaints GROUP BY status"
            ).fetchall()
        for row in rows:
            counts[row["status"]] = row["total"]
        return {"total": sum(counts.values()), **counts}

    def update_complaint_status(
        self, complaint_id: str, status: str, rejection_reason: str | None
    ) -> dict[str, Any] | None:
        complaint_id = validate_complaint_id(complaint_id)
        status, rejection_reason = validate_status(status, rejection_reason)
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE complaints SET status = ?, rejection_reason = ?, modified_at = ? WHERE complaint_id = ?",
                (status, rejection_reason, now, complaint_id),
            )
            row = connection.execute(
                "SELECT * FROM complaints WHERE complaint_id = ?", (complaint_id,)
            ).fetchone()
        return dict(row) if row else None

    def add_administrator(self, username: str, password_hash: str) -> None:
        username = _normalize_username(username)
        if not is_password_hash(password_hash):
            raise ValueError("Administrator password must be stored as a supported password hash")
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connection() as connection:
                connection.execute(
                    "INSERT INTO administrators (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, password_hash, now),
                )
        except sqlite3.IntegrityError as exc:
            if "administrators.username" in str(exc):
                raise DuplicateAdministratorError(username) from exc
            raise

    def get_administrator(self, username: str) -> dict[str, str] | None:
        username = _normalize_username(username)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT username, password_hash FROM administrators WHERE username = ?", (username,)
            ).fetchone()
        return dict(row) if row else None

    def reset_administrator_password(self, username: str, password_hash: str) -> bool:
        """Replace one SQLite administrator hash and revoke that account's sessions."""
        username = _normalize_username(username)
        if not is_password_hash(password_hash):
            raise ValueError("Administrator password must be stored as a supported password hash")
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE administrators SET password_hash = ? WHERE username = ?",
                (password_hash, username),
            )
            if cursor.rowcount:
                connection.execute("DELETE FROM admin_sessions WHERE username = ?", (username,))
        return cursor.rowcount == 1

    def create_admin_session(self, token_digest: str, username: str, expires_at: int) -> None:
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO admin_sessions (token_digest, username, expires_at) VALUES (?, ?, ?)",
                (token_digest, _normalize_username(username), expires_at),
            )

    def get_admin_session(self, token_digest: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT username, expires_at FROM admin_sessions WHERE token_digest = ?", (token_digest,)
            ).fetchone()
        return dict(row) if row else None

    def delete_admin_session(self, token_digest: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM admin_sessions WHERE token_digest = ?", (token_digest,))


def _normalize_username(username: str) -> str:
    if not isinstance(username, str) or not username.strip() or len(username.strip()) > 120:
        raise ValueError("Administrator username must contain 1 to 120 characters")
    return username.strip().casefold()


def _complaints_table_sql(table_name: str) -> str:
    # Table names are internal constants: only the migration's staging name is variable.
    if table_name not in {"complaints", "complaints_migration"}:
        raise ValueError("Unsupported internal table name")
    category_sql = ", ".join("'" + item.replace("'", "''") + "'" for item in CATEGORIES)
    status_sql = ", ".join("'" + item.replace("'", "''") + "'" for item in STATUSES)
    return f"""CREATE TABLE {table_name} (
        complaint_id TEXT NOT NULL PRIMARY KEY CHECK (
            typeof(complaint_id) = 'text'
            AND substr(complaint_id, 1, 3) = 'CP-'
            AND length(complaint_id) BETWEEN 19 AND 67
            AND substr(complaint_id, 4) NOT GLOB '*[^A-Za-z0-9_-]*'
        ),
        student_name TEXT NOT NULL CHECK(length(trim(student_name)) BETWEEN 1 AND 120),
        registration_number TEXT NOT NULL CHECK(length(trim(registration_number)) BETWEEN 1 AND 64),
        title TEXT NOT NULL CHECK(length(trim(title)) BETWEEN 1 AND 160),
        category TEXT NOT NULL CHECK(category IN ({category_sql})),
        description TEXT NOT NULL CHECK(length(trim(description)) BETWEEN 1 AND 5000),
        location TEXT NOT NULL CHECK(length(trim(location)) BETWEEN 1 AND 160),
        status TEXT NOT NULL CHECK(status IN ({status_sql})),
        rejection_reason TEXT,
        created_at TEXT NOT NULL,
        modified_at TEXT NOT NULL,
        CHECK(status != 'Rejected' OR length(trim(coalesce(rejection_reason, ''))) > 0)
    )"""


def _complaint_schema_is_current(connection: sqlite3.Connection, create_sql: str) -> bool:
    columns = {row["name"]: row for row in connection.execute("PRAGMA table_info(complaints)")}
    return (
        "complaint_id" in columns
        and bool(columns["complaint_id"]["notnull"])
        and "substr(complaint_id, 1, 3) = 'CP-'" in create_sql
        and "NOT GLOB '*[^A-Za-z0-9_-]*'" in create_sql
    )


def _migrate_complaints(connection: sqlite3.Connection) -> None:
    """Rebuild the old table transactionally, refusing invalid IDs without data loss."""
    try:
        rows = connection.execute("SELECT * FROM complaints").fetchall()
    except sqlite3.DatabaseError as exc:
        raise SchemaMigrationError("Legacy complaints table could not be inspected; no changes were applied") from exc

    for row in rows:
        try:
            validate_complaint_id(row["complaint_id"])
        except (ValidationError, IndexError, KeyError) as exc:
            raise SchemaMigrationError(
                "Legacy complaint data contains a missing or malformed ID; database was left unchanged"
            ) from exc

    try:
        connection.execute(_complaints_table_sql("complaints_migration"))
        connection.execute(
            """INSERT INTO complaints_migration (
                complaint_id, student_name, registration_number, title, category,
                description, location, status, rejection_reason, created_at, modified_at
            ) SELECT complaint_id, student_name, registration_number, title, category,
                description, location, status, rejection_reason, created_at, modified_at
            FROM complaints"""
        )
        connection.execute("DROP TABLE complaints")
        connection.execute("ALTER TABLE complaints_migration RENAME TO complaints")
    except sqlite3.DatabaseError as exc:
        raise SchemaMigrationError(
            "Legacy complaint data does not satisfy the current schema; database was left unchanged"
        ) from exc
