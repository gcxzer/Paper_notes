from __future__ import annotations

import json

import tools.visibility as tools_visibility
from app_config.ai_settings import ResolvedValue
from media import MediaStore
from tools import ToolContext, create_tools, tool_name
from tools.generated_files.tool import create_file_artifact


def _tool_names(context: ToolContext) -> set[str]:
    return {tool_name(tool) for tool in create_tools(context)}


def test_generated_file_tool_creates_downloadable_artifact(tmp_path):
    store = MediaStore(tmp_path / "media")

    result = create_file_artifact(
        {
            "file_name": "summary.md",
            "mime_type": "text/markdown",
            "content": "# Summary\n\nHello file.",
        },
        media_store=store,
        session_id="session-1",
        provider_name="openai",
        model="gpt-5.5",
    )

    artifact = result["artifact"]
    assert result["success"] is True
    assert artifact["id"].startswith("file_")
    assert artifact["source"] == "generated"
    assert artifact["fileName"] == "summary.md"
    assert artifact["downloadUrl"] == f"/api/media/{artifact['id']}/download"
    assert store.path_for(artifact["id"]).read_text(encoding="utf-8") == "# Summary\n\nHello file."


def test_generated_file_tool_honors_forced_file_generation_format(tmp_path):
    store = MediaStore(tmp_path / "media")

    result = create_file_artifact(
        {
            "file_name": "summary.md",
            "mime_type": "text/markdown",
            "content": "name,value\nalpha,1\n",
        },
        media_store=store,
        session_id="session-1",
        provider_name="openai",
        model="gpt-5.5",
        file_generation={"enabled": True, "mime_type": "text/csv"},
    )

    artifact = result["artifact"]
    assert artifact["mimeType"] == "text/csv"
    assert artifact["fileName"] == "summary.csv"


def test_generated_image_tool_is_available_only_for_configured_capable_models(monkeypatch, tmp_path):
    store = MediaStore(tmp_path / "media")
    auth_path = tmp_path / "codex-auth.json"
    auth_path.write_text(json.dumps({"tokens": {"access_token": "codex-token"}}), encoding="utf-8")
    monkeypatch.setenv("PAPER_NOTES_CODEX_AUTH_PATH", str(auth_path))
    monkeypatch.setattr(
        tools_visibility,
        "resolve_openai_api_key",
        lambda: ResolvedValue("sk-test", "test"),
    )

    openai_names = _tool_names(ToolContext(media_store=store, provider_name="openai", model="gpt-5.5"))
    codex_names = _tool_names(ToolContext(media_store=store, provider_name="codex-oauth", model="gpt-5.5"))
    spark_names = _tool_names(ToolContext(
        media_store=store,
        provider_name="codex-oauth",
        model="gpt-5.3-codex-spark",
    ))
    deepseek_names = _tool_names(ToolContext(media_store=store, provider_name="deepseek", model="deepseek-v4"))

    assert "create_file_artifact" in openai_names
    assert "create_image_artifact" in openai_names
    assert "create_image_artifact" in codex_names
    assert "create_image_artifact" not in spark_names
    assert "create_file_artifact" in deepseek_names
    assert "create_image_artifact" not in deepseek_names


def test_generated_image_tool_is_hidden_without_required_credentials(monkeypatch, tmp_path):
    store = MediaStore(tmp_path / "media")
    monkeypatch.setattr(tools_visibility, "resolve_openai_api_key", lambda: ResolvedValue())
    monkeypatch.setenv("PAPER_NOTES_CODEX_AUTH_PATH", str(tmp_path / "missing-codex-auth.json"))

    openai_names = _tool_names(ToolContext(media_store=store, provider_name="openai", model="gpt-5.5"))
    codex_names = _tool_names(ToolContext(media_store=store, provider_name="codex-oauth", model="gpt-5.5"))

    assert "create_file_artifact" in openai_names
    assert "create_image_artifact" not in openai_names
    assert "create_image_artifact" not in codex_names
