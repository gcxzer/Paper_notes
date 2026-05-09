from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.endpoint import URLLib3Session
from botocore.eventstream import EventStreamBuffer
from botocore.exceptions import BotoCoreError, ClientError, ParamValidationError, UnknownServiceError

from . import config


_boto3_session: boto3.Session | None = None
_s3_client = None
_dynamo_resource = None
_bedrock_agent_client = None
_bedrock_agent_runtime_client = None
_agentcore_client = None
_kb_session_ids: dict[str, str] = {}


def _session() -> boto3.Session:
    global _boto3_session
    if _boto3_session is None:
        _require_config("AWS_REGION", config.AWS_REGION)
        if config.AWS_PROFILE:
            _boto3_session = boto3.Session(profile_name=config.AWS_PROFILE, region_name=config.AWS_REGION)
        else:
            _boto3_session = boto3.Session(region_name=config.AWS_REGION)
    return _boto3_session


def _require_config(name: str, value: object) -> None:
    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Missing required configuration {name}. Add it to .env; see .env.example.")


def _s3():
    global _s3_client
    if _s3_client is None:
        _require_config("PAPER_NOTES_BUCKET", config.PAPER_NOTES_BUCKET)
        _s3_client = _session().client("s3", region_name=config.AWS_REGION)
    return _s3_client


def _dynamo():
    global _dynamo_resource
    if _dynamo_resource is None:
        _require_config("PAPER_NOTES_METADATA_TABLE", config.PAPER_NOTES_METADATA_TABLE)
        _dynamo_resource = _session().resource("dynamodb", region_name=config.AWS_REGION)
    return _dynamo_resource


def _bedrock_agent():
    global _bedrock_agent_client
    if _bedrock_agent_client is None:
        _bedrock_agent_client = _session().client("bedrock-agent", region_name=config.AWS_REGION)
    return _bedrock_agent_client


def _bedrock_agent_runtime():
    global _bedrock_agent_runtime_client
    if _bedrock_agent_runtime_client is None:
        _bedrock_agent_runtime_client = _session().client("bedrock-agent-runtime", region_name=config.AWS_REGION)
    return _bedrock_agent_runtime_client


def _agentcore():
    global _agentcore_client
    if _agentcore_client is None:
        _agentcore_client = _session().client("bedrock-agentcore", region_name=config.AWS_REGION)
    return _agentcore_client


def note_cloud_keys(note: dict, original_name: str, html_name: str) -> dict[str, str]:
    return {
        "pdfS3Key": f"papers/{original_name}",
        "noteS3Key": f"notes/{html_name}",
        "annotationS3Key": f"annotations/{note['id']}.json",
        "kbPaperS3Key": f"kb-documents/{note['id']}/paper.pdf",
        "kbNoteS3Key": f"kb-documents/{note['id']}/note.html",
        "kbAnnotationsS3Key": f"kb-documents/{note['id']}/annotations.md",
        "kbMetadataS3Key": f"kb-documents/{note['id']}/metadata.json",
    }


def create_knowledge_base_metadata(note: dict, keys: dict[str, str]) -> dict:
    return {
        "id": note.get("id"),
        "title": note.get("title"),
        "date": note.get("date"),
        "categoryId": note.get("categoryId"),
        "ownerId": config.PAPER_NOTES_OWNER_ID,
        "sourcePdf": f"s3://{config.PAPER_NOTES_BUCKET}/{keys['pdfS3Key']}",
        "sourceNote": f"s3://{config.PAPER_NOTES_BUCKET}/{keys['noteS3Key']}",
        "searchablePdf": f"s3://{config.PAPER_NOTES_BUCKET}/{keys['kbPaperS3Key']}",
        "searchableNote": f"s3://{config.PAPER_NOTES_BUCKET}/{keys['kbNoteS3Key']}",
        "searchableAnnotations": f"s3://{config.PAPER_NOTES_BUCKET}/{keys['kbAnnotationsS3Key']}",
        "searchableDocuments": [
            f"s3://{config.PAPER_NOTES_BUCKET}/{keys['kbPaperS3Key']}",
            f"s3://{config.PAPER_NOTES_BUCKET}/{keys['kbNoteS3Key']}",
            f"s3://{config.PAPER_NOTES_BUCKET}/{keys['kbAnnotationsS3Key']}",
        ],
        "importedAt": datetime.now(timezone.utc).isoformat(),
    }


def put_s3_object(key: str, body: bytes | str, content_type: str) -> None:
    _s3().put_object(Bucket=config.PAPER_NOTES_BUCKET, Key=key, Body=body, ContentType=content_type)


def start_knowledge_base_sync(note: dict) -> dict[str, str]:
    _require_config("PAPER_NOTES_KNOWLEDGE_BASE_ID", config.KNOWLEDGE_BASE_ID)
    _require_config("PAPER_NOTES_KB_DATA_SOURCE_ID", config.KNOWLEDGE_BASE_DATA_SOURCE_ID)
    try:
        result = _bedrock_agent().start_ingestion_job(
            knowledgeBaseId=config.KNOWLEDGE_BASE_ID,
            dataSourceId=config.KNOWLEDGE_BASE_DATA_SOURCE_ID,
            clientToken=str(uuid.uuid4()),
            description=f"Sync Paper Notes import {note['id']}",
        )
        job = result.get("ingestionJob") or {}
        return {
            "kbSyncStatus": job.get("status") or "STARTED",
            "kbIngestionJobId": job.get("ingestionJobId") or "",
        }
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        message = error.response.get("Error", {}).get("Message", str(error))
        if code == "ConflictException":
            return {
                "kbSyncStatus": "SYNC_ALREADY_RUNNING",
                "kbSyncError": "A Knowledge Base sync is already running. This document should be picked up by the next sync.",
            }
        return {"kbSyncStatus": "SYNC_START_FAILED", "kbSyncError": message}
    except Exception as error:
        return {"kbSyncStatus": "SYNC_START_FAILED", "kbSyncError": str(error) or "Knowledge Base sync failed to start."}


def put_dynamo_note(note: dict) -> None:
    table = _dynamo().Table(config.PAPER_NOTES_METADATA_TABLE)
    table.put_item(
        Item={
            "pk": f"OWNER#{config.PAPER_NOTES_OWNER_ID}",
            "sk": f"NOTE#{note.get('id')}",
            "ownerId": config.PAPER_NOTES_OWNER_ID,
            "entityType": "NOTE",
            "id": note.get("id"),
            "title": note.get("title"),
            "href": note.get("href"),
            "htmlHref": note.get("htmlHref"),
            "pdfStorageKey": note.get("pdfStorageKey") or None,
            "pdfS3Key": note.get("pdfS3Key") or None,
            "noteS3Key": note.get("noteS3Key") or None,
            "annotationS3Key": note.get("annotationS3Key") or None,
            "kbPaperS3Key": note.get("kbPaperS3Key") or None,
            "kbNoteS3Key": note.get("kbNoteS3Key") or None,
            "kbAnnotationsS3Key": note.get("kbAnnotationsS3Key") or None,
            "kbMetadataS3Key": note.get("kbMetadataS3Key") or None,
            "kbSyncStatus": note.get("kbSyncStatus") or None,
            "kbIngestionJobId": note.get("kbIngestionJobId") or None,
            "kbSyncError": note.get("kbSyncError") or None,
            "date": note.get("date"),
            "order": note.get("order"),
            "categoryId": note.get("categoryId"),
            "venue": note.get("venue") or None,
            "summary": note.get("summary") or None,
            "tags": note.get("tags") or [],
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        }
    )


def sync_imported_note_to_cloud(
    *,
    note: dict,
    original_name: str,
    html_name: str,
    pdf_buffer: bytes,
    note_html: str,
    annotation_json: str,
    annotations_markdown: str | None = None,
) -> dict:
    if config.DISABLE_CLOUD_SYNC:
        note["kbSyncStatus"] = "DISABLED"
        return note

    keys = note_cloud_keys(note, original_name, html_name)
    note.update(keys)
    annotations_markdown = annotations_markdown or f"# Annotations for {note.get('title') or 'Untitled Paper'}\n\nNo annotations yet.\n"

    try:
        metadata = create_knowledge_base_metadata(note, keys)
        put_s3_object(keys["pdfS3Key"], pdf_buffer, "application/pdf")
        put_s3_object(keys["noteS3Key"], note_html, "text/html; charset=utf-8")
        put_s3_object(keys["annotationS3Key"], annotation_json, "application/json; charset=utf-8")
        put_s3_object(keys["kbPaperS3Key"], pdf_buffer, "application/pdf")
        put_s3_object(keys["kbNoteS3Key"], note_html, "text/html; charset=utf-8")
        put_s3_object(keys["kbAnnotationsS3Key"], annotations_markdown, "text/markdown; charset=utf-8")
        put_s3_object(
            keys["kbMetadataS3Key"],
            f"{json.dumps(metadata, ensure_ascii=False, indent=2)}\n",
            "application/json; charset=utf-8",
        )
        note.update(start_knowledge_base_sync(note))
    except Exception as error:
        note["kbSyncStatus"] = "FAILED"
        note["kbSyncError"] = str(error) or "Cloud sync failed."

    try:
        put_dynamo_note(note)
    except Exception as error:
        note["kbSyncStatus"] = "FAILED" if note.get("kbSyncStatus") == "FAILED" else "METADATA_WRITE_FAILED"
        note["kbSyncError"] = " ".join(filter(None, [note.get("kbSyncError"), str(error) or "DynamoDB metadata write failed."]))

    return note


def format_harness_answer(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"<thinking>[\s\S]*?</thinking>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<cite>\s*[\s\S]*?\s*</cite>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"</?cite>", "", text, flags=re.IGNORECASE)
    text = _strip_source_uri_block(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def retrieve_and_generate_from_kb(session_id: str, prompt: str) -> dict:
    _require_config("PAPER_NOTES_KNOWLEDGE_BASE_ID", config.KNOWLEDGE_BASE_ID)
    _require_config("PAPER_NOTES_GENERATION_MODEL_ARN", config.GENERATION_MODEL_ARN)
    request = {
        "input": {"text": prompt},
        "retrieveAndGenerateConfiguration": {
            "type": "KNOWLEDGE_BASE",
            "knowledgeBaseConfiguration": {
                "knowledgeBaseId": config.KNOWLEDGE_BASE_ID,
                "modelArn": config.GENERATION_MODEL_ARN,
                "retrievalConfiguration": {
                    "vectorSearchConfiguration": {
                        "numberOfResults": config.KB_NUMBER_OF_RESULTS,
                    }
                },
            },
        },
    }
    if _kb_session_ids.get(session_id):
        request["sessionId"] = _kb_session_ids[session_id]

    try:
        result = _bedrock_agent_runtime().retrieve_and_generate(**request)
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code", "")
        message = error.response.get("Error", {}).get("Message", "")
        if code == "ValidationException" and "Session" in message and session_id in _kb_session_ids:
            _kb_session_ids.pop(session_id, None)
            request.pop("sessionId", None)
            result = _bedrock_agent_runtime().retrieve_and_generate(**request)
        else:
            raise

    kb_session_id = result.get("sessionId")
    if kb_session_id:
        _kb_session_ids[session_id] = kb_session_id

    answer = format_harness_answer((result.get("output") or {}).get("text") or "")
    sources = _kb_sources(result.get("citations") or [])

    return {
        "answer": answer.strip(),
        "rawAnswer": answer.strip(),
        "sources": sources,
        "metadata": {
            "backend": "knowledge-base",
            "knowledgeBaseId": config.KNOWLEDGE_BASE_ID,
            "modelArn": config.GENERATION_MODEL_ARN,
            "sources": sources,
        },
    }


def _kb_sources(citations: list[dict]) -> list[dict]:
    sources: list[dict] = []
    seen: set[tuple] = set()
    for citation in citations:
        for reference in citation.get("retrievedReferences") or []:
            source = _source_from_retrieved_reference(reference)
            if not source:
                continue
            key = (source.get("uri"), source.get("page"), source.get("type"))
            if key in seen:
                continue
            seen.add(key)
            sources.append(source)
    return sources


def _source_from_retrieved_reference(reference: dict) -> dict | None:
    location = reference.get("location") or {}
    s3_location = location.get("s3Location") or {}
    uri = normalize_source_uri(s3_location.get("uri"))
    if not uri:
        return None
    content = reference.get("content") or {}
    excerpt = normalize_source_excerpt(content.get("text"))
    metadata = reference.get("metadata") if isinstance(reference.get("metadata"), dict) else {}
    return source_from_uri(uri, excerpt=excerpt, metadata=metadata)


SOURCE_URI_PATTERN = re.compile(r"s3://[^\s<>)\\\"']+", re.IGNORECASE)


def normalize_source_uri(value: object) -> str:
    return str(value or "").strip().rstrip(".,;:")


def normalize_source_excerpt(value: object, max_length: int = 260) -> str:
    excerpt = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(excerpt) <= max_length:
        return excerpt
    return f"{excerpt[: max_length - 1].rstrip()}..."


def _strip_source_uri_block(text: str) -> str:
    lines = text.splitlines()
    output: list[str] = []
    in_sources = False
    for line in lines:
        stripped = line.strip()
        if re.match(r"^(sources?|citations?)\s*:\s*$", stripped, flags=re.IGNORECASE):
            in_sources = True
            continue
        if in_sources and (not stripped or re.match(r"^[-*]\s+s3://", stripped, flags=re.IGNORECASE)):
            continue
        in_sources = False
        output.append(line)
    return "\n".join(output)


def _source_page(metadata: dict, excerpt: str = "") -> int | None:
    for key, value in metadata.items():
        if "page" not in str(key).lower():
            continue
        try:
            page = int(float(str(value)))
        except (TypeError, ValueError):
            continue
        if page > 0:
            return page
    match = re.search(r"(?:^|\s)(?:##\s*)?page\s+(\d+)", excerpt, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _source_type_from_key(key: str) -> str:
    lowered = key.lower()
    if lowered.endswith("/paper.pdf") or lowered.endswith(".pdf"):
        return "pdf"
    if lowered.endswith("/note.html") or lowered.endswith(".html"):
        return "note"
    if lowered.endswith("/annotations.md") or lowered.endswith(".md"):
        return "annotation"
    if lowered.endswith("/metadata.json"):
        return "metadata"
    return "source"


def _source_note_id_from_key(key: str) -> str:
    match = re.search(r"(?:^|/)kb-documents/([^/]+)/", key)
    return match.group(1) if match else ""


def _source_s3_key(uri: str) -> str:
    match = re.match(r"^s3://[^/]+/(.+)$", uri, flags=re.IGNORECASE)
    return match.group(1) if match else ""


def source_from_uri(uri: str, *, excerpt: str = "", metadata: dict | None = None) -> dict:
    key = _source_s3_key(uri)
    source_type = _source_type_from_key(key)
    metadata = metadata or {}
    page = _source_page(metadata, excerpt)
    if source_type == "annotation":
        page = page or _source_page({}, excerpt)
    return {
        "type": source_type,
        "uri": uri,
        "s3Key": key,
        "noteId": _source_note_id_from_key(key),
        "page": page,
        "excerpt": excerpt,
    }


def extract_sources_from_text(value: object) -> list[dict]:
    sources: list[dict] = []
    seen: set[str] = set()
    text = str(value or "")
    for match in SOURCE_URI_PATTERN.finditer(text):
        uri = normalize_source_uri(match.group(0))
        if not uri or uri in seen:
            continue
        seen.add(uri)
        sources.append(source_from_uri(uri))
    return sources


def invoke_harness(
    session_id: str,
    prompt: str = "",
    *,
    messages: list[dict] | None = None,
    tools: list[dict] | None = None,
    allowed_tools: list[str] | None = None,
) -> dict:
    _require_config("PAPER_NOTES_AGENTCORE_HARNESS_ARN", config.HARNESS_ARN)
    payload = {
        "messages": messages
        if messages is not None
        else [
            {
                "role": "user",
                "content": [{"text": prompt}],
            }
        ],
    }
    if config.MEMORY_ACTOR_ID:
        payload["actorId"] = config.MEMORY_ACTOR_ID
    if tools:
        payload["tools"] = tools
    if allowed_tools:
        payload["allowedTools"] = allowed_tools

    try:
        client = _agentcore()
        if hasattr(client, "invoke_harness"):
            result = client.invoke_harness(
                harnessArn=config.HARNESS_ARN,
                runtimeSessionId=session_id,
                **payload,
            )
            return _collect_harness_response(result.get("stream") or [])
    except (UnknownServiceError, AttributeError, ParamValidationError):
        pass

    return _invoke_harness_with_signed_http(session_id, payload)


def _collect_harness_response(stream) -> dict:
    chunks: list[str] = []
    errors: list[str] = []
    tool_uses: list[dict] = []
    active_tool_use = None
    stop_reason = ""
    metadata = None

    for event in stream:
        metadata, active_tool_use, stop_reason = _accumulate_harness_event(
            event,
            chunks,
            errors,
            metadata,
            tool_uses,
            active_tool_use,
            stop_reason,
        )

    if active_tool_use:
        tool_uses.append(_finalize_tool_use(active_tool_use))

    if errors:
        raise RuntimeError("\n".join(errors))

    raw_answer = "".join(chunks)
    sources = _harness_sources(raw_answer, metadata)
    return {
        "answer": format_harness_answer(raw_answer),
        "rawAnswer": raw_answer,
        "sources": sources,
        "metadata": metadata,
        "stopReason": stop_reason,
        "toolUses": tool_uses,
    }


def _harness_sources(raw_answer: str, metadata: object) -> list[dict]:
    sources = extract_sources_from_text(raw_answer)
    if isinstance(metadata, dict):
        raw_sources = metadata.get("sources") or metadata.get("citations")
        if isinstance(raw_sources, list):
            for raw_source in raw_sources:
                if isinstance(raw_source, str):
                    sources.extend(extract_sources_from_text(raw_source))
                elif isinstance(raw_source, dict):
                    uri = normalize_source_uri(raw_source.get("uri") or raw_source.get("sourceUri"))
                    if uri:
                        sources.append(
                            source_from_uri(
                                uri,
                                excerpt=normalize_source_excerpt(raw_source.get("excerpt") or raw_source.get("text")),
                                metadata=raw_source,
                            )
                        )
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for source in sources:
        key = (source.get("uri"), source.get("page"), source.get("type"))
        if not source.get("uri") or key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _accumulate_harness_event(
    event: object,
    chunks: list[str],
    errors: list[str],
    metadata,
    tool_uses: list[dict],
    active_tool_use,
    stop_reason: str,
):
    if not isinstance(event, dict):
        return metadata, active_tool_use, stop_reason

    block_start = event.get("contentBlockStart")
    if isinstance(block_start, dict):
        start = block_start.get("start") if isinstance(block_start.get("start"), dict) else {}
        tool_use = start.get("toolUse") if isinstance(start.get("toolUse"), dict) else None
        if tool_use:
            if active_tool_use:
                tool_uses.append(_finalize_tool_use(active_tool_use))
            active_tool_use = {
                "toolUseId": str(tool_use.get("toolUseId") or ""),
                "name": str(tool_use.get("name") or ""),
                "type": str(tool_use.get("type") or ""),
                "inputText": "",
                "input": tool_use.get("input") if isinstance(tool_use.get("input"), dict) else None,
            }

    delta = event.get("contentBlockDelta", {}).get("delta", {}) if isinstance(event.get("contentBlockDelta"), dict) else {}
    text = delta.get("text")
    if text:
        chunks.append(str(text))

    tool_delta = delta.get("toolUse") if isinstance(delta.get("toolUse"), dict) else None
    if tool_delta:
        if active_tool_use is None:
            active_tool_use = {
                "toolUseId": str(tool_delta.get("toolUseId") or ""),
                "name": str(tool_delta.get("name") or ""),
                "type": str(tool_delta.get("type") or ""),
                "inputText": "",
                "input": None,
            }
        if tool_delta.get("toolUseId"):
            active_tool_use["toolUseId"] = str(tool_delta["toolUseId"])
        if tool_delta.get("name"):
            active_tool_use["name"] = str(tool_delta["name"])
        if tool_delta.get("type"):
            active_tool_use["type"] = str(tool_delta["type"])
        if isinstance(tool_delta.get("input"), dict):
            active_tool_use["input"] = {
                **(active_tool_use.get("input") or {}),
                **tool_delta["input"],
            }
        elif tool_delta.get("input") is not None:
            active_tool_use["inputText"] = str(active_tool_use.get("inputText") or "") + str(tool_delta["input"])

    if "contentBlockStop" in event and active_tool_use:
        tool_uses.append(_finalize_tool_use(active_tool_use))
        active_tool_use = None

    message_stop = event.get("messageStop")
    if isinstance(message_stop, dict):
        stop_reason = str(message_stop.get("stopReason") or stop_reason)

    runtime_error = event.get("runtimeClientError")
    if isinstance(runtime_error, dict) and runtime_error.get("message"):
        errors.append(str(runtime_error["message"]))

    if "metadata" in event:
        metadata = event["metadata"]

    return metadata, active_tool_use, stop_reason


def _finalize_tool_use(tool_use: dict) -> dict:
    input_value = tool_use.get("input") if isinstance(tool_use.get("input"), dict) else None
    input_text = str(tool_use.get("inputText") or "").strip()
    if input_value is None and input_text:
        try:
            input_value = json.loads(input_text)
        except json.JSONDecodeError:
            input_value = {"_raw": input_text}
    return {
        "toolUseId": str(tool_use.get("toolUseId") or ""),
        "name": str(tool_use.get("name") or ""),
        "type": str(tool_use.get("type") or ""),
        "input": input_value or {},
    }


def _invoke_harness_with_signed_http(session_id: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    url = f"https://bedrock-agentcore.{config.AWS_REGION}.amazonaws.com/harnesses/invoke?harnessArn={quote(config.HARNESS_ARN, safe='')}"
    request = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/vnd.amazon.eventstream",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        },
    )
    credentials = _session().get_credentials()
    if credentials is None:
        raise RuntimeError(f"AWS credentials were not found for profile {config.AWS_PROFILE}.")
    SigV4Auth(credentials.get_frozen_credentials(), "bedrock-agentcore", config.AWS_REGION).add_auth(request)

    response = URLLib3Session().send(request.prepare())
    if response.status_code >= 400:
        try:
            payload_json = json.loads(response.text)
            message = payload_json.get("message") or payload_json.get("Message") or response.text
        except Exception:
            message = response.text
        raise RuntimeError(message)

    content_type = str(response.headers.get("content-type", ""))
    if "eventstream" in content_type:
        return _collect_raw_eventstream(response)

    try:
        payload_json = json.loads(response.text)
    except json.JSONDecodeError:
        return {"answer": format_harness_answer(response.text), "rawAnswer": response.text, "metadata": None}

    return _collect_harness_response([payload_json])


def _collect_raw_eventstream(response) -> dict:
    buffer = EventStreamBuffer()
    chunks: list[str] = []
    errors: list[str] = []
    tool_uses: list[dict] = []
    active_tool_use = None
    stop_reason = ""
    metadata = None

    for chunk in response.raw.stream():
        buffer.add_data(chunk)
        while True:
            try:
                message = next(buffer)
            except StopIteration:
                break

            event_type = message.headers.get(":event-type")
            message_type = message.headers.get(":message-type")
            try:
                payload = json.loads(message.payload.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                payload = {"message": message.payload.decode("utf-8", errors="replace")}

            if message_type in {"error", "exception"}:
                errors.append(payload.get("message") or payload.get("Message") or json.dumps(payload))
                continue

            event = {event_type: payload} if event_type and event_type not in payload else payload
            metadata, active_tool_use, stop_reason = _accumulate_harness_event(
                event,
                chunks,
                errors,
                metadata,
                tool_uses,
                active_tool_use,
                stop_reason,
            )

    if active_tool_use:
        tool_uses.append(_finalize_tool_use(active_tool_use))

    if errors:
        raise RuntimeError("\n".join(errors))

    raw_answer = "".join(chunks)
    return {
        "answer": format_harness_answer(raw_answer),
        "rawAnswer": raw_answer,
        "sources": _harness_sources(raw_answer, metadata),
        "metadata": metadata,
        "stopReason": stop_reason,
        "toolUses": tool_uses,
    }


def is_expired_sso_error(error: Exception) -> bool:
    if isinstance(error, (BotoCoreError, ClientError)):
        message = str(error)
    else:
        message = str(error)
    return "Token is expired" in message or "SSO session" in message
