"""One JSON error shape for every API failure:

    {"error": {"code": "not_found", "message": "No such trip.", "fields": {"title": ["…"]}}}
"""

import logging

from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from ninja.errors import AuthenticationError, AuthorizationError, HttpError
from ninja.errors import ValidationError as NinjaValidationError

log = logging.getLogger(__name__)

CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
         405: "method_not_allowed", 409: "conflict", 413: "too_large", 422: "invalid",
         429: "rate_limited", 500: "server_error"}


def error_response(api, request, status, message, fields=None, code=None, extra=None):
    body = {"code": code or CODES.get(status, "error"), "message": message}
    if fields:
        body["fields"] = fields
    if extra:
        body.update(extra)
    return api.create_response(request, {"error": body}, status=status)


def _field_name(loc):
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "payload", "form", "file")]
    return ".".join(parts) or "__all__"


def install(api):
    @api.exception_handler(NinjaValidationError)
    def schema_invalid(request, exc):
        fields = {}
        for err in exc.errors:
            fields.setdefault(_field_name(err.get("loc", ())), []).append(err.get("msg", "Invalid."))
        return error_response(api, request, 422, "The request is not valid.", fields)

    @api.exception_handler(ValidationError)
    def domain_invalid(request, exc):
        if hasattr(exc, "error_dict"):
            return error_response(api, request, 422, "The request is not valid.", exc.message_dict)
        return error_response(api, request, 422, " ".join(exc.messages))

    @api.exception_handler(AuthenticationError)
    def unauthenticated(request, exc):
        return error_response(api, request, 401, "Log in first.")

    @api.exception_handler(AuthorizationError)
    def unauthorized(request, exc):
        return error_response(api, request, 403, str(exc.message) if hasattr(exc, "message") else "Forbidden.")

    @api.exception_handler(PermissionDenied)
    def forbidden(request, exc):
        return error_response(api, request, 403, str(exc) or "Forbidden.")

    @api.exception_handler(Http404)
    def not_found(request, exc):
        return error_response(api, request, 404, str(exc) or "Not found.")

    @api.exception_handler(HttpError)
    def http_error(request, exc):
        return error_response(api, request, exc.status_code, str(exc),
                              code=getattr(exc, "code", None), extra=getattr(exc, "extra", None))

    @api.exception_handler(Exception)
    def server_error(request, exc):
        log.exception("API error on %s %s", request.method, request.path)
        return error_response(api, request, 500, "Something went wrong on our side.")


class ApiError(HttpError):
    """Raise from an endpoint for a specific status with extra fields, e.g. a 409 with `received`."""

    def __init__(self, status_code, message, code=None, **extra):
        super().__init__(status_code, message)
        self.code, self.extra = code, extra
