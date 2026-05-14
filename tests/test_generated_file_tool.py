from __future__ import annotations

from media import MediaStore
from tools.generated_files import TOOL_NAME, register_generated_file_tool
from tools.registry import ToolRegistry


def test_generated_file_tool_creates_downloadable_artifact(tmp_path):
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    register_generated_file_tool(
        registry,
        media_store=store,
        session_id_provider=lambda: "session-1",
        provider_name_provider=lambda: "fake",
        model_provider=lambda: "test-model",
    )

    result = registry.dispatch(TOOL_NAME, {
        "file_name": "summary.md",
        "mime_type": "text/markdown",
        "content": "# Summary\n",
    })

    assert result.is_error is False
    assert '"success": true' in result.content
    artifact = store.get_artifact(next(iter(store._load_manifest())))
    assert artifact is not None
    assert artifact.file_name == "summary.md"
    assert artifact.download_url.endswith("/download")


def test_generated_file_tool_rejects_unsafe_or_unsupported_requests(tmp_path):
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    register_generated_file_tool(registry, media_store=store)

    unsafe = registry.dispatch(TOOL_NAME, {
        "file_name": "../secret.md",
        "mime_type": "text/markdown",
        "content": "secret",
    })
    binary = registry.dispatch(TOOL_NAME, {
        "file_name": "archive.zip",
        "mime_type": "application/zip",
        "content": "zip",
    })
    empty = registry.dispatch(TOOL_NAME, {
        "file_name": "empty.md",
        "mime_type": "text/markdown",
        "content": "",
    })

    assert unsafe.is_error is True
    assert "unsafe_file_name" in unsafe.content
    assert binary.is_error is True
    assert "unsupported_mime_type" in binary.content
    assert empty.is_error is True
    assert "empty_content" in empty.content


def test_generated_file_tool_forces_ui_selected_format(tmp_path):
    registry = ToolRegistry()
    store = MediaStore(tmp_path / ".paper-notes" / "media")
    register_generated_file_tool(
        registry,
        media_store=store,
        file_generation_provider=lambda: {
            "enabled": True,
            "format": "markdown",
            "mime_type": "text/markdown",
        },
    )

    result = registry.dispatch(TOOL_NAME, {
        "file_name": "deepseek-v4-note.txt",
        "mime_type": "text/plain",
        "content": "Generated content.",
    })

    artifact = next(iter(store._load_manifest().values()))
    assert result.is_error is False
    assert artifact.file_name == "deepseek-v4-note.md"
    assert artifact.mime_type == "text/markdown"
