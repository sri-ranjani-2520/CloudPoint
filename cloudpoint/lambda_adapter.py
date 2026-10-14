"""AWS HTTP API payload v2 adapter for the framework-free WSGI application."""

import base64
import binascii
from dataclasses import replace
from http import HTTPStatus
import io
import json
import logging
import os
from urllib.parse import unquote
from typing import Any, Callable

from .app import _error, create_app, normalize_request_id
from .config import Settings
from .dynamodb_repository import DynamoDBRepository


_cached_handler: Callable | None = None
logger = logging.getLogger("cloudpoint.lambda")


def _log_lambda_failure(operation: str, request_id: str, exception: Exception) -> None:
    logger.error("operation_failed", extra={
        "event": "operation_failed",
        "operation": operation,
        "request_id": request_id,
        "error_type": type(exception).__name__,
    })


def api_gateway_v2_adapter(
    application: Callable,
    event: object,
    lambda_request_id: object = None,
) -> dict[str, Any]:
    request_id = _event_request_id(event, lambda_request_id)
    if not isinstance(event, dict):
        return _gateway_error(HTTPStatus.BAD_REQUEST, "invalid_request", "Malformed API Gateway event.", request_id)
    request_context = event.get("requestContext")
    http_context = request_context.get("http") if isinstance(request_context, dict) else None
    method = http_context.get("method") if isinstance(http_context, dict) else None
    raw_path = event.get("rawPath")
    raw_query = event.get("rawQueryString", "")
    headers = event.get("headers", {})
    encoded_flag = event.get("isBase64Encoded", False)
    if (
        not isinstance(method, str)
        or not isinstance(raw_path, str)
        or not isinstance(raw_query, str)
        or not isinstance(headers, dict)
        or not isinstance(encoded_flag, bool)
        or any(not isinstance(key, str) or not isinstance(value, str) for key, value in headers.items())
    ):
        return _gateway_error(HTTPStatus.BAD_REQUEST, "invalid_request", "Malformed API Gateway event.", request_id)
    try:
        path = unquote(raw_path, errors="strict")
    except UnicodeDecodeError:
        return _gateway_error(HTTPStatus.BAD_REQUEST, "invalid_request", "Malformed API Gateway event.", request_id)

    raw_body = event.get("body") or ""
    if not isinstance(raw_body, str):
        return _gateway_error(HTTPStatus.BAD_REQUEST, "invalid_request", "Malformed API Gateway event.", request_id)
    try:
        body = base64.b64decode(raw_body, validate=True) if encoded_flag else raw_body.encode("utf-8")
    except (binascii.Error, UnicodeEncodeError):
        return _gateway_error(HTTPStatus.BAD_REQUEST, "invalid_request", "Malformed API Gateway event.", request_id)

    lowered_headers = {key.lower(): value for key, value in headers.items()}
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": raw_query,
        "SERVER_NAME": "lambda",
        "SERVER_PORT": "443",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "https",
        "wsgi.input": io.BytesIO(body),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": True,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": lowered_headers.get("content-type", ""),
        "cloudpoint.request_id": request_id,
    }
    for key, value in lowered_headers.items():
        if key not in {"content-type", "content-length"}:
            environ["HTTP_" + key.upper().replace("-", "_")] = value

    response_status: dict[str, Any] = {}

    def start_response(status: str, response_headers: list[tuple[str, str]]) -> None:
        response_status["code"] = int(status.split(" ", 1)[0])
        response_status["headers"] = {key.lower(): value for key, value in response_headers}

    try:
        response_body = b"".join(application(environ, start_response))
        return {
            "statusCode": response_status["code"],
            "headers": response_status["headers"],
            "body": response_body.decode("utf-8"),
            "isBase64Encoded": False,
        }
    except Exception as exc:
        _log_lambda_failure("lambda_request_adapter", request_id, exc)
        return _gateway_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.", request_id)


def create_lambda_handler(
    application: Callable | None = None,
    secrets_client_factory: Callable | None = None,
) -> Callable:
    """Build an injectable Lambda entry point; the default uses configured AWS adapters."""
    if application is not None:
        return lambda event, context: api_gateway_v2_adapter(
            application, event, getattr(context, "aws_request_id", None)
        )

    def handler(event: object, context: object) -> dict[str, Any]:
        global _cached_handler
        request_id = _event_request_id(event, getattr(context, "aws_request_id", None))
        try:
            if _cached_handler is None:
                settings = Settings.from_env()
                secret_arn = os.environ.get("CLOUDPOINT_SESSION_SECRET_ARN")
                if secret_arn:
                    secret = _read_session_secret(
                        secret_arn,
                        settings.aws_region,
                        secrets_client_factory,
                    )
                    settings = replace(settings, session_secret=secret)
                repository = DynamoDBRepository.from_settings(settings)
                _cached_handler = create_app(settings, repository=repository)
            return api_gateway_v2_adapter(_cached_handler, event, request_id)
        except Exception as exc:
            _log_lambda_failure("lambda_application_initialization", request_id, exc)
            return _gateway_error(HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error", "The request could not be completed.", request_id)

    return handler


def _read_session_secret(
    secret_arn: str,
    region: str | None,
    client_factory: Callable | None = None,
) -> str:
    """Read the signing key at Lambda initialization without placing it in configuration."""
    if client_factory is None:
        import boto3

        client_factory = boto3.client
    try:
        client = client_factory("secretsmanager", region_name=region)
        response = client.get_secret_value(SecretId=secret_arn)
    except Exception:
        raise RuntimeError("Administrator session signing key could not be loaded") from None
    secret = response.get("SecretString") if isinstance(response, dict) else None
    if not isinstance(secret, str) or len(secret) < 32:
        raise RuntimeError("Administrator session signing key is invalid")
    return secret


def lambda_handler(event: object, context: object) -> dict[str, Any]:
    return create_lambda_handler()(event, context)


def _event_request_id(event: object, lambda_request_id: object = None) -> str:
    if isinstance(event, dict):
        request_context = event.get("requestContext")
        gateway_request_id = request_context.get("requestId") if isinstance(request_context, dict) else None
        if isinstance(gateway_request_id, str) and gateway_request_id:
            return normalize_request_id(gateway_request_id)
    return normalize_request_id(lambda_request_id)


def _gateway_error(
    status: HTTPStatus,
    code: str,
    message: str,
    request_id: str | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def start_response(status_line: str, headers: list[tuple[str, str]]) -> None:
        captured["headers"] = {key.lower(): value for key, value in headers}

    body = b"".join(_error(start_response, status, code, message))
    if request_id:
        captured["headers"]["x-request-id"] = request_id
    return {
        "statusCode": status.value,
        "headers": captured["headers"],
        "body": body.decode("utf-8"),
        "isBase64Encoded": False,
    }
