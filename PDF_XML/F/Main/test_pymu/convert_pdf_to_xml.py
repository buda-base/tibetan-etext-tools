#!/usr/bin/env python3
"""
PDF → TEI XML converter.

**Extractors** (``--extractor``):

- **pymupdf** (default): ``page.get_text("rawdict")`` — one ``\n`` per MuPDF
  line; skips Wingdings; optional header/footer crop. Suited to MonlamUniOuChan
  Unicode PDFs.

- **pytiblegenc**: ``pytiblegenc.pdf_to_txt()`` with the same options as
  IE3KG664 / Desktop SRC_CODE.  Requires:
  ``pip install git+https://github.com/buda-base/py-tiblegenc.git``

Usage:
    python convert_pdf_to_xml.py
    python convert_pdf_to_xml.py --ve VE1ER999
    python convert_pdf_to_xml.py --single foo.pdf
    python convert_pdf_to_xml.py --crop-top 0.09 --crop-bottom 0.08
    python convert_pdf_to_xml.py --extractor pytiblegenc
"""

import sys
import re
import shutil
import argparse
import logging
from pathlib import Path
from typing import Optional
from collections import Counter
from natsort import natsorted

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from config import (
    IE_ID,
    SOURCES_DIR,
    TOPROCESS_DIR,
    OUTPUT_DIR,
    ARCHIVE_DIR,
    SOURCES_OUTPUT_DIR,
    PDF_TO_XML_LOG,
    PDF_TO_XML_CHECKPOINT,
    ensure_directories,
    get_ut_id,
    extract_ve_id_from_folder,
    get_max_archive_sequence,
    CROP_HEADER_FRACTION,
    CROP_FOOTER_FRACTION,
)
from normalization import normalize_unicode, remove_wingdings_private_use
from tei_generator import post_process_body, generate_tei_xml, calculate_sha256
from pdf_extract import (
    PAGE_BREAK_STR,
    PAGE_BREAK_PREFIX_RE,
    PYMUPDF_AVAILABLE,
    PYTIBLEGENC_AVAILABLE,
    extract_pdf_to_text,
    _FN_SENTINEL_START,
    _FN_SENTINEL_END,
)


def setup_logging():
    ensure_directories()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(PDF_TO_XML_LOG, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


logger = setup_logging()

ENABLE_FONT_CLASSIFICATION = True
ENABLE_NORMALIZATION = True

# "pymupdf" | "pytiblegenc" — set from CLI ``--extractor`` in main()
PDF_EXTRACTOR: str = "pymupdf"

CROP_TOP_FRACTION: float = CROP_HEADER_FRACTION
CROP_BOTTOM_FRACTION: float = CROP_FOOTER_FRACTION

# When set from CLI ``--preserve-box``, takes priority over CROP_TOP/BOTTOM_FRACTION.
# Format: [x0_frac, y0_frac, x1_frac, y1_frac] — normalised [0.0, 1.0] coordinates.
PRESERVE_BOX: Optional[list] = None

# Characters that may appear in PDF footer/header artifacts.
# NOTE: do NOT include \s here — it overlaps with the surrounding \s* and \n?
# quantifiers in strip_page_number_artifacts, causing catastrophic backtracking
# on large documents. Horizontal whitespace (space/tab) is listed explicitly.
_PAGE_ARTIFACT_CHARS = r"\u0F0B\u0F0C\u0F0D0-9\uFF10-\uFF19 \t"


# ─── Artifact stripping ────────────────────────────────────────────────────────

# Matches both bare <pb/> and attributed <pb n="..."/> so artifact-stripping
# regexes work regardless of whether a page label is present.
_PB_PAT   = r"<pb(?:\s[^/]*)*/>"       # non-capturing, for use inside patterns
_PB_CAP   = r"(<pb(?:\s[^/]*)*/?>)"    # capturing group version


def strip_page_number_artifacts(text: str) -> str:
    """Remove PDF footer artifacts (page numbers, tsheg runs) before page breaks."""
    pattern = (
        r"((?:<lb/>\s*[" + _PAGE_ARTIFACT_CHARS + r"]*\n?)+)"
        r"(\s*<lb/>\s*" + _PB_PAT + r")"
    )
    text = re.sub(pattern, r"\2", text)
    pattern2 = (
        r"((?:<lb/>\s*[" + _PAGE_ARTIFACT_CHARS + r"]*\n?)+)"
        r"(\s*" + _PB_PAT + r")"
    )
    text = re.sub(pattern2, r"\2", text)
    text = re.sub(r"<lb/>\s*\d+\s*(?=</[^>]+>)", "", text)
    return text


def strip_page_header_artifacts(text: str) -> str:
    """Remove PDF header artifacts (page numbers, Roman numerals) after page breaks."""
    # InDesign section running headers (UTF-16-BE hex), after XML escaping.
    text = re.sub(
        _PB_CAP
        + r"\n<lb/>&lt;FEFF005300650063003[12]003A&gt;"
        r"(?:[IVXLCDMivxlcdm]+|\d+)\s*\n",
        r"\1\n",
        text,
    )
    # Section roman numerals on the line immediately before a page break.
    # Each line gets its own <lb/>, so the pattern is often <lb/>II\n<lb/><pb/>.
    text = re.sub(
        r"<lb/>\s*[IVXLCDMivxlcdm]{1,6}\s*\n(?:<lb/>\s*)?(?=<pb)",
        r"",
        text,
    )
    # Numbers appearing inline on the same line as <pb/> (no <lb/> prefix)
    text = re.sub(_PB_CAP + r"\s*\d+\s*\n", r"\1\n", text)
    # Roman numerals (upper or lower case) on own line, with optional trailing close tag
    text = re.sub(_PB_CAP + r"\n<lb/>[IVXLCDMivxlcdm]+(?:</[^>]*>)?\s*\n", r"\1\n", text)
    # Arabic digits on own line, with optional trailing close tag (e.g. </hi>)
    text = re.sub(_PB_CAP + r"\n<lb/>\d+(?:</[^>]*>)?\s*\n", r"\1\n", text)
    text = re.sub(
        _PB_CAP + r'\n<lb/><hi rend="small">\d+\s*\n<lb/>[^\n]*</hi>\s*\n',
        r"\1\n",
        text,
    )
    text = re.sub(
        _PB_CAP + r'\n<lb/><hi rend="head">[IVXLCDMivxlcdm]+\s*\n',
        r'\1\n<lb/><hi rend="head">',
        text,
    )
    text = re.sub(r'(<hi rend="head">)[IVXLCDMivxlcdm]+\s*\n<lb/>', r"\1", text)
    return text


# ─── CJK intra-line deduplication ─────────────────────────────────────────────
# InDesign PDFs with CJK content embed 2–3 stacked text layers at the same
# y-coordinate.  MuPDF merges their spans into one line, producing 2–3 copies
# of the CJK content concatenated.  We remove the duplicates with a greedy
# character-level scan that skips any CJK run already present in the emitted
# buffer, while passing non-CJK text (Tibetan, Latin, digits) unchanged.

_CJK_INTRALINE_RE = re.compile(
    r"[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]"
)
_CJK_INTRALINE_SEG_RE = re.compile(
    r"[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]+"
    r"|[^\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]+"
)
_CJK_INTRALINE_MIN_REPEAT = 3


def deduplicate_cjk_intraline(text: str) -> str:
    """Remove internal CJK repetitions from a single assembled line."""
    segments = [
        (bool(_CJK_INTRALINE_RE.match(m.group()[0])), m.group())
        for m in _CJK_INTRALINE_SEG_RE.finditer(text)
    ]
    cjk_parts = [s for is_cjk, s in segments if is_cjk]
    if not cjk_parts:
        return text

    all_cjk = "".join(cjk_parts)
    if len(all_cjk) < _CJK_INTRALINE_MIN_REPEAT * 2:
        return text

    # Fast check: any repeated ngram anywhere?
    has_repeat = False
    for n in range(_CJK_INTRALINE_MIN_REPEAT, len(all_cjk) // 2 + 1):
        for start in range(len(all_cjk) - n):
            if all_cjk.find(all_cjk[start: start + n], start + 1) >= 0:
                has_repeat = True
                break
        if has_repeat:
            break
    if not has_repeat:
        return text

    emitted = ""
    result_segs: list[str] = []
    for is_cjk, seg in segments:
        if not is_cjk:
            result_segs.append(seg)
            continue
        out = ""
        i = 0
        while i < len(seg):
            look = seg[i: i + _CJK_INTRALINE_MIN_REPEAT]
            if len(look) == _CJK_INTRALINE_MIN_REPEAT and look in emitted:
                j = i
                while j < len(seg) and seg[i: j + 1] in emitted:
                    j += 1
                i = j
                continue
            look2 = seg[i: i + 2]
            if len(look2) == 2 and look2 in emitted and len(emitted) >= _CJK_INTRALINE_MIN_REPEAT:
                if seg[i] in emitted:
                    j = i
                    while j < len(seg) and seg[i: j + 1] in emitted:
                        j += 1
                    if j > i:
                        i = j
                        continue
            out += seg[i]
            emitted += seg[i]
            i += 1
        result_segs.append(out)

    return "".join(result_segs).rstrip()


def apply_cjk_intraline_dedup(text: str) -> str:
    """Apply ``deduplicate_cjk_intraline`` to every CJK-containing line."""
    lines = text.split("\n")
    result = []
    for line in lines:
        if _CJK_INTRALINE_RE.search(line):
            line = deduplicate_cjk_intraline(line)
        result.append(line)
    return "\n".join(result)


# ─── Font-size markup ──────────────────────────────────────────────────────────

def simplify_font_sizes(text: str) -> str:
    """Simplify font-size markup by merging segments without Tibetan separators."""
    pattern = r"<fs:(\d+)>"
    parts = re.split(pattern, text)

    segments = []
    current_fs = None
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part:
                segments.append((current_fs, part))
        else:
            current_fs = part

    if not segments:
        return text

    processed = []
    for i, (fs, content) in enumerate(segments):
        if not content:
            continue
        if content == "༼" and i + 1 < len(segments):
            next_fs, next_content = segments[i + 1]
            processed.append((next_fs, "༼" + next_content))
            segments[i + 1] = (None, "")
        elif content.startswith("༽") and processed:
            prev_fs, prev_content = processed[-1]
            processed[-1] = (prev_fs, prev_content + content)
        elif content == "༽" and processed:
            prev_fs, prev_content = processed[-1]
            processed[-1] = (prev_fs, prev_content + "༽")
        else:
            processed.append((fs, content))

    segments = [(fs, c) for fs, c in processed if c]

    merged = []
    for fs, content in segments:
        has_separator = "་" in content or "།" in content or content.endswith("༽")
        if not has_separator and merged:
            prev_fs, prev_content = merged[-1]
            # Only concatenate without separator when the boundary is naturally
            # joined: prev ends with tsheg/shad, or content starts with tsheg/shad,
            # or either side is purely whitespace/structural.
            prev_ends_joined = (
                prev_content.endswith("་")
                or prev_content.endswith("།")
                or prev_content.endswith("༽")
                or not prev_content.strip()
            )
            content_starts_joined = (
                content.startswith("་")
                or content.startswith("།")
                or content.startswith(" ")
            )
            if prev_ends_joined or content_starts_joined:
                merged[-1] = (prev_fs, prev_content + content)
            else:
                # No natural join: insert a space so words are not fused
                merged[-1] = (prev_fs, prev_content + " " + content)
        elif not has_separator and not merged and not content.strip():
            merged.append((None, content))
        else:
            merged.append((fs, content))

    final: list = []
    for fs, content in merged:
        if final and final[-1][0] == fs:
            final[-1] = (fs, final[-1][1] + content)
        else:
            final.append((fs, content))

    result = []
    for fs, content in final:
        if fs is not None:
            result.append(f"<fs:{fs}>{content}")
        else:
            result.append(content)
    return "".join(result)


def classify_font_sizes(text: str) -> dict:
    """Classify font sizes in text into large, regular, and small categories."""
    matches = re.findall(r"<fs:(\d+)>([^<]*)", text)
    if not matches:
        return {}

    size_counts: Counter = Counter()
    for fs, content in matches:
        char_count = sum(1 for c in content if 0x0F00 <= ord(c) <= 0x0FFF)
        if char_count > 0:
            size_counts[int(fs)] += char_count

    if not size_counts:
        return {}

    sizes = sorted(size_counts.keys())
    total_chars = sum(size_counts.values())
    size_pct = {fs: count / total_chars * 100 for fs, count in size_counts.items()}

    logger.info("    Font sizes: %s", dict(size_counts))
    logger.info("    Font percentages: %s", size_pct)

    classifications: dict = {}

    if len(sizes) == 1:
        classifications[sizes[0]] = "regular"

    elif len(sizes) == 2:
        fs1, fs2 = sizes
        pct1, pct2 = size_pct[fs1], size_pct[fs2]
        if pct1 > pct2 and pct2 > 10:
            classifications[fs2] = "regular"
            classifications[fs1] = "small"
            logger.info("    Inverted classification: %dpt (yigchung) vs %dpt (body)", fs1, fs2)
        elif pct1 > pct2:
            classifications[fs1] = "regular"
            classifications[fs2] = "large"
        else:
            classifications[fs2] = "regular"
            classifications[fs1] = "small"

    else:
        body_range = [fs for fs in sizes if 20 <= fs <= 26 and size_pct[fs] > 5]
        if body_range:
            most_common_fs = max(body_range)
        else:
            significant = [fs for fs in sizes if size_pct[fs] > 10]
            most_common_fs = (
                max(significant)
                if significant
                else max(size_counts.items(), key=lambda x: x[1])[0]
            )
        classifications[most_common_fs] = "regular"
        for fs in sizes:
            if fs != most_common_fs:
                classifications[fs] = "large" if fs > most_common_fs else "small"

    logger.info("    Classifications: %s", classifications)
    return classifications


def apply_font_markup(text: str, classifications: dict) -> str:
    """Apply <large>/<small> markup tags based on font size classifications."""

    def replace_fs(match):
        fs = int(match.group(1))
        cls = classifications.get(fs, "regular")
        if cls == "large":
            return "<LARGE_START>"
        if cls == "small":
            return "<SMALL_START>"
        return "<REGULAR_START>"

    text = re.sub(r"<fs:(\d+)>", replace_fs, text)

    result = []
    current_state = "regular"

    for part in re.split(r"(<(?:LARGE|SMALL|REGULAR)_START>)", text):
        if part == "<LARGE_START>":
            if current_state == "small":
                result.append("</small>")
            if current_state != "large":
                result.append("<large>")
                current_state = "large"
        elif part == "<SMALL_START>":
            if current_state == "large":
                result.append("</large>")
            if current_state != "small":
                result.append("<small>")
                current_state = "small"
        elif part == "<REGULAR_START>":
            if current_state == "large":
                result.append("</large>")
            elif current_state == "small":
                result.append("</small>")
            current_state = "regular"
        else:
            result.append(part)

    if current_state == "large":
        result.append("</large>")
    elif current_state == "small":
        result.append("</small>")

    text = "".join(result)
    text = re.sub(r"(<(?:large|small)>)(\s)", r"\2\1", text)
    text = re.sub(r"(\s)(</(?:large|small)>)", r"\2\1", text)
    text = re.sub(r"<large></large>", "", text)
    text = re.sub(r"<small></small>", "", text)
    return text


# ─── Footnote sentinel → TEI ───────────────────────────────────────────────────

def convert_footnote_sentinels_to_tei(text: str) -> str:
    """
    Convert ``ZZFN_START:<n>:<body>ZZFN_END`` sentinels into inline TEI
    ``<note n="N" place="foot">body</note>`` elements.

    Placement: the ``<note>`` is appended to the last main-text line before
    the ``<pb/>`` that closes the page (per BDRC spec §4.7).
    ZZFNM:<n> in-text markers are stripped (the number is carried by n=).
    """
    if _FN_SENTINEL_START not in text:
        text = re.sub(r"ZZFNM:(\d+)", r"\1", text)
        return text

    text = re.sub(r"ZZFNM:(\d+)", r"\1", text)

    _SENTINEL_RE = re.compile(r"ZZFN_START:(\d+):(.+?)ZZFN_END\n?", re.DOTALL)

    def _collect_page_notes(block: str) -> list:
        notes = []
        for m in _SENTINEL_RE.finditer(block):
            body = m.group(2).strip()
            body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            notes.append((m.group(1), body))
        return notes

    page_chunks = PAGE_BREAK_PREFIX_RE.split(f"\n{text}\n")
    page_chunks[0]  = page_chunks[0].lstrip("\n")
    page_chunks[-1] = page_chunks[-1].rstrip("\n")
    separators = PAGE_BREAK_PREFIX_RE.findall(f"\n{text}\n")
    result_parts: list[str] = []

    for i, chunk in enumerate(page_chunks):
        notes = _collect_page_notes(chunk)
        clean_chunk = _SENTINEL_RE.sub("", chunk)

        if notes:
            note_tags = "".join(
                f'<note n="{n}" place="foot">{body}</note>'
                for n, body in notes
            )
            lines = clean_chunk.rstrip("\n").split("\n")
            last_text_idx = next(
                (j for j in range(len(lines) - 1, -1, -1) if lines[j].strip()),
                None,
            )
            if last_text_idx is not None:
                lines[last_text_idx] += note_tags
                clean_chunk = "\n".join(lines)
                if chunk.rstrip("\n") != chunk:
                    clean_chunk += "\n"

        result_parts.append(clean_chunk)
        if i < len(separators):
            result_parts.append(separators[i])

    return "".join(result_parts)


# ─── TEI markup conversion ─────────────────────────────────────────────────────

def convert_markup_to_tei(text: str) -> str:
    """Convert internal markup tags to TEI ``<pb/>``, ``<lb/>``, and ``<hi>`` elements."""

    def escape_content(text_part: str) -> str:
        # Protect markup that must survive the XML-escaping pass.
        text_part = text_part.replace("<large>", "\x00LARGE\x00")
        text_part = text_part.replace("</large>", "\x00/LARGE\x00")
        text_part = text_part.replace("<small>", "\x00SMALL\x00")
        text_part = text_part.replace("</small>", "\x00/SMALL\x00")
        note_tags: dict = {}

        def _stash_tag(m):
            key = f"\x00NOTE{len(note_tags)}\x00"
            note_tags[key] = m.group(0)
            return key

        text_part = re.sub(r"<note\b[^>]*>", _stash_tag, text_part)
        text_part = re.sub(r"</note>", _stash_tag, text_part)

        text_part = text_part.replace("&", "&amp;")
        text_part = text_part.replace("<", "&lt;")
        text_part = text_part.replace(">", "&gt;")

        text_part = text_part.replace("\x00LARGE\x00", "<large>")
        text_part = text_part.replace("\x00/LARGE\x00", "</large>")
        text_part = text_part.replace("\x00SMALL\x00", "<small>")
        text_part = text_part.replace("\x00/SMALL\x00", "</small>")
        for key, tag in note_tags.items():
            text_part = text_part.replace(key, tag)
        return text_part

    # ── Step 1: extract page-break tokens BEFORE escape_content ──────────────
    # apply_font_markup may emit </small> or </large> on the same line as the
    # ZZZZ:<label> token when a font span closes at a page boundary (e.g.
    # "ZZZZ:b</small>").  We capture the label with [A-Za-z0-9.\-]* (valid PDF
    # PageLabel chars only) so trailing markup is separated out and re-emitted
    # on its own line.  \x01PB:label\x02 delimiters survive escape_content's
    # XML-escaping of < and >.
    _PB_TOKEN_RE = re.compile(rf"{PAGE_BREAK_STR}:([A-Za-z0-9.\-]*)([^\n]*)")

    def _replace_pb(m: re.Match) -> str:
        label    = m.group(1)           # clean label: "b", "V", "1", ""
        trailing = m.group(2).strip()   # leftover: "</small>", "</large>", …
        placeholder = f"\x01PB:{label}\x02"
        return f"{placeholder}\n{trailing}" if trailing else placeholder

    text = _PB_TOKEN_RE.sub(_replace_pb, text)

    # ── Step 2: XML-escape, with markup tags protected ───────────────────────
    text = escape_content(text)

    # Drop leading page-break placeholder (before first real content).
    if text.startswith("\n\x01PB:"):
        text = text[text.index("\n", 1) + 1:]
    elif text.startswith("\x01PB:"):
        text = text[text.index("\n") + 1:]

    # ── Step 3: prepend initial <pb/> and inject <lb/> line breaks ───────────
    text = "<pb/>\n" + text

    lines = text.split("\n")
    result = []
    for i, line in enumerate(lines):
        line = line.rstrip()
        if i > 0:
            result.append("\n<lb/>")
        result.append(line)
    text = "".join(result)

    # ── Step 4: materialise page-break placeholders as TEI <pb> elements ─────
    # ⚠️  MUST happen BEFORE strip_page_number_artifacts / strip_page_header_artifacts
    # so those regexes find actual <pb/> tags, not \x01PB:\x02 placeholders.
    def _emit_pb(m: re.Match) -> str:
        label = m.group(1)
        return f'<pb n="{label}"/>' if label else "<pb/>"

    text = re.sub(r"\x01PB:([A-Za-z0-9.\-]*)\x02", _emit_pb, text)

    text = strip_page_number_artifacts(text)
    text = strip_page_header_artifacts(text)

    text = re.sub(r"\n<lb/>\s*(?=<pb)", r"\n", text)
    text = re.sub(r"<lb/>\s*\n\s*(?=<pb)", r"", text)
    text = re.sub(r"\n<lb/>\s*$", "", text)

    text = text.replace("<large>", '<hi rend="head">')
    text = text.replace("<small>", '<hi rend="small">')
    text = text.replace("</large>", "</hi>")
    text = text.replace("</small>", "</hi>")

    text = re.sub(r"(<lb/>[\s\n]*)+</hi>", r"</hi>", text)
    text = re.sub(r"<lb/>[\s\n]*<pb", r"<pb", text)
    # Inline <hi> must close before any page break (bare or attributed).
    text = re.sub(r"(<pb(?:\s[^/]*)*/?>)\s*</hi>", r"</hi>\n\1", text)
    text = re.sub(r"\n(</hi>)", r"\1\n", text)
    text = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r"\n<lb/>\1", text)
    text = re.sub(r"<lb/> {2,}", r"<lb/> ", text)  # collapse multiple spaces → one
    text = re.sub(r"\n\n+", r"\n", text)
    text = re.sub(r"  +", r" ", text)

    # Remove lines that are only whitespace/lb tags
    lines = text.split("\n")
    filtered = [
        line for line in lines
        if re.sub(r"<lb/>", "", line.strip()).strip()
    ]
    text = "\n".join(filtered)

    text = re.sub(r"(<lb/>[ \t]*)+<lb/>", r"<lb/>", text)
    return text


# ─── Checkpoint helpers ────────────────────────────────────────────────────────

def load_checkpoints() -> set:
    if PDF_TO_XML_CHECKPOINT.exists():
        try:
            content = PDF_TO_XML_CHECKPOINT.read_text(encoding="utf-8").strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error("Error reading checkpoint file: %s", e)
    return set()


def save_checkpoint(file_path: str):
    PDF_TO_XML_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with open(PDF_TO_XML_CHECKPOINT, "a", encoding="utf-8") as f:
        f.write(f"{file_path}\n")


# ─── VE / file discovery ───────────────────────────────────────────────────────

def get_ve_ids_from_toprocess() -> list:
    ve_ids = []
    if not TOPROCESS_DIR.exists():
        return ve_ids
    for folder in TOPROCESS_DIR.iterdir():
        if folder.is_dir():
            ve_id = extract_ve_id_from_folder(folder.name)
            if ve_id:
                ve_ids.append(ve_id)
    return natsorted(ve_ids)


def assign_pdf_to_ve(ve_ids: list, pdf_list: list) -> dict:
    """Assign PDF files to VEs (one VE → all files; multiple → split in order)."""
    if not ve_ids or not pdf_list:
        return {}
    if len(ve_ids) == 1:
        return {ve_ids[0]: pdf_list}
    base, extra = divmod(len(pdf_list), len(ve_ids))
    chunks = []
    start = 0
    for i in range(len(ve_ids)):
        count = base + (1 if i < extra else 0)
        chunks.append(pdf_list[start: start + count])
        start += count
    return dict(zip(ve_ids, chunks))


def build_pdf_by_ve(
    ve_filter: Optional[str] = None,
    assign_flat_via_toprocess: bool = False,
    ve_ids_for_flat: Optional[list] = None,
) -> dict:
    """
    Map each volume (VE) ID to PDF paths under SOURCES_DIR.

    - Subfolders ``sources/<VE_ID>/``: volume ID = immediate subfolder name.
    - Flat ``sources/*.pdf``: only processed when ``assign_flat_via_toprocess``
      is True and ``ve_ids_for_flat`` is non-empty.
    """
    pdf_by_ve: dict = {}
    if not SOURCES_DIR.exists():
        return pdf_by_ve

    ve_ids_for_flat = list(ve_ids_for_flat or [])
    flat_pdfs = natsorted(SOURCES_DIR.glob("*.pdf"), key=lambda p: p.name)

    for item in natsorted(
        [p for p in SOURCES_DIR.iterdir() if p.is_dir()], key=lambda p: p.name
    ):
        if ve_filter and item.name != ve_filter:
            continue
        pdfs_in_folder = natsorted(item.rglob("*.pdf"), key=lambda p: str(p))
        if not pdfs_in_folder:
            continue
        folder_ve = item.name
        pdf_by_ve[folder_ve] = pdfs_in_folder
        logger.info(
            "  Volume from sources folder '%s': %d PDF(s) (under sources/%s/)",
            folder_ve, len(pdfs_in_folder), folder_ve,
        )

    if flat_pdfs:
        if not assign_flat_via_toprocess:
            logger.warning(
                "Skipping %d PDF(s) at sources/*.pdf (batch uses volume folders only; "
                "toprocess ignored). Move to sources/<VE_ID>/ or run with "
                "--assign-flat-toprocess.",
                len(flat_pdfs),
            )
        elif not ve_ids_for_flat:
            logger.error(
                "Skipping %d PDF(s) at sources/*.pdf: --assign-flat-toprocess set but "
                "no %s-VE* folders under toprocess/.",
                len(flat_pdfs), IE_ID,
            )
        else:
            ve_without_folder = [v for v in ve_ids_for_flat if v not in pdf_by_ve]
            targets = ve_without_folder if ve_without_folder else ve_ids_for_flat
            if not targets:
                logger.error("Flat PDFs in sources/ but no VE targets from toprocess.")
            else:
                assigned = assign_pdf_to_ve(targets, flat_pdfs)
                for ve, files in assigned.items():
                    pdf_by_ve.setdefault(ve, []).extend(files)

    return pdf_by_ve


def find_source_doc_file(pdf_path: Path, ve_id: str) -> Optional[Path]:
    """Find the source DOC file in toprocess/ for SHA-256 computation."""
    base_name = pdf_path.stem
    ve_folder = TOPROCESS_DIR / f"{IE_ID}-{ve_id}"
    if not ve_folder.exists():
        return None
    doc_path = ve_folder / f"{base_name}.doc"
    if doc_path.exists():
        return doc_path
    for doc_path in ve_folder.glob("*.doc"):
        if doc_path.stem.lower() == base_name.lower():
            return doc_path
    return None


# ─── Core conversion ───────────────────────────────────────────────────────────

def convert_pdf_to_tei(pdf_path: Path, ve_id: str, sequence: int) -> str:
    """Convert a single PDF file to a TEI XML string."""
    source_path = find_source_doc_file(pdf_path, ve_id) or pdf_path

    raw_text = extract_pdf_to_text(
        pdf_path,
        PDF_EXTRACTOR,
        crop_top=CROP_TOP_FRACTION,
        crop_bottom=CROP_BOTTOM_FRACTION,
        preserve_box=PRESERVE_BOX,
    )
    if not raw_text:
        raise ValueError(f"No text extracted from {pdf_path.name}")

    raw_text = apply_cjk_intraline_dedup(raw_text)
    simplified_text = simplify_font_sizes(raw_text)

    if ENABLE_NORMALIZATION:
        logger.info("    Applying normalization...")
        normalized_text = normalize_unicode(simplified_text)
    else:
        normalized_text = remove_wingdings_private_use(simplified_text)

    if _FN_SENTINEL_START in normalized_text:
        logger.info("    Converting footnote sentinels to TEI <note> elements...")
        normalized_text = convert_footnote_sentinels_to_tei(normalized_text)

    if ENABLE_FONT_CLASSIFICATION:
        classifications = classify_font_sizes(normalized_text)
    else:
        classifications = {}

    if classifications:
        marked_text = apply_font_markup(normalized_text, classifications)
    else:
        marked_text = re.sub(r"<fs:\d+>", "", normalized_text)

    tei_body = convert_markup_to_tei(marked_text)
    tei_body = post_process_body(tei_body)

    # Remove lines that contain only <lb/> and whitespace
    tei_body = "\n".join(
        line for line in tei_body.split("\n")
        if re.sub(r"<lb/>", "", line.strip()).strip()
    )

    ut_id = get_ut_id(ve_id, sequence)
    sha256 = calculate_sha256(source_path)
    src_path = (
        f"{ve_id}/{source_path.name}"
        if source_path != pdf_path
        else f"{ve_id}/{pdf_path.name}"
    )

    return generate_tei_xml(
        body_content=tei_body,
        title=pdf_path.stem,
        src_path=src_path,
        sha256=sha256,
        ve_id=ve_id,
        ut_id=ut_id,
    )


def copy_sources_to_output(ve_id: str, pdf_files: list):
    """Copy input PDFs (and matching DOC files) to the output sources directory."""
    sources_ve_dir = SOURCES_OUTPUT_DIR / ve_id
    sources_ve_dir.mkdir(parents=True, exist_ok=True)

    doc_count = pdf_count = 0
    for pdf_path in pdf_files:
        doc_path = find_source_doc_file(pdf_path, ve_id)
        if doc_path and doc_path.exists():
            try:
                shutil.copy2(doc_path, sources_ve_dir / doc_path.name)
                doc_count += 1
            except Exception as e:
                logger.warning("Failed to copy source DOC %s: %s", doc_path.name, e)
        if pdf_path.exists():
            try:
                shutil.copy2(pdf_path, sources_ve_dir / pdf_path.name)
                pdf_count += 1
            except Exception as e:
                logger.warning("Failed to copy PDF %s: %s", pdf_path.name, e)

    logger.info("  Copied %d DOC and %d PDF files to sources/%s/", doc_count, pdf_count, ve_id)


# ─── Single-file entry points ──────────────────────────────────────────────────

def _resolve_ve_for_single(explicit_ve: Optional[str]) -> Optional[str]:
    if explicit_ve:
        return explicit_ve
    ve_ids = get_ve_ids_from_toprocess()
    if len(ve_ids) == 1:
        return ve_ids[0]
    if not ve_ids:
        logger.error(
            "PDF is at sources/*.pdf (root). Use --ve VE_ID, or move to sources/<VE_ID>/file.pdf."
        )
        return None
    logger.error(
        "PDF is at sources/*.pdf (root) and toprocess has multiple VEs. Specify --ve VE_ID."
    )
    return None


def convert_single_file(relative_path: str, ve_id: Optional[str], sequence: Optional[int]):
    """Convert a single PDF under SOURCES_DIR to TEI XML."""
    pdf_path = (SOURCES_DIR / relative_path).resolve()
    src_root = SOURCES_DIR.resolve()

    try:
        rel = pdf_path.relative_to(src_root)
    except ValueError:
        logger.error("Path must be under sources/: %s", relative_path)
        return

    if not pdf_path.exists() or not pdf_path.is_file():
        logger.error("PDF file not found under sources/: %s", relative_path)
        return
    if pdf_path.suffix.lower() != ".pdf":
        logger.error("Not a PDF file: %s", relative_path)
        return

    inferred_ve = rel.parts[0] if len(rel.parts) >= 2 else None
    final_ve = ve_id or inferred_ve or _resolve_ve_for_single(None)
    if not final_ve:
        return
    ve_id = final_ve

    max_seq = get_max_archive_sequence(ve_id)
    if sequence is None:
        sequence = max_seq + 1
    ut_id = get_ut_id(ve_id, sequence)

    logger.info("Converting: %s", pdf_path.name)
    logger.info("  Extractor: %s", PDF_EXTRACTOR)
    logger.info("  VE ID: %s", ve_id)
    logger.info("  UT ID: %s", ut_id)

    try:
        tei_xml = convert_pdf_to_tei(pdf_path, ve_id, sequence)
    except Exception as e:
        logger.error("Error converting %s: %s", pdf_path.name, e)
        import traceback
        traceback.print_exc()
        return

    archive_ve_dir = ARCHIVE_DIR / ve_id
    archive_ve_dir.mkdir(parents=True, exist_ok=True)
    xml_path = archive_ve_dir / f"{ut_id}.xml"
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(tei_xml)
    logger.info("  Output: %s", xml_path)
    copy_sources_to_output(ve_id, [pdf_path])


def convert_all_files(
    ve_filter: Optional[str] = None,
    assign_flat_via_toprocess: bool = False,
):
    """Convert all PDFs under sources/<VE_ID>/."""
    logger.info("=" * 60)
    logger.info("PDF to TEI XML Converter for %s", IE_ID)
    logger.info("Extractor: %s", PDF_EXTRACTOR)
    if ve_filter:
        logger.info("Filtering: %s only", ve_filter)
    logger.info("PDF Source: %s", SOURCES_DIR)
    logger.info("Output: %s", OUTPUT_DIR)
    logger.info("=" * 60)

    ensure_directories()

    ve_ids_for_flat: list = []
    if assign_flat_via_toprocess:
        ve_ids_for_flat = get_ve_ids_from_toprocess()
        if ve_filter:
            ve_ids_for_flat = [v for v in ve_ids_for_flat if v == ve_filter]
        logger.info(
            "Also assigning flat sources/*.pdf via toprocess VEs: %s",
            ve_ids_for_flat or "(none)",
        )
    else:
        logger.info(
            "Batch: volume IDs from sources/<folder>/ only — toprocess ignored for assignment."
        )

    pdf_by_ve = build_pdf_by_ve(
        ve_filter=ve_filter,
        assign_flat_via_toprocess=assign_flat_via_toprocess,
        ve_ids_for_flat=ve_ids_for_flat,
    )
    total_files = sum(len(files) for files in pdf_by_ve.values())
    if not pdf_by_ve or total_files == 0:
        logger.error(
            "No PDF files found under sources/<VE_ID>/*.pdf. Put PDFs inside a volume folder "
            "(e.g. sources/VE1ER999/) or use --assign-flat-toprocess."
        )
        return

    logger.info(
        "PDFs under %s: %d file(s) -> %d volume(s): %s",
        SOURCES_DIR, total_files, len(pdf_by_ve), natsorted(pdf_by_ve.keys()),
    )

    checkpoints = load_checkpoints()
    logger.info("Existing checkpoint entries: %d", len(checkpoints))

    success_count = failed_count = 0

    for ve_id in natsorted(pdf_by_ve.keys()):
        pdf_files = pdf_by_ve[ve_id]
        logger.info("\nProcessing %s (%d files)", ve_id, len(pdf_files))

        archive_ve_dir = ARCHIVE_DIR / ve_id
        archive_ve_dir.mkdir(parents=True, exist_ok=True)

        max_seq = get_max_archive_sequence(ve_id)
        converted_files = []

        for idx, pdf_path in enumerate(pdf_files, start=1):
            pdf_path_str = str(pdf_path)

            if pdf_path_str in checkpoints:
                logger.info("  Skipping (already converted): %s", pdf_path.name)
                success_count += 1
                converted_files.append(pdf_path)
                continue

            sequence = max_seq + idx
            ut_id = get_ut_id(ve_id, sequence)
            logger.info("  [%d/%d] %s -> %s", idx, len(pdf_files), pdf_path.name, ut_id)

            try:
                tei_xml = convert_pdf_to_tei(pdf_path, ve_id, sequence)
                xml_path = archive_ve_dir / f"{ut_id}.xml"
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(tei_xml)
                save_checkpoint(pdf_path_str)
                success_count += 1
                converted_files.append(pdf_path)
            except Exception as e:
                logger.error("  Error converting %s: %s", pdf_path.name, e)
                import traceback
                traceback.print_exc()
                failed_count += 1

        if converted_files:
            copy_sources_to_output(ve_id, converted_files)

    logger.info("\n" + "=" * 60)
    logger.info("CONVERSION COMPLETE!")
    logger.info("  Success: %d", success_count)
    logger.info("  Failed:  %d", failed_count)
    logger.info("  Output:  %s", OUTPUT_DIR)
    logger.info("=" * 60)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Convert sources/*.pdf and sources/<VE>/**/*.pdf to TEI XML"
    )
    parser.add_argument(
        "--extractor",
        choices=["pymupdf", "pytiblegenc"],
        default="pymupdf",
        help="PDF text extraction backend (default: pymupdf)",
    )
    parser.add_argument(
        "--single", "-s",
        metavar="PATH",
        help="One PDF path under sources/ (e.g. file.pdf or VE1ER999/file.pdf)",
    )
    parser.add_argument("--ve", metavar="VE_ID", help="VE ID or filter batch to this VE")
    parser.add_argument(
        "--sequence", type=int, default=None, metavar="N",
        help="UT sequence for --single (default: next after max in archive)",
    )
    parser.add_argument("--no-font-tags", action="store_true", help="Disable font classification")
    parser.add_argument("--no-normalization", action="store_true", help="Disable Unicode normalization")
    parser.add_argument(
        "--assign-flat-toprocess", action="store_true",
        help="Assign sources/*.pdf across IE-VE* folders in toprocess",
    )
    parser.add_argument(
        "--crop-top", type=float, default=None, metavar="FRAC",
        help="Fraction of page height to redact at the top (0.0–0.49). Overrides config.",
    )
    parser.add_argument(
        "--crop-bottom", type=float, default=None, metavar="FRAC",
        help="Fraction of page height to redact at the bottom (0.0–0.49). Overrides config.",
    )
    parser.add_argument(
        "--preserve-box",
        type=float, nargs=4, default=None,
        metavar=("X0", "Y0", "X1", "Y1"),
        help=(
            "Normalised bounding box [0.0–1.0] of the region to KEEP on every page "
            "(everything outside is redacted). "
            "Format: X0 Y0 X1 Y1. "
            "Example: --preserve-box 0.11 0.09 0.89 0.82. "
            "Takes priority over --crop-top / --crop-bottom when provided."
        ),
    )
    args = parser.parse_args()

    if args.extractor == "pytiblegenc" and not PYTIBLEGENC_AVAILABLE:
        parser.error(
            "pytiblegenc is not installed. "
            "pip install git+https://github.com/buda-base/py-tiblegenc.git"
        )
    if args.extractor == "pymupdf" and not PYMUPDF_AVAILABLE:
        parser.error("PyMuPDF is not installed. pip install pymupdf")

    global PDF_EXTRACTOR, ENABLE_FONT_CLASSIFICATION, ENABLE_NORMALIZATION
    global CROP_TOP_FRACTION, CROP_BOTTOM_FRACTION, PRESERVE_BOX

    PDF_EXTRACTOR = args.extractor
    if args.no_font_tags:
        ENABLE_FONT_CLASSIFICATION = False
    if args.no_normalization:
        ENABLE_NORMALIZATION = False
    if args.crop_top is not None:
        if not 0.0 <= args.crop_top < 0.5:
            parser.error("--crop-top must be between 0.0 and 0.49")
        CROP_TOP_FRACTION = args.crop_top
    if args.crop_bottom is not None:
        if not 0.0 <= args.crop_bottom < 0.5:
            parser.error("--crop-bottom must be between 0.0 and 0.49")
        CROP_BOTTOM_FRACTION = args.crop_bottom
    if args.preserve_box is not None:
        px0, py0, px1, py1 = args.preserve_box
        for flag, val in (("X0", px0), ("Y0", py0), ("X1", px1), ("Y1", py1)):
            if not 0.0 <= val <= 1.0:
                parser.error(f"--preserve-box {flag} must be in [0.0, 1.0], got {val}")
        if px0 >= px1 or py0 >= py1:
            parser.error(
                f"--preserve-box requires X0 < X1 and Y0 < Y1, "
                f"got {px0} {py0} {px1} {py1}"
            )
        PRESERVE_BOX = args.preserve_box

    if args.single:
        convert_single_file(args.single, args.ve, args.sequence)
    else:
        convert_all_files(args.ve, assign_flat_via_toprocess=args.assign_flat_toprocess)


if __name__ == "__main__":
    main()