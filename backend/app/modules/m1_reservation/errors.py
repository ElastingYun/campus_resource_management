"""Business errors with a stable machine-readable code for M1 clients."""

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class M1Error(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


async def m1_error_handler(_request: Request, exc: M1Error) -> JSONResponse:
    body: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        body["details"] = exc.details
    return JSONResponse({"error": body}, status_code=exc.status_code)
