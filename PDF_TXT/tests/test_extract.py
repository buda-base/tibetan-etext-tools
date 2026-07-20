"""
Tests for pdf2line.extract.

PyMuPDF is required for most tests. Tests that open real PDFs are skipped
unless a fixture PDF is present. Unit-testable helpers (_tibetan_ratio,
_is_two_up_page, _pdf_has_legacy_font shape) are tested without PDFs.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pdf2line.extract import (
    _tibetan_ratio,
    _TWO_UP_RATIO,
    extract_pages,
)


# ---------------------------------------------------------------------------
# _tibetan_ratio
# ---------------------------------------------------------------------------

def test_tibetan_ratio_empty():
    assert _tibetan_ratio("") == 0.0


def test_tibetan_ratio_all_tibetan():
    text = "བོད་སྐད"
    r = _tibetan_ratio(text)
    assert r > 0.9


def test_tibetan_ratio_all_latin():
    assert _tibetan_ratio("hello world") == 0.0


def test_tibetan_ratio_mixed():
    # Half Tibetan, half Latin (approx).
    text = "ཀ abc"
    r = _tibetan_ratio(text)
    assert 0.0 < r < 1.0


def test_tibetan_ratio_whitespace_only():
    assert _tibetan_ratio("   \n\t  ") == 0.0


# ---------------------------------------------------------------------------
# _is_two_up_page logic (via aspect ratio)
# ---------------------------------------------------------------------------

def test_two_up_ratio_landscape_triggers():
    """A wide rect should exceed the 1.5x threshold."""
    from pdf2line.extract import _is_two_up_page
    mock_page = MagicMock()
    # width=300, height=100 → ratio=3 > 1.5
    mock_page.rect = MagicMock(width=300, height=100)
    assert _is_two_up_page(mock_page) is True


def test_two_up_ratio_portrait_does_not_trigger():
    from pdf2line.extract import _is_two_up_page
    mock_page = MagicMock()
    # width=100, height=200 → ratio=0.5 < 1.5
    mock_page.rect = MagicMock(width=100, height=200)
    assert _is_two_up_page(mock_page) is False


def test_two_up_ratio_square_does_not_trigger():
    from pdf2line.extract import _is_two_up_page
    mock_page = MagicMock()
    mock_page.rect = MagicMock(width=200, height=200)
    assert _is_two_up_page(mock_page) is False


# ---------------------------------------------------------------------------
# extract_pages backend routing (mocked fitz)
# ---------------------------------------------------------------------------

def _make_mock_doc(pages_text):
    """Build a minimal fitz-like mock returning given per-page text strings."""
    mock_pages = []
    for text in pages_text:
        p = MagicMock()
        p.get_text.return_value = text
        p.rect = MagicMock(x0=0, y0=0, x1=100, y1=200, width=100, height=200)
        p.get_fonts.return_value = []
        mock_pages.append(p)

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter(mock_pages))
    mock_doc.__len__ = MagicMock(return_value=len(mock_pages))
    mock_doc.__getitem__ = MagicMock(side_effect=lambda i: mock_pages[i])
    mock_doc.close = MagicMock()
    return mock_doc


@patch("pdf2line.extract.fitz")
@patch("pdf2line.extract._HAVE_PYMUPDF", True)
def test_extract_pages_pymupdf_backend(mock_fitz, tmp_path):
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"fake")

    expected = ["page one text\n", "page two text\n"]
    mock_fitz.open.return_value = _make_mock_doc(expected)

    from pdf2line.extract import extract_pages_pymupdf
    result = extract_pages_pymupdf(pdf)
    assert result == expected


@patch("pdf2line.extract.fitz")
@patch("pdf2line.extract._HAVE_PYMUPDF", True)
def test_extract_pages_two_up_splits(mock_fitz, tmp_path):
    """two_up=True should produce 2 entries per PDF page."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"fake")

    mock_page = MagicMock()
    mock_page.get_text.return_value = "half text\n"
    mock_page.rect = MagicMock(x0=0, y0=0, x1=200, y1=100, width=200, height=100)

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.close = MagicMock()
    mock_fitz.open.return_value = mock_doc
    mock_fitz.Rect = MagicMock(side_effect=lambda *a: MagicMock())

    from pdf2line.extract import extract_pages_pymupdf
    result = extract_pages_pymupdf(pdf, two_up=True)
    # One PDF page → two half-page entries.
    assert len(result) == 2


@patch("pdf2line.extract.fitz")
@patch("pdf2line.extract._HAVE_PYMUPDF", True)
def test_extract_pages_auto_two_up_portrait_no_split(mock_fitz, tmp_path):
    """auto_two_up should NOT split a portrait page."""
    pdf = tmp_path / "test.pdf"
    pdf.write_bytes(b"fake")

    mock_page = MagicMock()
    mock_page.get_text.return_value = "portrait text\n"
    # Portrait: width < height
    mock_page.rect = MagicMock(x0=0, y0=0, x1=100, y1=200, width=100, height=200)

    mock_doc = MagicMock()
    mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
    mock_doc.close = MagicMock()
    mock_fitz.open.return_value = mock_doc
    mock_fitz.Rect = MagicMock(side_effect=lambda *a: MagicMock())

    from pdf2line.extract import extract_pages_pymupdf
    result = extract_pages_pymupdf(pdf, auto_two_up=True)
    # Portrait page → not split → one entry.
    assert len(result) == 1


# ---------------------------------------------------------------------------
# extract_pages: backend selection
# ---------------------------------------------------------------------------

@patch("pdf2line.extract.extract_pages_pymupdf")
@patch("pdf2line.extract.extract_pages_pytiblegenc")
def test_extract_pages_routes_pymupdf(mock_pytib, mock_pymu, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"x")
    mock_pymu.return_value = ["p1"]
    extract_pages(pdf, backend="pymupdf")
    mock_pymu.assert_called_once()
    mock_pytib.assert_not_called()


@patch("pdf2line.extract.extract_pages_pymupdf")
@patch("pdf2line.extract.extract_pages_pytiblegenc")
def test_extract_pages_routes_pytiblegenc(mock_pytib, mock_pymu, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"x")
    mock_pytib.return_value = ["p1"]
    extract_pages(pdf, backend="pytiblegenc")
    mock_pytib.assert_called_once()
    mock_pymu.assert_not_called()


@patch("pdf2line.extract._pdf_has_legacy_font", return_value=False)
@patch("pdf2line.extract.extract_pages_pymupdf")
@patch("pdf2line.extract.extract_pages_pytiblegenc")
def test_extract_pages_hybrid_no_fallback(mock_pytib, mock_pymu, mock_legacy, tmp_path):
    """Hybrid: if Tibetan ratio is fine, pytiblegenc not called."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"x")
    # Return text with high Tibetan ratio.
    mock_pymu.return_value = ["བོད་སྐད་"]
    result = extract_pages(pdf, backend="hybrid")
    mock_pytib.assert_not_called()
    assert result == ["བོད་སྐད་"]


@patch("pdf2line.extract._pdf_has_legacy_font", return_value=True)
@patch("pdf2line.extract.extract_pages_pymupdf")
@patch("pdf2line.extract.extract_pages_pytiblegenc")
def test_extract_pages_hybrid_falls_back(mock_pytib, mock_pymu, mock_legacy, tmp_path):
    """Hybrid: low Tibetan ratio + legacy font → retry pytiblegenc."""
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"x")
    # Return text with zero Tibetan (triggers fallback).
    mock_pymu.return_value = ["all latin text here"]
    mock_pytib.return_value = ["tibetan from pytiblegenc"]
    result = extract_pages(pdf, backend="hybrid", hybrid_min_tibetan_ratio=0.20)
    mock_pytib.assert_called_once()
    assert result == ["tibetan from pytiblegenc"]
