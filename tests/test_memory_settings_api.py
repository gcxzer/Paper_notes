from __future__ import annotations

from fastapi.testclient import TestClient

from ui.backend import settings_api
from ui.backend.server import create_app
from ui.backend.settings_api import get_memory_settings, update_memory_settings


def test_get_memory_settings_reads_system_and_user_files(tmp_path) -> None:
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "system.md").write_text("## System\n\n- Project rule\n", encoding="utf-8")
    (memory_dir / "user.md").write_text("## User\n\n- Collaboration rule\n", encoding="utf-8")

    payload = get_memory_settings(memory_dir=memory_dir)

    assert payload["memoryDir"] == str(memory_dir)
    assert payload["system"] == "## System\n\n- Project rule\n"
    assert payload["user"] == "## User\n\n- Collaboration rule\n"
    assert payload["files"]["system"]["name"] == "system.md"
    assert payload["files"]["user"]["name"] == "user.md"


def test_update_memory_settings_writes_only_managed_files(tmp_path) -> None:
    memory_dir = tmp_path / "memory"

    payload = update_memory_settings(
        {
            "system": "## System\n\n- Updated system rule\n",
            "user": "## User\n\n- Updated user rule\n",
            "path": "/tmp/ignored.md",
        },
        memory_dir=memory_dir,
    )

    assert payload["system"] == "## System\n\n- Updated system rule\n"
    assert payload["user"] == "## User\n\n- Updated user rule\n"
    assert (memory_dir / "system.md").read_text(encoding="utf-8") == "## System\n\n- Updated system rule\n"
    assert (memory_dir / "user.md").read_text(encoding="utf-8") == "## User\n\n- Updated user rule\n"
    assert not (memory_dir / "ignored.md").exists()


def test_memory_settings_routes_save_and_read(monkeypatch, tmp_path) -> None:
    memory_dir = tmp_path / ".paper-notes" / "memory"
    monkeypatch.setattr(settings_api, "MEMORY_DIR", memory_dir)
    client = TestClient(create_app())

    saved = client.post(
        "/api/settings/memory",
        json={
            "system": "## System\n\n- Route system rule\n",
            "user": "## User\n\n- Route user rule\n",
        },
    )
    loaded = client.get("/api/settings/memory")

    assert saved.status_code == 200
    assert saved.json()["system"] == "## System\n\n- Route system rule\n"
    assert saved.json()["user"] == "## User\n\n- Route user rule\n"
    assert loaded.status_code == 200
    assert loaded.json()["files"]["system"]["path"] == str(memory_dir / "system.md")
    assert loaded.json()["files"]["user"]["path"] == str(memory_dir / "user.md")
