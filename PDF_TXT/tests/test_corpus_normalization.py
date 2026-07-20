"""Tests for pdf2line.corpus_normalization."""
import pytest
from pdf2line.corpus_normalization import normalize_corpus, normalize_spaces, merge_lines


# ---------------------------------------------------------------------------
# normalize_spaces
# ---------------------------------------------------------------------------

def test_normalize_spaces_collapses_runs():
    assert normalize_spaces("a  b   c") == "a b c"


def test_normalize_spaces_strips_around_newlines():
    assert normalize_spaces("a  \n  b") == "a\nb"


def test_normalize_spaces_collapses_newlines():
    assert normalize_spaces("a\n\n\nb") == "a\nb"


def test_normalize_spaces_tibetan_tsheg_letter():
    # Space between tsheg and initial letter should be removed.
    s = "་ ཀ"   # tsheg SPACE ka
    assert normalize_spaces(s) == "་ཀ"


def test_normalize_spaces_letter_tsheg():
    # Space between final letter and tsheg should be removed.
    s = "ས ་"   # sa SPACE tsheg
    assert normalize_spaces(s) == "ས་"


def test_normalize_spaces_unicode_space_mapped():
    # Non-breaking space → regular space.
    assert normalize_spaces("a b") == "a b"


# ---------------------------------------------------------------------------
# normalize_corpus
# ---------------------------------------------------------------------------

def test_normalize_corpus_nfc():
    # NFC: composed form should be returned (no change for already-NFC text).
    assert normalize_corpus("abc") == "abc"


def test_normalize_corpus_removes_bom():
    assert normalize_corpus("﻿text") == "text"


def test_normalize_corpus_removes_zero_width():
    assert normalize_corpus("a​b") == "ab"


def test_normalize_corpus_strips_control_chars():
    # Control chars (except newline) removed when strip_control=True.
    assert "\x01" not in normalize_corpus("a\x01b")
    assert normalize_corpus("a\nb") == "a\nb"   # newline kept


def test_normalize_corpus_tsheg_variant_folded():
    # U+0F0C (MARK TSHEG ABOVE) → U+0F0B (MARK TSHEG).
    assert "༌" not in normalize_corpus("༌")
    assert normalize_corpus("༌") == "་"


def test_normalize_corpus_double_shad_expanded():
    # U+0F0E (MARK DOUBLE SHAD) → two shad marks.
    result = normalize_corpus("༎")
    assert result == "།།"


def test_normalize_corpus_crlf_normalized():
    assert normalize_corpus("a\r\nb") == "a\nb"


def test_normalize_corpus_empty():
    assert normalize_corpus("") == ""


# ---------------------------------------------------------------------------
# merge_lines
# ---------------------------------------------------------------------------

def test_merge_lines_removes_newlines():
    result = merge_lines("line one\nline two\n")
    assert "\n" not in result


def test_merge_lines_folds_tsheg_at_boundary():
    # Double tsheg at end of line should be folded to one.
    s = "syllable་་\ncontinuation"
    result = merge_lines(s)
    assert "་་" not in result


def test_merge_lines_empty():
    assert merge_lines("") == ""
