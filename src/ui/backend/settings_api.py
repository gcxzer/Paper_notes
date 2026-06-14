from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app_config.ai_settings import (
    OPENAI_PROVIDER,
    delete_local_ai_api_key,
    resolve_ai_settings,
    save_local_ai_settings,
)
from ui.backend.agent_api import reset_agent_service
from ui.backend.codex_auth_api import get_codex_auth_status


def register_settings_routes(app: FastAPI) -> None:
    @app.get("/api/settings/ai")
    async def api_get_ai_settings() -> JSONResponse:
        return _json_or_error(lambda: get_ai_settings())

    @app.post("/api/settings/ai")
    async def api_update_ai_settings(request: Request) -> JSONResponse:
        body = await _json_body(request)
        return _json_or_error(lambda: update_ai_settings(body))

    @app.delete("/api/settings/ai/key")
    async def api_delete_ai_api_key(provider: str = OPENAI_PROVIDER) -> JSONResponse:
        return _json_or_error(lambda: delete_ai_api_key(provider))


def get_ai_settings(*, secrets_path: str | Path | None = None) -> dict[str, object]:
    return resolve_ai_settings(
        secrets_path=secrets_path,
        codex_auth=get_codex_auth_status(),
    ).to_public_dict()


def update_ai_settings(body: Any, *, secrets_path: str | Path | None = None) -> dict[str, object]:
    if not isinstance(body, dict):
        raise ValueError("Request body must be a JSON object.")
    settings = save_local_ai_settings(
        provider=_optional_text(body.get("provider")) if "provider" in body else None,
        model=_optional_text(body.get("model")) if "model" in body else None,
        api_key=_optional_text(body.get("apiKey", body.get("api_key"))) if (
            "apiKey" in body or "api_key" in body
        ) else None,
        api_key_provider=_optional_text(body.get("apiKeyProvider", body.get("api_key_provider"))) if (
            "apiKeyProvider" in body or "api_key_provider" in body
        ) else None,
        secrets_path=secrets_path,
        codex_auth=get_codex_auth_status(),
    )
    reset_agent_service()
    return settings.to_public_dict()


def delete_ai_api_key(
    provider: str = OPENAI_PROVIDER,
    *,
    secrets_path: str | Path | None = None,
) -> dict[str, object]:
    settings = delete_local_ai_api_key(
        provider,
        secrets_path=secrets_path,
        codex_auth=get_codex_auth_status(),
    )
    reset_agent_service()
    return settings.to_public_dict()


def _optional_text(value: Any) -> str:
    return str(value or "").strip()


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
        return JSONResponse({"success": False, "error": str(error), "code": "settings_failed"}, status_code=400)
