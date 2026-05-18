from __future__ import annotations

from ui.backend.server import content_disposition_attachment


def test_content_disposition_attachment_supports_unicode_file_names():
    header = content_disposition_attachment("朱旋-阅读3-课前打卡.pdf")

    assert header.encode("latin-1")
    assert 'filename*=' in header
    assert "%E6%9C%B1%E6%97%8B-%E9%98%85%E8%AF%BB3-" in header
