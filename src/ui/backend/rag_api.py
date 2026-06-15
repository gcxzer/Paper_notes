from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from dataclasses import field
from typing import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app_config import load_app_config
from rag.service import RAGServiceError, get_rag_service


_RAG_JOB_EVENT_LIMIT = 300
_RAG_JOB_ACTIVE_STATUSES = {"queued", "running", "paused"}
_RAG_JOB_TERMINAL_STATUSES = {"succeeded", "failed"}


@dataclass(slots=True)
class _RagJobEvent:
    seq: int
    event: str
    payload: dict[str, Any]


@dataclass(slots=True)
class _RagIndexJob:
    id: str
    note_id: str
    request_id: str
    body: dict[str, Any]
    status: str = "queued"
    sequence: int = 0
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    events: list[_RagJobEvent] = field(default_factory=list)
    condition: threading.Condition = field(default_factory=lambda: threading.Condition(threading.RLock()))
    pause_gate: threading.Event = field(default_factory=threading.Event)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_RAG_INDEX_JOBS: dict[str, _RagIndexJob] = {}
_RAG_INDEX_JOBS_BY_NOTE: dict[str, str] = {}
_RAG_INDEX_JOBS_LOCK = threading.RLock()


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
            payload = _build_rag_index(body)
        except RAGServiceError as error:
            return _rag_error_response(error)
        except Exception as error:
            return _rag_error_response(RAGServiceError(str(error), code="index_failed"))
        return JSONResponse(payload)

    @app.post("/api/rag/index/stream")
    async def api_rag_index_stream(request: Request) -> StreamingResponse:
        body = await _json_body(request)
        job = _start_or_get_rag_index_job(body)
        return StreamingResponse(
            _rag_job_sse_events(job),
            media_type="text/event-stream; charset=utf-8",
            headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
        )

    @app.get("/api/rag/index/jobs")
    async def api_rag_index_jobs(noteId: str = "", note_id: str = "") -> JSONResponse:
        note_id_value = _text(noteId or note_id)
        if note_id_value:
            job = _latest_rag_job_for_note(note_id_value)
            return JSONResponse({"success": True, "job": _rag_job_summary(job) if job else None})
        return JSONResponse({"success": True, "jobs": [_rag_job_summary(job) for job in _all_rag_jobs()]})

    @app.get("/api/rag/index/jobs/{job_id}/events")
    async def api_rag_index_job_events(job_id: str, after: int = 0):
        job = _get_rag_job(job_id)
        if job is None:
            return _rag_job_not_found_response(job_id)
        return StreamingResponse(
            _rag_job_sse_events(job, after_seq=max(0, after)),
            media_type="text/event-stream; charset=utf-8",
            headers={"Cache-Control": "no-store", "Connection": "keep-alive"},
        )

    @app.post("/api/rag/index/jobs/{job_id}/pause")
    async def api_rag_index_job_pause(job_id: str) -> JSONResponse:
        job = _get_rag_job(job_id)
        if job is None:
            return _rag_job_not_found_response(job_id)
        return JSONResponse({"success": True, "job": _pause_rag_job(job)})

    @app.post("/api/rag/index/jobs/{job_id}/resume")
    async def api_rag_index_job_resume(job_id: str) -> JSONResponse:
        job = _get_rag_job(job_id)
        if job is None:
            return _rag_job_not_found_response(job_id)
        return JSONResponse({"success": True, "job": _resume_rag_job(job)})


def _build_rag_index(
    body: dict[str, Any],
    *,
    progress_callback: Any | None = None,
) -> dict[str, Any]:
    build_config = load_app_config().rag.build
    return get_rag_service().build_index(
        note_id=_text(_first(body, "noteId", "note_id")),
        pdf_path=_first(body, "pdfPath", "pdf_path"),
        index_key=_text(_first(body, "indexKey", "index_key")),
        loader=_optional_text(_first(body, "loader")),
        include_images=_optional_bool(_first(body, "includeImages", "include_images")),
        rebuild=_bool(_first(body, "rebuild")),
        build_qdrant=_optional_bool(_first(body, "buildQdrant", "build_qdrant"), default=build_config.qdrant),
        build_bm25=_optional_bool(_first(body, "buildBm25", "build_bm25"), default=build_config.bm25),
        embedding_provider=_optional_text(_first(body, "embeddingProvider", "embedding_provider")),
        embedding_model=_optional_text(_first(body, "embeddingModel", "embedding_model")),
        caption_images=_optional_bool(_first(body, "captionImages", "caption_images", "imageCaptioningEnabled")),
        caption_provider=_optional_text(_first(body, "captionProvider", "caption_provider")),
        caption_model=_optional_text(_first(body, "captionModel", "caption_model")),
        caption_prompt=_optional_text(_first(body, "captionPrompt", "caption_prompt")),
        caption_max_images=_optional_int(_first(body, "captionMaxImages", "caption_max_images")),
        progress_callback=progress_callback,
    )


async def _rag_job_sse_events(job: _RagIndexJob, *, after_seq: int = 0) -> AsyncIterator[bytes]:
    next_seq = max(1, int(after_seq) + 1)
    while True:
        event = await asyncio.to_thread(_wait_for_rag_job_event, job, next_seq)
        if event is None:
            break
        yield _sse_frame(event.event, event.payload)
        next_seq = event.seq + 1
        if event.event == "done":
            break


def _start_or_get_rag_index_job(body: dict[str, Any]) -> _RagIndexJob:
    request_id = _text(_first(body, "requestId", "request_id")) or f"rag-{uuid4().hex}"
    note_id = _text(_first(body, "noteId", "note_id"))

    with _RAG_INDEX_JOBS_LOCK:
        existing = _latest_rag_job_for_note_locked(note_id)
        if existing is not None and existing.status in _RAG_JOB_ACTIVE_STATUSES:
            return existing

        job = _RagIndexJob(
            id=f"rag-{uuid4().hex}",
            note_id=note_id,
            request_id=request_id,
            body=dict(body),
        )
        job.pause_gate.set()
        _RAG_INDEX_JOBS[job.id] = job
        if note_id:
            _RAG_INDEX_JOBS_BY_NOTE[note_id] = job.id

    _append_rag_job_event(
        job,
        "start",
        {
            "stage": "queued",
            "message": "Starting RAG indexing.",
            "percent": 0,
        },
        status="queued",
    )
    threading.Thread(target=_run_rag_index_job, args=(job,), daemon=True).start()
    return job


def _run_rag_index_job(job: _RagIndexJob) -> None:
    def progress(payload: dict[str, Any]) -> None:
        _wait_if_rag_job_paused(job)
        _append_rag_job_event(job, "progress", dict(payload), status="running")

    try:
        _append_rag_job_event(
            job,
            "progress",
            {"stage": "loading", "message": "Preparing RAG index worker.", "percent": 1},
            status="running",
        )
        payload = _build_rag_index(job.body, progress_callback=progress)
        _append_rag_job_event(job, "final", payload, status="succeeded")
        _append_rag_job_event(
            job,
            "done",
            {"stage": "complete", "message": "RAG indexing complete.", "percent": 100},
            status="succeeded",
        )
    except RAGServiceError as error:
        error_payload = {
            "stage": "error",
            "code": error.code,
            "error": str(error),
            "message": str(error),
            "percent": 100,
        }
        _append_rag_job_event(job, "error", error_payload, status="failed")
        _append_rag_job_event(job, "done", error_payload, status="failed")
    except Exception as error:
        error_payload = {
            "stage": "error",
            "code": "index_failed",
            "error": str(error),
            "message": str(error),
            "percent": 100,
        }
        _append_rag_job_event(job, "error", error_payload, status="failed")
        _append_rag_job_event(job, "done", error_payload, status="failed")
    finally:
        job.pause_gate.set()


def _wait_if_rag_job_paused(job: _RagIndexJob) -> None:
    while not job.pause_gate.is_set():
        job.pause_gate.wait(timeout=0.25)


def _wait_for_rag_job_event(job: _RagIndexJob, next_seq: int) -> _RagJobEvent | None:
    with job.condition:
        while True:
            for event in job.events:
                if event.seq >= next_seq:
                    return event
            if job.status in _RAG_JOB_TERMINAL_STATUSES:
                return None
            job.condition.wait(timeout=30)


def _append_rag_job_event(
    job: _RagIndexJob,
    event: str,
    payload: dict[str, Any],
    *,
    status: str | None = None,
) -> _RagJobEvent:
    with job.condition:
        return _append_rag_job_event_locked(job, event, payload, status=status)


def _append_rag_job_event_locked(
    job: _RagIndexJob,
    event: str,
    payload: dict[str, Any],
    *,
    status: str | None = None,
) -> _RagJobEvent:
    if status is not None:
        job.status = status
    job.updated_at = time.time()

    event_payload = dict(payload)
    event_payload.setdefault("jobId", job.id)
    event_payload.setdefault("requestId", job.request_id)
    event_payload.setdefault("noteId", job.note_id)
    event_payload["status"] = job.status

    if event in {"start", "progress", "done", "error"}:
        job.progress = dict(event_payload)
    if event == "final":
        job.result = dict(event_payload)
    if event == "error":
        job.error = dict(event_payload)

    job.sequence += 1
    event_payload["seq"] = job.sequence
    queued = _RagJobEvent(seq=job.sequence, event=event, payload=event_payload)
    job.events.append(queued)
    if len(job.events) > _RAG_JOB_EVENT_LIMIT:
        del job.events[: len(job.events) - _RAG_JOB_EVENT_LIMIT]
    job.condition.notify_all()
    return queued


def _pause_rag_job(job: _RagIndexJob) -> dict[str, Any]:
    with job.condition:
        if job.status in _RAG_JOB_TERMINAL_STATUSES:
            return _rag_job_summary_locked(job)
        job.pause_gate.clear()
        percent = job.progress.get("percent", 0)
        _append_rag_job_event_locked(
            job,
            "progress",
            {
                "stage": "paused",
                "message": "Indexing paused. Waiting for the current step to reach a checkpoint.",
                "percent": percent,
                "paused": True,
            },
            status="paused",
        )
        return _rag_job_summary_locked(job)


def _resume_rag_job(job: _RagIndexJob) -> dict[str, Any]:
    with job.condition:
        if job.status in _RAG_JOB_TERMINAL_STATUSES:
            return _rag_job_summary_locked(job)
        job.pause_gate.set()
        percent = job.progress.get("percent", 0)
        _append_rag_job_event_locked(
            job,
            "progress",
            {
                "stage": "resuming",
                "message": "Resuming RAG indexing.",
                "percent": percent,
                "paused": False,
            },
            status="running",
        )
        return _rag_job_summary_locked(job)


def _get_rag_job(job_id: str) -> _RagIndexJob | None:
    with _RAG_INDEX_JOBS_LOCK:
        return _RAG_INDEX_JOBS.get(_text(job_id))


def _latest_rag_job_for_note(note_id: str) -> _RagIndexJob | None:
    with _RAG_INDEX_JOBS_LOCK:
        return _latest_rag_job_for_note_locked(note_id)


def _latest_rag_job_for_note_locked(note_id: str) -> _RagIndexJob | None:
    clean_note_id = _text(note_id)
    if not clean_note_id:
        return None
    job_id = _RAG_INDEX_JOBS_BY_NOTE.get(clean_note_id)
    return _RAG_INDEX_JOBS.get(job_id or "")


def _all_rag_jobs() -> list[_RagIndexJob]:
    with _RAG_INDEX_JOBS_LOCK:
        return sorted(_RAG_INDEX_JOBS.values(), key=lambda job: job.updated_at, reverse=True)


def _rag_job_summary(job: _RagIndexJob) -> dict[str, Any]:
    with job.condition:
        return _rag_job_summary_locked(job)


def _rag_job_summary_locked(job: _RagIndexJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "jobId": job.id,
        "noteId": job.note_id,
        "requestId": job.request_id,
        "status": job.status,
        "active": job.status in _RAG_JOB_ACTIVE_STATUSES,
        "seq": job.sequence,
        "progress": dict(job.progress),
        "result": dict(job.result) if job.result is not None else None,
        "error": dict(job.error) if job.error is not None else None,
        "createdAt": job.created_at,
        "updatedAt": job.updated_at,
    }


def _rag_job_not_found_response(job_id: str) -> JSONResponse:
    return JSONResponse(
        {"success": False, "error": f"RAG indexing job not found: {_text(job_id)}", "code": "job_not_found"},
        status_code=404,
    )


def _sse_frame(event: str, payload: dict[str, Any]) -> bytes:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event}\ndata: {data}\n\n".encode("utf-8")


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


def _optional_bool(value: Any, *, default: bool | None = None) -> bool | None:
    if value is None:
        return default
    return _bool(value, default=False)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
