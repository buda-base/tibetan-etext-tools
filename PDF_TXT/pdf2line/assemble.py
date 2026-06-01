"""
pdf2line.assemble — Split a document into pecha pages and preserve line breaks.

Segmentation rule:

A new page segment begins at each **page-number line** — a line consisting only
of digits, either Latin (``3``, ``014``), a dotted section index (``1.2``), a
Jonang-style folio marker (``p1``, ``P7``, ``p1036``), or a ``PageN`` marker
(optional colon) with optional blank/missing annotations (``354 空白``,
``Page306:空白``). The marker itself is dropped. Everything between two number
lines belongs to
one pecha page, INCLUDING the short header that follows the number
(``དཀར་གཉྱིས་ཆག``, ``ཏཾ ༢`` ...).

Output structure:
- Visual line breaks WITHIN a pecha page are preserved as single newlines.
- Pecha pages are separated by a blank line (double newline) in the output
  file (handled by convert.py).

Lines with no Tibetan script (Latin boilerplate such as ``www.jonangdharma.org``
and English notes) are, by default, collected and emitted as one block at the
TOP of the file, with single newlines between lines (not blank-line spacing).
The sample output places the URL last in the block when ``reverse_boilerplate``
is enabled.

Spaces are collapsed to one, and spaces around inline Tibetan/Latin digits are
removed. Newline characters within a page are preserved.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

_TIBETAN_RE = re.compile(r"[\u0f00-\u0fff]")

# A page-number line: only Latin digits (3, 014) or a dotted index (1.2),
# possibly with surrounding whitespace.
_NUM_LINE_RE = re.compile(r"^\s*(?:\d+|\d+\.\d+)\s*$")

# Jonang-style folio marker: p/P + digits, optional space (p1, P7, P 904).
_FOLIO_LINE_RE = re.compile(r"^\s*[pP]\s*\d+\s*$")

# Page number token: dotted folios, optional (sub-index). Optional ``:`` after
# ``Page`` (Ladakh: ``Page:402:``) or glued digits (``Page79:``).
_PAGE_NUM = r"\d+(?:\.\d+)*(?:\(\d+\))?"

# Ladakh / volunteer blank-page wording (order and 頁 variants).
_BLANK_MARKERS = (
    r"(?:缺空白|缺頁空白|空白缺頁|空白頁|此為空白頁|缺頁|缺|空白)"
)

# PageN marker with optional (sub-index), optional colon; rest may be Tibetan.
_PAGE_BOUNDARY_RE = re.compile(
    rf"^\s*Page\s*:?\s*{_PAGE_NUM}\s*(?:[:\uff1a]\s*)?(?P<rest>.*)$",
    re.IGNORECASE,
)

# Page + glued blank/missing suffix without colon (Page56缺).
_PAGE_SUFFIX_RE = re.compile(
    rf"^\s*Page\s*:?\s*{_PAGE_NUM}\s*(?:{_BLANK_MARKERS})\s*$",
    re.IGNORECASE,
)

# Digits + blank/missing annotation, with or without space (354 空白, 764空白缺頁).
_DIGIT_ANNOTATION_RE = re.compile(
    rf"^\s*\d+\s*(?:{_BLANK_MARKERS})\s*$"
)
_DIGIT_GLUED_ANNOTATION_RE = re.compile(
    rf"^\s*\d+(?:{_BLANK_MARKERS})\s*$"
)

# Blank/missing or placeholder text only (after PageN:).
_ANNOTATION_ONLY_RE = re.compile(
    rf"^(?:{_BLANK_MARKERS}|[xX]+|\s)+$"
)

# Volunteer placeholder lines (missing folio / illegible).
_PLACEHOLDER_LINE_RE = re.compile(r"^\s*[xX]{3,}\s*$")
_IMAGE_PLACEHOLDER_RE = re.compile(
    r"^\s*Image\s+As\s+Per\s+Original\s+Document\s*$",
    re.IGNORECASE,
)

# Asterisk-only artifact lines (* **).
_ASTERISK_ARTIFACT_RE = re.compile(r"^\s*\*+\s*(\*+\s*)*$")

_FS_TAG_RE = re.compile(r"<\d+(?:\.\d+)?>")

# Tibetan digit range, for the inline-digit space rule.
_TIB_DIGIT = "\u0f20-\u0f33"


def has_tibetan(text: str) -> bool:
    """True if the string contains at least one Tibetan-script codepoint."""
    return bool(_TIBETAN_RE.search(text))


def _match_page_boundary(line: str) -> Tuple[bool, Optional[str]]:
    """
    Return ``(is_boundary, rest_to_keep)``.

    *rest_to_keep* is Tibetan (or other) content after ``PageN:`` to place at
    the start of the new segment. ``None`` means drop the line entirely.
    """
    if _PAGE_SUFFIX_RE.match(line):
        return True, None
    m = _PAGE_BOUNDARY_RE.match(line)
    if not m:
        return False, None
    rest = m.group("rest").strip()
    # A fullwidth colon glued directly to Tibetan (e.g. ``Page1：ཀ``) is consumed
    # into ``rest`` by the optional colon group; drop any stray leading colon.
    rest = rest.lstrip(":\uff1a").strip()
    if not rest:
        return True, None
    if has_tibetan(rest):
        return True, rest
    if _ANNOTATION_ONLY_RE.match(rest):
        return True, None
    # Ladakh blank folios: Page79:xxxx, Page290:xxx — drop marker and placeholder.
    return True, None


def is_page_number(line: str) -> bool:
    """True if *line* is a bare page-number / folio / section-index line."""
    return bool(
        _NUM_LINE_RE.match(line)
        or _FOLIO_LINE_RE.match(line)
        or _DIGIT_ANNOTATION_RE.match(line)
        or _DIGIT_GLUED_ANNOTATION_RE.match(line)
    )


def is_artifact_line(line: str) -> bool:
    """True if *line* is noise to skip (artifacts, placeholders, lone punctuation)."""
    return bool(
        _ASTERISK_ARTIFACT_RE.match(line)
        or _PLACEHOLDER_LINE_RE.match(line)
        or _IMAGE_PLACEHOLDER_RE.match(line)
        or re.match(r"^\s*\\+\s*$", line)
    )


def is_boilerplate(line: str) -> bool:
    """True if *line* has no Tibetan script (Latin URLs / English notes)."""
    return not has_tibetan(line)


def _normalize_spaces(text: str) -> str:
    """
    Collapse runs of spaces to one; strip spaces around inline digits.

    NOTE: This function preserves newlines (uses ``[ \\t]`` rather than ``\\s``)
    so that visual line breaks within a pecha page are kept intact.
    """
    text = re.sub(r"[ \t\u00a0]{2,}", " ", text)
    # Remove space before/after a Tibetan or Latin digit cluster (matches the
    # sample, e.g. "ལ་ ༨ ༼" -> "ལ་༨༼"). Use [ \t] not \s so newlines are kept.
    text = re.sub(rf"[ \t]+([{_TIB_DIGIT}0-9])", r"\1", text)
    text = re.sub(rf"([{_TIB_DIGIT}0-9])[ \t]+", r"\1", text)
    # Strip trailing spaces on each line and leading/trailing whitespace overall.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.strip()


def split_into_pages(
    page_texts: Iterable[str],
    *,
    drop_page_numbers: bool = True,
    collect_boilerplate: bool = True,
    boilerplate_at_top: bool = True,
    reverse_boilerplate: bool = False,
    strip_font_tags: bool = True,
    normalize_spaces: bool = True,
) -> List[str]:
    """
    Convert a sequence of per-PDF-page texts into a list of pecha-page strings,
    split on page-number lines.

    Each returned string corresponds to one pecha page. Visual line breaks
    within a pecha page are preserved as single newlines.

    Returns a list of output strings: optionally one boilerplate block (first or
    last), then one entry per Tibetan pecha page segment. Boilerplate is a
    single string with ``\\n`` between lines so file assembly only inserts blank
    lines between pecha pages, not between boilerplate lines. Empty segments are
    dropped.
    """
    boiler: List[str] = []
    segments: List[List[str]] = [[]]

    for page_text in page_texts:
        for raw in re.split(r"[\r\n]+", page_text):
            line = raw.strip()
            if strip_font_tags:
                line = _FS_TAG_RE.sub("", line)
            line = line.strip()
            if not line:
                continue
            boundary, rest = _match_page_boundary(line)
            if boundary:
                segments.append([])
                if not drop_page_numbers:
                    segments[-1].append(line)
                elif rest:
                    segments[-1].append(rest)
                continue
            if is_artifact_line(line):
                continue
            if is_page_number(line):
                segments.append([])  # boundary; number itself dropped
                if not drop_page_numbers:
                    segments[-1].append(line)
                continue
            if collect_boilerplate and is_boilerplate(line):
                boiler.append(line)
                continue
            segments[-1].append(line)

    # Join within each segment, preserving visual line breaks as newlines.
    seg_lines = ["\n".join(seg) for seg in segments if seg]

    if normalize_spaces:
        seg_lines = [_normalize_spaces(l) for l in seg_lines]
        boiler = [_normalize_spaces(l) for l in boiler]

    # De-duplicate boilerplate (e.g. a footer URL repeated on every page),
    # preserving first-seen order.
    if collect_boilerplate and boiler:
        seen = set()
        deduped = []
        for b in boiler:
            if b not in seen:
                seen.add(b)
                deduped.append(b)
        boiler = deduped

    def _boilerplate_block() -> str:
        ordered = list(reversed(boiler)) if reverse_boilerplate else boiler
        return "\n".join(ordered)

    if collect_boilerplate and boiler:
        block = _boilerplate_block()
        if boilerplate_at_top:
            out = [block] + seg_lines
        else:
            out = seg_lines + [block]
    else:
        out = seg_lines

    # Drop any empty entries (e.g. an empty boilerplate block).
    return [l for l in out if l]