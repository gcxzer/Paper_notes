from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app_infra.paths import RESOURCES_DIR
from app_config import load_app_config
from ui.backend.agent_api import register_agent_routes
from ui.backend.library_api import register_library_routes
from ui.backend.rag_api import register_rag_routes


CONFIG = load_app_config()


def create_app() -> FastAPI:
    app = FastAPI(
        title=str(CONFIG.get("server.title", "Paper Notes")),
        docs_url=CONFIG.get("server.docs_url", "/docs"),
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
    app.mount("/resources", StaticFiles(directory=RESOURCES_DIR), name="resources")

    return app


app = create_app()


def main() -> None:
    host = str(CONFIG.get("server.host", "127.0.0.1"))
    port = int(CONFIG.get("server.port", 8765))
    print(f"Paper Notes is running at http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
