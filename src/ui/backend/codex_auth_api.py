from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openai_codex import Codex

from ui.backend.agent_api import reset_agent_service


DEFAULT_POLL_INTERVAL_SECONDS = 3


@dataclass(slots=True)
class CodexAuthAttempt:
    codex: Any
    handle: Any
    login_id: str
    user_code: str
    verification_uri: str
    status: str = "pending"
    error: str = ""
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _closed: bool = False

    def to_start_payload(self) -> dict[str, object]:
        return {
            "status": "started",
            "userCode": self.user_code,
            "deviceAuthId": self.login_id,
            "verificationUri": self.verification_uri,
            "interval": DEFAULT_POLL_INTERVAL_SECONDS,
        }

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {"status": self.status, "error": self.error}

    def finish(self, *, status: str, error: str = "") -> None:
        with self._lock:
            self.status = status
            self.error = error

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        close = getattr(self.codex, "close", None)
        if callable(close):
            close()


_ATTEMPTS: dict[str, CodexAuthAttempt] = {}
_ATTEMPTS_LOCK = threading.Lock()
_CodexFactory = Callable[[], Any]


def register_codex_auth_routes(app: FastAPI) -> None:
    @app.post("/api/auth/codex/start")
    async def api_start_codex_auth() -> JSONResponse:
        return _json_or_error(lambda: start_codex_auth())

    @app.post("/api/auth/codex/poll")
    async def api_poll_codex_auth(request: Request) -> JSONResponse:
        body = await _json_body(request)
        return _json_or_error(lambda: poll_codex_auth(body))

    @app.post("/api/auth/codex/logout")
    async def api_logout_codex_auth() -> JSONResponse:
        return _json_or_error(lambda: logout_codex_auth())


def get_codex_auth_status(*, codex_factory: _CodexFactory = Codex) -> dict[str, object]:
    try:
        with codex_factory() as codex:
            account = codex.account()
    except Exception as error:
        return _logged_out_status(error=str(error))
    return _account_status_payload(account)


def start_codex_auth(*, codex_factory: _CodexFactory = Codex) -> dict[str, object]:
    codex = codex_factory()
    try:
        handle = codex.login_chatgpt_device_code()
    except Exception:
        _close_codex(codex)
        raise

    attempt = CodexAuthAttempt(
        codex=codex,
        handle=handle,
        login_id=str(getattr(handle, "login_id", "")),
        user_code=str(getattr(handle, "user_code", "")),
        verification_uri=str(getattr(handle, "verification_url", "")),
    )
    if not attempt.login_id or not attempt.user_code or not attempt.verification_uri:
        attempt.close()
        raise RuntimeError("Codex device-code login did not return the expected login details.")

    with _ATTEMPTS_LOCK:
        previous = _ATTEMPTS.pop(attempt.login_id, None)
        _ATTEMPTS[attempt.login_id] = attempt
    _cancel_attempt(previous)

    thread = threading.Thread(target=_wait_for_login, args=(attempt,), daemon=True)
    thread.start()
    return attempt.to_start_payload()


def poll_codex_auth(body: Any, *, codex_factory: _CodexFactory = Codex) -> dict[str, object]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    login_id = _required_text(body.get("deviceAuthId", body.get("device_auth_id")), "deviceAuthId")
    user_code = _required_text(body.get("userCode", body.get("user_code")), "userCode")
    attempt = _attempt(login_id)
    if attempt is None or attempt.user_code != user_code:
        raise ValueError("Codex login attempt was not found.")

    snapshot = attempt.snapshot()
    if snapshot["status"] == "connected":
        _remove_attempt(login_id)
        return {
            "status": "connected",
            "auth": get_codex_auth_status(codex_factory=codex_factory),
        }
    if snapshot["status"] == "error":
        _remove_attempt(login_id)
        raise RuntimeError(snapshot["error"] or "Codex OAuth failed.")
    return {"status": "pending"}


def logout_codex_auth(*, codex_factory: _CodexFactory = Codex) -> dict[str, object]:
    _cancel_all_attempts()
    with codex_factory() as codex:
        codex.logout()
    reset_agent_service()
    return get_codex_auth_status(codex_factory=codex_factory)


def _wait_for_login(attempt: CodexAuthAttempt) -> None:
    try:
        result = attempt.handle.wait()
        if bool(getattr(result, "success", False)):
            attempt.finish(status="connected")
            reset_agent_service()
        else:
            attempt.finish(status="error", error=str(getattr(result, "error", "") or "Codex OAuth failed."))
    except Exception as error:
        attempt.finish(status="error", error=str(error))
    finally:
        attempt.close()


def _account_status_payload(response: Any) -> dict[str, object]:
    account = getattr(response, "account", None)
    if account is None or bool(getattr(response, "requires_openai_auth", False)):
        return _logged_out_status()
    root = getattr(account, "root", account)
    account_type = _enum_value(getattr(root, "type", "")) or type(root).__name__
    return {
        "loggedIn": True,
        "authMode": "chatgpt" if account_type == "chatgpt" else account_type,
        "accountEmail": str(getattr(root, "email", "") or ""),
        "accountId": "",
        "planType": _enum_value(getattr(root, "plan_type", "")),
        "lastRefresh": "",
        "authStorePath": "",
    }


def _logged_out_status(*, error: str = "") -> dict[str, object]:
    payload: dict[str, object] = {
        "loggedIn": False,
        "authMode": "",
        "accountEmail": "",
        "accountId": "",
        "planType": "",
        "lastRefresh": "",
        "authStorePath": "",
    }
    if error:
        payload["error"] = error
    return payload


def _attempt(login_id: str) -> CodexAuthAttempt | None:
    with _ATTEMPTS_LOCK:
        return _ATTEMPTS.get(login_id)


def _remove_attempt(login_id: str) -> CodexAuthAttempt | None:
    with _ATTEMPTS_LOCK:
        return _ATTEMPTS.pop(login_id, None)


def _cancel_all_attempts() -> None:
    with _ATTEMPTS_LOCK:
        attempts = list(_ATTEMPTS.values())
        _ATTEMPTS.clear()
    for attempt in attempts:
        _cancel_attempt(attempt)


def _cancel_attempt(attempt: CodexAuthAttempt | None) -> None:
    if attempt is None:
        return
    cancel = getattr(attempt.handle, "cancel", None)
    if callable(cancel):
        try:
            cancel()
        except Exception:
            pass
    attempt.close()


def _close_codex(codex: Any) -> None:
    close = getattr(codex, "close", None)
    if callable(close):
        close()


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value) or "").strip()


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _json_or_error(callback: Callable[[], dict[str, object]]) -> JSONResponse:
    try:
        return JSONResponse(callback())
    except ValueError as error:
        return JSONResponse({"success": False, "error": str(error), "code": "invalid_request"}, status_code=400)
    except Exception as error:
        return JSONResponse({"success": False, "error": str(error), "code": "codex_auth_failed"}, status_code=400)
