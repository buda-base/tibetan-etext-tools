"""Tests for pdf2line.assemble page-boundary detection."""
from pdf2line.assemble import (
    is_artifact_line,
    is_page_number,
    split_into_pages,
    _match_page_boundary,
)


def test_is_page_number_digits():
    assert is_page_number("3")
    assert is_page_number("014")
    assert is_page_number("1.2")
    assert is_page_number("  42  ")


def test_is_page_number_folio():
    assert is_page_number("p1")
    assert is_page_number("P7")
    assert is_page_number("p1036")
    assert is_page_number("  P33  ")
    assert is_page_number("P 904")
    assert is_page_number("p 12")


def test_is_page_number_digit_annotations():
    assert is_page_number("354 空白")
    assert is_page_number("506 缺空白")
    assert is_page_number("506缺空白")
    assert is_page_number("764空白缺頁")
    assert is_page_number("802缺頁空白")
    assert is_page_number("226空白頁")
    assert is_page_number("530此為空白頁")


def test_is_page_number_rejects_non_boundaries():
    assert not is_page_number("p1 extra")
    assert not is_page_number("Page1:")
    assert not is_page_number("www.jonangdharma.org")
    assert not is_page_number("")


def test_match_page_boundary_plain_and_annotations():
    assert _match_page_boundary("Page54") == (True, None)
    assert _match_page_boundary("Page781") == (True, None)
    assert _match_page_boundary("Page56 缺") == (True, None)
    assert _match_page_boundary("Page56缺") == (True, None)
    assert _match_page_boundary("Page306:空白") == (True, None)
    assert _match_page_boundary("Page296: 缺") == (True, None)
    assert _match_page_boundary("Page:402:") == (True, None)
    assert _match_page_boundary("Page:702") == (True, None)
    assert _match_page_boundary("Page79:xxxx") == (True, None)
    assert _match_page_boundary("Page290:xxx") == (True, None)


def test_match_page_boundary_keeps_tibetan():
    line = "Page1: ༄།།title"
    boundary, rest = _match_page_boundary(line)
    assert boundary is True
    assert rest is not None
    assert "༄" in rest

    boundary, rest = _match_page_boundary("Page:401:བདེ་བརྒྱ་ཐམས་")
    assert boundary is True
    assert rest is not None
    assert "བདེ" in rest


def test_match_page_boundary_paren_index():
    assert _match_page_boundary("Page981(157):") == (True, None)
    boundary, rest = _match_page_boundary("Page979(155):ལྷོ་སྒོས བརྒྱད་བྱོན། ཆོ་ག")
    assert boundary is True
    assert rest is not None
    assert "ལྷོ" in rest
    boundary, rest = _match_page_boundary("Page981(157):ཁ གཅིག")
    assert boundary is True
    assert rest == "ཁ གཅིག"


def test_split_drops_paren_page_marker_prefix():
    pages = ["Page825(1):ཁ་གཅིག\nbody\n"]
    out = split_into_pages(pages, collect_boilerplate=False)
    assert len(out) == 1
    assert out[0].startswith("ཁ")
    assert "Page825" not in out[0]


def test_artifact_line():
    assert is_artifact_line("*     **")
    assert is_artifact_line("**")
    assert not is_artifact_line("*ཀགཅིག")
    assert is_artifact_line("xxxx")
    assert is_artifact_line("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    assert is_artifact_line("Image As Per Original Document")
    assert is_artifact_line("\\")


def test_split_drops_ladakh_blank_folio_markers():
    pages = [
        "764空白缺頁\n802缺頁空白\n"
        "Page79:xxxx\nxxxxxxxxxxx\n"
        "Image As Per Original Document\n"
        "Page:402:\ncontent\n"
    ]
    out = split_into_pages(pages, collect_boilerplate=False)
    assert out == ["content"]
    joined = "\n".join(out)
    assert "764" not in joined
    assert "Page79" not in joined
    assert "Image As" not in joined
    assert "xxxx" not in joined


def test_split_drops_folio_markers():
    pages = ["p1\nline one\np2\nline two\n"]
    out = split_into_pages(pages, drop_page_numbers=True, collect_boilerplate=False)
    assert out == ["line one", "line two"]


def test_split_drops_page_markers_and_annotations():
    pages = [
        "Page54\nPage55\nPage56缺\n354 空白\n"
        "Page306:空白\n*     **\ncontent line\n"
    ]
    out = split_into_pages(pages, drop_page_numbers=True, collect_boilerplate=False)
    assert out == ["content line"]
    joined = "\n".join(out)
    assert "Page54" not in joined
    assert "空白" not in joined
    assert "**" not in joined


def test_split_page_marker_keeps_tibetan_rest():
    pages = ["Page1: ༄།།title\nbody line\n"]
    out = split_into_pages(pages, collect_boilerplate=False)
    assert len(out) == 1
    assert out[0].startswith("༄")
    assert "body line" in out[0]
