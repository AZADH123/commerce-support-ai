"""Domain exceptions translated to HTTP responses by the API layer.

Agent tools catch these and return plain dicts instead, so a business-rule
failure inside the agent is reported to the customer rather than crashing the
pipeline (which would otherwise trigger a spurious retry/escalation).
"""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 400
    code = "service_error"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class NotFound(ServiceError):
    status_code = 404
    code = "not_found"


class Forbidden(ServiceError):
    status_code = 403
    code = "forbidden"


class Conflict(ServiceError):
    status_code = 409
    code = "conflict"


class Unprocessable(ServiceError):
    status_code = 422
    code = "unprocessable"
