from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rag.service import RAGServiceError, get_rag_service


def register_rag_routes(app: FastAPI) -> None:
    @app.get("/api/rag/status")
    async def api_rag_status(
        indexKey: str = "",
        noteId: str = "",
        pdfPath: str = "",
    ) -> JSONResponse:
        try:
            payload = get_rag_service().status(index_key=indexKey, note_id=noteId, pdf_path=pdfPath or None)
        except RAGServiceError as error:
            return _rag_error_response(error)
        return JSONResponse(payload)

    @app.post("/api/rag/index")
    async def api_rag_index(request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            payload = get_rag_service().build_index(
                note_id=_text(_first(body, "noteId", "note_id")),
                pdf_path=_first(body, "pdfPath", "pdf_path"),
                index_key=_text(_first(body, "indexKey", "index_key")),
                loader=_text(_first(body, "loader")) or "pymupdf",
                include_images=_bool(_first(body, "includeImages", "include_images")),
                rebuild=_bool(_first(body, "rebuild")),
                build_qdrant=_bool(_first(body, "buildQdrant", "build_qdrant"), default=True),
                build_bm25=_bool(_first(body, "buildBm25", "build_bm25"), default=True),
                embedding_provider=_text(_first(body, "embeddingProvider", "embedding_provider")) or "ollama",
                embedding_model=_optional_text(_first(body, "embeddingModel", "embedding_model")),
            )
        except RAGServiceError as error:
            return _rag_error_response(error)
        except Exception as error:
            return _rag_error_response(RAGServiceError(str(error), code="index_failed"))
        return JSONResponse(payload)


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _rag_error_response(error: RAGServiceError) -> JSONResponse:
    return JSONResponse(
        {"success": False, "error": str(error), "code": error.code},
        status_code=400,
    )


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)
