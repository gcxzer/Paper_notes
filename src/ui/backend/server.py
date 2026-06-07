from __future__ import annotations

from typing import Any

import uvicorn
from fastapi import FastAPI

from app_config import load_app_config


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

    return app


app = create_app()


def main() -> None:
    host = str(CONFIG.get("server.host", "127.0.0.1"))
    port = int(CONFIG.get("server.port", 8765))
    print(f"Paper Notes is running at http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
