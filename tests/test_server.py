from __future__ import annotations

import importlib

from ui.backend.server import content_disposition_attachment


def test_content_disposition_attachment_supports_unicode_file_names():
    header = content_disposition_attachment("朱旋-阅读3-课前打卡.pdf")

    assert header.encode("latin-1")
    assert 'filename*=' in header
    assert "%E6%9C%B1%E6%97%8B-%E9%98%85%E8%AF%BB3-" in header


def test_paths_host_defaults_to_localhost(monkeypatch):
    monkeypatch.delenv("HOST", raising=False)

    import app_infra.paths as paths

    try:
        importlib.reload(paths)
        assert paths.HOST == "127.0.0.1"
    finally:
        importlib.reload(paths)


def test_paths_host_can_be_overridden(monkeypatch):
    monkeypatch.setenv("HOST", "0.0.0.0")

    import app_infra.paths as paths

    try:
        importlib.reload(paths)
        assert paths.HOST == "0.0.0.0"
    finally:
        monkeypatch.delenv("HOST", raising=False)
        importlib.reload(paths)
