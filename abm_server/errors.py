from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    retryable: bool = False
    action: str = "none"

    def __str__(self) -> str:
        return self.message


def error_body(
    *,
    code: str,
    message: str,
    request_id: str,
    retryable: bool = False,
    action: str = "none",
    details: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {
        "code": code,
        "message": message,
        "requestId": request_id,
        "retryable": retryable,
        "action": action,
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                code=exc.code,
                message=exc.message,
                request_id=getattr(request.state, "request_id", ""),
                retryable=exc.retryable,
                action=exc.action,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        safe_errors = []
        for error in exc.errors():
            safe_errors.append(
                {
                    "location": list(error.get("loc", ())),
                    "message": error.get("msg", "invalid value"),
                    "type": error.get("type", "validation_error"),
                }
            )
        return JSONResponse(
            status_code=400,
            content=error_body(
                code="ABM_VALIDATION_ERROR",
                message="Invalid request parameters.",
                request_id=getattr(request.state, "request_id", ""),
                details=safe_errors,
            ),
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled request error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body(
                code="ABM_INTERNAL_ERROR",
                message="Internal server error.",
                request_id=getattr(request.state, "request_id", ""),
                retryable=True,
                action="wait",
            ),
        )
