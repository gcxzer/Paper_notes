"""说明：校验附件类型并提取文本内容。

作用：支持 PDF、纯文本和现代 Office 文件，让非图片附件可以进入聊天上下文。
"""

from __future__ import annotations

import io
import unicodedata
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


SUPPORTED_ATTACHMENT_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

UNSUPPORTED_LEGACY_OFFICE_EXTENSIONS = {".doc", ".ppt", ".xls"}
UNSUPPORTED_LEGACY_OFFICE_MIME_TYPES = {
    "application/msword",
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-excel",
}
UNSUPPORTED_ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar"}
UNSUPPORTED_ARCHIVE_MIME_TYPES = {
    "application/zip",
    "application/x-zip-compressed",
    "application/x-tar",
    "application/gzip",
    "application/x-gzip",
    "application/x-7z-compressed",
    "application/vnd.rar",
}
TEXT_ATTACHMENT_MIME_TYPES = {"text/plain", "text/markdown"}
MAX_EXTRACTED_TEXT_CHARS = 120_000
TEXT_SNIFF_SAMPLE_BYTES = 64 * 1024
MAX_CONTROL_CHARACTER_RATIO = 0.08

_MIME_BY_EXTENSION = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_EXTENSION_BY_MIME = {
    "application/pdf": ".pdf",
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
}


class AttachmentExtractionError(ValueError):
    pass


def attachment_mime_for_name(file_name: str) -> str:
    return _MIME_BY_EXTENSION.get(Path(file_name or "").suffix.lower(), "")


def attachment_extension_for_mime(mime_type: str) -> str:
    normalized = str(mime_type or "").lower()
    if normalized.startswith("text/"):
        return ".txt"
    return _EXTENSION_BY_MIME.get(normalized, ".bin")


def attachment_kind(mime_type: str) -> str:
    normalized = str(mime_type or "").lower()
    if normalized == "application/pdf":
        return "pdf"
    if normalized in TEXT_ATTACHMENT_MIME_TYPES or normalized.startswith("text/"):
        return "text"
    if normalized == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return "document"
    if normalized == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        return "presentation"
    if normalized == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return "spreadsheet"
    return "file"


def ensure_supported_attachment(file_name: str, mime_type: str) -> str:
    extension = Path(file_name or "").suffix.lower()
    if extension in UNSUPPORTED_LEGACY_OFFICE_EXTENSIONS:
        raise AttachmentExtractionError(f"Legacy Office files ({extension}) are not supported yet. Use modern Office files instead.")
    if extension in UNSUPPORTED_ARCHIVE_EXTENSIONS:
        raise AttachmentExtractionError("Archive attachments are not supported yet.")
    normalized = str(mime_type or "").lower()
    if normalized in UNSUPPORTED_LEGACY_OFFICE_MIME_TYPES:
        raise AttachmentExtractionError("Legacy Office files are not supported yet. Use modern Office files instead.")
    if normalized in UNSUPPORTED_ARCHIVE_MIME_TYPES:
        raise AttachmentExtractionError("Archive attachments are not supported yet.")
    if normalized in SUPPORTED_ATTACHMENT_MIME_TYPES:
        return normalized
    if normalized.startswith("text/"):
        return normalized
    guessed = attachment_mime_for_name(file_name)
    if guessed:
        return guessed
    return "text/plain"


def extract_attachment_text(data: bytes, *, mime_type: str, file_name: str = "") -> str:
    normalized = ensure_supported_attachment(file_name, mime_type)
    if normalized in TEXT_ATTACHMENT_MIME_TYPES or normalized.startswith("text/"):
        return _trim_extracted_text(_decode_text_attachment(data))
    if normalized == "application/pdf":
        return _trim_extracted_text(_extract_pdf_text(data))
    if normalized == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        return _trim_extracted_text(_extract_docx_text(data))
    if normalized == "application/vnd.openxmlformats-officedocument.presentationml.presentation":
        return _trim_extracted_text(_extract_pptx_text(data))
    if normalized == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet":
        return _trim_extracted_text(_extract_xlsx_text(data))
    return ""


def _decode_text_attachment(data: bytes) -> str:
    if _looks_binary(data):
        raise AttachmentExtractionError("This file looks binary and cannot be read as text.")
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            text = data.decode(encoding)
            if not _looks_like_text(text):
                raise AttachmentExtractionError("This file looks binary and cannot be read as text.")
            return text
        except UnicodeDecodeError:
            continue
    text = data.decode("utf-8", errors="replace")
    if not _looks_like_text(text):
        raise AttachmentExtractionError("This file looks binary and cannot be read as text.")
    return text


def _looks_binary(data: bytes) -> bool:
    sample = data[:TEXT_SNIFF_SAMPLE_BYTES]
    return b"\x00" in sample


def _looks_like_text(text: str) -> bool:
    if not text:
        return True
    sample = text[:TEXT_SNIFF_SAMPLE_BYTES]
    control_count = sum(
        1
        for char in sample
        if unicodedata.category(char)[0] == "C" and char not in {"\n", "\r", "\t", "\f"}
    )
    return (control_count / max(len(sample), 1)) <= MAX_CONTROL_CHARACTER_RATIO


def _extract_pdf_text(data: bytes) -> str:
    try:
        import fitz
    except Exception as error:
        raise AttachmentExtractionError("PyMuPDF is required to read PDF attachments.") from error
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            return "\n\n".join(page.get_text("text").strip() for page in document if page.get_text("text").strip())
    except Exception as error:
        raise AttachmentExtractionError("Could not extract text from this PDF.") from error


def _extract_docx_text(data: bytes) -> str:
    with _open_zip(data) as archive:
        names = sorted(name for name in archive.namelist() if name.startswith("word/") and name.endswith(".xml"))
        paragraphs: list[str] = []
        for name in names:
            if name not in {"word/document.xml"} and not name.startswith("word/header") and not name.startswith("word/footer"):
                continue
            paragraphs.extend(_xml_text_runs(archive.read(name)))
        return "\n".join(paragraphs)


def _extract_pptx_text(data: bytes) -> str:
    with _open_zip(data) as archive:
        slide_names = sorted(
            (name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")),
            key=_natural_xml_name_key,
        )
        slides: list[str] = []
        for index, name in enumerate(slide_names, start=1):
            text = "\n".join(_xml_text_runs(archive.read(name))).strip()
            if text:
                slides.append(f"Slide {index}\n{text}")
        return "\n\n".join(slides)


def _extract_xlsx_text(data: bytes) -> str:
    with _open_zip(data) as archive:
        shared_strings = _xlsx_shared_strings(archive)
        sheet_names = sorted(
            (name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")),
            key=_natural_xml_name_key,
        )
        sheets: list[str] = []
        for index, name in enumerate(sheet_names, start=1):
            rows = _xlsx_sheet_rows(archive.read(name), shared_strings)
            if rows:
                sheets.append(f"Sheet {index}\n" + "\n".join(rows))
        return "\n\n".join(sheets)


def _open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as error:
        raise AttachmentExtractionError("This Office file is not a valid modern Office document.") from error


def _xml_text_runs(data: bytes) -> list[str]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    lines: list[str] = []
    current: list[str] = []
    for element in root.iter():
        tag = _local_name(element.tag)
        if tag in {"t", "instrText"} and element.text:
            current.append(element.text)
        elif tag in {"tab"}:
            current.append("\t")
        elif tag in {"br", "cr", "p"} and current:
            line = "".join(current).strip()
            if line:
                lines.append(line)
            current = []
    if current:
        line = "".join(current).strip()
        if line:
            lines.append(line)
    return lines


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        data = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    return [" ".join(_xml_text_runs(ElementTree.tostring(item, encoding="utf-8"))) for item in _xml_children(data, "si")]


def _xlsx_sheet_rows(data: bytes, shared_strings: list[str]) -> list[str]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    rows: list[str] = []
    for row in root.iter():
        if _local_name(row.tag) != "row":
            continue
        values: list[str] = []
        for cell in list(row):
            if _local_name(cell.tag) != "c":
                continue
            value = _xlsx_cell_value(cell, shared_strings)
            if value:
                values.append(value)
        if values:
            rows.append("\t".join(values))
    return rows


def _xlsx_cell_value(cell: Any, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t", "")
    inline_text: list[str] = []
    value = ""
    for child in cell.iter():
        name = _local_name(child.tag)
        if name == "v" and child.text:
            value = child.text
        elif name == "t" and child.text:
            inline_text.append(child.text)
    if inline_text:
        return "".join(inline_text).strip()
    if cell_type == "s" and value.isdigit():
        index = int(value)
        return shared_strings[index] if 0 <= index < len(shared_strings) else ""
    return value.strip()


def _xml_children(data: bytes, child_name: str) -> list[Any]:
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        return []
    return [child for child in list(root) if _local_name(child.tag) == child_name]


def _local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _natural_xml_name_key(name: str) -> tuple[str, int]:
    stem = Path(name).stem
    digits = "".join(char for char in stem if char.isdigit())
    return (name.rstrip("0123456789"), int(digits or 0))


def _trim_extracted_text(text: str) -> str:
    normalized = "\n".join(line.rstrip() for line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    normalized = normalized.strip()
    if len(normalized) <= MAX_EXTRACTED_TEXT_CHARS:
        return normalized
    return normalized[:MAX_EXTRACTED_TEXT_CHARS].rstrip() + "\n\n[Attachment text truncated.]"
