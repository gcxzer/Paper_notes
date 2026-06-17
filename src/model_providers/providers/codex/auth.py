from __future__ import annotations

import base64
import json
import os
import tempfile
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

__all__ = [
    "DEFAULT_CODEX_BASE_URL",
    "codex_auth_path",
    "codex_default_headers",
    "runtime_codex_credentials",
]

DEFAULT_CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 120
CODEX_CLIENT_HEADERS = {
    "User-Agent": "codex_cli_rs/0.0.0 (Paper Notes)",
    "originator": "codex_cli_rs",
}
CODEX_AUTH_PATH_ENV = "PAPER_NOTES_CODEX_AUTH_PATH"


@dataclass(frozen=True, slots=True)
class CodexCredentials:
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    account_id: str = ""
    base_url: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.access_token or self.refresh_token)


def runtime_codex_credentials(*, auth_path: Any = None) -> CodexCredentials:
    path = codex_auth_path(auth_path)
    payload = _read_auth_payload(path)
    credentials = _credentials_from_auth_payload(payload)
    if credentials.refresh_token and _access_token_is_expiring(credentials.access_token):
        credentials = _refresh_codex_credentials(credentials)
        _write_refreshed_auth_payload(path, payload, credentials)
    return credentials


def codex_auth_path(value: Any = None) -> Path:
    if value:
        return Path(str(value)).expanduser()
    override = os.environ.get(CODEX_AUTH_PATH_ENV, "").strip()
    return Path(override).expanduser() if override else Path.home() / ".codex" / "auth.json"


def codex_default_headers(credentials: CodexCredentials) -> dict[str, str]:
    headers = dict(CODEX_CLIENT_HEADERS)
    account_id = credentials.account_id or chatgpt_account_id(credentials.access_token)
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return headers


def login_codex(*_args: Any, **_kwargs: Any) -> None:
    # Backwards-compatible hook for older tests/integrations. The Responses provider reads the
    # existing Codex auth store and no longer opens an app-server login flow during generation.
    webbrowser.open("https://auth.openai.com/codex/device")


def chatgpt_account_id(token: str) -> str:
    claims = _jwt_claims(token)
    for key in ("https://api.openai.com/auth", "chatgpt_account_id", "account_id"):
        value = claims.get(key)
        if isinstance(value, dict):
            account_id = value.get("chatgpt_account_id") or value.get("account_id")
            if account_id:
                return str(account_id)
        if isinstance(value, str) and value:
            return value
    return ""


def _read_auth_payload(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _credentials_from_auth_payload(payload: dict[str, Any]) -> CodexCredentials:
    tokens = payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {}
    return CodexCredentials(
        access_token=str(tokens.get("access_token") or payload.get("accessToken") or payload.get("access_token") or ""),
        refresh_token=str(tokens.get("refresh_token") or payload.get("refreshToken") or payload.get("refresh_token") or ""),
        id_token=str(tokens.get("id_token") or payload.get("idToken") or payload.get("id_token") or ""),
        account_id=str(tokens.get("account_id") or payload.get("accountId") or payload.get("account_id") or ""),
        base_url=str(tokens.get("base_url") or payload.get("baseUrl") or payload.get("base_url") or DEFAULT_CODEX_BASE_URL),
    )


def _refresh_codex_credentials(credentials: CodexCredentials) -> CodexCredentials:
    status, payload = _post_form(
        CODEX_OAUTH_TOKEN_URL,
        {
            "grant_type": "refresh_token",
            "refresh_token": credentials.refresh_token,
            "client_id": CODEX_OAUTH_CLIENT_ID,
        },
    )
    if status != 200:
        return credentials
    access_token = str(payload.get("access_token") or "")
    if not access_token:
        return credentials
    return CodexCredentials(
        access_token=access_token,
        refresh_token=str(payload.get("refresh_token") or credentials.refresh_token),
        id_token=str(payload.get("id_token") or credentials.id_token),
        account_id=credentials.account_id or chatgpt_account_id(access_token),
        base_url=credentials.base_url or DEFAULT_CODEX_BASE_URL,
    )


def _write_refreshed_auth_payload(path: Path, original: dict[str, Any], credentials: CodexCredentials) -> None:
    payload = dict(original)
    tokens = dict(payload.get("tokens") if isinstance(payload.get("tokens"), dict) else {})
    tokens.update({
        "access_token": credentials.access_token,
        "refresh_token": credentials.refresh_token,
        "id_token": credentials.id_token,
        "account_id": credentials.account_id,
    })
    payload["tokens"] = tokens
    payload["last_refresh"] = datetime.now(timezone.utc).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".codex_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _post_form(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    data = urlencode(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={**CODEX_CLIENT_HEADERS, "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, _parse_json(response.read())
    except HTTPError as error:
        return error.code, _parse_json(error.read())
    except OSError:
        return 0, {}


def _parse_json(data: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(data.decode("utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _access_token_is_expiring(token: str, skew_seconds: int = CODEX_ACCESS_TOKEN_REFRESH_SKEW_SECONDS) -> bool:
    if not token:
        return False
    exp = _jwt_claims(token).get("exp")
    try:
        expires_at = int(exp)
    except (TypeError, ValueError):
        return False
    return time.time() >= expires_at - skew_seconds


def _jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        claims = json.loads(decoded.decode("utf-8"))
    except Exception:
        return {}
    return claims if isinstance(claims, dict) else {}

