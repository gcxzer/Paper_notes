from __future__ import annotations

from http import HTTPStatus

from fastapi.responses import JSONResponse

__all__ = [
    "ChatAPIError",
    "api_error_response",
    "chat_error_response",
]

class ChatAPIError(ValueError):
    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def api_error_response(status: HTTPStatus, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        {"success": False, "code": code, "error": message},
        status_code=int(status),
    )


def chat_error_response(error: Exception) -> JSONResponse:
    if isinstance(error, ChatAPIError):
        return api_error_response(error.status, error.code, str(error))
    return api_error_response(HTTPStatus.BAD_REQUEST, "chat_failed", str(error) or "Chat failed.")

