#!/usr/bin/env python3
"""
IE1KG25273: PDF under ``sources/`` → TEI XML.

**Extractors** (``--extractor``):

- **pymupdf** (default): ``page.get_text("rawdict")`` — one ``\\n`` per MuPDF
  **line** (block → line → span); skips **Wingdings**; optional **header/footer
  crop** (``--crop-top`` / ``--crop-bottom`` or config). Suited to
  **MonlamUniOuChan** Unicode PDFs.

- **pytiblegenc**: ``pytiblegenc.pdf_to_txt()`` with the same options as
  IE3KG664 / Desktop SRC_CODE — line breaks follow that library’s layout.
  Header/footer **crop** uses the same redacted temp PDF as **pymupdf**
  (requires PyMuPDF to build it). Requires:
  ``pip install git+https://github.com/buda-base/py-tiblegenc.git``

Later steps map each extractor newline to ``<lb/>`` (layout, not linguistics).

Optional: matching ``.doc`` in ``toprocess/<IE_ID>-<VE_ID>/`` for SHA256; else
checksum from the PDF.

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
#from tibetan_text_fixes import fix_hi_tag_spacing, fix_toc_leader_dots
from tei_generator import post_process_body, generate_tei_xml, calculate_sha256
from pdf_extract import (
    PAGE_BREAK_STR,
    PYMUPDF_AVAILABLE,
    PYTIBLEGENC_AVAILABLE,
    extract_pdf_to_text,
    _FN_SENTINEL_START,
    _FN_SENTINEL_END,
)


def setup_logging():
    """Configure logging with file and console output."""
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

# "pymupdf" | "pytiblegenc" — set from CLI ``--extractor`` in ``main()``.
PDF_EXTRACTOR: str = "pymupdf"

CROP_TOP_FRACTION: float = CROP_HEADER_FRACTION   
CROP_BOTTOM_FRACTION: float = CROP_FOOTER_FRACTION

# Tibetan tsheg (U+0F0B), vowel ུ (U+0F74), ASCII digits, fullwidth digits (U+FF10-U+FF19)
_PAGE_ARTIFACT_CHARS = r"\u0F0B\u0F740-9\uFF10-\uFF19\s"


def strip_page_number_artifacts(text: str) -> str:
    """
    Remove PDF footer artifacts that appear before page breaks: page numbers,
    long tsheg runs, and standalone vowel ུ (e.g. "１ུ", "２ུ", "ུ", "་་་...1").
    """
    pattern = (
        r"((?:<lb/>\s*[" + _PAGE_ARTIFACT_CHARS + r"]*\n?)+)" r"(\s*<lb/>\s*<pb/>)"
    )
    text = re.sub(pattern, r"\2", text)
    pattern2 = (
        r"((?:<lb/>\s*[" + _PAGE_ARTIFACT_CHARS + r"]*\n?)+)" r"(\s*<pb/>)"
    )
    text = re.sub(pattern2, r"\2", text)
    
    # Remove page numbers before closing tags (e.g., <lb/>703</p>)
    text = re.sub(r'<lb/>\s*\d+\s*(?=</[^>]+>)', '', text)
    
    return text


def strip_page_header_artifacts(text: str) -> str:
    """
    Remove PDF header artifacts that appear after page breaks: page numbers,
    Roman numerals, and running headers with book/chapter titles.
    
    Patterns removed:
    - <pb/>\n<lb/>VII\n → <pb/>\n
    - <pb/>\n<lb/>123\n → <pb/>\n
    - <pb/>\n<lb/><hi rend="small">123\n<lb/>དུང་དཀར་གྲུབ་མཐའ།</hi>\n → <pb/>\n
    - <pb/>\n<lb/><hi rend="head">VII\n → <pb/>\n<lb/><hi rend="head">
    """
    # Remove standalone Roman numerals after <pb/>
    text = re.sub(r'(<pb/>\s*)\n<lb/>[IVXLCDM]+\s*\n', r'\1\n', text)
    text = re.sub(r'(<pb/>\s*)\n<lb/>\d+\s*\n', r'\1\n', text)
    # Remove <hi rend="small"> blocks with page number + title after <pb/>
    text = re.sub(r'(<pb/>\s*)\n<lb/><hi rend="small">\d+\s*\n<lb/>[^\n]*</hi>\s*\n', r'\1\n', text)
    text = re.sub(r'(<pb/>\s*)\n<lb/><hi rend="head">[IVXLCDM]+\s*\n', r'\1\n<lb/><hi rend="head">', text)
    
    # Remove Roman numerals at start of <hi rend="head"> sections (section headings)
    text = re.sub(r'(<hi rend="head">)[IVXLCDM]+\s*\n<lb/>', r'\1', text)
    
    return text


# ---------------------------------------------------------------------------
# CJK intra-line deduplication
# ---------------------------------------------------------------------------
# InDesign PDFs with Chinese/CJK content often embed 2–3 stacked text layers
# at the same y-coordinate.  When those layers share a starting x (within a
# few points) MuPDF merges all their spans into a single line dict, and
# _extract_line_text concatenates them left-to-right.  The result is a line
# whose CJK text contains 2–3 overlapping copies of the true content, e.g.:
#
#   '宗 派: 藏傳格魯藏傳格魯巴 藏傳格魯'  →  '宗 派: 藏傳格魯巴'
#   '作 者: 色拉傑格西色拉傑格西 洛桑群培色拉傑格西洛桑群培'
#       →  '作 者: 色拉傑格西 洛桑群培'
#
# The fix is a greedy character-level scan: maintain a running 'emitted CJK'
# string and skip any CJK character (or run) whose leading ngram is already
# present in the emitted buffer.  Non-CJK text (Latin, digits, punctuation,
# Tibetan) is always passed through unchanged so the Tibetan body text is
# never affected.

_CJK_INTRALINE_RE = re.compile(
    r"[\u4E00-\u9FFF"          # CJK Unified Ideographs
    r"\u3400-\u4DBF"           # CJK Extension A
    r"\uF900-\uFAFF"           # CJK Compatibility Ideographs
    r"\u3000-\u303F"           # CJK Symbols and Punctuation
    r"\uFF00-\uFFEF"           # Halfwidth/Fullwidth Forms
    r"]"
)
_CJK_INTRALINE_SEG_RE = re.compile(
    r"[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]+"
    r"|[^\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF\u3000-\u303F\uFF00-\uFFEF]+"
)
_CJK_INTRALINE_MIN_REPEAT = 3   # minimum ngram length to trigger dedup


def deduplicate_cjk_intraline(text: str) -> str:
    """
    Remove internal CJK repetitions from a single assembled line.

    The function is a no-op for:
      - Lines with no CJK characters.
      - Lines whose CJK content contains no repeated ngrams (fast path).
      - Non-CJK text within a mixed line (always passed through verbatim).

    Algorithm
    ---------
    1. Split *text* into alternating CJK / non-CJK segments.
    2. Collect all CJK characters and check for any repeated ngram of length
       ``_CJK_INTRALINE_MIN_REPEAT`` (≥3).  If none found → return early.
    3. For each CJK segment, walk character by character:
       - **Primary check (trigram):** if the next 3 chars already appear in
         ``emitted``, find how far the run extends and skip all of it.
       - **Secondary check (bigram):** if the next 2 chars already appear in
         ``emitted`` (and ``emitted`` has some substance), extend the skip
         logic to single-char stragglers that precede a known dup block.
    4. Non-CJK segments are appended verbatim.
    5. Strip trailing whitespace left by any skipped trailing dup span.
    """
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
            if all_cjk.find(all_cjk[start : start + n], start + 1) >= 0:
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
            # Primary check: trigram already in emitted → skip the dup run.
            look = seg[i : i + _CJK_INTRALINE_MIN_REPEAT]
            if len(look) == _CJK_INTRALINE_MIN_REPEAT and look in emitted:
                j = i
                while j < len(seg) and seg[i : j + 1] in emitted:
                    j += 1
                i = j
                continue
            # Secondary check: bigram already in emitted → try single-char skip.
            look2 = seg[i : i + 2]
            if len(look2) == 2 and look2 in emitted and len(emitted) >= _CJK_INTRALINE_MIN_REPEAT:
                if seg[i] in emitted:
                    j = i
                    while j < len(seg) and seg[i : j + 1] in emitted:
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
    """
    Apply ``deduplicate_cjk_intraline`` to every line in *text*.

    Lines are separated by ``\\n``.  Only lines containing CJK characters are
    processed; all others are returned unchanged.  The PAGE_BREAK_STR sentinel
    and font-size tags (``<fs:N>``) are preserved verbatim.
    """
    lines = text.split("\n")
    result = []
    for line in lines:
        if _CJK_INTRALINE_RE.search(line):
            line = deduplicate_cjk_intraline(line)
        result.append(line)
    return "\n".join(result)


def simplify_font_sizes(text: str) -> str:
    """Simplify font size markup by removing layout-related changes."""
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

    processed_segments = []

    for i, (fs, content) in enumerate(segments):
        if not content:
            continue

        if content == "༼" and i + 1 < len(segments):
            next_fs, next_content = segments[i + 1]
            processed_segments.append((next_fs, "༼" + next_content))
            segments[i + 1] = (None, "")
        elif content.startswith("༽") and processed_segments:
            prev_fs, prev_content = processed_segments[-1]
            processed_segments[-1] = (prev_fs, prev_content + content)
        elif content == "༽" and processed_segments:
            prev_fs, prev_content = processed_segments[-1]
            processed_segments[-1] = (prev_fs, prev_content + "༽")
        else:
            processed_segments.append((fs, content))

    segments = [(fs, c) for fs, c in processed_segments if c]

    merged_segments = []

    for i, (fs, content) in enumerate(segments):
        has_separator = "་" in content or "།" in content or content.endswith("༽")

        if not has_separator and merged_segments:
            prev_fs, prev_content = merged_segments[-1]
            merged_segments[-1] = (prev_fs, prev_content + content)
        elif not has_separator and not merged_segments and not content.strip():
            merged_segments.append((None, content))
        else:
            merged_segments.append((fs, content))

    final_segments = []
    for fs, content in merged_segments:
        if final_segments and final_segments[-1][0] == fs:
            prev_fs, prev_content = final_segments[-1]
            final_segments[-1] = (fs, prev_content + content)
        else:
            final_segments.append((fs, content))

    result = []
    for fs, content in final_segments:
        if fs is not None:
            result.append(f"<fs:{fs}>{content}")
        else:
            result.append(content)

    return "".join(result)


def classify_font_sizes(text: str) -> dict:
    """Classify font sizes in text into large, regular, and small categories."""
    pattern = r"<fs:(\d+)>([^<]*)"
    matches = re.findall(pattern, text)

    if not matches:
        return {}

    size_counts = Counter()
    for fs, content in matches:
        char_count = len([c for c in content if 0x0F00 <= ord(c) <= 0x0FFF])
        if char_count > 0:
            size_counts[int(fs)] += char_count

    if not size_counts:
        return {}

    sizes = sorted(size_counts.keys())
    total_chars = sum(size_counts.values())
    size_percentages = {fs: (count / total_chars * 100) for fs, count in size_counts.items()}

    logger.info(f"    Font sizes: {dict(size_counts)}")
    logger.info(f"    Font percentages: {size_percentages}")

    classifications = {}

    if len(sizes) == 1:
        classifications[sizes[0]] = "regular"

    elif len(sizes) == 2:
        fs1, fs2 = sizes
        pct1, pct2 = size_percentages[fs1], size_percentages[fs2]

        if pct1 > pct2 and pct2 > 10:
            classifications[fs2] = "regular"
            classifications[fs1] = "small"
            logger.info(f"    Inverted classification: {fs1}pt (yigchung) vs {fs2}pt (body)")
        elif pct1 > pct2:
            classifications[fs1] = "regular"
            classifications[fs2] = "large"
        else:
            classifications[fs2] = "regular"
            classifications[fs1] = "small"

    else:
        body_text_range = [fs for fs in sizes if 20 <= fs <= 26 and size_percentages[fs] > 5]

        if body_text_range:
            most_common_fs = max(body_text_range)
        else:
            significant_sizes = [fs for fs in sizes if size_percentages[fs] > 10]
            if significant_sizes:
                most_common_fs = max(significant_sizes)
            else:
                most_common_fs = max(size_counts.items(), key=lambda x: x[1])[0]

        classifications[most_common_fs] = "regular"

        for fs in sizes:
            if fs == most_common_fs:
                continue
            if fs > most_common_fs:
                classifications[fs] = "large"
            else:
                classifications[fs] = "small"

    logger.info(f"    Classifications: {classifications}")
    return classifications


def apply_font_markup(text: str, classifications: dict) -> str:
    """Apply <large> and <small> markup based on font size classifications."""

    def replace_fs(match):
        fs = int(match.group(1))
        classification = classifications.get(fs, "regular")
        if classification == "large":
            return "<LARGE_START>"
        elif classification == "small":
            return "<SMALL_START>"
        else:
            return "<REGULAR_START>"

    text = re.sub(r"<fs:(\d+)>", replace_fs, text)

    result = []
    current_state = "regular"

    parts = re.split(r"(<(?:LARGE|SMALL|REGULAR)_START>)", text)

    for part in parts:
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


def convert_footnote_sentinels_to_tei(text: str) -> str:
    """
    Convert ``ZZFN_START:<n>:<body>ZZFN_END`` sentinels into inline TEI
    ``<note n="N" place="foot">body</note>`` elements, and replace
    ``ZZFNM:<n>`` in-text marker placeholders with empty strings (the
    footnote number is carried by the ``n=`` attribute on ``<note>``).

    Placement rule (per BDRC spec §4.7):
      - The ``<note>`` is inserted at the end of the LAST main-text line
        before the ``<pb/>`` that closes the page.  This satisfies the spec
        requirement that no opening or self-closing markup appears at the end
        of a line (the ``<note/>`` is self-contained, so it can safely sit
        between the last text and the newline).

    ZZFNM markers are stripped: the footnote number in the main text is
    removed and replaced by the inline ``<note>`` at end-of-page, exactly
    as shown in the spec example:
      ``<p>This is the main text<note n="1" place="foot">…</note>.</p>``

    If no ``ZZFN_START`` sentinels exist, the text is returned unchanged.
    """
    import re as _re

    # Fast exit if no footnotes in text
    if _FN_SENTINEL_START not in text:
        # Still strip any ZZFNM markers (shouldn't happen, but be safe)
        text = _re.sub(r"ZZFNM:(\d+)", r"\1", text)
        return text

    # ── Step 1: Remove ZZFNM:<n> in-text markers ────────────────────────────
    # The marker digit is carried by n= on <note>; the superscript digit
    # itself is dropped from the main text stream.
    text = _re.sub(r"ZZFNM:(\d+)", r"\1", text)

    # ── Step 2: Convert ZZFN_START sentinels into <note> elements ───────────
    # Sentinel format (one per line): ZZFN_START:<n>:<body text>ZZFN_END
    _SENTINEL_RE = _re.compile(
        r"ZZFN_START:(\d+):(.+?)ZZFN_END\n?", _re.DOTALL
    )

    def _collect_page_notes(sentinel_block: str) -> list[tuple[str, str]]:
        """Return list of (number, escaped_body) pairs from a sentinel block."""
        notes = []
        for m in _SENTINEL_RE.finditer(sentinel_block):
            n = m.group(1)
            body = m.group(2).strip()
            # Escape XML special characters in footnote body
            body = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            notes.append((n, body))
        return notes

    # Split the text into page-chunks around page-break markers.
    # After convert_markup_to_tei the page break is already <pb/>, but this
    # function is called BEFORE that step, so page breaks are still PAGE_BREAK_STR.
    from pdf_extract import PAGE_BREAK_STR as _PB

    # Split on page-break boundaries; keep the delimiters.
    page_chunks = _re.split(rf"({_re.escape(_PB)})", text)

    result_parts: list[str] = []
    for chunk in page_chunks:
        if chunk == _PB:
            result_parts.append(chunk)
            continue

        # Collect all footnote sentinels in this chunk
        notes = _collect_page_notes(chunk)
        if not notes:
            result_parts.append(chunk)
            continue

        # Remove the sentinel lines from the chunk
        clean_chunk = _SENTINEL_RE.sub("", chunk)

        if not notes:
            result_parts.append(clean_chunk)
            continue

        # Build the <note> elements string
        note_tags = "".join(
            f'<note n="{n}" place="foot">{body}</note>'
            for n, body in notes
        )

        # Insert note tags at the end of the last non-empty line of this chunk.
        # The spec says no opening markup at end of a line, but <note> is
        # self-contained (has a closing tag), so it is safe to append inline.
        lines = clean_chunk.rstrip("\n").split("\n")
        # Find the last line that has actual text content (not just whitespace)
        last_text_idx = None
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip():
                last_text_idx = i
                break

        if last_text_idx is not None:
            lines[last_text_idx] = lines[last_text_idx] + note_tags
            clean_chunk = "\n".join(lines)
            # Restore trailing newline if the original had one
            if chunk.rstrip("\n") != chunk:
                clean_chunk += "\n"

        result_parts.append(clean_chunk)

    return "".join(result_parts)


def convert_markup_to_tei(text: str) -> str:
    """Convert markup to TEI format.
    """

    def escape_content(text_part):
        import re as _re
        # Protect XML markup that must survive the & < > escaping pass.
        # <note n="N" place="foot">…</note> elements were injected by
        # convert_footnote_sentinels_to_tei() and must remain as XML tags.
        text_part = text_part.replace("<large>", "\x00LARGE\x00")
        text_part = text_part.replace("</large>", "\x00/LARGE\x00")
        text_part = text_part.replace("<small>", "\x00SMALL\x00")
        text_part = text_part.replace("</small>", "\x00/SMALL\x00")
        # Protect <note> open tags (with attributes) and close tags
        note_tags = {}
        def _stash_tag(m):
            key = f"\x00NOTE{len(note_tags)}\x00"
            note_tags[key] = m.group(0)
            return key
        text_part = _re.sub(r'<note\b[^>]*>', _stash_tag, text_part)
        text_part = _re.sub(r'</note>', _stash_tag, text_part)

        text_part = text_part.replace("&", "&amp;")
        text_part = text_part.replace("<", "&lt;")
        text_part = text_part.replace(">", "&gt;")

        text_part = text_part.replace("\x00LARGE\x00", "<large>")
        text_part = text_part.replace("\x00/LARGE\x00", "</large>")
        text_part = text_part.replace("\x00SMALL\x00", "<small>")
        text_part = text_part.replace("\x00/SMALL\x00", "</small>")
        # Restore <note> tags
        for key, tag in note_tags.items():
            text_part = text_part.replace(key, tag)

        return text_part

    text = escape_content(text)

    if text.startswith(f"\n{PAGE_BREAK_STR}\n"):
        text = text[len(PAGE_BREAK_STR) + 2 :]
    elif text.startswith(f"{PAGE_BREAK_STR}\n"):
        text = text[len(PAGE_BREAK_STR) + 1 :]

    text = re.sub(PAGE_BREAK_STR, "<<<PB>>>", text)

    text = "<pb/>\n" + text

    lines = text.split("\n")
    result = []

    for i, line in enumerate(lines):
        line = line.rstrip()
        if i > 0:
            result.append("\n<lb/>")
        result.append(line)

    text = "".join(result)

    text = re.sub(r"<<<PB>>>", "<pb/>", text)

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
    # Inline hi must close before page breaks (<pb/></hi> often when small/head spans a page).
    text = re.sub(r"<pb/>\s*</hi>", r"</hi>\n<pb/>", text)
    text = re.sub(r"\n(</hi>)", r"\1\n", text)
    text = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r"\n<lb/>\1", text)
    text = re.sub(r"<lb/> +", r"<lb/>", text)
    text = re.sub(r"\n\n+", r"\n", text)
    text = re.sub(r"  +", r" ", text)

    lines = text.split("\n")
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        content_only = re.sub(r"<lb/>", "", stripped).strip()
        if content_only == "":
            continue
        filtered_lines.append(line)
    text = "\n".join(filtered_lines)

    text = re.sub(r"(<lb/>[ \t]*)+<lb/>", r"<lb/>", text)

    return text


def load_checkpoints() -> set:
    """Load previously converted files from checkpoint."""
    if PDF_TO_XML_CHECKPOINT.exists():
        try:
            content = PDF_TO_XML_CHECKPOINT.read_text(encoding="utf-8").strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error(f"Error reading checkpoint file: {e}")
    return set()


def save_checkpoint(file_path: str):
    """Save a converted file to checkpoint."""
    PDF_TO_XML_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with open(PDF_TO_XML_CHECKPOINT, "a", encoding="utf-8") as f:
        f.write(f"{file_path}\n")


def get_ve_ids_from_toprocess():
    """Collect VE IDs from toprocess folders."""
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
    """
    Assign PDF files to VEs. One VE -> all files; multiple VEs -> split in order.
    """
    if not ve_ids or not pdf_list:
        return {}
    if len(ve_ids) == 1:
        return {ve_ids[0]: pdf_list}
    n = len(ve_ids)
    size = len(pdf_list)
    base, extra = divmod(size, n)
    chunks = []
    start = 0
    for i in range(n):
        count = base + (1 if i < extra else 0)
        chunks.append(pdf_list[start : start + count])
        start += count
    return dict(zip(ve_ids, chunks))


def build_pdf_by_ve(
    ve_filter: Optional[str] = None,
    assign_flat_via_toprocess: bool = False,
    ve_ids_for_flat: Optional[list] = None,
) -> dict:
    """
    Map each volume (VE) ID to PDF paths under SOURCES_DIR.

    - **Subfolders** ``sources/<VE_ID>/`` (any depth): volume ID = immediate subfolder name.
      **toprocess is not used** for discovery or filtering.
    - **Flat** ``sources/*.pdf``: only processed if ``assign_flat_via_toprocess`` is True and
      ``ve_ids_for_flat`` is non-empty; otherwise skipped with a short log (put PDFs under
      ``sources/<VE_ID>/`` instead).
    """
    pdf_by_ve: dict = {}
    if not SOURCES_DIR.exists():
        return pdf_by_ve

    ve_ids_for_flat = list(ve_ids_for_flat or [])
    flat_pdfs = natsorted(SOURCES_DIR.glob("*.pdf"), key=lambda p: p.name)

    for item in natsorted([p for p in SOURCES_DIR.iterdir() if p.is_dir()], key=lambda p: p.name):
        if ve_filter and item.name != ve_filter:
            continue
        pdfs_in_folder = natsorted(item.rglob("*.pdf"), key=lambda p: str(p))
        if not pdfs_in_folder:
            continue
        folder_ve = item.name
        pdf_by_ve[folder_ve] = pdfs_in_folder
        logger.info(
            f"  Volume from sources folder '{folder_ve}': {len(pdfs_in_folder)} PDF(s) "
            f"(under sources/{folder_ve}/)"
        )

    if flat_pdfs:
        if not assign_flat_via_toprocess:
            logger.warning(
                f"Skipping {len(flat_pdfs)} PDF(s) at sources/*.pdf (batch uses volume folders "
                f"only; toprocess ignored). Move to sources/<VE_ID>/ or run with --assign-flat-toprocess."
            )
        elif not ve_ids_for_flat:
            logger.error(
                f"Skipping {len(flat_pdfs)} PDF(s) at sources/*.pdf: --assign-flat-toprocess set but "
                f"no {IE_ID}-VE* folders under toprocess/."
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


def find_source_doc_file(pdf_path: Path, ve_id: str) -> Path:
    """Find the source DOC file in toprocess folder for SHA256 computation."""
    base_name = pdf_path.stem
    ve_folder_name = f"{IE_ID}-{ve_id}"
    ve_folder = TOPROCESS_DIR / ve_folder_name

    if not ve_folder.exists():
        return None

    doc_path = ve_folder / f"{base_name}.doc"
    if doc_path.exists() and doc_path.is_file():
        return doc_path

    for doc_path in ve_folder.glob("*.doc"):
        if doc_path.stem.lower() == base_name.lower() and doc_path.is_file():
            return doc_path

    return None


def convert_pdf_to_tei(pdf_path: Path, ve_id: str, sequence: int) -> str:
    """Convert a single PDF file to TEI XML."""
    source_path = find_source_doc_file(pdf_path, ve_id)
    if not source_path:
        logger.warning(f"Source DOC file not found for {pdf_path.name}, using PDF for SHA256")
        source_path = pdf_path

    raw_text = extract_pdf_to_text(
        pdf_path,
        PDF_EXTRACTOR,
        crop_top=CROP_TOP_FRACTION,
        crop_bottom=CROP_BOTTOM_FRACTION,
    )
    if not raw_text:
        raise ValueError(f"No text extracted from {pdf_path.name}")

    # ── CJK intra-line dedup ─────────────────────────────────────────────────
    # InDesign PDFs stack 2-3 CJK text layers at the same y; MuPDF merges their
    # spans into one line and concatenates them.  Remove the duplicate CJK runs
    # before any other processing so downstream steps see clean text.
    raw_text = apply_cjk_intraline_dedup(raw_text)

    simplified_text = simplify_font_sizes(raw_text)

    if ENABLE_NORMALIZATION:
        logger.info("    Applying normalization...")
        normalized_text = normalize_unicode(simplified_text)
    else:
        # Still strip Wingdings PUA when full normalization is off (font artefact only).
        normalized_text = remove_wingdings_private_use(simplified_text)

    # ── Footnote sentinel → TEI conversion ──────────────────────────────────
    # Convert ZZFN_START/ZZFNM sentinels (emitted by pdf_extract.py when
    # FOOTNOTE_DETECTION=True) into inline <note n="N" place="foot"> elements.
    # This runs after normalization so Tibetan text in footnote bodies is clean.
    if _FN_SENTINEL_START in normalized_text:
        logger.info("    Converting footnote sentinels to TEI <note> elements...")
        normalized_text = convert_footnote_sentinels_to_tei(normalized_text)

    # normalized_text = fix_toc_leader_dots(normalized_text)

    if ENABLE_FONT_CLASSIFICATION:
        classifications = classify_font_sizes(normalized_text)
    else:
        classifications = {}

    if classifications:
        marked_text = apply_font_markup(normalized_text, classifications)
    else:
        marked_text = re.sub(r"<fs:\d+>", "", normalized_text)

    tei_body = convert_markup_to_tei(marked_text)

    #if ENABLE_NORMALIZATION:
    #    tei_body = fix_hi_tag_spacing(tei_body)

    tei_body = post_process_body(tei_body)

    lines = tei_body.split("\n")
    filtered_lines = []
    for line in lines:
        stripped = line.strip()
        content_only = re.sub(r"<lb/>", "", stripped).strip()
        if content_only == "":
            continue
        filtered_lines.append(line)
    tei_body = "\n".join(filtered_lines)

    ut_id = get_ut_id(ve_id, sequence)
    sha256 = calculate_sha256(source_path)
    # TEI src_path: document used for checksum (DOC if present, else PDF name under VE output tree)
    if source_path == pdf_path:
        src_path = f"{ve_id}/{pdf_path.name}"
    else:
        src_path = f"{ve_id}/{source_path.name}"

    tei_xml = generate_tei_xml(
        body_content=tei_body,
        title=pdf_path.stem,
        src_path=src_path,
        sha256=sha256,
        ve_id=ve_id,
        ut_id=ut_id,
    )

    return tei_xml


def copy_sources_to_output(ve_id: str, pdf_files: list):
    """Copy input PDFs to output; copy matching DOC from toprocess when present."""
    sources_ve_dir = SOURCES_OUTPUT_DIR / ve_id
    sources_ve_dir.mkdir(parents=True, exist_ok=True)

    doc_copied_count = 0
    pdf_copied_count = 0

    for pdf_path in pdf_files:
        doc_path = find_source_doc_file(pdf_path, ve_id)
        if doc_path and doc_path.exists():
            doc_dest = sources_ve_dir / doc_path.name
            try:
                shutil.copy2(doc_path, doc_dest)
                doc_copied_count += 1
            except Exception as e:
                logger.warning(f"Failed to copy source DOC {doc_path.name}: {e}")

        if pdf_path.exists():
            pdf_dest = sources_ve_dir / pdf_path.name
            try:
                shutil.copy2(pdf_path, pdf_dest)
                pdf_copied_count += 1
            except Exception as e:
                logger.warning(f"Failed to copy PDF {pdf_path.name}: {e}")

    logger.info(f"  Copied {doc_copied_count} DOC and {pdf_copied_count} PDF files to sources/{ve_id}/")


def _resolve_ve_for_single(explicit_ve: Optional[str]) -> Optional[str]:
    """
    For a PDF directly in sources/*.pdf (no subfolder): use --ve, or one IE1KG25273-VE* in toprocess.
    toprocess is not used when the path is sources/<VE_ID>/file.pdf (volume from folder name).
    """
    if explicit_ve:
        return explicit_ve
    ve_ids = get_ve_ids_from_toprocess()
    if len(ve_ids) == 1:
        return ve_ids[0]
    if not ve_ids:
        logger.error(
            "PDF is at sources/*.pdf (root). Use --ve VE_ID, or move to sources/<VE_ID>/file.pdf "
            "(volume ID = folder name; toprocess not required)."
        )
        return None
    logger.error(
        "PDF is at sources/*.pdf (root) and toprocess has multiple VEs. Specify --ve VE_ID, "
        "or use sources/<VE_ID>/file.pdf."
    )
    return None


def convert_single_file(relative_path: str, ve_id: Optional[str], sequence: Optional[int]):
    """Convert a single PDF under SOURCES_DIR to TEI XML (flat or e.g. VE_ID/file.pdf)."""
    pdf_path = (SOURCES_DIR / relative_path).resolve()
    src_root = SOURCES_DIR.resolve()

    try:
        rel = pdf_path.relative_to(src_root)
    except ValueError:
        logger.error(f"Path must be under sources/: {relative_path}")
        return

    if not pdf_path.exists() or not pdf_path.is_file():
        logger.error(f"PDF file not found under sources/: {relative_path}")
        return
    if pdf_path.suffix.lower() != ".pdf":
        logger.error(f"Not a PDF file: {relative_path}")
        return

    inferred_ve = rel.parts[0] if len(rel.parts) >= 2 else None

    if ve_id:
        final_ve = ve_id
    elif inferred_ve:
        # Volume ID from sources/<VE_ID>/... — toprocess is not consulted (may list a different VE).
        final_ve = inferred_ve
    else:
        final_ve = _resolve_ve_for_single(None)

    if not final_ve:
        return
    ve_id = final_ve

    max_seq = get_max_archive_sequence(ve_id)
    if sequence is None:
        sequence = max_seq + 1
    ut_id = get_ut_id(ve_id, sequence)

    logger.info(f"Converting: {pdf_path.name}")
    logger.info(f"  Extractor: {PDF_EXTRACTOR}")
    logger.info(f"  VE ID: {ve_id}")
    logger.info(f"  UT ID: {ut_id}")

    try:
        tei_xml = convert_pdf_to_tei(pdf_path, ve_id, sequence)
    except Exception as e:
        logger.error(f"Error converting {pdf_path.name}: {e}")
        import traceback

        traceback.print_exc()
        return

    archive_ve_dir = ARCHIVE_DIR / ve_id
    archive_ve_dir.mkdir(parents=True, exist_ok=True)

    xml_path = archive_ve_dir / f"{ut_id}.xml"
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(tei_xml)

    logger.info(f"  Output: {xml_path}")

    copy_sources_to_output(ve_id, [pdf_path])


def convert_all_files(
    ve_filter: Optional[str] = None,
    assign_flat_via_toprocess: bool = False,
):
    """
    Convert all PDFs under sources/<VE_ID>/ (volume = folder name; toprocess not used for that).
    Optional: --assign-flat-toprocess to also split sources/*.pdf using toprocess VEs.
    """
    logger.info("=" * 60)
    logger.info(f"PDF to TEI XML Converter for {IE_ID}")
    logger.info(f"Extractor: {PDF_EXTRACTOR}")
    if ve_filter:
        logger.info(f"Filtering: {ve_filter} only")
    logger.info(f"PDF Source: {SOURCES_DIR}")
    logger.info(f"Output: {OUTPUT_DIR}")
    logger.info("=" * 60)

    ensure_directories()

    ve_ids_for_flat: list = []
    if assign_flat_via_toprocess:
        ve_ids_top = get_ve_ids_from_toprocess()
        ve_ids_for_flat = [v for v in ve_ids_top if not ve_filter or v == ve_filter]
        logger.info(
            f"Also assigning flat sources/*.pdf via toprocess VEs: {ve_ids_for_flat or '(none)'}"
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
            "(e.g. sources/VE1ER999/) or use --assign-flat-toprocess with IE1KG25273-VE* in toprocess."
        )
        return

    logger.info(
        f"PDFs under {SOURCES_DIR}: {total_files} file(s) -> {len(pdf_by_ve)} volume(s): "
        f"{natsorted(pdf_by_ve.keys())}"
    )

    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")

    success_count = 0
    failed_count = 0

    for ve_id in natsorted(pdf_by_ve.keys()):
        pdf_files = pdf_by_ve[ve_id]

        logger.info(f"\nProcessing {ve_id} ({len(pdf_files)} files)")

        archive_ve_dir = ARCHIVE_DIR / ve_id
        archive_ve_dir.mkdir(parents=True, exist_ok=True)

        max_seq = get_max_archive_sequence(ve_id)
        converted_files = []

        for idx, pdf_path in enumerate(pdf_files, start=1):
            pdf_path_str = str(pdf_path)

            if pdf_path_str in checkpoints:
                logger.info(f"  Skipping (already converted): {pdf_path.name}")
                success_count += 1
                converted_files.append(pdf_path)
                continue

            sequence = max_seq + idx
            ut_id = get_ut_id(ve_id, sequence)
            logger.info(f"  [{idx}/{len(pdf_files)}] {pdf_path.name} -> {ut_id}")

            try:
                tei_xml = convert_pdf_to_tei(pdf_path, ve_id, sequence)

                xml_path = archive_ve_dir / f"{ut_id}.xml"
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(tei_xml)

                save_checkpoint(pdf_path_str)
                success_count += 1
                converted_files.append(pdf_path)

            except Exception as e:
                logger.error(f"  Error converting {pdf_path.name}: {e}")
                import traceback

                traceback.print_exc()
                failed_count += 1

        if converted_files:
            copy_sources_to_output(ve_id, converted_files)

    logger.info("\n" + "=" * 60)
    logger.info("CONVERSION COMPLETE!")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Failed: {failed_count}")
    logger.info(f"  Output: {OUTPUT_DIR}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "IE1KG25273: Convert sources/*.pdf and sources/<VE>/**/*.pdf to TEI XML "
            "(PyMuPDF rawdict or pytiblegenc pdf_to_txt)"
        )
    )
    parser.add_argument(
        "--extractor",
        choices=["pymupdf", "pytiblegenc"],
        default="pymupdf",
        help=(
            "PDF text extraction backend: pymupdf = MuPDF rawdict line breaks (default); "
            "pytiblegenc = same pdf_to_txt options as IE3KG664 / Desktop SRC_CODE"
        ),
    )
    parser.add_argument(
        "--single",
        "-s",
        metavar="PATH",
        help="One PDF path under sources/ (e.g. file.pdf or VE1ER999/TI596-01-001.pdf; --ve if ambiguous)",
    )
    parser.add_argument("--ve", metavar="VE_ID", help="VE ID (e.g. VE1ER999) or filter batch to this VE")
    parser.add_argument(
        "--sequence",
        type=int,
        default=None,
        metavar="N",
        help="UT sequence for --single (default: next after max in archive)",
    )
    parser.add_argument("--no-font-tags", action="store_true", help="Disable font classification")
    parser.add_argument("--no-normalization", action="store_true", help="Disable Unicode normalization")
    parser.add_argument(
        "--assign-flat-toprocess",
        action="store_true",
        help="Also assign sources/*.pdf (root) across IE1KG25273-VE* folders in toprocess (default: ignore root PDFs)",
    )
    parser.add_argument(
        "--crop-top",
        type=float,
        default=None,
        metavar="FRAC",
        help=(
            "Fraction of page height to physically redact at the TOP (running header). "
            "E.g. 0.08 blanks the top 8%% and removes text there. Overrides config.CROP_HEADER_FRACTION. "
            "Used for both extractors (redacted temp PDF; pip install pymupdf)."
        ),
    )
    parser.add_argument(
        "--crop-bottom",
        type=float,
        default=None,
        metavar="FRAC",
        help=(
            "Fraction of page height to physically redact at the BOTTOM (running footer). "
            "E.g. 0.07 blanks the bottom 7%% and removes text there. Overrides config.CROP_FOOTER_FRACTION. "
            "Used for both extractors (redacted temp PDF; pip install pymupdf)."
        ),
    )
    args = parser.parse_args()

    if args.extractor == "pytiblegenc" and not PYTIBLEGENC_AVAILABLE:
        parser.error(
            "pytiblegenc is not installed. pip install git+https://github.com/buda-base/py-tiblegenc.git"
        )
    if args.extractor == "pymupdf" and not PYMUPDF_AVAILABLE:
        parser.error("PyMuPDF is not installed. pip install pymupdf")

    global PDF_EXTRACTOR
    PDF_EXTRACTOR = args.extractor

    global ENABLE_FONT_CLASSIFICATION, ENABLE_NORMALIZATION
    global CROP_TOP_FRACTION, CROP_BOTTOM_FRACTION
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

    if args.single:
        convert_single_file(args.single, args.ve, args.sequence)
    else:
        convert_all_files(args.ve, assign_flat_via_toprocess=args.assign_flat_toprocess)


if __name__ == "__main__":
    main()