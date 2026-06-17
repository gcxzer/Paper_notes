"""说明：处理图片 MIME 识别、验证和上传规范化。

作用：确保图片 artifact 类型可信、大小受控，并在保存前提取宽高信息。
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

from media.base64_payload import Base64PayloadErrors, parse_base64_payload as _parse_base64_payload


SUPPORTED_IMAGE_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_RESIZE_TARGET_BYTES = 5 * 1024 * 1024
_BASE64_IMAGE_ERRORS = Base64PayloadErrors(
    empty="Image data is required.",
    invalid="Image data must be valid base64.",
    too_large="Image payload is too large.",
)


class ImageValidationError(ValueError):
    pass


def sniff_image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return ""


def extension_for_mime(mime_type: str) -> str:
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime_type, ".img")


def parse_base64_image(value: str, *, max_bytes: int = DEFAULT_MAX_IMAGE_BYTES) -> tuple[bytes, str]:
    data, declared_mime = _parse_base64_payload(
        value,
        max_bytes=max_bytes,
        errors=_BASE64_IMAGE_ERRORS,
        error_type=ImageValidationError,
    )
    sniffed_mime = sniff_image_mime(data)
    if sniffed_mime not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ImageValidationError("Unsupported image type.")
    if declared_mime and declared_mime != sniffed_mime:
        raise ImageValidationError("Image MIME type does not match its content.")
    return data, sniffed_mime


def data_url_for_bytes(data: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def image_dimensions(data: bytes) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 0, 0


def normalize_upload_image(
    data: bytes,
    *,
    mime_type: str,
    max_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
    resize_target_bytes: int = DEFAULT_RESIZE_TARGET_BYTES,
) -> tuple[bytes, str, int, int]:
    if len(data) > max_bytes:
        raise ImageValidationError("Image payload is too large.")
    if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
        raise ImageValidationError("Unsupported image type.")
    if mime_type == "image/gif":
        width, height = image_dimensions(data)
        return data, mime_type, width, height

    try:
        from PIL import Image, ImageOps
    except Exception as error:
        raise ImageValidationError("Pillow is required for image upload normalization.") from error

    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        output_format = "PNG" if mime_type == "image/png" else "JPEG" if mime_type == "image/jpeg" else "WEBP"
        save_kwargs: dict[str, Any] = {}
        if output_format in {"JPEG", "WEBP"}:
            if image.mode == "RGBA":
                image = image.convert("RGB")
            save_kwargs["quality"] = 90
        encoded = _encode_image(image, output_format, save_kwargs)
        if len(encoded) > resize_target_bytes:
            encoded = _resize_to_target(image, output_format, save_kwargs, resize_target_bytes)
        if len(encoded) > max_bytes:
            raise ImageValidationError("Image remains too large after normalization.")
        final_mime = {
            "PNG": "image/png",
            "JPEG": "image/jpeg",
            "WEBP": "image/webp",
        }[output_format]
        width, height = image_dimensions(encoded)
        return encoded, final_mime, width, height


def image_dimensions_for_path(path: str | Path) -> tuple[int, int]:
    try:
        return image_dimensions(Path(path).read_bytes())
    except OSError:
        return 0, 0


def _encode_image(image: Any, output_format: str, save_kwargs: dict[str, Any]) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format=output_format, **save_kwargs)
    return buffer.getvalue()


def _resize_to_target(image: Any, output_format: str, save_kwargs: dict[str, Any], target_bytes: int) -> bytes:
    current = image.copy()
    encoded = _encode_image(current, output_format, save_kwargs)
    while len(encoded) > target_bytes and min(current.size) > 256:
        width, height = current.size
        current = current.resize((max(1, int(width * 0.85)), max(1, int(height * 0.85))))
        encoded = _encode_image(current, output_format, save_kwargs)
    return encoded
