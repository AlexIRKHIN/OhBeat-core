"""Single error format of the API: {"error_code", "message", "details"} (REST API Contracts, intro)."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.i18n import t

log = logging.getLogger(__name__)


class ApiError(Exception):
    """Business error. The message is looked up by error_code in app/common/i18n.py."""

    def __init__(self, status_code: int, error_code: str, details: list[dict] | None = None):
        super().__init__(error_code)
        self.status_code = status_code
        self.error_code = error_code
        self.details = details or []


def field_error(field: str, issue_key: str, **params: object) -> ApiError:
    """400 VALIDATION_ERROR about one field, for checks that need the database or storage."""
    return ApiError(400, "VALIDATION_ERROR", [{"field": field, "issue": t(issue_key, **params)}])


def error_body(error_code: str, details: list[dict] | None = None) -> dict:
    return {"error_code": error_code, "message": t(error_code), "details": details or []}


def _field_path(loc: tuple) -> str:
    """('body', 'licenses', 1, 'price') -> 'licenses[1].price'."""
    path = ""
    for part in loc:
        if part in ("body", "query", "path"):
            continue
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path


# Pydantic error types -> our message keys
_PYDANTIC_ISSUES = {
    "missing": "required",
    "string_too_short": "too_short",
    "string_too_long": "too_long",
    "value_error": "invalid_value",
    "literal_error": "invalid_value",
    "enum": "invalid_value",
    "greater_than_equal": "invalid_value",
    "less_than_equal": "invalid_value",
    "string_type": "invalid_type",
    "int_parsing": "invalid_type",
    "bool_parsing": "invalid_type",
    "json_invalid": "invalid_value",
}


def _issue(error: dict) -> str:
    if error["type"] == "ohbeat":
        # Our own validators put a message key into the error message
        return t(error["msg"], **error.get("ctx", {}).get("params", {}))
    if error["type"] == "value_error" and "email" in str(error.get("msg", "")).lower():
        return t("invalid_email")
    key = _PYDANTIC_ISSUES.get(error["type"], "invalid_value")
    ctx = error.get("ctx", {})
    if key == "too_short":
        return t(key, min=ctx.get("min_length", ""))
    if key == "too_long":
        return t(key, max=ctx.get("max_length", ""))
    return t(key)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(error_body(exc.error_code, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": _field_path(e["loc"]), "issue": _issue(e)} for e in exc.errors()]
        return JSONResponse(error_body("VALIDATION_ERROR", details), status_code=400)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "AUTH_ERROR", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "INTERNAL_ERROR"
        )
        return JSONResponse(error_body(code), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Unhandled error", exc_info=exc)
        return JSONResponse(error_body("INTERNAL_ERROR"), status_code=500)
