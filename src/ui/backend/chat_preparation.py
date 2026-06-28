from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from agent_prompts import AgentPromptContext, build_agent_instructions, extract_tool_names
from agent_runtime import ATTACHMENT_ONLY_MESSAGE, AgentService, AgentServiceRequest
from agent_runtime.request_config import model_config_for_request
from media import MediaStore, MediaStoreError
from ui.backend.agent_api import get_agent_service
from ui.backend.api_errors import ChatAPIError
from ui.backend.chat_payloads import (
    bool_value,
    file_generation_options,
    image_generation_options,
    is_image_artifact,
    model_options_from_body,
    optional_int,
    optional_text,
    optional_text_list,
    request_message,
    request_metadata,
    session_title,
    user_message_request_metadata,
    visible_annotations,
)

__all__ = [
    "persist_latest_user_request_metadata",
    "prepare_chat_run",
    "prepare_stream_body",
    "system_prompt",
]

@dataclass(frozen=True, slots=True)
class PreparedChatRun:
    service: AgentService
    request: AgentServiceRequest
    attachments: list[dict[str, Any]]
    visible_text: str


def prepare_chat_run(
    body: Any,
    *,
    service: AgentService | None = None,
    media_store: MediaStore,
) -> PreparedChatRun:
    if not isinstance(body, dict):
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    agent_service = service or get_agent_service()
    message = request_message(body)
    attachments = attachment_artifacts(body.get("attachments"), media_store)
    if not message and not attachments:
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "message_required", "Message is required.")

    session_id = optional_text(body.get("sessionId"))
    if bool_value(body.get("editLatestUserMessage")) and session_id:
        truncate_latest_user_turn(agent_service, session_id)

    enable_tools = bool_value(body.get("enableTools"), default=True)
    model_options = model_options_from_body(body)
    model_options["_write_note_media_store"] = media_store
    model_options["_paper_notes_attachments"] = attachments
    if session_id:
        model_options["_paper_notes_session_id"] = session_id
    image_generation = image_generation_options(body)
    if image_generation:
        model_options["_paper_notes_image_generation"] = image_generation
    file_generation = file_generation_options(body)
    if file_generation:
        model_options["_paper_notes_file_generation"] = file_generation
    request = AgentServiceRequest(
        message=message_content(message, attachments, media_store),
        session_id=session_id or None,
        title=session_title(body, message),
        note_id=optional_text(body.get("noteId")) or None,
        provider=optional_text(body.get("provider")),
        model=optional_text(body.get("model")),
        system_prompt=None,
        enable_tools=enable_tools,
        metadata=request_metadata(body),
        model_options=model_options,
        disabled_tools=tuple(optional_text_list(body.get("disabledTools"))),
        run_config=body.get("runConfig") if isinstance(body.get("runConfig"), dict) else None,
        stream_mode=optional_text(body.get("streamMode")) or "values",
    )
    prompt_session = agent_service.session_store.get_session(session_id) if session_id else None
    prompt_model_config = model_config_for_request(
        agent_service.app_config,
        request,
        session=prompt_session,
        media_store=media_store,
    )
    request.system_prompt = system_prompt(
        body,
        tools=agent_service._tools_for_request(request, model_config=prompt_model_config, session=prompt_session),
        model=request.model,
        attachments=attachments,
    )
    return PreparedChatRun(
        service=agent_service,
        request=request,
        attachments=attachments,
        visible_text=message or ATTACHMENT_ONLY_MESSAGE,
    )


def prepare_stream_body(body: Any, *, service: AgentService | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_body", "Request body must be a JSON object.")
    prepared = dict(body)
    session_id = optional_text(prepared.get("sessionId"))
    if session_id or bool_value(prepared.get("editLatestUserMessage")):
        return prepared
    message = request_message(prepared)
    if not message and not prepared.get("attachments"):
        return prepared
    agent_service = service or get_agent_service()
    session = agent_service.session_store.create_session(
        title=session_title(prepared, message),
        note_id=optional_text(prepared.get("noteId")) or None,
        provider=optional_text(prepared.get("provider")) or None,
        model=optional_text(prepared.get("model")) or None,
        metadata=request_metadata(prepared),
    )
    prepared["sessionId"] = session.metadata.session_id
    return prepared


def persist_latest_user_request_metadata(
    service: AgentService,
    session_id: str,
    *,
    attachments: list[dict[str, Any]],
    visible_text: str,
    body: dict[str, Any],
) -> Any:
    session = service.session_store.require_session(session_id)
    metadata_from_request = user_message_request_metadata(body)
    if not attachments and not metadata_from_request:
        return session
    messages = [dict(message) for message in session.messages]
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("role") != "user":
            continue
        metadata = dict(messages[index].get("metadata") or {})
        metadata.update(metadata_from_request)
        if metadata:
            messages[index]["metadata"] = metadata
        if attachments:
            messages[index]["attachments"] = attachments
            messages[index]["text"] = visible_text
        break
    return service.session_store.replace_messages(session_id, messages)


def message_content(message: str, attachments: list[dict[str, Any]], media_store: MediaStore) -> Any:
    context = attachment_context(attachments, media_store)
    text = message or ATTACHMENT_ONLY_MESSAGE
    if context:
        text = f"{text}\n\n{context}"
    image_parts = image_content_parts(attachments, media_store)
    if not image_parts:
        return text
    return [{"type": "text", "text": text}, *image_parts]


def attachment_context(attachments: list[dict[str, Any]], media_store: MediaStore) -> str:
    sections: list[str] = []
    for artifact in attachments:
        if is_image_artifact(artifact):
            sections.append(f"- Image: {artifact.get('fileName') or artifact.get('id')} ({artifact.get('mimeType')})")
            continue
        try:
            extracted = media_store.extracted_text_for_artifact(str(artifact.get("id") or ""))
        except Exception:
            extracted = ""
        heading = f"Attachment: {artifact.get('fileName') or artifact.get('id')} ({artifact.get('mimeType')})"
        sections.append(f"{heading}\n{extracted}".rstrip())
    return "\n\n".join(section for section in sections if section).strip()


def image_content_parts(attachments: list[dict[str, Any]], media_store: MediaStore) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for artifact in attachments:
        if not is_image_artifact(artifact):
            continue
        try:
            data_url = media_store.data_url_for_artifact(str(artifact.get("id") or ""))
        except Exception:
            continue
        parts.append({"type": "image_url", "image_url": {"url": data_url}})
    return parts


def attachment_artifacts(raw_attachments: Any, media_store: MediaStore) -> list[dict[str, Any]]:
    if not isinstance(raw_attachments, list):
        return []
    artifacts: list[dict[str, Any]] = []
    for raw in raw_attachments:
        artifact_id = optional_text(raw.get("id") if isinstance(raw, dict) else raw)
        if not artifact_id:
            continue
        try:
            artifacts.append(media_store.public_artifact(artifact_id))
        except MediaStoreError as error:
            raise ChatAPIError(HTTPStatus.BAD_REQUEST, "invalid_attachment", str(error)) from error
    return artifacts


def truncate_latest_user_turn(service: AgentService, session_id: str) -> None:
    session = service.session_store.require_session(session_id)
    messages = list(session.messages)
    latest_user = -1
    for index, message in enumerate(messages):
        if message.get("role") == "user":
            latest_user = index
    if latest_user >= 0:
        service.session_store.replace_messages(session_id, messages[:latest_user])


def system_prompt(
    body: dict[str, Any],
    *,
    tools: list[Any] | None = None,
    model: str = "",
    attachments: list[dict[str, Any]] | None = None,
) -> str:
    resolved_tools = tools or []
    extra_instructions = "\n\n".join(
        instruction
        for instruction in [
            generation_mode_instructions(body, tools=resolved_tools),
            attachment_image_instructions(attachments or []),
        ]
        if instruction
    )
    return build_agent_instructions(
        tools=resolved_tools,
        context=agent_prompt_context(body),
        extra_instructions=extra_instructions,
        model=model,
    )


def attachment_image_instructions(attachments: list[dict[str, Any]]) -> str:
    if not any(is_image_artifact(artifact) for artifact in attachments):
        return ""
    return (
        "# Attached image handling\n"
        "- The user attached one or more images as visible chat content. For requests to translate, OCR/transcribe, "
        "describe, summarize, explain, or answer questions about those attached images, answer directly from the "
        "attached image content.\n"
        "- Do not call write_note_media, write_note, update_note_metadata, manage_annotations, or inspect_paper_visuals for ordinary "
        "attached-image Q&A. Use Paper Notes tools only if the user explicitly asks to write/update the note, "
        "update note metadata, insert media into the note, change annotations, render/extract a PDF page, or inspect "
        "a paper image that is not already attached.\n"
        "- If you cannot read the attached image content, say so directly instead of trying a note-writing tool."
    )


def generation_mode_instructions(body: dict[str, Any], *, tools: list[Any] | None = None) -> str:
    instructions: list[str] = []
    tool_names = extract_tool_names(tools or [])
    if image_generation_options(body):
        if "create_image_artifact" in tool_names:
            instructions.append(
                "The frontend image generation mode is selected for this turn. Treat it as a strong preference "
                "to create a downloadable image if the user request is compatible. Call `create_image_artifact` "
                "with `prompt`, `mode`, and optional `input_artifact_ids`; do not only describe the image. After "
                "the tool succeeds, briefly describe the result and mention the artifact id if useful, but do not "
                "write raw download URLs or sandbox links; the UI will attach the generated artifact card."
            )
        else:
            instructions.append(
                "The frontend image generation mode is selected for this turn, but `create_image_artifact` is not "
                "available for the current provider/model. Do not call unsupported image tools, do not fabricate "
                "image files, artifact ids, download URLs, Markdown image tags, data URLs, SVG/HTML stand-ins, or "
                "local temp paths. Respond directly to the user in natural language: explain that this current "
                "model cannot generate downloadable images in Paper Notes, and offer a useful text prompt, plan, "
                "or a suggestion to switch to an image-capable OpenAI or Codex model."
            )
    file_generation = file_generation_options(body)
    if file_generation:
        mime_type = str(file_generation.get("mime_type") or "text/markdown")
        if "create_file_artifact" in tool_names:
            instructions.append(
                "The frontend file generation mode is selected for this turn. Treat it as a strong preference "
                "to create a downloadable file if the user request is compatible. Call `create_file_artifact` "
                "with `file_name`, `mime_type`, and `content`; prefer "
                f"`{mime_type}` unless the user asks for a different allowed text format. Do not only paste the "
                "file contents in chat. If the file content depends on the current paper, page, note, or selected "
                "text and you need more source material, first call the relevant local Paper Notes reading/search "
                "tool, then call `create_file_artifact` in the same turn. After the tool succeeds, briefly describe "
                "the file and mention the artifact id if useful, but do not write raw download URLs or sandbox links; "
                "the UI will attach the file card."
            )
        else:
            instructions.append(
                "The frontend file generation mode is selected for this turn, but `create_file_artifact` is not "
                "available. Do not fabricate artifact ids, download URLs, sandbox links, or local paths. Respond "
                "directly in chat, explain that a downloadable file cannot be created in this run, and provide the "
                f"requested `{mime_type}` content inline if that is still useful."
            )
    return "\n".join(instructions)


def agent_prompt_context(body: dict[str, Any]) -> AgentPromptContext | None:
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    note_id = optional_text(
        body.get("noteId")
        or context.get("selectedNoteId")
        or context.get("noteId")
    )
    note_title = optional_text(
        body.get("noteTitle")
        or context.get("selectedNoteTitle")
        or context.get("noteTitle")
    )
    collection_path = optional_text(
        context.get("selectedCategoryName")
        or context.get("collectionPath")
    )
    current_page = optional_int(body.get("currentPage") or context.get("currentPage"))
    selection = optional_text(
        body.get("selectionText")
        or context.get("selectionText")
    )
    annotations = visible_annotations(
        body.get("visibleAnnotations")
        or context.get("visibleAnnotations")
    )
    if not any([note_id, note_title, collection_path, current_page is not None, selection, annotations]):
        return None
    note = {"id": note_id, "title": note_title}
    if collection_path:
        note["collectionPath"] = collection_path
    return AgentPromptContext.from_note(
        note,
        current_page=current_page,
        selection_text=selection,
        visible_annotations=annotations,
        session_title=optional_text(body.get("sessionTitle") or body.get("title")),
    )
