from __future__ import annotations

import os
import subprocess
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app_infra.formatting import normalize_text
from app_infra.files import NODE_MODULES_DIR, PUBLIC_DIR, RESOURCES_DIR
from app_config import load_app_config
from library import read_annotations, write_annotations
from ui.backend.agent_api import register_agent_routes
from ui.backend.api_errors import api_error_response as _api_error
from ui.backend.chat_api import register_chat_routes
from ui.backend.chat_projects_api import register_chat_project_routes
from ui.backend.codex_auth_api import register_codex_auth_routes
from ui.backend.library_api import register_library_routes
from ui.backend.mcp_api import register_mcp_routes
from ui.backend.model_providers_api import register_model_provider_routes
from ui.backend.rag_api import register_rag_routes
from ui.backend.saved_prompts_api import register_saved_prompt_routes
from ui.backend.scratchpads_api import register_scratchpad_routes
from ui.backend.settings_api import register_settings_routes
from ui.backend.skills_api import register_skills_routes


CONFIG = load_app_config()
FRONTEND_NODE_PACKAGES = ("katex", "lucide-static", "mermaid", "pdfjs-dist")


def create_app() -> FastAPI:
    app = FastAPI(
        title=CONFIG.server.title,
        docs_url=CONFIG.server.docs_url,
        redoc_url=None,
    )

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "configPath": str(CONFIG.path) if CONFIG.path else "",
        }

    register_rag_routes(app)
    register_library_routes(app)
    register_agent_routes(app)
    register_chat_routes(app)
    register_chat_project_routes(app)
    register_codex_auth_routes(app)
    register_mcp_routes(app)
    register_settings_routes(app)
    register_model_provider_routes(app)
    register_skills_routes(app)
    register_scratchpad_routes(app)
    register_saved_prompt_routes(app)

    @app.get("/api/annotations")
    async def api_read_annotations(noteId: str = "") -> JSONResponse:
        payload = read_annotations(noteId)
        if payload is None:
            return _api_error(HTTPStatus.BAD_REQUEST, "noteId_required", "noteId is required.")
        return JSONResponse(payload)

    @app.post("/api/annotations")
    async def api_write_annotations(request: Request) -> JSONResponse:
        body = await _read_json_body(request)
        payload = write_annotations(body.get("noteId"), body.get("annotations")) if isinstance(body, dict) else None
        if payload is None:
            return _api_error(HTTPStatus.BAD_REQUEST, "noteId_required", "noteId is required.")
        return JSONResponse(payload)

    @app.post("/api/open-local-file")
    async def api_open_local_file(request: Request) -> JSONResponse:
        if request.headers.get("X-Paper-Notes-Local-Action") != "open-local-file":
            return _api_error(
                HTTPStatus.FORBIDDEN,
                "missing_local_action_header",
                "Local file open requests require a trusted reader header.",
            )
        body = await _read_json_body(request)
        if not isinstance(body, dict):
            return _api_error(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
        raw_target = normalize_text(body.get("path") or body.get("href"))
        if not raw_target:
            return _api_error(HTTPStatus.BAD_REQUEST, "path_required", "path is required.")
        parsed = urlparse(raw_target)
        if parsed.scheme and parsed.scheme != "file":
            return _api_error(
                HTTPStatus.BAD_REQUEST,
                "unsupported_scheme",
                "Only local filesystem paths can be opened.",
            )
        raw_path = unquote(parsed.path if parsed.scheme == "file" else raw_target)
        target = Path(raw_path).expanduser()
        if not target.is_absolute():
            return _api_error(
                HTTPStatus.BAD_REQUEST,
                "absolute_path_required",
                "Local file links must use an absolute path.",
            )
        target = target.resolve()
        if not target.exists():
            return _api_error(HTTPStatus.NOT_FOUND, "file_not_found", f"File not found: {target}")
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            elif os.name == "nt":
                os.startfile(str(target))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as error:
            return _api_error(HTTPStatus.INTERNAL_SERVER_ERROR, "open_failed", str(error))
        return JSONResponse({"success": True, "path": str(target)})

    app.mount("/resources", StaticFiles(directory=RESOURCES_DIR), name="resources")
    for package_name in FRONTEND_NODE_PACKAGES:
        package_dir = NODE_MODULES_DIR / package_name
        if package_dir.exists():
            app.mount(
                f"/node_modules/{package_name}",
                StaticFiles(directory=package_dir),
                name=f"node_modules_{package_name.replace('-', '_')}",
            )
    app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="frontend")

    return app


app = create_app()


async def _read_json_body(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return {}


def main() -> None:
    host = os.environ.get("HOST") or CONFIG.server.host
    port = int(os.environ.get("PORT") or CONFIG.server.port)
    print(f"Paper Notes is running at http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
