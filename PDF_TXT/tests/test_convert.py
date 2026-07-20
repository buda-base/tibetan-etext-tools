"""Tests for pdf2line.convert — orchestration, parallel safety, summary."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pdf2line.convert import convert_pdf, convert_folder, discover_pdfs, Result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_extract(pdf_path, **kwargs):
    """Return two synthetic pecha pages."""
    return [
        "1\nབོད་སྐད།\nfirst line\n",
        "2\nགཉིས་པ།\nsecond line\n",
    ]


# ---------------------------------------------------------------------------
# convert_pdf
# ---------------------------------------------------------------------------

@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_pdf_creates_txt(mock_extract, tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    r = convert_pdf(pdf, out_dir)

    assert r.ok
    assert r.pages > 0
    out_file = out_dir / "book.txt"
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "བོད་སྐད།" in content


@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_pdf_skips_existing(mock_extract, tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"fake")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "book.txt").write_text("existing", encoding="utf-8")

    r = convert_pdf(pdf, out_dir, overwrite=False)
    assert "skipped" in r.error


@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_pdf_overwrites_when_flag_set(mock_extract, tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"fake")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "book.txt").write_text("old content", encoding="utf-8")

    r = convert_pdf(pdf, out_dir, overwrite=True)
    assert r.ok
    content = (out_dir / "book.txt").read_text(encoding="utf-8")
    assert "old content" not in content


@patch("pdf2line.convert.extract_pages", side_effect=RuntimeError("boom"))
def test_convert_pdf_captures_exception(mock_extract, tmp_path):
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(b"fake")
    r = convert_pdf(pdf, tmp_path / "out")
    assert not r.ok
    assert "boom" in r.error


@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_pdf_pecha_pages_separated_by_blank_line(mock_extract, tmp_path):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"fake")
    out_dir = tmp_path / "out"

    convert_pdf(pdf, out_dir)
    content = (out_dir / "book.txt").read_text(encoding="utf-8")
    # Pecha pages must be separated by a blank line.
    assert "\n\n" in content


# ---------------------------------------------------------------------------
# convert_folder
# ---------------------------------------------------------------------------

@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_folder_processes_all_pdfs(mock_extract, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name in ["a.pdf", "b.pdf", "c.pdf"]:
        (src / name).write_bytes(b"fake")
    out = tmp_path / "out"

    results = convert_folder(src, out)
    assert len(results) == 3
    assert all(r.ok for r in results)


@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_folder_writes_summary(mock_extract, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"fake")
    out = tmp_path / "out"

    convert_folder(src, out, write_summary=True)
    summary = out / "_summary.json"
    assert summary.exists()
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["pdf"] == "a.pdf"


@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_folder_no_summary_flag(mock_extract, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pdf").write_bytes(b"fake")
    out = tmp_path / "out"

    convert_folder(src, out, write_summary=False)
    assert not (out / "_summary.json").exists()


@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_folder_empty_dir_returns_empty(mock_extract, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    results = convert_folder(src, tmp_path / "out")
    assert results == []


@patch("pdf2line.convert.extract_pages", side_effect=_fake_extract)
def test_convert_folder_parallel_mode(mock_extract, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    for name in ["x.pdf", "y.pdf"]:
        (src / name).write_bytes(b"fake")
    out = tmp_path / "out"

    results = convert_folder(src, out, jobs=2)
    assert len(results) == 2
    assert all(r.ok for r in results)


# ---------------------------------------------------------------------------
# discover_pdfs
# ---------------------------------------------------------------------------

def test_discover_pdfs_flat(tmp_path):
    (tmp_path / "a.pdf").write_bytes(b"x")
    (tmp_path / "b.pdf").write_bytes(b"x")
    (tmp_path / "c.txt").write_text("x")
    results = discover_pdfs(tmp_path, recursive=False)
    names = [p.name for p in results]
    assert "a.pdf" in names
    assert "b.pdf" in names
    assert "c.txt" not in names


def test_discover_pdfs_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.pdf").write_bytes(b"x")
    (tmp_path / "top.pdf").write_bytes(b"x")

    flat = discover_pdfs(tmp_path, recursive=False)
    assert not any(p.name == "deep.pdf" for p in flat)

    recursive = discover_pdfs(tmp_path, recursive=True)
    assert any(p.name == "deep.pdf" for p in recursive)
    assert any(p.name == "top.pdf" for p in recursive)
