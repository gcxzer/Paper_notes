from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any, Callable

from app_config import load_app_config
from app_config.ai_settings import CODEX_PROVIDER, OPENAI_PROVIDER, normalize_ai_provider, resolve_openai_api_key
from app_infra.formatting import normalize_text
from model_providers.providers.codex.auth import (
    DEFAULT_CODEX_BASE_URL,
    codex_default_headers,
    runtime_codex_credentials,
)


def caption_image_records(
    image_records: list[dict],
    *,
    provider: str | None = None,
    model: str | None = None,
    prompt: str | None = None,
    max_images: int | None = None,
    max_image_bytes: int | None = None,
    timeout: float | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict]:
    """Caption extracted PDF images so they can be indexed as ordinary text."""
    if not image_records:
        return []

    config = load_app_config().rag.image_captioning
    resolved_provider = _caption_provider(provider or config.provider)
    resolved_model = normalize_text(model or config.model)
    resolved_prompt = normalize_text(prompt or config.prompt)
    resolved_max_images = config.max_images if max_images is None else max(0, int(max_images))
    resolved_max_image_bytes = config.max_image_bytes if max_image_bytes is None else max(1, int(max_image_bytes))
    resolved_timeout = config.timeout if timeout is None else max(1.0, float(timeout))

    if not resolved_provider:
        raise ValueError("Image captioning provider must be 'openai' or 'codex-oauth'.")
    if not resolved_model:
        raise ValueError("Image captioning model is required.")
    if resolved_max_images <= 0:
        return []

    images_to_caption = image_records[:resolved_max_images]
    _report_progress(
        progress_callback,
        stage="captioning",
        message=f"Captioning {len(images_to_caption)} extracted images.",
        percent=30,
        current=0,
        total=len(images_to_caption),
    )
    client = _caption_client(resolved_provider, timeout=resolved_timeout)
    captioned_records: list[dict] = []
    total = len(images_to_caption)
    for index, image_record in enumerate(images_to_caption, start=1):
        image_path = Path(image_record["image_path"])
        if not image_path.is_file():
            print(f"Skipping image captioning; file does not exist: {image_path}")
            _report_caption_step(progress_callback, index=index, total=total, skipped=True)
            continue
        if image_path.stat().st_size > resolved_max_image_bytes:
            print(f"Skipping image captioning; image exceeds max bytes: {image_path}")
            _report_caption_step(progress_callback, index=index, total=total, skipped=True)
            continue

        _report_caption_step(progress_callback, index=index, total=total)
        caption = _caption_one_image(
            client,
            model=resolved_model,
            image_record=image_record,
            prompt=resolved_prompt,
            stream=resolved_provider == CODEX_PROVIDER,
        )
        if not caption:
            _report_caption_step(progress_callback, index=index, total=total, skipped=True)
            continue

        captioned_records.append({
            **image_record,
            "caption": caption,
            "caption_provider": resolved_provider,
            "caption_model": resolved_model,
            "caption_generated": True,
        })
        _report_caption_step(progress_callback, index=index, total=total, completed=True)

    _report_progress(
        progress_callback,
        stage="captioning",
        message=f"Generated {len(captioned_records)} image captions.",
        percent=44,
        current=len(captioned_records),
        total=total,
    )
    return captioned_records


def _caption_client(provider: str, *, timeout: float) -> Any:
    from openai import OpenAI

    if provider == OPENAI_PROVIDER:
        api_key = resolve_openai_api_key().value
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI image captioning.")
        return OpenAI(api_key=api_key, timeout=timeout)

    if provider == CODEX_PROVIDER:
        credentials = runtime_codex_credentials()
        if not credentials.access_token:
            raise RuntimeError("Codex OAuth is not connected. Open Settings > AI Provider and connect Codex OAuth.")
        return OpenAI(
            api_key=credentials.access_token,
            base_url=(credentials.base_url or DEFAULT_CODEX_BASE_URL).rstrip("/"),
            default_headers=codex_default_headers(credentials),
            timeout=timeout,
        )

    raise ValueError("Image captioning provider must be 'openai' or 'codex-oauth'.")


def _caption_one_image(client: Any, *, model: str, image_record: dict, prompt: str, stream: bool = False) -> str:
    payload = _caption_request_payload(model=model, image_record=image_record, prompt=prompt)
    if stream:
        return _caption_one_image_streaming(client, payload)

    response = client.responses.create(**payload)
    return _response_text(response)


def _caption_request_payload(*, model: str, image_record: dict, prompt: str) -> dict[str, Any]:
    image_path = Path(image_record["image_path"])
    page_number = image_record.get("page_number")
    image_index = image_record.get("image_index")
    source_hint = (
        f"Source: page {page_number}, image {image_index}."
        if page_number is not None
        else f"Source: image {image_index}; page number was not provided by the parser."
    )
    existing_caption = normalize_text(image_record.get("caption"))
    if existing_caption:
        source_hint = f"{source_hint}\nExisting PDF caption/OCR hint: {existing_caption}"

    return {
        "model": model,
        "instructions": prompt,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": source_hint},
                    {"type": "input_image", "image_url": _image_data_url(image_path, image_record.get("content_type"))},
                ],
            }
        ],
        "store": False,
    }


def _caption_one_image_streaming(client: Any, payload: dict[str, Any]) -> str:
    responses = getattr(client, "responses", None)
    stream_factory = getattr(responses, "stream", None)
    if callable(stream_factory):
        collected_text_deltas: list[str] = []
        final_response = None
        terminal_response = None
        with stream_factory(**payload) as stream:
            for event in stream:
                _collect_stream_event(event, collected_text_deltas)
                if str(_get_value(event, "type") or "") in {"response.completed", "response.incomplete", "response.failed"}:
                    terminal_response = _get_value(event, "response") or terminal_response
            get_final_response = getattr(stream, "get_final_response", None)
            if callable(get_final_response):
                final_response = get_final_response()

        text = _response_text(final_response or terminal_response)
        return text or "".join(collected_text_deltas).strip()

    response_stream = responses.create(**payload, stream=True)
    collected_text_deltas: list[str] = []
    terminal_response = None
    for event in response_stream:
        _collect_stream_event(event, collected_text_deltas)
        if str(_get_value(event, "type") or "") in {"response.completed", "response.incomplete", "response.failed"}:
            terminal_response = _get_value(event, "response") or terminal_response
    text = _response_text(terminal_response)
    return text or "".join(collected_text_deltas).strip()


def _collect_stream_event(event: Any, collected_text_deltas: list[str]) -> None:
    event_type = str(_get_value(event, "type") or "")
    if event_type in {"response.output_text.delta", "response.text.delta"}:
        delta = str(_get_value(event, "delta") or "")
        if delta:
            collected_text_deltas.append(delta)


def _image_data_url(image_path: Path, content_type: object = None) -> str:
    data = image_path.read_bytes()
    mime_type = _image_mime_type(image_path, data=data, content_type=content_type)
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _image_mime_type(image_path: Path, *, data: bytes, content_type: object = None) -> str:
    mime_type = normalize_text(content_type)
    if mime_type.startswith("image/"):
        return mime_type

    guessed_mime = mimetypes.guess_type(image_path.name)[0] or ""
    if guessed_mime.startswith("image/"):
        return guessed_mime

    try:
        from media.image import sniff_image_mime

        sniffed_mime = sniff_image_mime(data)
    except Exception:
        sniffed_mime = ""
    if sniffed_mime.startswith("image/"):
        return sniffed_mime

    return "image/png"


def _response_text(response: Any) -> str:
    output_text = _get_value(response, "output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    parts: list[str] = []
    for item in _get_value(response, "output") or []:
        for content in _get_value(item, "content") or []:
            text = _get_value(content, "text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts).strip()


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _caption_provider(provider: str) -> str:
    normalized = normalize_ai_provider(provider)
    if normalized in {OPENAI_PROVIDER, CODEX_PROVIDER}:
        return normalized
    if normalize_text(provider).lower() == "codex":
        return CODEX_PROVIDER
    return ""


def _report_caption_step(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    index: int,
    total: int,
    completed: bool = False,
    skipped: bool = False,
) -> None:
    if total <= 0:
        return
    base_percent = 30
    span = 14
    current = index if completed or skipped else max(0, index - 1)
    percent = base_percent + int(span * (current / max(1, total)))
    if skipped:
        message = f"Skipped image {index} of {total}."
    elif completed:
        message = f"Captioned image {index} of {total}."
    else:
        message = f"Captioning image {index} of {total}."
    _report_progress(
        callback,
        stage="captioning",
        message=message,
        percent=percent,
        current=current,
        total=total,
    )


def _report_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    stage: str,
    message: str,
    percent: int | float | None = None,
    **extra: Any,
) -> None:
    if not callable(callback):
        return
    payload: dict[str, Any] = {"stage": stage, "message": message}
    if percent is not None:
        payload["percent"] = max(0, min(100, int(percent)))
    payload.update({key: value for key, value in extra.items() if value is not None})
    callback(payload)
