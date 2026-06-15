from __future__ import annotations

from http import HTTPStatus

from fastapi.responses import JSONResponse


class ChatAPIError(ValueError):
    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def chat_error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ChatAPIError):
        return JSONResponse(
            {"success": False, "code": error.code, "error": str(error)},
            status_code=int(error.status),
        )
    return JSONResponse(
        {"success": False, "code": "chat_failed", "error": str(error) or "Chat failed."},
        status_code=HTTPStatus.BAD_REQUEST,
    )


__all__ = ["ChatAPIError", "chat_error_response"]
