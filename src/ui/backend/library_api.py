from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from library import delete_note, import_pdf, import_pdf_from_url, read_library, rename_note, update_note_summary, write_library


def register_library_routes(app: FastAPI) -> None:
    @app.get("/api/library")
    async def api_library() -> JSONResponse:
        return JSONResponse({"success": True, "library": read_library()})

    @app.post("/api/library")
    async def api_write_library(request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            library = write_library(_library_payload(body))
        except Exception as error:
            return _library_error_response(error, status_code=400)
        return JSONResponse({"success": True, "library": library})

    @app.post("/api/library/import/pdf")
    async def api_import_pdf(request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            note = import_pdf(body)
        except Exception as error:
            return _library_error_response(error, status_code=400)
        return JSONResponse({"success": True, "note": note, "library": read_library()})

    @app.post("/api/library/import/url")
    async def api_import_url(request: Request) -> JSONResponse:
        body = await _json_body(request)
        try:
            note = import_pdf_from_url(body)
        except Exception as error:
            return _library_error_response(error, status_code=400)
        return JSONResponse({"success": True, "note": note, "library": read_library()})

    @app.post("/api/library/notes/{note_id}/rename")
    async def api_rename_note(note_id: str, request: Request) -> JSONResponse:
        body = await _json_body(request)
        title = _text(body.get("title"))
        if not title:
            return _library_error_response(ValueError("Title is required."), status_code=400)
        note = rename_note(note_id, title)
        if note is None:
            return _library_error_response(ValueError("Note not found."), status_code=404)
        return JSONResponse({"success": True, "note": note, "library": read_library()})

    @app.post("/api/library/notes/{note_id}/summary")
    async def api_update_summary(note_id: str, request: Request) -> JSONResponse:
        body = await _json_body(request)
        note = update_note_summary(note_id, _text(body.get("summary")))
        if note is None:
            return _library_error_response(ValueError("Note not found."), status_code=404)
        return JSONResponse({"success": True, "note": note, "library": read_library()})

    @app.delete("/api/library/notes/{note_id}")
    async def api_delete_note(note_id: str) -> JSONResponse:
        note = delete_note(note_id)
        if note is None:
            return _library_error_response(ValueError("Note not found."), status_code=404)
        return JSONResponse({"success": True, "note": note, "library": read_library()})


async def _json_body(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _library_error_response(error: Exception, *, status_code: int) -> JSONResponse:
    return JSONResponse({"success": False, "error": str(error)}, status_code=status_code)


def _library_payload(body: dict[str, Any]) -> dict[str, Any]:
    payload = body.get("library") if isinstance(body.get("library"), dict) else body
    if not isinstance(payload, dict) or not any(key in payload for key in ("categories", "notes")):
        raise ValueError("Library payload is required.")
    return payload


def _text(value: Any) -> str:
    return str(value or "").strip()
