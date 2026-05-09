from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from . import config
from .aws_services import invoke_harness, is_expired_sso_error, retrieve_and_generate_from_kb, sync_imported_note_to_cloud
from .chat_sessions import (
    append_chat_message,
    create_chat_session,
    delete_chat_session_permanently,
    ensure_chat_session,
    get_chat_session,
    get_chat_session_jsonl_path,
    list_chat_sessions,
    normalize_session_id,
    rename_chat_session,
    restore_chat_session,
    trash_chat_session,
)
from .chat_progress import (
    complete_chat_progress,
    fail_chat_progress,
    get_chat_progress,
    normalize_request_id,
    set_chat_progress,
)
from .local_tools import run_harness_with_local_tools
from .note_editor import (
    extract_note_body_html,
    replace_note_body_html,
)
from .storage import (
    BASE_LIBRARY,
    annotation_path_for,
    create_annotations_markdown,
    create_paper_note_html,
    encoded_project_path,
    escape_html,
    get_today_label,
    is_within,
    note_id_from_title,
    note_title_from_pdf,
    normalize_text,
    project_path_from_href,
    read_library,
    safe_file_name,
    sanitize_library,
    write_library,
)


app = FastAPI(title="Paper Notes")


@app.middleware("http")
async def add_common_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET,HEAD,POST,PATCH,DELETE,OPTIONS"
    return response


@app.options("/{path:path}")
async def options_handler(path: str) -> Response:
    return Response(status_code=204)


@app.get("/api/health")
async def health() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "backend": "python-fastapi",
            "version": "0.1.0",
            "awsProfile": config.AWS_PROFILE,
            "awsRegion": config.AWS_REGION,
            "chatBackend": config.CHAT_BACKEND,
            "memoryActorIdConfigured": bool(config.MEMORY_ACTOR_ID),
            "cloudSyncDisabled": config.DISABLE_CLOUD_SYNC,
        }
    )


@app.get("/api/chat-progress")
async def chat_progress(requestId: str = "") -> Response:
    request_id = normalize_request_id(requestId)
    if not request_id:
        return PlainTextResponse("requestId is required.", status_code=400)
    progress = get_chat_progress(request_id)
    return JSONResponse(progress or {"requestId": request_id, "status": "unknown", "events": []})


@app.post("/api/import-pdf")
async def import_pdf(request: Request) -> Response:
    body = await read_json_body(request)
    original_name = safe_file_name(body.get("fileName"))
    if not original_name.lower().endswith(".pdf"):
        return PlainTextResponse("Only PDF files can be imported.", status_code=400)

    try:
        pdf_buffer = base64.b64decode(str(body.get("dataBase64") or ""))
    except Exception:
        return PlainTextResponse("PDF data is not valid base64.", status_code=400)

    if not pdf_buffer:
        return PlainTextResponse("PDF file is empty.", status_code=400)

    config.PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    config.HTML_DIR.mkdir(parents=True, exist_ok=True)
    config.ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)

    html_name = f"{Path(original_name).stem}.html"
    title = note_title_from_pdf(original_name)
    date_label = get_today_label()
    note_html = create_paper_note_html(title=title, date_label=date_label, file_name=original_name)
    annotation_json = f"{json.dumps({'annotations': []}, ensure_ascii=False, indent=2)}\n"

    library = read_library()
    library["categories"] = library.get("categories") if isinstance(library.get("categories"), list) else BASE_LIBRARY["categories"]
    library["notes"] = library.get("notes") if isinstance(library.get("notes"), list) else []
    existing_notes = [
        note
        for note in library["notes"]
        if note.get("href") != encoded_project_path("Papers", original_name)
        and note.get("htmlHref") != encoded_project_path("Paper-html", html_name)
    ]
    next_order = max(
        [float(note.get("order", index)) for index, note in enumerate(existing_notes)] + [-1],
    ) + 1
    note = {
        "id": note_id_from_title(title),
        "title": title,
        "href": encoded_project_path("Papers", original_name),
        "htmlHref": encoded_project_path("Paper-html", html_name),
        "pdfStorageKey": "",
        "date": date_label,
        "order": next_order,
        "categoryId": normalize_text(body.get("categoryId")) or "uncategorized",
        "venue": "",
        "summary": "",
        "tags": [],
    }

    (config.PAPERS_DIR / original_name).write_bytes(pdf_buffer)
    (config.HTML_DIR / html_name).write_text(note_html, encoding="utf-8")
    (config.ANNOTATIONS_DIR / f"{note['id']}.json").write_text(annotation_json, encoding="utf-8")

    await asyncio.to_thread(
        sync_imported_note_to_cloud,
        note=note,
        original_name=original_name,
        html_name=html_name,
        pdf_buffer=pdf_buffer,
        note_html=note_html,
        annotation_json=annotation_json,
    )

    library["notes"] = existing_notes + [note]
    write_library(library)

    return JSONResponse(note, status_code=201)


@app.post("/api/rename-note")
async def rename_note(request: Request) -> Response:
    body = await read_json_body(request)
    note_id = normalize_text(body.get("id"))
    next_title = normalize_text(body.get("title"))

    if not note_id or not next_title:
        return PlainTextResponse("Note id and title are required.", status_code=400)

    library = read_library()
    note = next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)
    if not note:
        return PlainTextResponse("Note not found.", status_code=404)

    note["title"] = next_title
    write_library(library)

    html_href = normalize_text(note.get("htmlHref"))
    if html_href:
        html_path = project_path_from_href(html_href)
        if is_within(html_path, config.HTML_DIR):
            try:
                safe_title = escape_html(next_title)
                note_html = html_path.read_text(encoding="utf-8")
                note_html = re.sub(r"<title>[\s\S]*?</title>", f"<title>{safe_title}</title>", note_html, count=1, flags=re.I)
                note_html = re.sub(r"<h1>[\s\S]*?</h1>", f"<h1>{safe_title}</h1>", note_html, count=1, flags=re.I)
                html_path.write_text(note_html, encoding="utf-8")
            except Exception as error:
                print(f"Could not update note HTML title for {note_id}: {error}")

    return JSONResponse(note)


@app.post("/api/update-note-summary")
async def update_note_summary(request: Request) -> Response:
    body = await read_json_body(request)
    note_id = normalize_text(body.get("id"))
    summary = normalize_text(body.get("summary"))

    if not note_id:
        return PlainTextResponse("Note id is required.", status_code=400)

    library = read_library()
    note = next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)
    if not note:
        return PlainTextResponse("Note not found.", status_code=404)

    note["summary"] = summary
    write_library(library)
    return JSONResponse(note)


@app.post("/api/library")
async def write_library_route(request: Request) -> JSONResponse:
    body = await read_json_body(request)
    return JSONResponse(write_library(sanitize_library(body)))


@app.post("/api/sync-note-rag")
async def sync_note_rag(request: Request) -> Response:
    body = await read_json_body(request)
    note_id = normalize_text(body.get("noteId"))
    if not note_id:
        return PlainTextResponse("noteId is required.", status_code=400)

    library = read_library()
    note = next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)
    if not note:
        return PlainTextResponse("Note not found.", status_code=404)

    pdf_path = project_path_from_href(normalize_text(note.get("href")))
    if not is_within(pdf_path, config.PAPERS_DIR) or not pdf_path.is_file():
        return PlainTextResponse("Local PDF file not found.", status_code=404)

    html_path = project_path_from_href(normalize_text(note.get("htmlHref")))
    if not is_within(html_path, config.HTML_DIR) or not html_path.is_file():
        return PlainTextResponse("Local HTML note file not found.", status_code=404)

    annotations_path = annotation_path_for(note_id)
    annotation_json = "{\"annotations\": []}\n"
    if annotations_path and annotations_path.exists():
        annotation_json = annotations_path.read_text(encoding="utf-8")

    try:
        annotation_body = json.loads(annotation_json)
    except json.JSONDecodeError:
        annotation_body = {"annotations": []}
        annotation_json = f"{json.dumps(annotation_body, ensure_ascii=False, indent=2)}\n"

    annotations = annotation_body.get("annotations") if isinstance(annotation_body, dict) else []
    annotations_markdown = create_annotations_markdown(note, annotations if isinstance(annotations, list) else [])

    note["kbSyncStatus"] = "SYNCING"
    note["kbSyncError"] = ""
    write_library(library)

    await asyncio.to_thread(
        sync_imported_note_to_cloud,
        note=note,
        original_name=pdf_path.name,
        html_name=html_path.name,
        pdf_buffer=pdf_path.read_bytes(),
        note_html=html_path.read_text(encoding="utf-8"),
        annotation_json=annotation_json,
        annotations_markdown=annotations_markdown,
    )

    write_library(library)
    return JSONResponse(note)


@app.get("/api/chat-sessions")
async def read_chat_sessions(noteId: str = "", trashed: str = "") -> Response:
    note_id = normalize_text(noteId)
    if not note_id:
        return PlainTextResponse("noteId is required.", status_code=400)
    return JSONResponse({"sessions": list_chat_sessions(note_id, trashed=trashed in {"1", "true", "yes"})})


@app.post("/api/chat-sessions")
async def create_chat_session_route(request: Request) -> Response:
    body = await read_json_body(request)
    note_id = normalize_text(body.get("noteId"))
    if not note_id:
        return PlainTextResponse("noteId is required.", status_code=400)
    session = create_chat_session(note_id=note_id, title=body.get("title"))
    return JSONResponse(session, status_code=201)


@app.get("/api/chat-sessions/{session_id}")
async def read_chat_session(session_id: str) -> Response:
    session = get_chat_session(session_id)
    if not session:
        return PlainTextResponse("Chat session not found.", status_code=404)
    return JSONResponse(session)


@app.get("/api/chat-sessions/{session_id}/export")
async def export_chat_session(session_id: str) -> Response:
    path = get_chat_session_jsonl_path(session_id)
    if not path:
        return PlainTextResponse("Chat session not found.", status_code=404)
    return FileResponse(path, media_type="application/x-ndjson", filename=path.name)


@app.post("/api/apply-note-edit")
async def apply_note_edit(request: Request) -> Response:
    body = await read_json_body(request)
    note_id = normalize_text(body.get("noteId"))
    replacement_html = str(body.get("replacementHtml") or "").strip()
    if not note_id:
        return PlainTextResponse("noteId is required.", status_code=400)
    if not replacement_html:
        return PlainTextResponse("replacementHtml is required.", status_code=400)

    library = read_library()
    note = next((entry for entry in library.get("notes", []) if entry.get("id") == note_id), None)
    if not note:
        return PlainTextResponse("Note not found.", status_code=404)

    html_path = project_path_from_href(normalize_text(note.get("htmlHref")))
    if not is_within(html_path, config.HTML_DIR) or not html_path.is_file():
        return PlainTextResponse("Local HTML note file not found.", status_code=404)

    try:
        current_html = html_path.read_text(encoding="utf-8")
        updated_html = replace_note_body_html(current_html, replacement_html)
        note_body_html = extract_note_body_html(updated_html)
    except ValueError as error:
        return PlainTextResponse(str(error), status_code=400)

    html_path.write_text(updated_html, encoding="utf-8")
    note["kbSyncStatus"] = "LOCAL_NOTE_CHANGED"
    note["kbSyncError"] = "Local note changed. Use Settings > Sync RAG to update the Knowledge Base."
    write_library(library)
    return JSONResponse(
        {
            "ok": True,
            "noteId": note_id,
            "htmlHref": note.get("htmlHref"),
            "noteBodyHtml": note_body_html,
            "note": note,
        }
    )


@app.patch("/api/chat-sessions/{session_id}")
async def rename_chat_session_route(session_id: str, request: Request) -> Response:
    body = await read_json_body(request)
    title = normalize_text(body.get("title"))
    if not title:
        return PlainTextResponse("Session title is required.", status_code=400)
    session = rename_chat_session(session_id, title)
    if not session:
        return PlainTextResponse("Chat session not found.", status_code=404)
    return JSONResponse(session)


@app.delete("/api/chat-sessions/{session_id}")
async def delete_chat_session_route(session_id: str) -> Response:
    session = trash_chat_session(session_id)
    if not session:
        return PlainTextResponse("Chat session not found.", status_code=404)
    return JSONResponse({"ok": True, "session": session})


@app.post("/api/chat-sessions/{session_id}/restore")
async def restore_chat_session_route(session_id: str) -> Response:
    session = restore_chat_session(session_id)
    if not session:
        return PlainTextResponse("Chat session not found.", status_code=404)
    return JSONResponse(session)


@app.delete("/api/chat-sessions/{session_id}/permanent")
async def permanently_delete_chat_session_route(session_id: str) -> Response:
    if not delete_chat_session_permanently(session_id):
        return PlainTextResponse("Chat session not found.", status_code=404)
    return JSONResponse({"ok": True})


@app.post("/api/chat")
async def chat(request: Request) -> Response:
    body = await read_json_body(request)
    message = normalize_text(body.get("message"))
    if not message:
        return PlainTextResponse("Message is required.", status_code=400)
    request_id = normalize_request_id(body.get("requestId"))
    set_chat_progress(request_id, "received", "Received your question.")

    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    note_id = normalize_text(context.get("selectedNoteId")) or normalize_text(body.get("noteId")) or "workspace"
    set_chat_progress(request_id, "session", "Loading the chat session.")
    chat_session = ensure_chat_session(body.get("sessionId"), note_id, first_message=message)
    session_id = chat_session["id"]
    agent_session_id = normalize_session_id(chat_session.get("agentSessionId")) or session_id
    append_chat_message(session_id, "user", message)

    context_lines = []
    selected_note_title = normalize_text(context.get("selectedNoteTitle"))
    selected_category_name = normalize_text(context.get("selectedCategoryName"))
    if selected_note_title:
        context_lines.append(f"Selected note in the web app: {selected_note_title}")
    if selected_category_name:
        context_lines.append(f"Active collection in the web app: {selected_category_name}")

    prompt = f"{chr(10).join(context_lines)}\n\nUser question: {message}" if context_lines else message

    def report_progress(stage: str, detail: str) -> None:
        set_chat_progress(request_id, stage, detail)

    try:
        chat_backend = config.CHAT_BACKEND
        if chat_backend in {"knowledge-base", "knowledge_base", "kb"}:
            report_progress("rag", "Querying Bedrock Knowledge Base.")
            result = await asyncio.to_thread(retrieve_and_generate_from_kb, agent_session_id, prompt)
            report_progress("answer", "Knowledge Base returned an answer.")
        else:
            result = await asyncio.to_thread(
                run_harness_with_local_tools,
                session_id=agent_session_id,
                user_message=message,
                note_id=note_id,
                context_lines=context_lines,
                invoke_model=invoke_harness,
                progress=report_progress,
            )
        answer = normalize_text(result.get("answer")) or "No answer returned."
        sources = result.get("sources") if isinstance(result.get("sources"), list) else []
        note_edit = result.get("noteEdit") if isinstance(result.get("noteEdit"), dict) else None
        result["answer"] = answer
        result["sources"] = sources
        if note_edit:
            result["noteEdit"] = note_edit
        report_progress("saving", "Saving the assistant response to the local session.")
        append_chat_message(session_id, "assistant", answer, sources=sources, note_edit=note_edit)
        complete_chat_progress(request_id, "Answer ready.")
        return JSONResponse({"ok": True, "sessionId": session_id, "agentSessionId": agent_session_id, **result})
    except Exception as error:
        status_code = 401 if is_expired_sso_error(error) else 500
        error_message = (
            f"AWS SSO session expired. Run: aws sso login --profile {config.AWS_PROFILE or '<your-profile>'}"
            if status_code == 401
            else str(error) or "Agent request failed."
        )
        fail_chat_progress(request_id, error_message)
        append_chat_message(
            session_id,
            "assistant",
            "I could not reach the agent. Check that the local server is running and AWS SSO is logged in.",
            error=True,
        )
        return JSONResponse(
            {"ok": False, "sessionId": session_id, "agentSessionId": agent_session_id, "error": error_message},
            status_code=status_code,
        )


@app.get("/api/annotations")
async def read_annotations(noteId: str = "") -> Response:
    annotations_path = annotation_path_for(noteId)
    if not annotations_path:
        return PlainTextResponse("noteId is required.", status_code=400)

    try:
        return Response(annotations_path.read_text(encoding="utf-8"), media_type="application/json; charset=utf-8")
    except FileNotFoundError:
        return JSONResponse({"annotations": []})


@app.post("/api/annotations")
async def write_annotations(request: Request) -> Response:
    body = await read_json_body(request)
    annotations_path = annotation_path_for(body.get("noteId"))
    if not annotations_path:
        return PlainTextResponse("noteId is required.", status_code=400)

    annotations = body.get("annotations") if isinstance(body.get("annotations"), list) else []
    config.ANNOTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    annotations_path.write_text(f"{json.dumps({'annotations': annotations}, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
    return JSONResponse({"annotations": annotations})


@app.api_route("/{requested_path:path}", methods=["GET", "HEAD"])
async def serve_static(requested_path: str) -> Response:
    safe_path = requested_path or "index.html"
    target = (config.ROOT / safe_path).resolve(strict=False)

    if not is_within(target, config.ROOT):
        return PlainTextResponse("Forbidden", status_code=403)
    if not target.is_file():
        return PlainTextResponse("Not found", status_code=404)

    media_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
    if target.suffix == ".js":
        media_type = "text/javascript; charset=utf-8"
    elif target.suffix in {".html", ".css", ".json"}:
        media_type = f"{media_type}; charset=utf-8"
    return FileResponse(target, media_type=media_type)


async def read_json_body(request: Request) -> dict[str, Any]:
    body = await request.body()
    if len(body) > config.MAX_BODY_SIZE:
        raise ValueError("Request body is too large.")
    if not body:
        return {}
    return json.loads(body.decode("utf-8"))
