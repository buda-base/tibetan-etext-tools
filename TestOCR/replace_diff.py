"""
Apply position-based token replacements to TEI-like XML using a JSON diff list.

Each occurrence is ``(page_index, line_index, left_token_index)`` (same page/line
splitting as ``compare_tei_lb.py`` / ``group_tibetan_csv_diffs.py``):

* Pages: segments between ``<pb/>`` markers (after optional ``<body>`` extraction).
* Lines: segments between ``<lb/>`` markers within one page block.
* **left_token_index:** 0-based index into ``tokenize_line_text`` for that line
  (the left file’s token list). Regenerate ``*_grouped.json`` from a correction
  CSV that includes the ``left_token_index`` column (``compare_tei_lb`` writes
  it). Older grouped files used ``aligned_index`` (Levenshtein column) as the
  third number and will mis-apply edits—do not use them with this script.

Replacements are applied in descending token-index order within each line so
indices stay stable. Edits are **string slices** on each line’s segment so
``<hi>``…``</hi>`` blocks that span multiple ``<lb/>`` lines are not broken by
per-line XML unwrapping. Output: ``<input_stem>_modified.xml`` next to the input.

Usage:
  python replace_diff.py
"""

from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

# Edit these, then run: python replace_diff.py
INPUT_XML = Path(r"D:\Work\OpenPecha\conversion\IE3KG694\IE3KG694_output\archive\VE1ER1074\UT1ER1074_0001.xml")
DIFF_JSON = Path(r"D:\Work\OpenPecha\conversion\IE3KG694\IE3KG694_output\archive\VE1ER1074\lb_diff_pairs_correction_dataset_grouped.json")
# If True, treat page_index / line_index in JSON as 1-based (subtract 1 before use).
ONE_BASED = False
# If True, only split <pb/> within <body>…</body>; if False, over the whole file.
BODY_ONLY = True

logger = logging.getLogger(__name__)

# Capturing groups so ``re.split`` retains exact delimiter strings for round-trip.
_PB_SPLIT_CAP = re.compile(r"(<pb\s*/>)", re.IGNORECASE)
_LB_SPLIT_CAP = re.compile(r"(<lb\s*/>)", re.IGNORECASE)
_BODY = re.compile(r"<body\b[^>]*>([\s\S]*?)</body>", re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]+>")
# Same as compare_tei_lb: non-whitespace, non-tshek runs.
_TOKEN_SPAN = re.compile(r"[^\s་]+")

_NS_TEI = "http://www.tei-c.org/ns/1.0"
_HI_TAGS = ("hi", f"{{{_NS_TEI}}}hi")


def extract_body(xml: str, body_only: bool) -> str:
    if not body_only:
        return xml
    m = _BODY.search(xml)
    return m.group(1) if m else xml


def inject_body(xml: str, new_body: str, body_only: bool) -> str:
    if not body_only:
        return new_body
    m = _BODY.search(xml)
    if not m:
        return new_body
    return xml[: m.start(1)] + new_body + xml[m.end(1) :]


def split_keep_delim(pattern: re.Pattern[str], fragment: str) -> tuple[list[str], list[str]]:
    """Split on matches of pattern; odd chunks are delimiter strings (exact).

    ``pattern`` must include a **capturing** group around the delimiter so
    ``re.split`` preserves separators (same idea as ``compare_tei_lb`` splits,
    but we keep original tag strings for output).
    """
    chunks = pattern.split(fragment)
    texts: list[str] = []
    seps: list[str] = []
    for i, c in enumerate(chunks):
        if i % 2 == 0:
            texts.append(c)
        else:
            seps.append(c)
    return texts, seps


def join_keep_delim(texts: list[str], seps: list[str]) -> str:
    if not seps:
        return texts[0] if texts else ""
    out: list[str] = [texts[0]]
    for i, s in enumerate(seps):
        out.append(s)
        out.append(texts[i + 1])
    return "".join(out)


def _parse_xml_fragment_or_doc(xml_str: str):
    try:
        from lxml import etree
    except ImportError as e:
        raise SystemExit(
            "replace_diff.py requires the 'lxml' package (same as compare_tei_lb.py)."
        ) from e

    parser = etree.XMLParser(recover=True, huge_tree=True)
    s = xml_str.strip()
    if not s:
        return None
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


def _strip_hi_elements(root) -> None:
    from lxml.etree import strip_tags

    strip_tags(root, *_HI_TAGS)


def normalize_for_compare(segment: str) -> str:
    """Plain text for alignment (unwrap ``<hi>``, drop other tags); matches compare_tei_lb."""
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
    t = _TAG.sub("", segment)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def token_spans(s: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _TOKEN_SPAN.finditer(s)]


def tokenize_line_text(segment: str) -> list[str]:
    text = normalize_for_compare(segment)
    return [text[a:b] for a, b in token_spans(text)]


def _norm_span_to_contiguous_segment_slice(
    segment: str, a: int, b: int
) -> tuple[int, int] | None:
    """
    Map ``norm[a:b]`` (indices into ``normalize_for_compare(segment)``) to a
    contiguous ``[sa, sb)`` slice of *segment* when possible.

    This avoids mutating a per-line XML tree with ``strip_tags(<hi>)``, which
    destroyed ``<hi>`` that spans multiple ``<lb/>`` lines and broke ``<p>`` /
    ``</hi>`` pairing in the full document.
    """
    if a < 0 or b < a:
        return None
    norm_ref = normalize_for_compare(segment)
    if b > len(norm_ref):
        return None

    root = _parse_xml_fragment_or_doc(segment)
    if root is None:
        return None

    st = copy.deepcopy(root)
    _strip_hi_elements(st)

    t0_chars: list[str] = []
    t0_seg: list[int] = []  # start index in segment per t0 char; -1 = join space (not in segment)
    search_pos = 0
    first = True
    for t in st.xpath(".//text()"):
        if t is None:
            continue
        raw = str(t)
        stripped = raw.strip()
        if not stripped:
            continue
        lead = len(raw) - len(raw.lstrip())
        if not first:
            t0_chars.append(" ")
            t0_seg.append(-1)
        first = False
        blk = segment.find(stripped, search_pos)
        if blk < 0:
            return None
        search_pos = blk + len(stripped)
        for k in range(len(stripped)):
            t0_chars.append(stripped[k])
            t0_seg.append(blk + lead + k)

    if not t0_chars:
        return None

    t0 = "".join(t0_chars)
    # Collapse whitespace (same as _build_norm_provenance_from_root).
    out_chars: list[str] = []
    out_src: list[int] = []
    i = 0
    n = len(t0)
    while i < n:
        if t0[i].isspace():
            out_chars.append(" ")
            out_src.append(t0_seg[i])
            i += 1
            while i < n and t0[i].isspace():
                i += 1
        else:
            out_chars.append(t0[i])
            out_src.append(t0_seg[i])
            i += 1
    collapsed = "".join(out_chars)
    ls = 0
    while ls < len(collapsed) and collapsed[ls].isspace():
        ls += 1
    rs = len(collapsed)
    while rs > ls and collapsed[rs - 1].isspace():
        rs -= 1
    final = collapsed[ls:rs]
    src = out_src[ls:rs]

    if final != norm_ref:
        return None

    if b > len(src):
        return None
    starts = src[a:b]
    if any(x < 0 for x in starts):
        return None
    sa = starts[0]
    sb = starts[-1] + 1
    for j in range(1, len(starts)):
        if starts[j] != starts[j - 1] + 1:
            return None
    if segment[sa:sb] != norm_ref[a:b]:
        return None
    return (sa, sb)


def replace_token_in_line_segment(
    segment: str,
    token_index: int,
    expect_left: str,
    right_text: str,
) -> tuple[str, bool, str]:
    """
    Replace one token in a raw ``<lb/>`` segment string.

    Edits are applied as a **slice on the original segment string** so
    ``<hi>``…``</hi>`` pairs that span many lines stay intact (we never
    re-serialize a per-line tree after ``strip_tags(<hi>)``).
    """
    norm = normalize_for_compare(segment)
    spans = token_spans(norm)
    if token_index < 0 or token_index >= len(spans):
        return segment, False, f"left_token_index {token_index} out of range (n_tokens={len(spans)})"
    a, b = spans[token_index]
    tok = norm[a:b]
    if tok != expect_left:
        return segment, False, f"token mismatch at left_token_index {token_index}: got {tok!r} expected {expect_left!r}"

    sl = _norm_span_to_contiguous_segment_slice(segment, a, b)
    if sl is not None:
        sa, sb = sl
        return segment[:sa] + right_text + segment[sb:], True, ""

    if not _TAG.search(segment):
        if segment == norm:
            return segment[:a] + right_text + segment[b:], True, ""
        return (
            segment,
            False,
            "could not map token to substring (normalized text differs from raw segment)",
        )

    return (
        segment,
        False,
        "could not map token to one contiguous substring in this line (markup splits the syllable or mapping failed)",
    )


def load_json(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise SystemExit("JSON root must be a list")
    return data


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    inp = INPUT_XML.resolve()
    js = DIFF_JSON.resolve()
    if not inp.is_file():
        raise SystemExit(f"Not found: {inp}")
    if not js.is_file():
        raise SystemExit(f"Not found: {js}")

    xml_raw = inp.read_text(encoding="utf-8")
    body = extract_body(xml_raw, BODY_ONLY)

    pb_texts, pb_seps = split_keep_delim(_PB_SPLIT_CAP, body)

    # Collect operations: (page_i, line_i, tok_i, left, right)
    ops: list[tuple[int, int, int, str, str]] = []
    entries = load_json(js)
    for ent in entries:
        left_tok = ent.get("left_token", "")
        right_tok = ent.get("right_token", "")
        occs = ent.get("occurrences", [])
        if not isinstance(occs, list):
            continue
        for occ in occs:
            if not isinstance(occ, (list, tuple)) or len(occ) != 3:
                logger.warning("skip bad occurrence (need [page, line, left_token_index]): %s", occ)
                continue
            pi, li, ti = int(occ[0]), int(occ[1]), int(occ[2])
            if ONE_BASED:
                pi -= 1
                li -= 1
            ops.append((pi, li, ti, str(left_tok), str(right_tok)))

    attempted = len(ops)
    ok_count = 0
    skipped = 0

    # Sort: same line, descending token index first (preserve indices)
    ops.sort(key=lambda t: (t[0], t[1], -t[2]))

    # Mutable copy of page strings
    page_parts = list(pb_texts)

    for pi, li, ti, left_tok, right_tok in ops:
        if pi < 0 or pi >= len(page_parts):
            logger.warning(
                "skip occurrence page_index=%s line_index=%s left_token_index=%s: page out of range (n_pages=%s)",
                pi,
                li,
                ti,
                len(page_parts),
            )
            skipped += 1
            continue
        lb_texts, lb_seps = split_keep_delim(_LB_SPLIT_CAP, page_parts[pi])
        if li < 0 or li >= len(lb_texts):
            logger.warning(
                "skip occurrence page_index=%s line_index=%s left_token_index=%s: line out of range (n_lines=%s)",
                pi,
                li,
                ti,
                len(lb_texts),
            )
            skipped += 1
            continue
        seg = lb_texts[li]
        new_seg, ok, reason = replace_token_in_line_segment(seg, ti, left_tok, right_tok)
        if not ok:
            logger.warning(
                "skip page_index=%s line_index=%s left_token_index=%s (%s → %s): %s",
                pi,
                li,
                ti,
                left_tok,
                right_tok,
                reason,
            )
            skipped += 1
            continue
        lb_texts[li] = new_seg
        page_parts[pi] = join_keep_delim(lb_texts, lb_seps)
        ok_count += 1

    new_body = join_keep_delim(page_parts, pb_seps)
    out_xml = inject_body(xml_raw, new_body, BODY_ONLY)
    out_path = inp.with_name(f"{inp.stem}_modified.xml")
    out_path.write_text(out_xml, encoding="utf-8")

    print(f"Replacements attempted: {attempted}")
    print(f"Successful: {ok_count}")
    print(f"Skipped: {skipped}")
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
