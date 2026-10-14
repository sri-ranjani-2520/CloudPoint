"""Environment-based local configuration."""

from dataclasses import dataclass, field
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE_PATH = PROJECT_ROOT / "instance" / "cloudpoint.sqlite3"


@dataclass(frozen=True)
class Settings:
    database_path: Path
    host: str = "127.0.0.1"
    port: int = 8000
    dynamodb_table: str | None = None
    aws_region: str | None = None
    session_secret: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "Settings":
        values = _read_dotenv(PROJECT_ROOT / ".env")
        values.update(os.environ if environ is None else environ)
        raw_port = values.get("CLOUDPOINT_PORT", "8000")
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise ValueError("CLOUDPOINT_PORT must be an integer") from exc
        if not 1 <= port <= 65535:
            raise ValueError("CLOUDPOINT_PORT must be between 1 and 65535")
        configured_database_path = values.get("CLOUDPOINT_DB_PATH")
        database_path = (
            Path(configured_database_path)
            if configured_database_path
            else DEFAULT_DATABASE_PATH
        )
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path
        return cls(
            database_path=database_path.resolve(),
            host=values.get("CLOUDPOINT_HOST", "127.0.0.1"),
            port=port,
            dynamodb_table=values.get("CLOUDPOINT_DYNAMODB_TABLE"),
            aws_region=values.get("CLOUDPOINT_AWS_REGION") or values.get("AWS_REGION"),
            session_secret=values.get("CLOUDPOINT_SESSION_SECRET") or None,
        )


def _read_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE settings; never execute or expand file contents."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key.startswith("CLOUDPOINT_") and key.replace("_", "").isalnum():
            values[key] = value.strip().strip("\"'")
    return values
