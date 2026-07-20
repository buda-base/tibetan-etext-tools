"""Tests for pdf2line.normalize (normalize_line)."""
from pdf2line.normalize import normalize_line


def test_normalize_line_empty():
    assert normalize_line("") == ""


def test_normalize_line_single_line():
    # Basic pass-through for clean Tibetan text.
    text = "བོད་སྐད།"
    result = normalize_line(text)
    assert "བོད" in result


def test_normalize_line_strips_control_chars():
    assert "\x01" not in normalize_line("བོད\x01སྐད")


def test_normalize_line_multiline_preserved():
    # Visual line breaks inside a pecha page should be kept.
    text = "line one\nline two\nline three"
    result = normalize_line(text)
    assert result.count("\n") == 2


def test_normalize_line_empty_visual_lines_dropped():
    # Lines that become empty after normalization are dropped.
    text = "གཅིག\n\x01\x02\nགཉིས"
    result = normalize_line(text)
    lines = result.split("\n")
    # Only non-empty lines should remain.
    assert all(l.strip() for l in lines)


def test_normalize_line_tsheg_variant_folded():
    # U+0F0C → U+0F0B.
    result = normalize_line("ཀ༌")
    assert "༌" not in result
    assert "་" in result


def test_normalize_line_double_shad_expanded():
    result = normalize_line("།། ༎")
    assert "༎" not in result


def test_normalize_line_removes_zero_width():
    result = normalize_line("ཀ​ཁ")
    assert "​" not in result
