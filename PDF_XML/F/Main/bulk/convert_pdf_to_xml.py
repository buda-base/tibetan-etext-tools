#!/usr/bin/env python3
"""
PDF under ``<IE_ID>/to_convert/<VE_ID>/`` → TEI XML (see ``config.SOURCES_DIR``).

Text is extracted using the hybrid PyMuPDF + pytiblegenc pipeline.  Each
newline maps to a ``<lb/>`` in the final TEI output (layout breaks, not
linguistic structure).

Optional: matching ``.doc`` in ``toprocess/<IE_ID>-<VE_ID>/`` for SHA256; else
checksum from the PDF.

Usage:
    python convert_pdf_to_xml.py
    python convert_pdf_to_xml.py --ve VE1ER999
    python convert_pdf_to_xml.py --single foo.pdf
    python convert_pdf_to_xml.py --single VE1ER999/TI596-01-001.pdf
    python convert_pdf_to_xml.py --assign-flat-toprocess
    python convert_pdf_to_xml.py --no-font-tags
    python convert_pdf_to_xml.py --no-normalization
    python convert_pdf_to_xml.py --crop-top 0.09 --crop-bottom 0.08

    Debug missing / corrupted text:

    python convert_pdf_to_xml.py --single VE1ER1172/TI904-01-001.pdf --dump-extraction ./debug_out
    python convert_pdf_to_xml.py --single ... --no-extraction-dedup --no-phantom-space
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
    extract_pdf_to_text,
    get_pdf_page_labels,
    get_pdf_page_content_flags,
    _NOTE_OPEN,
    _NOTE_CLOSE,
    _NOTE_TOKEN_RE,
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


CROP_TOP_FRACTION: float = CROP_HEADER_FRACTION   
CROP_BOTTOM_FRACTION: float = CROP_FOOTER_FRACTION

# Extraction tuning (CLI: --no-extraction-dedup, --no-phantom-space)
EXTRACTION_DEDUP: bool = True
EXTRACTION_PHANTOM_SPACE_DROP: bool = True

# If set, convert_pdf_to_tei writes per-PDF debug text files under this directory.
EXTRACTION_DUMP_DIR: Optional[Path] = None

# Coordinate-based preserve box [x0_frac, y0_frac, x1_frac, y1_frac] (CLI: --preserve-box).
PRESERVE_BOX: Optional[list] = None

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


def inject_page_labels(
    tei_body: str,
    page_labels: dict,
    content_flags: Optional[list] = None,
) -> str:
    """
    Replace each ``<pb/>`` in *tei_body* with ``<pb n="LABEL"/>`` using the
    page-label map returned by :func:`pdf_extract.get_pdf_page_labels`.

    ``page_labels`` maps **0-based physical page index** → label string.

    Alignment
    ---------
    Blank pages produce no text, so their ``<pb/>`` is collapsed away by the
    body post-processing and the body ends up with *fewer* ``<pb/>`` than the
    PDF has physical pages.  Counting ``<pb/>`` sequentially against physical
    page indices therefore drifts by one for every blank page that precedes a
    given page — putting labels on the wrong pages.

    To stay aligned, *content_flags* (from
    :func:`pdf_extract.get_pdf_page_content_flags`) lists which physical pages
    actually contribute body text.  The Nth surviving ``<pb/>`` is mapped to
    the Nth ``True`` entry, so blank-page labels are skipped and every
    remaining page gets the label the PDF assigned to it.

    When *content_flags* is ``None`` (or its ``True`` count doesn't match the
    number of ``<pb/>`` in the body, e.g. an unexpected collapse), the function
    falls back to the legacy 1:1 physical-index mapping rather than guessing.

    Pages whose physical index has no label keep the bare ``<pb/>`` form.
    When *page_labels* is empty the body is returned unchanged.
    """
    if not page_labels:
        return tei_body

    pb_count = len(re.findall(r"<pb/>", tei_body))

    # Build the ordered list of physical page indices that each surviving
    # <pb/> maps to.
    physical_indices: list
    if content_flags is not None:
        content_pages = [i for i, has in enumerate(content_flags) if has]
        if len(content_pages) == pb_count:
            physical_indices = content_pages
        else:
            # Counts disagree — don't risk a worse misalignment; log and fall
            # back to the straight physical mapping.
            logger.warning(
                "    Page-label alignment: %d content-bearing page(s) but %d "
                "<pb/> in body; falling back to direct index mapping.",
                len(content_pages), pb_count,
            )
            physical_indices = list(range(pb_count))
    else:
        physical_indices = list(range(pb_count))

    pb_seq = 0

    def _replace(m):
        nonlocal pb_seq
        if pb_seq < len(physical_indices):
            phys = physical_indices[pb_seq]
            label = page_labels.get(phys)
        else:
            label = None
        pb_seq += 1
        if label:
            # Escape XML attribute value characters just in case the label
            # contains an ampersand or quote (extremely rare but possible).
            safe = label.replace("&", "&amp;").replace('"', "&quot;")
            return f'<pb n="{safe}"/>'
        return "<pb/>"

    return re.sub(r"<pb/>", _replace, tei_body)


def convert_markup_to_tei(text: str) -> str:
    """Convert markup to TEI format.
    """

    def escape_content(text_part):
        text_part = text_part.replace("<large>", "\x00LARGE\x00")
        text_part = text_part.replace("</large>", "\x00/LARGE\x00")
        text_part = text_part.replace("<small>", "\x00SMALL\x00")
        text_part = text_part.replace("</small>", "\x00/SMALL\x00")

        text_part = text_part.replace("&", "&amp;")
        text_part = text_part.replace("<", "&lt;")
        text_part = text_part.replace(">", "&gt;")

        text_part = text_part.replace("\x00LARGE\x00", "<large>")
        text_part = text_part.replace("\x00/LARGE\x00", "</large>")
        text_part = text_part.replace("\x00SMALL\x00", "<small>")
        text_part = text_part.replace("\x00/SMALL\x00", "</small>")

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

    text = _convert_footnote_tokens_to_notes(text)

    return text


# Inline footnote reference marker inside the body: a short ASCII digit run
# (the print's superscript reference) that follows Tibetan text — possibly with
# an intervening shad (༎ ། etc.) or closing quote (” ’ " ').  Examples:
#   ``རིག་2``  ``སྲི།།3``  ``འགྱུར་རོ།།”1``  ``མཆོག།”5``
# The running/page number (e.g. ``262``) sits alone on its own line with no
# Tibetan before it, so it is not matched.  Limited to 1–2 digits because real
# references are small; longer runs (years, page refs) are left in the text.
_INLINE_REF_RE = re.compile(
    r"(?<=[\u0f00-\u0fff])"          # a Tibetan char …
    r"([\u0f0d\u0f0e\u201c\u201d\u2018\u2019\"']*)"  # … optional shad/quotes
    r"([0-9]{1,2})"                 # … then 1–2 ASCII digits (the marker)
    r"(?![0-9])"
)

# Tibetan digits U+0F20–U+0F29, indexed 0–9.
_TIB_DIGITS = "༠༡༢༣༤༥༦༧༨༩"


def _to_tibetan_digits(num: str) -> str:
    """Render an ASCII/Tibetan number string as Tibetan digits (best effort)."""
    out = []
    for ch in num:
        if ch.isdigit():
            out.append(_TIB_DIGITS[int(ch)])
        elif "\u0f20" <= ch <= "\u0f29":
            out.append(ch)  # already Tibetan
    return "".join(out) or num


def _build_note_element(num: str, note_text: str) -> str:
    """
    Build the TEI <note> element for one footnote, per
    doc/tei_xml_spec_paginated.md §4.7:

        <note n="N" place="foot">…</note>

    ``n`` is the footnote number in Tibetan digits.  When the note has no number
    (no numbering chain was detected) the ``n`` attribute is omitted but
    ``place="foot"`` is still set.
    """
    attrs = ' place="foot"'
    if num:
        attrs = f' n="{_to_tibetan_digits(num)}"' + attrs
    return f"<note{attrs}>{note_text}</note>"


def _splice_notes_into_page(page_text: str, notes: list[tuple[str, str]]) -> str:
    """
    Attach each note in ``notes`` to its inline reference marker in
    ``page_text``, removing the marker digit.

    Matching is by NUMBER first: a note numbered N is spliced at the body
    reference digit whose value is N (both the print's superscript reference and
    the footnote itself carry the same number).  This is robust against extra
    numeric content in the line and against gaps in detection.  Reference
    markers are bare ASCII digit runs that sit right after Tibetan text
    (e.g. ``རིག་2``); the page/running number (``262``) is body-size and lives
    on its own line, so it is not adjacent to Tibetan and won't be matched.

    Unnumbered notes (no chain detected) fall back to positional matching in
    reading order.  Any note without a usable marker is appended at the end of
    the page so content is never dropped.
    """
    if not notes:
        return page_text

    refs = list(_INLINE_REF_RE.finditer(page_text))

    # The digit run is group(2); group(1) is preceding shad/quotes we keep.
    # Replace only the digit span (start2..end), leaving punctuation in place.
    def _digit_span(m: "re.Match") -> tuple[int, int]:
        return (m.start(2), m.end(2))

    # Index reference markers by their numeric value (first occurrence wins).
    ref_by_value: dict[str, "re.Match"] = {}
    for m in refs:
        ref_by_value.setdefault(m.group(2), m)

    have_numbers = all(num for num, _ in notes if _)

    # Decide a (match_start, match_end, note_element) for each note.
    placements: list[tuple[int, int, str]] = []
    leftover: list[str] = []
    used_spans: set[tuple[int, int]] = set()

    if have_numbers:
        for num, note_text in notes:
            if not note_text:
                continue
            note_el = _build_note_element(num, note_text)
            m = ref_by_value.get(num)
            if m and _digit_span(m) not in used_spans:
                s, e = _digit_span(m)
                placements.append((s, e, note_el))
                used_spans.add((s, e))
            else:
                leftover.append(note_el)
    else:
        # Positional fallback: Nth note → Nth marker in reading order.
        for i, (num, note_text) in enumerate(notes):
            if not note_text:
                continue
            note_el = _build_note_element(num, note_text)
            if i < len(refs):
                s, e = _digit_span(refs[i])
                placements.append((s, e, note_el))
            else:
                leftover.append(note_el)

    # Stitch placements into the page left-to-right.
    placements.sort(key=lambda p: p[0])
    pieces: list[str] = []
    cursor = 0
    for start, end, note_el in placements:
        if start < cursor:
            # Overlapping/duplicate marker — keep note for the tail.
            leftover.append(note_el)
            continue
        pieces.append(page_text[cursor:start])  # text before the digit
        pieces.append(note_el)                  # note replaces the digit
        cursor = end
    pieces.append(page_text[cursor:])
    result = "".join(pieces)

    if leftover:
        result = result.rstrip("\n") + "\n" + "\n".join(leftover)
    return result


def _convert_footnote_tokens_to_notes(text: str) -> str:
    """
    Replace footnote tokens emitted by the extractor with TEI <note> elements.

    A token looks like ``@@FNOTE@@N|note text@@ENDFN@@``.  Footnotes are numbered
    per page in the source, so we process the document one page (``<pb/>``) at a
    time: collect that page's note tokens, strip them from the flow, then splice
    each note inline at its reference marker (a bare digit after Tibetan text),
    removing the marker.  See _splice_notes_into_page for the matching rule and
    _build_note_element for the validator-compliant output shape.

    The note text was XML-escaped together with the body in escape_content, so
    no further escaping is needed here.
    """
    if _NOTE_OPEN not in text:
        return text

    # Split into page segments, keeping the <pb/> delimiters attached to the
    # segment that follows them so reassembly is exact.
    segments = re.split(r"(<pb/>)", text)
    rebuilt: list[str] = []
    for seg in segments:
        if seg == "<pb/>" or _NOTE_OPEN not in seg:
            rebuilt.append(seg)
            continue

        notes: list[tuple[str, str]] = []
        for m in _NOTE_TOKEN_RE.finditer(seg):
            num, _, note_text = m.group(1).partition("|")
            notes.append((num.strip(), note_text.strip()))

        seg = _NOTE_TOKEN_RE.sub("", seg)        # drop standalone token lines
        seg = _splice_notes_into_page(seg, notes)
        rebuilt.append(seg)

    text = "".join(rebuilt)

    # Clean up <lb/> lines left empty after token removal / digit stripping.
    lines = text.split("\n")
    kept = []
    for line in lines:
        if re.sub(r"<lb/>", "", line).strip() == "":
            continue
        kept.append(line)
    return "\n".join(kept)


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
    Map each volume (VE) ID to PDF paths under SOURCES_DIR (``<IE_ID>/to_convert``).

    - **Subfolders** ``to_convert/<VE_ID>/`` (any depth): volume ID = immediate subfolder name.
      **toprocess is not used** for discovery or filtering.
    - **Flat** ``to_convert/*.pdf``: only processed if ``assign_flat_via_toprocess`` is True and
      ``ve_ids_for_flat`` is non-empty; otherwise skipped with a short log (put PDFs under
      ``to_convert/<VE_ID>/`` instead).
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
            f"  Volume from to_convert folder '{folder_ve}': {len(pdfs_in_folder)} PDF(s) "
            f"(under to_convert/{folder_ve}/)"
        )

    if flat_pdfs:
        if not assign_flat_via_toprocess:
            logger.warning(
                f"Skipping {len(flat_pdfs)} PDF(s) at to_convert/*.pdf (batch uses volume folders "
                f"only; toprocess ignored). Move to to_convert/<VE_ID>/ or run with --assign-flat-toprocess."
            )
        elif not ve_ids_for_flat:
            logger.error(
                f"Skipping {len(flat_pdfs)} PDF(s) at to_convert/*.pdf: --assign-flat-toprocess set but "
                f"no {IE_ID}-VE* folders under toprocess/."
            )
        else:
            ve_without_folder = [v for v in ve_ids_for_flat if v not in pdf_by_ve]
            targets = ve_without_folder if ve_without_folder else ve_ids_for_flat
            if not targets:
                logger.error("Flat PDFs in to_convert/ but no VE targets from toprocess.")
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
    stem = pdf_path.stem
    source_path = find_source_doc_file(pdf_path, ve_id)
    if not source_path:
        logger.warning(f"Source DOC file not found for {pdf_path.name}, using PDF for SHA256")
        source_path = pdf_path

    raw_text = extract_pdf_to_text(
        pdf_path,
        crop_top=CROP_TOP_FRACTION,
        crop_bottom=CROP_BOTTOM_FRACTION,
        preserve_box=PRESERVE_BOX,
        extraction_dedup=EXTRACTION_DEDUP,
        phantom_space_drop=EXTRACTION_PHANTOM_SPACE_DROP,
    )
    if not raw_text:
        raise ValueError(f"No text extracted from {pdf_path.name}")

    dump_dir = EXTRACTION_DUMP_DIR
    if dump_dir is not None:
        dump_dir = dump_dir.expanduser().resolve()
        dump_dir.mkdir(parents=True, exist_ok=True)
        (dump_dir / f"{stem}_01_raw_extract.txt").write_text(
            raw_text, encoding="utf-8"
        )
        logger.info(f"    Wrote extraction dump: {dump_dir / (stem + '_01_raw_extract.txt')}")

    simplified_text = simplify_font_sizes(raw_text)

    if ENABLE_NORMALIZATION:
        logger.info("    Applying normalization...")
        normalized_text = normalize_unicode(simplified_text)
    else:
        # Still strip Wingdings PUA when full normalization is off (font artefact only).
        normalized_text = remove_wingdings_private_use(simplified_text)

    # normalized_text = fix_toc_leader_dots(normalized_text)

    if ENABLE_FONT_CLASSIFICATION:
        classifications = classify_font_sizes(normalized_text)
    else:
        classifications = {}

    if classifications:
        marked_text = apply_font_markup(normalized_text, classifications)
    else:
        marked_text = re.sub(r"<fs:\d+>", "", normalized_text)

    if dump_dir is not None:
        (dump_dir / f"{stem}_02_after_normalize.txt").write_text(
            normalized_text, encoding="utf-8"
        )
        (dump_dir / f"{stem}_03_pre_tei_markup.txt").write_text(
            marked_text, encoding="utf-8"
        )
        logger.info(
            f"    Wrote normalization dumps: {stem}_02_after_normalize.txt, "
            f"{stem}_03_pre_tei_markup.txt"
        )

    tei_body = convert_markup_to_tei(marked_text)

    #if ENABLE_NORMALIZATION:
    #    tei_body = fix_hi_tag_spacing(tei_body)

    tei_body = post_process_body(tei_body)

    # Inject <pb n="..."/> labels from the PDF's PageLabels dictionary.
    page_labels = get_pdf_page_labels(pdf_path)
    if page_labels:
        # Content flags let inject_page_labels skip blank pages (whose <pb/> is
        # collapsed away) so labels land on the right pages.  Use the same
        # crop/preserve settings as extraction so the page set matches.
        content_flags = get_pdf_page_content_flags(
            pdf_path,
            crop_top=CROP_TOP_FRACTION,
            crop_bottom=CROP_BOTTOM_FRACTION,
            preserve_box=PRESERVE_BOX,
        )
        logger.info(f"    Page labels found: {len(page_labels)} labelled page(s) "
                    f"(e.g. first={next(iter(page_labels.values()))})")
        tei_body = inject_page_labels(tei_body, page_labels, content_flags)
    else:
        logger.debug("    No custom PageLabels in PDF; <pb/> elements have no n= attribute.")

    if dump_dir is not None:
        (dump_dir / f"{stem}_04_tei_body_postprocess.txt").write_text(
            tei_body, encoding="utf-8"
        )
        logger.info(f"    Wrote TEI body dump: {stem}_04_tei_body_postprocess.txt")

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
    # TEI src_path: checksum from DOC in toprocess if present, else PDF under to_convert
    if source_path == pdf_path:
        src_path = f"{ve_id}/{pdf_path.name}"
    else:
        src_path = f"{IE_ID}-{ve_id}/{source_path.name}"

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
    For a PDF directly in to_convert/*.pdf (no subfolder): use --ve, or one <IE_ID>-VE* in toprocess.
    toprocess is not used when the path is to_convert/<VE_ID>/file.pdf (volume from folder name).
    """
    if explicit_ve:
        return explicit_ve
    ve_ids = get_ve_ids_from_toprocess()
    if len(ve_ids) == 1:
        return ve_ids[0]
    if not ve_ids:
        logger.error(
            "PDF is at to_convert/*.pdf (root). Use --ve VE_ID, or move to to_convert/<VE_ID>/file.pdf "
            "(volume ID = folder name; toprocess not required)."
        )
        return None
    logger.error(
        "PDF is at to_convert/*.pdf (root) and toprocess has multiple VEs. Specify --ve VE_ID, "
        "or use to_convert/<VE_ID>/file.pdf."
    )
    return None


def convert_single_file(relative_path: str, ve_id: Optional[str], sequence: Optional[int]):
    """Convert a single PDF under SOURCES_DIR (to_convert) to TEI XML (flat or e.g. VE_ID/file.pdf)."""
    pdf_path = (SOURCES_DIR / relative_path).resolve()
    src_root = SOURCES_DIR.resolve()

    try:
        rel = pdf_path.relative_to(src_root)
    except ValueError:
        logger.error(f"Path must be under to_convert/: {relative_path}")
        return

    if not pdf_path.exists() or not pdf_path.is_file():
        logger.error(f"PDF file not found under to_convert/: {relative_path}")
        return
    if pdf_path.suffix.lower() != ".pdf":
        logger.error(f"Not a PDF file: {relative_path}")
        return

    inferred_ve = rel.parts[0] if len(rel.parts) >= 2 else None

    if ve_id:
        final_ve = ve_id
    elif inferred_ve:
        # Volume ID from to_convert/<VE_ID>/... — toprocess is not consulted (may list a different VE).
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
    Convert all PDFs under to_convert/<VE_ID>/ (volume = folder name; toprocess not used for that).
    Optional: --assign-flat-toprocess to also split to_convert/*.pdf using toprocess VEs.
    """
    logger.info("=" * 60)
    logger.info(f"PDF to TEI XML Converter for {IE_ID}")
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
            f"Also assigning flat to_convert/*.pdf via toprocess VEs: {ve_ids_for_flat or '(none)'}"
        )
    else:
        logger.info(
            "Batch: volume IDs from to_convert/<folder>/ only — toprocess ignored for assignment."
        )

    pdf_by_ve = build_pdf_by_ve(
        ve_filter=ve_filter,
        assign_flat_via_toprocess=assign_flat_via_toprocess,
        ve_ids_for_flat=ve_ids_for_flat,
    )
    total_files = sum(len(files) for files in pdf_by_ve.values())
    if not pdf_by_ve or total_files == 0:
        logger.error(
            "No PDF files found under to_convert/<VE_ID>/*.pdf. Put PDFs inside a volume folder "
            f"(e.g. to_convert/VE1ER999/) or use --assign-flat-toprocess with {IE_ID}-VE* in toprocess."
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
            f"{IE_ID}: Convert to_convert/*.pdf and to_convert/<VE>/**/*.pdf to TEI XML "
            "Convert PDFs to TEI XML using the hybrid extraction pipeline"
        )
    )
    parser.add_argument(
        "--single",
        "-s",
        metavar="PATH",
        help="One PDF path under to_convert/ (e.g. file.pdf or VE1ER999/TI596-01-001.pdf; --ve if ambiguous)",
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
        "--no-extraction-dedup",
        action="store_true",
        help=(
            "Disable InDesign duplicate-layer dedup (raw-line dedup, within-row shadow dedup, "
            "and sliding-window line dedup). Use when suspected duplicate suppression removes real lines."
        ),
    )
    parser.add_argument(
        "--no-phantom-space",
        action="store_true",
        help=(
            "PyMuPDF only: do not drop phantom U+0020 spaces (Monlam vowel-gap artefact). "
            "Use when suspected mis-classification removes real narrow spaces."
        ),
    )
    parser.add_argument(
        "--dump-extraction",
        metavar="DIR",
        help=(
            "Write per-PDF debug text files under DIR: "
            "<stem>_01_raw_extract.txt (after extract), "
            "_02_after_normalize.txt, _03_pre_tei_markup.txt, "
            "_04_tei_body_postprocess.txt (after TEI body post-process, before empty-line filter)."
        ),
    )
    parser.add_argument(
        "--assign-flat-toprocess",
        action="store_true",
        help=(
            f"Also assign to_convert/*.pdf (root) across {IE_ID}-VE* folders in toprocess "
            "(default: ignore root PDFs)"
        ),
    )
    parser.add_argument(
        "--crop-top",
        type=float,
        default=None,
        metavar="FRAC",
        help=(
            "Fraction of page height to physically redact at the TOP (running header). "
            "E.g. 0.08 blanks the top 8%% and removes text there. Overrides config.CROP_HEADER_FRACTION. "
            "Requires PyMuPDF (pip install pymupdf)."
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
            "Requires PyMuPDF (pip install pymupdf)."
        ),
    )
    parser.add_argument(
        "--preserve-box",
        type=float,
        nargs=4,
        metavar=("X0", "Y0", "X1", "Y1"),
        help=(
            "Normalised page fractions [x0 y0 x1 y1] of the region to KEEP. "
            "Everything outside is physically redacted before extraction. "
            "Takes priority over --crop-top/--crop-bottom. "
            "E.g. --preserve-box 0.11 0.09 0.89 0.82"
        ),
    )
    args = parser.parse_args()

    if not PYMUPDF_AVAILABLE:
        parser.error("PyMuPDF is not installed. pip install pymupdf")

    global ENABLE_FONT_CLASSIFICATION, ENABLE_NORMALIZATION
    global CROP_TOP_FRACTION, CROP_BOTTOM_FRACTION
    global EXTRACTION_DEDUP, EXTRACTION_PHANTOM_SPACE_DROP, EXTRACTION_DUMP_DIR, PRESERVE_BOX
    if args.no_font_tags:
        ENABLE_FONT_CLASSIFICATION = False
    if args.no_normalization:
        ENABLE_NORMALIZATION = False
    if args.no_extraction_dedup:
        EXTRACTION_DEDUP = False
    if args.no_phantom_space:
        EXTRACTION_PHANTOM_SPACE_DROP = False
    if args.dump_extraction:
        EXTRACTION_DUMP_DIR = Path(args.dump_extraction)

    if args.crop_top is not None:
        if not 0.0 <= args.crop_top < 0.5:
            parser.error("--crop-top must be between 0.0 and 0.49")
        CROP_TOP_FRACTION = args.crop_top
    if args.crop_bottom is not None:
        if not 0.0 <= args.crop_bottom < 0.5:
            parser.error("--crop-bottom must be between 0.0 and 0.49")
        CROP_BOTTOM_FRACTION = args.crop_bottom
    if args.preserve_box is not None:
        x0, y0, x1, y1 = args.preserve_box
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            parser.error("--preserve-box fractions must satisfy 0 ≤ x0 < x1 ≤ 1 and 0 ≤ y0 < y1 ≤ 1")
        PRESERVE_BOX = args.preserve_box

    if args.single:
        convert_single_file(args.single, args.ve, args.sequence)
    else:
        convert_all_files(args.ve, assign_flat_via_toprocess=args.assign_flat_toprocess)


if __name__ == "__main__":
    main()