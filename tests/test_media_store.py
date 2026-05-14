from __future__ import annotations

import base64
import io
import zipfile

import pytest

from media import MediaStore, MediaStoreError


PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)


def test_media_store_uploads_and_serves_registered_image(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    artifact = store.create_upload(PNG_DATA_URL, file_name="tiny.png", scope="session-1")

    assert artifact.id
    assert artifact.mime_type == "image/png"
    assert artifact.url == f"/api/media/{artifact.id}"
    assert artifact.download_url == f"/api/media/{artifact.id}/download"
    assert store.data_url_for_artifact(artifact.id).startswith("data:image/png;base64,")
    assert store.path_for(artifact.id).exists()


def test_media_store_rejects_invalid_image(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    with pytest.raises(ValueError):
        store.create_upload("not base64", file_name="bad.png", scope="session-1")


def test_media_store_requires_registered_artifact(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    with pytest.raises(MediaStoreError):
        store.path_for("missing")


def test_media_store_uploads_text_attachment_and_extracts_text(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    artifact = store.create_upload("data:text/plain;base64,SGVsbG8gZmlsZQ==", file_name="notes.txt", scope="session-1")

    assert artifact.id.startswith("att_")
    assert artifact.kind == "text"
    assert artifact.mime_type == "text/plain"
    assert artifact.size == len(b"Hello file")
    assert artifact.metadata["extractionStatus"] == "complete"
    assert store.extracted_text_for_artifact(artifact.id) == "Hello file"


def test_media_store_preserves_upload_display_name_when_storage_name_collides(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    first = store.create_upload("data:text/plain;base64,SGVsbG8=", file_name="README.md", scope="session-1")
    second = store.create_upload("data:text/plain;base64,V29ybGQ=", file_name="README.md", scope="session-1")

    assert first.file_name == "README.md"
    assert second.file_name == "README.md"
    assert first.path != second.path
    assert second.metadata["storageFileName"].startswith("README-att_")


@pytest.mark.parametrize(
    ("mime_type", "file_name", "kind"),
    [
        ("text/markdown", "notes.md", "text"),
        ("text/plain", "notes.txt", "text"),
        ("application/json", "data.json", "json"),
        ("text/csv", "data.csv", "csv"),
        ("text/html", "page.html", "html"),
    ],
)
def test_media_store_creates_generated_text_files(tmp_path, mime_type, file_name, kind):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    artifact = store.create_generated_file(
        "Hello file",
        file_name=file_name,
        mime_type=mime_type,
        session_id="session-1",
        provider="fake",
        model="test-model",
    )

    assert artifact.id.startswith("file_")
    assert artifact.kind == kind
    assert artifact.source == "generated"
    assert artifact.mime_type == mime_type
    assert artifact.file_name == file_name
    assert artifact.url == f"/api/media/{artifact.id}"
    assert artifact.download_url == f"/api/media/{artifact.id}/download"
    assert store.path_for(artifact.id).read_text(encoding="utf-8") == "Hello file"
    assert store.extracted_text_for_artifact(artifact.id) == "Hello file"


def test_media_store_accepts_unknown_text_like_attachment(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    source = b"def hello():\n    return 'world'\n"
    artifact = store.create_upload(_data_url(source), file_name="example.py", scope="session-1")

    assert artifact.kind == "text"
    assert artifact.mime_type == "text/plain"
    assert artifact.file_name == "example.py"
    assert artifact.metadata["detectedText"] is True
    assert "def hello" in store.extracted_text_for_artifact(artifact.id)


def test_media_store_rejects_unknown_binary_attachment(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    with pytest.raises(ValueError, match="looks binary"):
        store.create_upload(_data_url(b"\x00\x01\x02\x03\x04"), file_name="program.bin", scope="session-1")


def test_media_store_rejects_archive_attachment(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    with pytest.raises(ValueError, match="Archive"):
        store.create_upload(_data_url(_zip_bytes({"file.txt": "Hello"}), "application/zip"), file_name="bundle.zip", scope="session-1")


def test_media_store_rejects_legacy_office_attachment(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    with pytest.raises(ValueError, match="Legacy Office"):
        store.create_upload("data:application/msword;base64,SGVsbG8=", file_name="old.doc", scope="session-1")
    with pytest.raises(ValueError, match="Legacy Office"):
        store.create_upload("data:application/msword;base64,SGVsbG8=", file_name="old-file", scope="session-1")


def test_media_store_extracts_modern_office_attachments(tmp_path):
    store = MediaStore(tmp_path / ".paper-notes" / "media")

    docx = store.create_upload(_data_url(_zip_bytes({"word/document.xml": _xml_text("Docx body")})), file_name="paper.docx")
    pptx = store.create_upload(
        _data_url(_zip_bytes({"ppt/slides/slide1.xml": _xml_text("Slide body")})),
        file_name="slides.pptx",
    )
    xlsx = store.create_upload(
        _data_url(_zip_bytes({"xl/worksheets/sheet1.xml": """
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData><row><c><v>42</v></c></row></sheetData>
            </worksheet>
        """})),
        file_name="sheet.xlsx",
    )

    assert docx.kind == "document"
    assert "Docx body" in store.extracted_text_for_artifact(docx.id)
    assert pptx.kind == "presentation"
    assert "Slide body" in store.extracted_text_for_artifact(pptx.id)
    assert xlsx.kind == "spreadsheet"
    assert "42" in store.extracted_text_for_artifact(xlsx.id)


def _data_url(data: bytes, mime_type: str = "application/octet-stream") -> str:
    return f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def _xml_text(text: str) -> str:
    return f"""
        <root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
          <w:p><w:r><w:t>{text}</w:t></w:r></w:p>
        </root>
    """
