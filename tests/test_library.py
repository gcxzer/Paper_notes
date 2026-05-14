from __future__ import annotations

import base64

import library.store as library_module
from library import read_library, sanitize_library, write_library


def test_sanitize_library_strips_legacy_cloud_fields():
    library = sanitize_library({
        "categories": [],
        "notes": [{
            "id": "note-1",
            "title": "Paper",
            "categoryId": "missing",
            "pdfS3Key": "legacy",
            "kbPaperS3Key": "legacy",
            "kbSyncStatus": "legacy",
        }],
    })

    note = library["notes"][0]
    assert note["categoryId"] == "uncategorized"
    assert "pdfS3Key" not in note
    assert "kbPaperS3Key" not in note
    assert "kbSyncStatus" not in note


def test_sanitize_library_keeps_notes_only_in_leaf_categories():
    library = sanitize_library({
        "categories": [
            {"id": "parent", "name": "Parent", "parentId": None, "order": 2},
            {"id": "child", "name": "Child", "parentId": "parent", "order": 0},
        ],
        "notes": [{"id": "note-1", "title": "Paper", "categoryId": "parent"}],
    })

    assert library["notes"][0]["categoryId"] == "uncategorized"


def test_write_library_uses_sanitized_shape(tmp_path):
    target = tmp_path / "notes.json"
    write_library({"notes": [{"id": "note-1", "title": "Paper", "pdfS3Key": "legacy"}]}, target)

    loaded = read_library(target)

    assert loaded["notes"][0]["title"] == "Paper"
    assert "pdfS3Key" not in loaded["notes"][0]


def test_import_pdf_generates_note_outline_from_pdf_toc(tmp_path, monkeypatch):
    import pymupdf

    papers_dir = tmp_path / "Papers"
    html_dir = tmp_path / "Paper-html"
    notes_path = tmp_path / "notes.json"
    monkeypatch.setattr(library_module, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(library_module, "HTML_DIR", html_dir)
    monkeypatch.setattr(library_module, "NOTES_PATH", notes_path)

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "DeepSeek V4\n1 Introduction\n1.1 Contributions\n2 Method")
    document.new_page().insert_text((72, 72), "Method details")
    document.set_toc([
        [1, "Introduction", 1],
        [2, "Contributions", 1],
        [1, "Method", 2],
        [2, "Training Setup", 2],
        [3, "Training Details", 2],
    ])
    pdf_data = document.tobytes()
    document.close()

    note = library_module.import_pdf({
        "fileName": "DeepSeek-V4.pdf",
        "dataBase64": base64.b64encode(pdf_data).decode("ascii"),
    })

    html_path = html_dir / "DeepSeek-V4.html"
    html = html_path.read_text(encoding="utf-8")

    assert note["htmlHref"] == "resources/Paper-html/DeepSeek-V4.html"
    assert "<section class=\"note-body\">" in html
    assert "<h2>1. Introduction</h2>" in html
    assert "<h3>1.1. Contributions</h3>" in html
    assert "<h2>2. Method</h2>" in html
    assert "<h3>2.1. Training Setup</h3>" in html
    assert "<h4>2.1.1. Training Details</h4>" in html


def test_resolve_paper_pdf_url_supports_arxiv_and_doi():
    assert library_module.resolve_paper_pdf_url("arxiv:1706.03762") == "https://arxiv.org/pdf/1706.03762.pdf"
    assert library_module.resolve_paper_pdf_url("https://arxiv.org/abs/1706.03762v7") == "https://arxiv.org/pdf/1706.03762v7.pdf"
    assert (
        library_module.resolve_paper_pdf_url("https://doi.org/10.48550/arXiv.1706.03762")
        == "https://arxiv.org/pdf/1706.03762.pdf"
    )


def test_import_pdf_from_url_reuses_local_import_pipeline(tmp_path, monkeypatch):
    import pymupdf

    papers_dir = tmp_path / "Papers"
    html_dir = tmp_path / "Paper-html"
    notes_path = tmp_path / "notes.json"
    monkeypatch.setattr(library_module, "PAPERS_DIR", papers_dir)
    monkeypatch.setattr(library_module, "HTML_DIR", html_dir)
    monkeypatch.setattr(library_module, "NOTES_PATH", notes_path)

    document = pymupdf.open()
    document.new_page().insert_text((72, 72), "URL import")
    pdf_data = document.tobytes()
    document.close()

    def fake_download(url):
        assert url == "https://arxiv.org/pdf/1706.03762.pdf"
        return pdf_data, "Attention Is All You Need.pdf", "https://arxiv.org/pdf/1706.03762.pdf"

    monkeypatch.setattr(library_module, "download_paper_pdf", fake_download)

    note = library_module.import_pdf_from_url({"url": "arxiv:1706.03762", "categoryId": "uncategorized"})

    assert note["title"] == "Attention Is All You Need"
    assert note["sourceUrl"] == "https://arxiv.org/pdf/1706.03762.pdf"
    assert (papers_dir / "Attention Is All You Need.pdf").exists()
    assert (html_dir / "Attention Is All You Need.html").exists()
