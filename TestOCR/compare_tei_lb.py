"""
Compare two TEI-like XML files that both use <pb/> and <lb/>.

Default (``ALIGN_PAGES_BY_INDEX_ONLY``): page *i* on the left is compared only to
page *i* on the right.

Within each matched page, line pairing is controlled by ``ALIGN_LB_BY_INDEX_ONLY``:
if True, ``<lb/>`` segment *j* is compared only to segment *j*; if False (default),
lines are matched with multiset cancellation of identical normalized lines, then
ordered diff on the remainder (same as legacy inner logic).

Legacy mode (``ALIGN_PAGES_BY_INDEX_ONLY = False``): similarity-based page
alignment, then multiset + ordered line diff (can pair different page indices).

**Position-stable correction dataset** (``WRITE_CORRECTION_DATASET``): for each
differing line pair, Tibetan tokens are aligned with a Levenshtein backtrace on
token sequences (same tokenization as legacy snippets). Only **substitutions**
(both sides non-empty, tokens differ) are written, keyed by
``(page_index, line_index, aligned_index)`` plus ``left_token_index`` (0-based
index into ``tokenize_line_text(left)``). Use ``left_token_index`` for
``replace_diff.py``; ``aligned_index`` is the Levenshtein alignment column.

``left_value`` / ``right_value`` use ``normalize_for_compare`` (``<hi>`` unwrapped).
Legacy CSV cells use ``format_diff_snippets``: **one row per** token-level
``replace``/``delete``/``insert``, each with one neighbor token before/after when
present (same line only). Columns ``line_left`` / ``line_right`` are 0-based
indices of the ``<lb/>`` segment within its page block (from ``split_lb_units``),
matching ``page_*``: a leading ``<lb/>`` on each page adds an extra first segment.
``page_left`` / ``page_right`` use the same 0-based convention for page blocks
and a leading ``<pb/>``.


Usage:
  python compare_tei_lb.py
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections import defaultdict, deque
from difflib import SequenceMatcher
from pathlib import Path

from lxml import etree
from lxml.etree import strip_tags

# --- set your inputs here ---
PATH_XML_LEFT = Path(r"D:\Work\OpenPecha\conversion\IE3KG694\IE3KG694_output\archive\VE1ER1074\UT1ER1074_0001.xml")  # e.g. PyMuPDF output
PATH_XML_RIGHT = Path(r"D:\Work\OpenPecha\conversion\IE3KG694\IE3KG694_output\archive\VE1ER1074\UT1ER1074_0008.xml")  # e.g. Tesseract output
OUTPUT_CSV = Path(r"D:\Work\OpenPecha\conversion\IE3KG694\IE3KG694_output\archive\VE1ER1074\lb_diff_pairs.csv")

# If True, only compare text inside <body>...</body> when those tags exist.
USE_BODY_ONLY = True

# If True (recommended): page index i on the left is compared only to page i on
# the right. If False: legacy mode uses SequenceMatcher on whole-page text to
# align pages (can pair unrelated page indices).
ALIGN_PAGES_BY_INDEX_ONLY = True

# Only used when ALIGN_PAGES_BY_INDEX_ONLY is True. If True: within each page,
# <lb/> segment j is compared only to segment j (positional). If False: multiset
# match of identical normalized lines, then ordered diff on leftovers (tolerates
# extra/missing <lb/> better than positional pairing).
ALIGN_LB_BY_INDEX_ONLY = False

# If True, log a warning for each page (1-based index) where the raw <lb/> tag
# count differs between left and right.
WARN_ON_LB_COUNT_MISMATCH_PER_PAGE = True

# Hard cap per cell (characters); longer snippets get a middle ellipsis.
DIFF_SNIPPET_MAX_CHARS = 200

# Position-stable correction dataset (token alignment + aligned_index per line).
OUTPUT_CORRECTION_CSV = OUTPUT_CSV.with_name(
    OUTPUT_CSV.stem + "_correction_dataset.csv"
)
# If True, write legacy left_value/right_value snippet rows to OUTPUT_CSV.
WRITE_LEGACY_LB_CSV = True
# If True, write page_index, line_index, aligned_index, left_token, right_token.
WRITE_CORRECTION_DATASET = True
# If True, add a JSON array column left_context (debug only; not for matching).
INCLUDE_LEFT_CONTEXT_IN_CORRECTION_CSV = False

_PB_SPLIT = re.compile(r"<pb\s*/>", re.IGNORECASE)
_LB_SPLIT = re.compile(r"<lb\s*/>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
# Non-whitespace, non-tshek runs (Tibetan “word” / syllable clusters for context).
_TOKEN_SPAN = re.compile(r"[^\s་]+")
_BODY = re.compile(
    r"<body\b[^>]*>([\s\S]*?)</body>", re.IGNORECASE | re.DOTALL
)

_NS_TEI = "http://www.tei-c.org/ns/1.0"
_HI_TAGS = ("hi", f"{{{_NS_TEI}}}hi")

logger = logging.getLogger(__name__)


def extract_body(xml: str) -> str:
    if not USE_BODY_ONLY:
        return xml
    m = _BODY.search(xml)
    return m.group(1) if m else xml


def split_pb_pages(fragment: str) -> list[str]:
    """Segments between <pb/> markers (one unit per page block)."""
    return _PB_SPLIT.split(fragment)


def split_lb_units(fragment: str) -> list[str]:
    """Segments between <lb/> markers within one page."""
    return _LB_SPLIT.split(fragment)


def count_lb_tags(page_fragment: str) -> int:
    """Raw ``<lb/>`` tag count in one page block (matches ``<lb`` … ``/>``)."""
    return len(_LB_SPLIT.findall(page_fragment))


def _parse_xml_fragment_or_doc(xml_str: str) -> etree._Element | None:
    """
    Parse a full document (XML declaration), or wrap a fragment in ``<wrap>…</wrap>``.

    Fragments like ``<hi>…</hi>more`` are not valid single-root XML; parsing them
    without a wrapper drops text after the first element, so we always wrap unless
    the string is a full document.
    """
    s = xml_str.strip()
    if not s:
        return None
    parser = etree.XMLParser(recover=True, huge_tree=True)
    if s.startswith("<?xml"):
        try:
            return etree.fromstring(s.encode("utf-8"), parser=parser)
        except etree.XMLSyntaxError:
            return None
    wrapped = f"<wrap>{s}</wrap>"
    try:
        return etree.fromstring(wrapped.encode("utf-8"), parser=parser)
    except etree.XMLSyntaxError:
        return None


def _strip_hi_elements(root: etree._Element) -> None:
    """Remove <hi> wrappers but keep their text (and tails), TEI namespaced or not."""
    strip_tags(root, *_HI_TAGS)


def extract_text_blocks(xml_str: str) -> list[str]:
    """
    Like walking the tree for text, but ``<hi>`` is unwrapped first so its inner
    text is kept; other element markup is ignored by taking text nodes only.

    Returns non-empty stripped text node strings in document order.
    """
    root = _parse_xml_fragment_or_doc(xml_str)
    if root is None:
        fb = _normalize_regex_fallback(xml_str)
        return [fb] if fb else []
    _strip_hi_elements(root)
    out: list[str] = []
    for t in root.xpath(".//text()"):
        if t is None:
            continue
        u = str(t).strip()
        if u:
            out.append(u)
    return out


def _normalize_regex_fallback(segment: str) -> str:
    """If XML parse fails: strip all tags (including <hi>), collapse space."""
    t = _TAG.sub("", segment)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_for_compare(segment: str) -> str:
    """
    Plain text for alignment: unwrap ``<hi>`` via lxml, then join text nodes;
    other tags are dropped (text only). Falls back to regex if parsing fails.
    """
    root = _parse_xml_fragment_or_doc(segment)
    if root is not None:
        _strip_hi_elements(root)
        parts = [
            str(t).strip()
            for t in root.xpath(".//text()")
            if t is not None and str(t).strip()
        ]
        t = " ".join(parts)
        t = re.sub(r"\s+", " ", t).strip()
        return t
    return _normalize_regex_fallback(segment)


def normalize_page(segment: str) -> str:
    """Whole page string for page-level SequenceMatcher."""
    return normalize_for_compare(segment)


def load_pages(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    text = extract_body(text)
    return split_pb_pages(text)


def collect_lb_lines(
    pages: list[str], start: int, end: int
) -> tuple[list[str], list[str], list[int], list[int]]:
    """Flatten <lb/> line units across pages[start:end]; page_idx is 0-based in ``pages``.

    line_idx is 0-based index of each segment among ``split_lb_units`` for that page.
    """
    norm_lines: list[str] = []
    raw_lines: list[str] = []
    page_idx: list[int] = []
    line_idx: list[int] = []
    for pidx in range(start, end):
        for lj, seg in enumerate(split_lb_units(pages[pidx])):
            raw_lines.append(seg)
            norm_lines.append(normalize_for_compare(seg))
            page_idx.append(pidx)
            line_idx.append(lj)
    return norm_lines, raw_lines, page_idx, line_idx


def _page_cell(idx: int | None) -> str:
    """Page block index for CSV (0-based: first segment after a leading ``<pb/>`` is 0).

    ``split_pb_pages`` counts one segment before the first ``<pb/>`` and one per
    following ``<pb/>``; a lone ``<pb/>`` at the top makes the first real page
    block index 1, which used to display as ``2``. We subtract 1 from that naive
    1-based count so ``page_left`` / ``page_right`` align with folio numbers.
    """
    if idx is None:
        return ""
    return str(idx)


def _line_cell(idx: int | None) -> str:
    """0-based ``<lb/>`` segment index within its page for CSV; empty if no line.

    When each page starts with ``<lb/>``, ``split_lb_units`` has an extra first
    segment (same idea as ``_page_cell``). We use ``idx`` not ``idx + 1`` so the
    first real line of each page is not shifted to ``2``.
    """
    if idx is None:
        return ""
    return str(idx)


def _token_spans(s: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _TOKEN_SPAN.finditer(s)]


def tokenize_line_text(segment: str) -> list[str]:
    """
    Tibetan “word” tokens for one ``<lb/>`` segment: normalized plain text, then
    ``_TOKEN_SPAN`` runs (same tokenization as ``format_diff_snippets``).
    """
    text = normalize_for_compare(segment)
    return [text[a:b] for a, b in _token_spans(text)]


def _levenshtein_token_alignment_slots(
    left_toks: list[str],
    right_toks: list[str],
    start_ai: int,
) -> tuple[list[tuple[int, int | None, int | None, str | None, str | None]], int]:
    """
    Ordered alignment columns via Levenshtein backtrace on token sequences.

    Each tuple is
    ``(aligned_index, left_token_index_or_none, right_token_index_or_none,
       left_token_or_none, right_token_or_none)``.
    ``aligned_index`` increases by one per column (match / substitute / insert /
    delete) in path order. Indices refer to positions in ``left_toks`` /
    ``right_toks``.
    """
    n, m = len(left_toks), len(right_toks)
    if n == 0 and m == 0:
        return [], start_ai
    # dp[i][j] = min cost to align left[:i] with right[:j]
    inf = n + m + 5
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best = inf
            if i > 0 and j > 0:
                sub = 0 if left_toks[i - 1] == right_toks[j - 1] else 1
                best = min(best, dp[i - 1][j - 1] + sub)
            if i > 0:
                best = min(best, dp[i - 1][j] + 1)
            if j > 0:
                best = min(best, dp[i][j - 1] + 1)
            dp[i][j] = best
    # Backtrace from (n, m); collect ops in reverse.
    ops: list[tuple[str, int | None, int | None]] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            sub = 0 if left_toks[i - 1] == right_toks[j - 1] else 1
            if dp[i][j] == dp[i - 1][j - 1] + sub:
                ops.append(("diag", i - 1, j - 1))
                i, j = i - 1, j - 1
                continue
        if i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            ops.append(("up", i - 1, None))
            i -= 1
            continue
        if j > 0 and dp[i][j] == dp[i][j - 1] + 1:
            ops.append(("left", None, j - 1))
            j -= 1
            continue
        # Prefer diagonal on ties (stable path).
        if i > 0 and j > 0:
            ops.append(("diag", i - 1, j - 1))
            i, j = i - 1, j - 1
            continue
        if i > 0:
            ops.append(("up", i - 1, None))
            i -= 1
            continue
        ops.append(("left", None, j - 1))
        j -= 1
    ops.reverse()
    slots: list[tuple[int, int | None, int | None, str | None, str | None]] = []
    ai = start_ai
    for kind, li, rj in ops:
        if kind == "diag":
            assert li is not None and rj is not None
            slots.append(
                (ai, li, rj, left_toks[li], right_toks[rj])
            )
            ai += 1
        elif kind == "up":
            assert li is not None
            slots.append((ai, li, None, left_toks[li], None))
            ai += 1
        else:
            assert rj is not None
            slots.append((ai, None, rj, None, right_toks[rj]))
            ai += 1
    return slots, ai


def substitution_rows_for_line_segments(
    left_segment: str,
    right_segment: str,
    *,
    page_index: int,
    line_index: int,
    include_left_context: bool,
) -> list[dict[str, int | str]]:
    """
    Sequence-align LEFT vs RIGHT tokens for one line pair; return one dict per
    **substitution** (both sides non-empty and tokens differ).

    ``aligned_index`` is the 0-based column index in the aligned sequence for this
    line (counts equal, insert, delete, and substitute columns in order).
    """
    tl = tokenize_line_text(left_segment)
    tr = tokenize_line_text(right_segment)
    slots, _ = _levenshtein_token_alignment_slots(tl, tr, 0)
    rows: list[dict[str, int | str]] = []
    for aligned_index, _li, _rj, ltok, rtok in slots:
        if ltok is None or rtok is None:
            continue
        if ltok == rtok:
            continue
        row: dict[str, int | str] = {
            "page_index": page_index,
            "line_index": line_index,
            "aligned_index": aligned_index,
            # Index into ``tokenize_line_text(left_segment)`` (left token column).
            # Use this for deterministic replacement; ``aligned_index`` is the
            # Levenshtein alignment column and may differ when inserts/deletes occur.
            "left_token_index": int(_li),
            "left_token": ltok,
            "right_token": rtok,
        }
        if include_left_context and _li is not None:
            i = _li
            ctx = []
            for d in (-2, -1, 0, 1, 2):
                j = i + d
                ctx.append(tl[j] if 0 <= j < len(tl) else "")
            row["left_context"] = json.dumps(ctx, ensure_ascii=False)
        rows.append(row)
    return rows


def _span_idx_for_pos(spans: list[tuple[int, int]], pos: int) -> int:
    """Index of the token containing character offset ``pos``."""
    if not spans:
        return 0
    pos = max(0, pos)
    for i, (a, b) in enumerate(spans):
        if pos < b:
            return i
    return len(spans) - 1


def _char_diff_core_exclusive(left: str, right: str) -> tuple[int, int, int, int]:
    """
    Return ``(sl, el, sr, er)`` exclusive end indices: left[sl:el] vs right[sr:er]
    after stripping longest common prefix and suffix (character-wise).
    """
    la, lb = len(left), len(right)
    pf = 0
    while pf < la and pf < lb and left[pf] == right[pf]:
        pf += 1
    ps = 0
    while (
        ps < la - pf
        and ps < lb - pf
        and left[la - 1 - ps] == right[lb - 1 - ps]
    ):
        ps += 1
    return pf, la - ps, pf, lb - ps


def _expand_core_plus_neighbor_tokens(
    s: str,
    spans: list[tuple[int, int]],
    sl: int,
    el_exc: int,
) -> str:
    """
    ``left[sl:el_exc]`` is the char-level diff core. Widen to whole tokens and
    include **one** token before and **one** after when they exist (same string).
    """
    if not spans:
        return s[sl:el_exc] if el_exc > sl else ""
    if el_exc <= sl:
        return ""
    first_tok = _span_idx_for_pos(spans, sl)
    last_tok = _span_idx_for_pos(spans, el_exc - 1)
    lo = max(0, first_tok - 1)
    hi = min(len(spans) - 1, last_tok + 1)
    return s[spans[lo][0] : spans[hi][1]]


def _snippet_for_token_replace(
    s: str,
    spans: list[tuple[int, int]],
    i1: int,
    i2_exc: int,
) -> str:
    """
    ``i1:i2_exc`` = diff opcode range on token indices (exclusive end).
    Include one full token before and one full token after when present.
    """
    n = len(spans)
    if n == 0:
        return s
    start_tok = (i1 - 1) if i1 > 0 else i1
    if i2_exc < n:
        end_tok = i2_exc
    else:
        end_tok = i2_exc - 1
    return s[spans[start_tok][0] : spans[end_tok][1]]


def _cap_middle(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    half = max_chars // 2 - 2
    return s[:half] + " … " + s[-half:]


def _trim_common_prefix_suffix(a: str, b: str) -> tuple[str, str]:
    """Drop shared prefix/suffix between two strings (character-wise)."""
    if not a or not b:
        return a, b
    la, lb = len(a), len(b)
    i = 0
    while i < la and i < lb and a[i] == b[i]:
        i += 1
    j = 0
    while (
        j < la - i
        and j < lb - i
        and a[la - 1 - j] == b[lb - 1 - j]
    ):
        j += 1
    return a[i : la - j], b[i : lb - j]


def format_diff_snippets(
    left: str,
    right: str,
    *,
    max_chars: int | None = None,
) -> list[tuple[str, str]]:
    """
    One ``(left, right)`` snippet per token-level difference: every
    ``replace`` / ``delete`` / ``insert`` from ``SequenceMatcher``, each with
    one token before and after the changed run when present (same string only).

    If tokenization yields no opcodes but strings differ, one char-LCP/LCS
    fallback pair is returned.
    """
    cap = max_chars if max_chars is not None else DIFF_SNIPPET_MAX_CHARS
    left = left or ""
    right = right or ""
    if left == right:
        return []
    if not left:
        return [("", _cap_middle(right, cap))]
    if not right:
        return [(_cap_middle(left, cap), "")]

    sp_l = _token_spans(left)
    sp_r = _token_spans(right)
    if not sp_l or not sp_r:
        tl, tr = _trim_common_prefix_suffix(left, right)
        return [(_cap_middle(tl, cap), _cap_middle(tr, cap))]

    tl = [left[a:b] for a, b in sp_l]
    tr = [right[a:b] for a, b in sp_r]
    sm = SequenceMatcher(None, tl, tr, autojunk=False)

    out: list[tuple[str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 > i1 and j2 > j1:
            sn_l = _snippet_for_token_replace(left, sp_l, i1, i2)
            sn_r = _snippet_for_token_replace(right, sp_r, j1, j2)
            out.append((_cap_middle(sn_l, cap), _cap_middle(sn_r, cap)))
        elif tag == "delete" and i2 > i1:
            sn_l = _snippet_for_token_replace(left, sp_l, i1, i2)
            out.append((_cap_middle(sn_l, cap), ""))
        elif tag == "insert" and j2 > j1:
            sn_r = _snippet_for_token_replace(right, sp_r, j1, j2)
            out.append(("", _cap_middle(sn_r, cap)))

    if not out:
        sl, el, sr, er = _char_diff_core_exclusive(left, right)
        sn_l = _expand_core_plus_neighbor_tokens(left, sp_l, sl, el)
        sn_r = _expand_core_plus_neighbor_tokens(right, sp_r, sr, er)
        out.append((_cap_middle(sn_l, cap), _cap_middle(sn_r, cap)))

    return out


def compare_pages_by_index_only(
    pages_left: list[str],
    pages_right: list[str],
) -> list[tuple[str, str, str, str, str, str]]:
    """
    Page ``i`` ↔ page ``i`` only; line ``j`` ↔ line ``j`` only.
    Skip rows where both sides normalize to the same string.
    """
    rows: list[tuple[str, str, str, str, str, str]] = []
    n = min(len(pages_left), len(pages_right))
    for i in range(n):
        norms_l = [normalize_for_compare(s) for s in split_lb_units(pages_left[i])]
        norms_r = [normalize_for_compare(s) for s in split_lb_units(pages_right[i])]
        max_j = max(len(norms_l), len(norms_r))
        p_cell = _page_cell(i)
        for j in range(max_j):
            vl = norms_l[j] if j < len(norms_l) else ""
            vr = norms_r[j] if j < len(norms_r) else ""
            if vl == vr:
                continue
            lL = _line_cell(j) if j < len(norms_l) else ""
            lR = _line_cell(j) if j < len(norms_r) else ""
            rows.append((vl, vr, p_cell, lL, p_cell, lR))
    for i in range(n, len(pages_left)):
        p_cell = _page_cell(i)
        for lj, seg in enumerate(split_lb_units(pages_left[i])):
            t = normalize_for_compare(seg)
            if not t:
                continue
            rows.append((t, "", p_cell, _line_cell(lj), "", ""))
    for i in range(n, len(pages_right)):
        p_cell = _page_cell(i)
        for lj, seg in enumerate(split_lb_units(pages_right[i])):
            t = normalize_for_compare(seg)
            if not t:
                continue
            rows.append(("", t, "", "", p_cell, _line_cell(lj)))
    return rows


def compare_pages_by_index_then_diff_lb(
    pages_left: list[str],
    pages_right: list[str],
) -> list[tuple[str, str, str, str, str, str]]:
    """
    Page ``i`` ↔ page ``i`` only; within each page, ``diff_lb_units`` (not j↔j).
    """
    rows: list[tuple[str, str, str, str, str, str]] = []
    n = min(len(pages_left), len(pages_right))
    for i in range(n):
        rows.extend(_diff_one_page_pair(pages_left, pages_right, i, i))
    for i in range(n, len(pages_left)):
        n_l, _, pl, ll = collect_lb_lines(pages_left, i, i + 1)
        rows.extend(diff_lb_units(n_l, pl, ll, [], [], []))
    for i in range(n, len(pages_right)):
        n_r, _, pr, lr = collect_lb_lines(pages_right, i, i + 1)
        rows.extend(diff_lb_units([], [], [], n_r, pr, lr))
    return rows


def warn_lb_count_mismatches_per_page(
    pages_left: list[str],
    pages_right: list[str],
) -> None:
    """Emit a warning when raw ``<lb/>`` counts differ for the same page block index."""
    if not WARN_ON_LB_COUNT_MISMATCH_PER_PAGE:
        return
    n = min(len(pages_left), len(pages_right))
    mismatch_pages = 0
    for i in range(n):
        c_l = count_lb_tags(pages_left[i])
        c_r = count_lb_tags(pages_right[i])
        if c_l != c_r:
            mismatch_pages += 1
            logger.warning(
                f"<lb/> count mismatch on page block index {i}: left has {c_l} <lb/>, "
                f"right {c_r} <lb/>"
            )
    if mismatch_pages:
        logger.warning(
            f"Total page block(s) with <lb/> count mismatch: {mismatch_pages}"
        )


def _diff_lb_units_sequence(
    norm_left: list[str],
    page_left: list[int],
    line_left: list[int],
    norm_right: list[str],
    page_right: list[int],
    line_right: list[int],
) -> list[tuple[str, str, str, str, str, str]]:
    """Ordered line diff (SequenceMatcher) on parallel lists."""
    assert (
        len(norm_left) == len(page_left) == len(line_left)
        and len(norm_right) == len(page_right) == len(line_right)
    )
    sm = SequenceMatcher(None, norm_left, norm_right, autojunk=False)
    rows: list[tuple[str, str, str, str, str, str]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace":
            la, ra = i2 - i1, j2 - j1
            m = min(la, ra)
            for t in range(m):
                rows.append(
                    (
                        norm_left[i1 + t],
                        norm_right[j1 + t],
                        _page_cell(page_left[i1 + t]),
                        _line_cell(line_left[i1 + t]),
                        _page_cell(page_right[j1 + t]),
                        _line_cell(line_right[j1 + t]),
                    )
                )
            for t in range(m, la):
                rows.append(
                    (
                        norm_left[i1 + t],
                        "",
                        _page_cell(page_left[i1 + t]),
                        _line_cell(line_left[i1 + t]),
                        "",
                        "",
                    )
                )
            for t in range(m, ra):
                rows.append(
                    (
                        "",
                        norm_right[j1 + t],
                        "",
                        "",
                        _page_cell(page_right[j1 + t]),
                        _line_cell(line_right[j1 + t]),
                    )
                )
        elif tag == "delete":
            for k in range(i1, i2):
                rows.append(
                    (
                        norm_left[k],
                        "",
                        _page_cell(page_left[k]),
                        _line_cell(line_left[k]),
                        "",
                        "",
                    )
                )
        elif tag == "insert":
            for k in range(j1, j2):
                rows.append(
                    (
                        "",
                        norm_right[k],
                        "",
                        "",
                        _page_cell(page_right[k]),
                        _line_cell(line_right[k]),
                    )
                )
    return rows


def diff_lb_units(
    norm_left: list[str],
    page_left: list[int],
    line_left: list[int],
    norm_right: list[str],
    page_right: list[int],
    line_right: list[int],
) -> list[tuple[str, str, str, str, str, str]]:
    """
    Within a single page: lines that match exactly (normalized text) cancel in
    any order; only **unmatched** lines are compared top-to-bottom via
    SequenceMatcher.
    """
    assert (
        len(norm_left) == len(page_left) == len(line_left)
        and len(norm_right) == len(page_right) == len(line_right)
    )
    q_l: dict[str, deque[int]] = defaultdict(deque)
    q_r: dict[str, deque[int]] = defaultdict(deque)
    for i, n in enumerate(norm_left):
        q_l[n].append(i)
    for j, n in enumerate(norm_right):
        q_r[n].append(j)
    paired_l: set[int] = set()
    paired_r: set[int] = set()
    for n in set(q_l) | set(q_r):
        while q_l[n] and q_r[n]:
            paired_l.add(q_l[n].popleft())
            paired_r.add(q_r[n].popleft())
    rem_l_norm = [norm_left[i] for i in range(len(norm_left)) if i not in paired_l]
    rem_l_page = [page_left[i] for i in range(len(norm_left)) if i not in paired_l]
    rem_l_line = [line_left[i] for i in range(len(norm_left)) if i not in paired_l]
    rem_r_norm = [norm_right[j] for j in range(len(norm_right)) if j not in paired_r]
    rem_r_page = [page_right[j] for j in range(len(norm_right)) if j not in paired_r]
    rem_r_line = [line_right[j] for j in range(len(norm_right)) if j not in paired_r]
    return _diff_lb_units_sequence(
        rem_l_norm, rem_l_page, rem_l_line, rem_r_norm, rem_r_page, rem_r_line
    )


def _diff_one_page_pair(
    pages_left: list[str],
    pages_right: list[str],
    idx_left: int,
    idx_right: int,
) -> list[tuple[str, str, str, str, str, str]]:
    """Compare ``<lb/>`` lines only within the two given page indices."""
    n_l, _, pl, ll = collect_lb_lines(pages_left, idx_left, idx_left + 1)
    n_r, _, pr, lr = collect_lb_lines(pages_right, idx_right, idx_right + 1)
    return diff_lb_units(n_l, pl, ll, n_r, pr, lr)


def diff_replace_page_span(
    pages_left: list[str],
    pages_right: list[str],
    pi1: int,
    pi2: int,
    pj1: int,
    pj2: int,
) -> list[tuple[str, str, str, str, str, str]]:
    """
    Align pages first, then diff ``<lb/>`` lines **within** matched page pairs only.

    Inner ``replace`` spans with unequal page counts no longer merge all ``<lb/>``
    lines into one list (that paired unrelated page indices).
    """
    rows: list[tuple[str, str, str, str, str, str]] = []
    np_l, np_r = pi2 - pi1, pj2 - pj1
    if np_l == np_r:
        for k in range(np_l):
            rows.extend(
                _diff_one_page_pair(pages_left, pages_right, pi1 + k, pj1 + k)
            )
        return rows

    sub_l = [normalize_page(pages_left[i]) for i in range(pi1, pi2)]
    sub_r = [normalize_page(pages_right[i]) for i in range(pj1, pj2)]
    sm_sub = SequenceMatcher(None, sub_l, sub_r, autojunk=False)
    for st, a1, a2, b1, b2 in sm_sub.get_opcodes():
        if st == "equal":
            for k in range(a2 - a1):
                rows.extend(
                    _diff_one_page_pair(
                        pages_left,
                        pages_right,
                        pi1 + a1 + k,
                        pj1 + b1 + k,
                    )
                )
        elif st == "replace":
            na, nb = a2 - a1, b2 - b1
            # Pair page (a1+k) with (b1+k) for k < min(na, nb); never flatten lines
            # across multiple pages (that paired line i on the left with line i
            # across unrelated page indices, e.g. 117 vs 9).
            m = min(na, nb)
            for k in range(m):
                rows.extend(
                    _diff_one_page_pair(
                        pages_left,
                        pages_right,
                        pi1 + a1 + k,
                        pj1 + b1 + k,
                    )
                )
            for k in range(m, na):
                idx = pi1 + a1 + k
                n_l, _, pl, ll = collect_lb_lines(pages_left, idx, idx + 1)
                rows.extend(diff_lb_units(n_l, pl, ll, [], [], []))
            for k in range(m, nb):
                idx = pj1 + b1 + k
                n_r, _, pr, lr = collect_lb_lines(pages_right, idx, idx + 1)
                rows.extend(diff_lb_units([], [], [], n_r, pr, lr))
        elif st == "delete":
            for k in range(a1, a2):
                n_l, _, pl, ll = collect_lb_lines(pages_left, pi1 + k, pi1 + k + 1)
                rows.extend(diff_lb_units(n_l, pl, ll, [], [], []))
        elif st == "insert":
            for k in range(b1, b2):
                n_r, _, pr, lr = collect_lb_lines(pages_right, pj1 + k, pj1 + k + 1)
                rows.extend(diff_lb_units([], [], [], n_r, pr, lr))
    return rows


def main() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    pages_left = load_pages(PATH_XML_LEFT)
    pages_right = load_pages(PATH_XML_RIGHT)

    n_pages_left = len(pages_left)
    n_pages_right = len(pages_right)
    logger.info(f"n_pages_left: {n_pages_left}, n_pages_right: {n_pages_right}")
    if n_pages_left != n_pages_right:
        delta = n_pages_left - n_pages_right
        logger.warning(
            f"Page block count mismatch (split on <pb/> in <body>): "
            f"left has {n_pages_left} blocks, right has {n_pages_right} blocks "
            f"(difference left - right: {delta:+d})"
        )

    warn_lb_count_mismatches_per_page(pages_left, pages_right)

    if ALIGN_PAGES_BY_INDEX_ONLY:
        if ALIGN_LB_BY_INDEX_ONLY:
            rows = compare_pages_by_index_only(pages_left, pages_right)
            ratio_msg = "index-aligned pages; positional <lb/> (j ↔ j)"
        else:
            rows = compare_pages_by_index_then_diff_lb(pages_left, pages_right)
            ratio_msg = (
                "index-aligned pages; multiset/ordered <lb/> diff within page"
            )
    else:
        norm_pages_left = [normalize_page(p) for p in pages_left]
        norm_pages_right = [normalize_page(p) for p in pages_right]

        page_sm = SequenceMatcher(
            None, norm_pages_left, norm_pages_right, autojunk=False
        )
        rows: list[tuple[str, str, str, str, str, str]] = []
        for p_tag, pi1, pi2, pj1, pj2 in page_sm.get_opcodes():
            if p_tag == "equal":
                for k in range(pi2 - pi1):
                    rows.extend(
                        _diff_one_page_pair(
                            pages_left, pages_right, pi1 + k, pj1 + k
                        )
                    )
            elif p_tag == "replace":
                rows.extend(
                    diff_replace_page_span(
                        pages_left, pages_right, pi1, pi2, pj1, pj2
                    )
                )
            elif p_tag == "delete":
                for k in range(pi1, pi2):
                    n_l, _, pl, ll = collect_lb_lines(pages_left, k, k + 1)
                    rows.extend(diff_lb_units(n_l, pl, ll, [], [], []))
            elif p_tag == "insert":
                for k in range(pj1, pj2):
                    n_r, _, pr, lr = collect_lb_lines(pages_right, k, k + 1)
                    rows.extend(diff_lb_units([], [], [], n_r, pr, lr))
        ratio_msg = f"similarity page-sequence ratio: {page_sm.ratio():.4f}"

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)

    def _parse_csv_int(s: str, default: int = -1) -> int:
        if s is None or str(s).strip() == "":
            return default
        return int(str(s).strip())

    written_legacy = 0
    if WRITE_LEGACY_LB_CSV:
        with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "left_value",
                    "right_value",
                    "page_left",
                    "line_left",
                    "page_right",
                    "line_right",
                ]
            )
            for left, right, pL, linL, pR, linR in rows:
                for sl, sr in format_diff_snippets(left, right):
                    w.writerow([sl, sr, pL, linL, pR, linR])
                    written_legacy += 1

    written_correction = 0
    if WRITE_CORRECTION_DATASET:
        fieldnames = [
            "page_index",
            "line_index",
            "aligned_index",
            "left_token_index",
            "left_token",
            "right_token",
        ]
        if INCLUDE_LEFT_CONTEXT_IN_CORRECTION_CSV:
            fieldnames.append("left_context")
        with OUTPUT_CORRECTION_CSV.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            w.writeheader()
            for left, right, pL, linL, _pR, _linR in rows:
                pi = _parse_csv_int(pL, default=-1)
                li = _parse_csv_int(linL, default=-1)
                for row in substitution_rows_for_line_segments(
                    left or "",
                    right or "",
                    page_index=pi,
                    line_index=li,
                    include_left_context=INCLUDE_LEFT_CONTEXT_IN_CORRECTION_CSV,
                ):
                    w.writerow(row)
                    written_correction += 1

    if WRITE_LEGACY_LB_CSV:
        print(
            f"Wrote {written_legacy} legacy row(s) from {len(rows)} differing "
            f"line pair(s) to {OUTPUT_CSV.resolve()} ({ratio_msg})"
        )
    if WRITE_CORRECTION_DATASET:
        print(
            f"Wrote {written_correction} correction substitution row(s) "
            f"(aligned_index + left_token_index) to {OUTPUT_CORRECTION_CSV.resolve()} ({ratio_msg})"
        )
    if not WRITE_LEGACY_LB_CSV and not WRITE_CORRECTION_DATASET:
        print("No CSV output (both WRITE_LEGACY_LB_CSV and WRITE_CORRECTION_DATASET are False).")


if __name__ == "__main__":
    main()
