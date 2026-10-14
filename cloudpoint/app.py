"""Minimal WSGI application foundation with health and static routes."""

from http import HTTPStatus
import json
import logging
from pathlib import Path
import re
import uuid
from typing import Any, Callable, Iterable
from urllib.parse import parse_qs
from wsgiref.simple_server import WSGIRequestHandler, make_server

from .config import Settings
from .auth import AdminAuth, AuthenticationError
from .repository import Repository
from .repository_interface import ComplaintRepository
from .services import ComplaintService
from .validation import ValidationError


ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("cloudpoint")
METHOD_PATTERN = re.compile(r"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$")
TRACKING_PATH_PATTERN = re.compile(r"^/api/complaints/([^/]+)$")
ADMIN_COMPLAINT_PATH_PATTERN = re.compile(r"^/api/admin/complaints/([^/]+)$")
ADMIN_STATUS_PATH_PATTERN = re.compile(r"^/api/admin/complaints/([^/]+)/status$")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_REQUEST_BYTES = 16_384


def create_app(
    settings: Settings | None = None,
    repository: ComplaintRepository | None = None,
) -> Callable:
    configuration = settings or Settings.from_env()
    persistence = repository if repository is not None else Repository(configuration.database_path)
    if repository is None:
        persistence.initialize()
    complaint_service = ComplaintService(persistence)
    admin_auth = AdminAuth(persistence, configuration.session_secret)

    def application(environ: dict, start_response: Callable) -> Iterable[bytes]:
        request_id = normalize_request_id(
            environ.get("cloudpoint.request_id") if isinstance(environ, dict) else None
        )
        original_start_response = start_response

        def correlated_start_response(status: str, headers: list[tuple[str, str]]) -> None:
            safe_headers = [(key, value) for key, value in headers if key.lower() != "x-request-id"]
            safe_headers.append(("X-Request-Id", request_id))
            original_start_response(status, safe_headers)

        start_response = correlated_start_response
        if not isinstance(environ, dict):
            return _error(start_response, HTTPStatus.BAD_REQUEST, "invalid_request", "Malformed request environment.")
        raw_method = environ.get("REQUEST_METHOD")
        path = environ.get("PATH_INFO")
        if (
            not isinstance(raw_method, str)
            or not METHOD_PATTERN.fullmatch(raw_method)
            or not isinstance(path, str)
            or not path.startswith("/")
            or any(
                ord(character) < 32
                or 0x7F <= ord(character) <= 0x9F
                or 0xD800 <= ord(character) <= 0xDFFF
                for character in path
            )
        ):
            return _error(start_response, HTTPStatus.BAD_REQUEST, "invalid_request", "Malformed request environment.")

        method = raw_method.upper()
        static_candidate = _static_candidate(path) if path.startswith("/static/") else None
        tracking_match = TRACKING_PATH_PATTERN.fullmatch(path)
        admin_status_match = ADMIN_STATUS_PATH_PATTERN.fullmatch(path)
        admin_complaint_match = ADMIN_COMPLAINT_PATH_PATTERN.fullmatch(path)
        allowed_method = None
        if path in ("/health", "/", "/index.html", "/admin", "/admin.html") or static_candidate is not None:
            allowed_method = "GET"
        elif path == "/api/complaints":
            allowed_method = "POST"
        elif tracking_match:
            allowed_method = "GET"
        elif path == "/api/admin/login":
            allowed_method = "POST"
        elif path == "/api/admin/logout":
            allowed_method = "POST"
        elif path == "/api/admin/dashboard":
            allowed_method = "GET"
        elif path == "/api/admin/complaints":
            allowed_method = "GET"
        elif admin_status_match:
            allowed_method = "PATCH"
        elif admin_complaint_match:
            allowed_method = "GET"
        if allowed_method is not None and method != allowed_method:
            return _error(
                start_response,
                HTTPStatus.METHOD_NOT_ALLOWED,
                "method_not_allowed",
                f"This route only supports {allowed_method}.",
                headers=(("Allow", allowed_method),),
            )
        if method == "GET" and path == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            return _response(start_response, HTTPStatus.OK, "application/json; charset=utf-8", body)
        if method == "POST" and path == "/api/admin/login":
            try:
                request = _read_json_request(environ)
            except UnsupportedMediaTypeError:
                return _error(start_response, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type", "Content-Type must be application/json.")
            except RequestTooLargeError:
                return _error(start_response, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "Request body exceeds the allowed size.")
            except MalformedJsonError:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be a JSON object.")
            try:
                result = admin_auth.login(request.get("username"), request.get("password"))
            except AuthenticationError:
                return _error(start_response, HTTPStatus.UNAUTHORIZED, "authentication_failed", "Invalid username or password.")
            except Exception as exc:
                _log_failure("administrator_login", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            return _json_response(start_response, HTTPStatus.OK, result)

        is_admin_route = path.startswith("/api/admin/") and allowed_method is not None
        token_digest = None
        if is_admin_route and path != "/api/admin/login":
            try:
                _, token_digest = admin_auth.authenticate(environ.get("HTTP_AUTHORIZATION"))
            except AuthenticationError:
                return _error(start_response, HTTPStatus.UNAUTHORIZED, "unauthorized", "Administrator authentication is required.", headers=(("WWW-Authenticate", "Bearer"),))
            except Exception as exc:
                _log_failure("administrator_authorization", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")

        if method == "POST" and path == "/api/admin/logout":
            try:
                admin_auth.logout(token_digest)
            except Exception as exc:
                _log_failure("administrator_logout", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            return _json_response(start_response, HTTPStatus.OK, {"message": "Logged out successfully."})

        if method == "GET" and path == "/api/admin/dashboard":
            try:
                counts = persistence.dashboard_counts()
            except Exception as exc:
                _log_failure("administrator_dashboard", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            return _json_response(start_response, HTTPStatus.OK, counts)

        if method == "GET" and path == "/api/admin/complaints":
            try:
                query = _query_parameters(environ.get("QUERY_STRING", ""))
                page = persistence.list_complaints(
                    category=query.get("category"), status=query.get("status"), search=query.get("search"),
                    cursor=query.get("cursor"), limit=query.get("limit"),
                )
            except ValidationError as exc:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "validation_error", "Request validation failed.", details=exc.errors)
            except ValueError:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "invalid_request", "Query parameters are malformed.")
            except Exception as exc:
                _log_failure("administrator_complaint_list", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            items = [_admin_list_item(item) for item in page.items]
            return _json_response(start_response, HTTPStatus.OK, {"items": items, "next_cursor": page.next_cursor})

        if method == "GET" and admin_complaint_match:
            try:
                record = persistence.get_complaint(admin_complaint_match.group(1))
            except ValidationError as exc:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "validation_error", "Request validation failed.", details=exc.errors)
            except Exception as exc:
                _log_failure("administrator_complaint_detail", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            if record is None:
                return _error(start_response, HTTPStatus.NOT_FOUND, "not_found", "Complaint not found.")
            return _json_response(start_response, HTTPStatus.OK, record)

        if method == "PATCH" and admin_status_match:
            try:
                request = _read_json_request(environ)
            except UnsupportedMediaTypeError:
                return _error(start_response, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type", "Content-Type must be application/json.")
            except RequestTooLargeError:
                return _error(start_response, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "Request body exceeds the allowed size.")
            except MalformedJsonError:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be a JSON object.")
            if set(request) - {"status", "rejection_reason"}:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "invalid_request", "Only status and rejection_reason are accepted.")
            from .validation import validate_status
            try:
                status, reason = validate_status(request.get("status"), request.get("rejection_reason"))
                updated = persistence.update_complaint_status(admin_status_match.group(1), status, reason)
            except ValidationError as exc:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "validation_error", "Request validation failed.", details=exc.errors)
            except RuntimeError:
                _log_event(logging.WARNING, "operation_conflict", request_id=request_id, operation="complaint_status_update")
                return _error(start_response, HTTPStatus.CONFLICT, "update_conflict", "The complaint changed during this update; reload and retry.")
            except Exception as exc:
                _log_failure("complaint_status_update", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            if updated is None:
                return _error(start_response, HTTPStatus.NOT_FOUND, "not_found", "Complaint not found.")
            _log_event(logging.INFO, "operation_succeeded", request_id=request_id, operation="complaint_status_update")
            return _json_response(start_response, HTTPStatus.OK, updated)
        if method == "GET" and path in ("/", "/index.html"):
            return _file_response(start_response, ROOT / "frontend" / "index.html", "text/html; charset=utf-8", request_id)
        if method == "GET" and path in ("/admin", "/admin.html"):
            return _file_response(start_response, ROOT / "frontend" / "admin.html", "text/html; charset=utf-8", request_id)
        if method == "GET" and path.startswith("/static/"):
            if static_candidate is None:
                return _error(start_response, HTTPStatus.NOT_FOUND, "not_found", "Resource not found.")
            content_types = {
                ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
            }
            content_type = content_types.get(static_candidate.suffix, "application/octet-stream")
            return _file_response(start_response, static_candidate, content_type, request_id)
        if method == "POST" and path == "/api/complaints":
            try:
                complaint = _read_json_request(environ)
                complaint_id = complaint_service.submit(complaint)
            except ValidationError as exc:
                return _error(
                    start_response,
                    HTTPStatus.BAD_REQUEST,
                    "validation_error",
                    "Request validation failed.",
                    details=exc.errors,
                )
            except UnsupportedMediaTypeError:
                return _error(start_response, HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "unsupported_media_type", "Content-Type must be application/json.")
            except RequestTooLargeError:
                return _error(start_response, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "request_too_large", "Request body exceeds the allowed size.")
            except MalformedJsonError:
                return _error(start_response, HTTPStatus.BAD_REQUEST, "invalid_json", "Request body must be a JSON object.")
            except Exception as exc:
                _log_failure("complaint_submission", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            body = json.dumps({
                "message": "Complaint submitted successfully.",
                "complaint_id": complaint_id,
            }).encode("utf-8")
            _log_event(logging.INFO, "operation_succeeded", request_id=request_id, operation="complaint_submission")
            return _response(start_response, HTTPStatus.CREATED, "application/json; charset=utf-8", body)
        if method == "GET" and tracking_match:
            try:
                record = complaint_service.track(tracking_match.group(1))
            except ValidationError as exc:
                return _error(
                    start_response,
                    HTTPStatus.BAD_REQUEST,
                    "validation_error",
                    "Request validation failed.",
                    details=exc.errors,
                )
            except Exception as exc:
                _log_failure("student_complaint_tracking", request_id, exc)
                return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
            if record is None:
                return _error(start_response, HTTPStatus.NOT_FOUND, "not_found", "Complaint not found.")
            body = json.dumps(record).encode("utf-8")
            return _response(start_response, HTTPStatus.OK, "application/json; charset=utf-8", body)
        return _error(start_response, HTTPStatus.NOT_FOUND, "not_found", "Resource not found.")
    return application


def _static_candidate(path: str) -> Path | None:
    static_root = (ROOT / "frontend" / "static").resolve()
    relative = path.removeprefix("/static/")
    try:
        candidate = (static_root / relative).resolve()
        if static_root in candidate.parents and candidate.is_file():
            return candidate
    except (OSError, RuntimeError, ValueError):
        pass
    return None


def normalize_request_id(candidate: object) -> str:
    """Accept only a bounded, log-safe platform request ID; otherwise create one."""
    if isinstance(candidate, str) and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def _log_event(level: int, event: str, **fields: str) -> None:
    logger.log(level, event, extra={"event": event, **fields})


def _log_failure(operation: str, request_id: str, exception: Exception) -> None:
    _log_event(
        logging.ERROR,
        "operation_failed",
        request_id=request_id,
        operation=operation,
        error_type=type(exception).__name__,
    )


def _response(
    start_response: Callable,
    status: HTTPStatus,
    content_type: str,
    body: bytes,
    headers: tuple[tuple[str, str], ...] = (),
) -> list[bytes]:
    start_response(f"{status.value} {status.phrase}", [
        ("Content-Type", content_type), ("Content-Length", str(len(body))),
        ("X-Content-Type-Options", "nosniff"),
        *headers,
    ])
    return [body]


def _json_response(start_response: Callable, status: HTTPStatus, value: Any) -> list[bytes]:
    return _response(start_response, status, "application/json; charset=utf-8", json.dumps(value).encode("utf-8"))


def _query_parameters(raw_query: object) -> dict[str, str]:
    if not isinstance(raw_query, str) or len(raw_query) > 4096:
        raise ValueError("Malformed query")
    parsed = parse_qs(raw_query, keep_blank_values=True, strict_parsing=False)
    allowed = {"category", "status", "search", "cursor", "limit"}
    if set(parsed) - allowed or any(len(values) != 1 for values in parsed.values()):
        raise ValueError("Malformed query")
    return {key: values[0] for key, values in parsed.items()}


def _admin_list_item(item: dict[str, Any]) -> dict[str, Any]:
    fields = ("complaint_id", "title", "registration_number", "category", "status", "created_at", "modified_at")
    return {key: item[key] for key in fields if key in item}


def _error(
    start_response: Callable,
    status: HTTPStatus,
    code: str,
    message: str,
    headers: tuple[tuple[str, str], ...] = (),
    details: dict[str, str] | None = None,
) -> list[bytes]:
    error = {"code": code, "message": message}
    if details:
        error["details"] = details
    body = json.dumps({"error": error}).encode("utf-8")
    return _response(start_response, status, "application/json; charset=utf-8", body, headers)


class UnsupportedMediaTypeError(ValueError):
    pass


class RequestTooLargeError(ValueError):
    pass


class MalformedJsonError(ValueError):
    pass


def _read_json_request(environ: dict) -> dict[str, Any]:
    raw_content_type = environ.get("CONTENT_TYPE", "")
    if not isinstance(raw_content_type, str):
        raise UnsupportedMediaTypeError()
    content_type = raw_content_type.split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise UnsupportedMediaTypeError()
    raw_length = environ.get("CONTENT_LENGTH", "")
    try:
        content_length = int(raw_length)
    except (TypeError, ValueError) as exc:
        raise MalformedJsonError() from exc
    if content_length < 1:
        raise MalformedJsonError()
    if content_length > MAX_REQUEST_BYTES:
        raise RequestTooLargeError()
    stream = environ.get("wsgi.input")
    if not hasattr(stream, "read"):
        raise MalformedJsonError()
    try:
        payload = stream.read(content_length)
        decoded = payload.decode("utf-8")
        data = json.loads(decoded)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError) as exc:
        raise MalformedJsonError() from exc
    if not isinstance(data, dict):
        raise MalformedJsonError()
    return data


def _file_response(start_response: Callable, path: Path, content_type: str, request_id: str) -> list[bytes]:
    try:
        body = path.read_bytes()
    except OSError as exc:
        _log_failure("static_file_read", request_id, exc)
        return _error(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.")
    return _response(start_response, HTTPStatus.OK, content_type, body)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(_LocalOperationLogFormatter())
    settings = Settings.from_env()
    app = create_app(settings)
    logger.info("Starting local CloudPoint server on %s:%s", settings.host, settings.port)
    with make_server(settings.host, settings.port, app, handler_class=_QuietWSGIRequestHandler) as server:
        server.serve_forever()


class _QuietWSGIRequestHandler(WSGIRequestHandler):
    """Suppress default access lines, which include complaint IDs in request paths."""

    def log_message(self, format: str, *args: Any) -> None:
        return


class _LocalOperationLogFormatter(logging.Formatter):
    """Format operation events as standalone JSON in local development logs."""

    def format(self, record: logging.LogRecord) -> str:
        event_fields = ("event", "request_id", "operation", "error_type")
        if hasattr(record, "event"):
            payload = {field: getattr(record, field) for field in event_fields if hasattr(record, field)}
            return json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return super().format(record)


if __name__ == "__main__":
    main()
