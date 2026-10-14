"""Administrator credential verification and revocable opaque bearer sessions."""

from collections import defaultdict
import hashlib
import hmac
import base64
import secrets
import re
import threading
import time
from typing import Any

from .repository_interface import ComplaintRepository

SESSION_TTL_SECONDS = 30 * 60
MAX_LOGIN_FAILURES = 5
LOGIN_LOCK_SECONDS = 15 * 60
TOKEN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
TOKEN_SIGNATURE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


class AuthenticationError(Exception):
    pass


class LoginThrottle:
    """Per-process prototype throttle; production must also rate-limit at API Gateway."""

    def __init__(self):
        self._lock = threading.Lock()
        self._failures: dict[str, tuple[int, float]] = defaultdict(lambda: (0, 0.0))

    def locked(self, username: str, now: float) -> bool:
        with self._lock:
            return self._failures[username][1] > now

    def fail(self, username: str, now: float) -> None:
        with self._lock:
            count, until = self._failures[username]
            if until and until <= now:
                count = 0
            count += 1
            self._failures[username] = (count, now + LOGIN_LOCK_SECONDS if count >= MAX_LOGIN_FAILURES else 0.0)

    def clear(self, username: str) -> None:
        with self._lock:
            self._failures.pop(username, None)


class AdminAuth:
    def __init__(
        self,
        repository: ComplaintRepository,
        session_secret: str | None,
        ttl_seconds: int = SESSION_TTL_SECONDS,
    ):
        self.repository = repository
        self.session_secret = session_secret
        self.ttl_seconds = ttl_seconds
        self.throttle = LoginThrottle()

    def login(self, username: object, password: object) -> dict[str, Any]:
        self._require_secret()
        if not isinstance(username, str) or not isinstance(password, str):
            raise AuthenticationError()
        normalized = username.strip().casefold()
        if not normalized or len(normalized) > 120 or not password or len(password) > 1024:
            raise AuthenticationError()
        now = time.time()
        if self.throttle.locked(normalized, now):
            raise AuthenticationError()
        admin = self.repository.get_administrator(normalized)
        encoded = admin.get("password_hash") if admin else None
        # Keep unknown-user failures close to the cost of a valid scrypt check.
        valid = _verify_password(password, encoded) if encoded else _burn_scrypt(password)
        if not admin or not valid:
            self.throttle.fail(normalized, now)
            raise AuthenticationError()
        self.throttle.clear(normalized)
        token_id = secrets.token_urlsafe(32)
        signature = self._signature(token_id)
        token = token_id + "." + signature
        expires_at = int(now) + self.ttl_seconds
        self.repository.create_admin_session(_digest(token_id), admin["username"], expires_at)
        return {"access_token": token, "token_type": "Bearer", "expires_in": self.ttl_seconds}

    def authenticate(self, authorization: object) -> tuple[str, str]:
        self._require_secret()
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            raise AuthenticationError()
        token = authorization[7:]
        if not token or len(token) > 160 or any(ch.isspace() for ch in token):
            raise AuthenticationError()
        try:
            token_id, signature = token.split(".", 1)
        except ValueError:
            raise AuthenticationError() from None
        if (
            not TOKEN_ID_PATTERN.fullmatch(token_id)
            or not TOKEN_SIGNATURE_PATTERN.fullmatch(signature)
            or not hmac.compare_digest(signature, self._signature(token_id))
        ):
            raise AuthenticationError()
        digest = _digest(token_id)
        session = self.repository.get_admin_session(digest)
        if not session:
            raise AuthenticationError()
        if int(session["expires_at"]) <= int(time.time()):
            self.repository.delete_admin_session(digest)
            raise AuthenticationError()
        return session["username"], digest

    def logout(self, digest: str) -> None:
        self.repository.delete_admin_session(digest)

    def _signature(self, token_id: str) -> str:
        return base64.urlsafe_b64encode(
            hmac.new(self.session_secret.encode("utf-8"), token_id.encode("ascii"), hashlib.sha256).digest()
        ).decode("ascii").rstrip("=")

    def _require_secret(self) -> None:
        if not isinstance(self.session_secret, str) or len(self.session_secret) < 32:
            raise RuntimeError("CLOUDPOINT_SESSION_SECRET must contain at least 32 characters")


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _verify_password(password: str, encoded: str) -> bool:
    try:
        if len(encoded) > 512:
            return False
        scheme, salt_hex, digest_hex = encoded.split("$", 2)
        if scheme != "scrypt":
            return False
        salt, expected = bytes.fromhex(salt_hex), bytes.fromhex(digest_hex)
        if len(salt) < 16 or len(expected) != 64:
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError):
        return False


def is_password_hash(encoded: object) -> bool:
    if not isinstance(encoded, str) or len(encoded) > 512:
        return False
    try:
        scheme, salt_hex, digest_hex = encoded.split("$", 2)
        return scheme == "scrypt" and len(bytes.fromhex(salt_hex)) >= 16 and len(bytes.fromhex(digest_hex)) == 64
    except (ValueError, TypeError):
        return False


def _burn_scrypt(password: str) -> bool:
    hashlib.scrypt(password.encode("utf-8"), salt=b"cloudpoint-dummy-salt", n=2**14, r=8, p=1, dklen=64)
    return False
