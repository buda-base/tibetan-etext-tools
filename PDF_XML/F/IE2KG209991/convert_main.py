#!/usr/bin/env python3
"""
IE2KG209991: PDF to TEI XML converter with Qomolangma CID remapping.
Extracts text from Tibetan PDFs using PyMuPDF rawdict, applies font-specific
CID remapping (Qomolangma-Uchen-Sarchen, MonlamUniOuChan2, Kailasa), deduplicates
overlaid glyphs by position+Unicode, filters non-Tibetan garbage from Tibetan fonts,
normalises Unicode (NFC, Tibetan reordering, combining-mark collapse), classifies
font sizes, and generates TEI XML output.
Input:  PDFs under sources/<VE_ID>/ (volume ID = folder name).
Output: <IE_ID>_output/archive/<VE_ID>/UT*.xml  +  sources/<VE_ID>/ (PDF + optional DOC).
Optional: matching .doc in toprocess/<IE_ID>-<VE_ID>/ for SHA256; otherwise SHA256 from PDF.
Usage:
    python convert_main.py                              # Convert all PDFs (assigned to VEs)
    python convert_main.py --ve VE1ER1017               # One VE only
    python convert_main.py --single foo.pdf
    python convert_main.py --single VE1ER1017/TI992-01-001.pdf
    python convert_main.py --assign-flat-toprocess      # also assign root *.pdf via toprocess
    python convert_main.py --no-font-tags
    python convert_main.py --no-normalization
    python convert_main.py --crop-top 0.08 --crop-bottom 0.07
"""

import sys
import re
import shutil
import argparse
import logging
import tempfile
import os
from pathlib import Path
from typing import Optional
from collections import Counter
from natsort import natsorted
from cid_remap import CIDRemapper


try:
    import pymupdf as fitz          # PyMuPDF >= 1.23
    PYMUPDF_AVAILABLE = True
except ImportError:
    try:
        import fitz                 # PyMuPDF < 1.23
        PYMUPDF_AVAILABLE = True
    except ImportError:
        PYMUPDF_AVAILABLE = False

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

# --- THE PATCH: Initialize the CIDRemapper globally ---
# We use script_dir to ensure it finds the JSON map regardless of where you run the command from
cid_map_path = script_dir / "qomolangma_cid_map.json"
cid_remapper = CIDRemapper(str(cid_map_path))

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
)
from normalization import normalize_unicode
from tibetan_text_fixes import fix_hi_tag_spacing, fix_toc_leader_dots, fix_flying_vowels_and_linebreaks
from dedris_converter import reset_stats, print_conversion_stats, write_stats_file
from tei_generator import post_process_body, generate_tei_xml, calculate_sha256

try:
    from pytiblegenc import pdf_to_txt
    PYTIBLEGENC_AVAILABLE = True
except ImportError:
    PYTIBLEGENC_AVAILABLE = False
    print(
        "Error: pytiblegenc not installed. Run: pip install git+https://github.com/buda-base/py-tiblegenc.git"
    )
    sys.exit(1)


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
CROP_TOP_FRACTION: float = 0.0      # fraction of page height to strip from top (header)
CROP_BOTTOM_FRACTION: float = 0.0   # fraction of page height to strip from bottom (footer)

PAGE_BREAK_STR = "ZZZZ"
FONT_SIZE_FORMAT = "<fs:{}>"

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
    return text


def create_cropped_pdf(pdf_path: Path, top_frac: float, bottom_frac: float) -> Optional[Path]:
    """
    Return a path to a temporary PDF where the header and footer regions have
    been physically blanked out using white rectangles + redaction annotations.

    Unlike set_cropbox(), this approach removes the underlying text from those
    regions so PDF text extractors (including pytiblegenc/pdf_to_txt) cannot
    see it.

    Args:
        pdf_path:   Source PDF.
        top_frac:   Fraction of page height to blank at the TOP    (0.0–0.49).
        bottom_frac: Fraction of page height to blank at the BOTTOM (0.0–0.49).

    Returns:
        Path to a temporary PDF file, or None if cropping is skipped.
        Caller is responsible for deleting the temp file when done.
    """
    if top_frac == 0.0 and bottom_frac == 0.0:
        return None

    if not PYMUPDF_AVAILABLE:
        logger.warning(
            "Page cropping requested but PyMuPDF is not installed.\n"
            "Install with:  pip install pymupdf\n"
            "Continuing WITHOUT cropping."
        )
        return None

    try:
        doc = fitz.open(str(pdf_path))

        for page in doc:
            w = page.rect.width
            h = page.rect.height

            # --- header band (top of page) ---
            if top_frac > 0.0:
                header_rect = fitz.Rect(0, 0, w, h * top_frac)
                # Add a redaction annotation that will erase all content
                page.add_redact_annot(header_rect)

            # --- footer band (bottom of page) ---
            if bottom_frac > 0.0:
                footer_rect = fitz.Rect(0, h * (1.0 - bottom_frac), w, h)
                page.add_redact_annot(footer_rect)

            # apply_redactions() removes ALL content (text, images, drawings)
            # under the annotation rectangles and replaces them with white fill.
            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,   # leave images untouched
                graphics=0,                           # remove vector graphics too
                text=fitz.PDF_REDACT_TEXT_REMOVE,    # this is what removes the text
            )

        tmp = tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, dir=tempfile.gettempdir()
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        doc.save(str(tmp_path), garbage=4, deflate=True)
        doc.close()

        logger.info(
            f"    Cropped temp PDF: {tmp_path.name} "
            f"(top={top_frac*100:.1f}%, bottom={bottom_frac*100:.1f}%)"
        )
        return tmp_path

    except Exception as e:
        logger.warning(f"    Could not crop {pdf_path.name}: {e} — using original.")
        return None


TIBETAN_FONT_KEYWORDS = (
    "qomolangma",
    "monlamuniouchan2",
    "kailasa",
)

ALLOWED_NON_TIBETAN_IN_TIBETAN_FONTS = set(
    " \n\t\r་།༎༏༐༑༔()[]{}<>-–—.,:;!?\"'0123456789"
)


def is_tibetan_char(ch: str) -> bool:
    if not ch:
        return False
    return all(0x0F00 <= ord(c) <= 0x0FFF for c in ch)


def looks_like_tibetan_font(font_name: str) -> bool:
    f = (font_name or "").lower()
    return any(k in f for k in TIBETAN_FONT_KEYWORDS)


def map_char_with_font_rules(c_char: str, font_name: str, cid_dict: dict) -> str:
    """
    Return mapped char (or original if no mapping).
    Applies CID remap for known problematic Tibetan fonts.
    """
    if not c_char:
        return c_char

    f = (font_name or "").lower()
    if any(k in f for k in TIBETAN_FONT_KEYWORDS):
        # ord() is valid only for one code point.
        if len(c_char) == 1:
            cid_str = str(ord(c_char))
            mapped = cid_dict.get(cid_str)
            if mapped:
                return mapped
        return c_char

    return c_char


def should_drop_as_font_garbage(ch: str, font_name: str) -> bool:
    """
    If a Tibetan-intended font yields non-Tibetan junk, drop it.
    Keep Tibetan chars and strict punctuation/digit allowlist.
    """
    if not ch:
        return True
    if not looks_like_tibetan_font(font_name):
        return False
    for c in ch:
        if 0x0F00 <= ord(c) <= 0x0FFF:
            continue
        if c in ALLOWED_NON_TIBETAN_IN_TIBETAN_FONTS:
            continue
        return True
    return False


def char_position_key(char_obj: dict):
    """Stable key for dedup by same Unicode + same position."""
    bbox = char_obj.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return tuple(round(float(v), 3) for v in bbox)

    origin = char_obj.get("origin")
    if isinstance(origin, (list, tuple)) and len(origin) >= 2:
        return (round(float(origin[0]), 3), round(float(origin[1]), 3))

    return None


def extract_pdf_to_text(pdf_path: Path) -> str:
    """
    Extracts text from a PDF file using raw PyMuPDF.
    Bypasses pytiblegenc to rescue missing CIDs using the character's numerical value.
    """
    logger.info(f"    Extracting & Remapping via rawdict: {pdf_path.name}")

    tmp_pdf: Optional[Path] = None

    try:
        # 1. Handle cropping if requested
        if CROP_TOP_FRACTION > 0.0 or CROP_BOTTOM_FRACTION > 0.0:
            tmp_pdf = create_cropped_pdf(pdf_path, CROP_TOP_FRACTION, CROP_BOTTOM_FRACTION)

        target_pdf = tmp_pdf if tmp_pdf else pdf_path
        
        # 2. Access the loaded JSON map directly from our global remapper
        cid_dict = cid_remapper.cid_map 
        
        doc = fitz.open(str(target_pdf))
        raw_text_parts = []

        for page_idx, page in enumerate(doc, start=1):
            page_dict = page.get_text("rawdict")
            seen_chars = set()

            for block in page_dict.get("blocks", []):
                if block.get("type", 1) != 0:
                    continue

                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        fs = round(span.get("size", 12))
                        raw_text_parts.append(f"<fs:{fs}>")

                        font_name = span.get("font", "")
                        for char in span.get("chars", []):
                            c_char = char.get("c", "")
                            mapped_char = map_char_with_font_rules(c_char, font_name, cid_dict)

                            if should_drop_as_font_garbage(mapped_char, font_name):
                                continue

                            pos_key = char_position_key(char)
                            if pos_key is not None and mapped_char:
                                dedup_key = (page_idx, mapped_char, pos_key)
                                if dedup_key in seen_chars:
                                    continue
                                seen_chars.add(dedup_key)

                            raw_text_parts.append(mapped_char)

                    raw_text_parts.append("\n")

            raw_text_parts.append(f"\n{PAGE_BREAK_STR}\n")

        doc.close()
        
        return "".join(raw_text_parts)

    except Exception as e:
        logger.error(f"    ERROR extracting {pdf_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return ""

    finally:
        if tmp_pdf and tmp_pdf.exists():
            try:
                os.unlink(tmp_pdf)
            except Exception:
                pass


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


def convert_markup_to_tei(text: str) -> str:
    """Convert markup to TEI format."""

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

    text = re.sub(r"\n<lb/>\s*(?=<pb)", r"\n", text)
    text = re.sub(r"<lb/>\s*\n\s*(?=<pb)", r"", text)

    text = re.sub(r"\n<lb/>\s*$", "", text)

    text = text.replace("<large>", '<hi rend="head">')
    text = text.replace("<small>", '<hi rend="small">')
    text = text.replace("</large>", "</hi>")
    text = text.replace("</small>", "</hi>")

    text = re.sub(r"(<lb/>[\s\n]*)+</hi>", r"</hi>", text)
    text = re.sub(r"<lb/>[\s\n]*<pb", r"<pb", text)
    text = re.sub(r"(\n)<pb/>[\s]*</hi>", r"</hi>\1<pb/>", text)
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
    """Collect VE IDs from toprocess folders named IE3KG664-VE*."""
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

    raw_text = extract_pdf_to_text(pdf_path)
    if not raw_text:
        raise ValueError(f"No text extracted from {pdf_path.name}")

    # Fix spurious subjoined consonants from Qomolangma-Uchen-Sarchen font
    # before any other processing. The font's ToUnicode map encodes vowel-bearing
    # combining glyphs as (subjoined_consonant + vowel_sign), where the subjoined
    # consonant is an artefact of the font's internal rendering logic and carries
    # no orthographic meaning. Strip it here while the raw 2-codepoint sequences
    # are still intact (NFC would merge them into composed forms).
    from tibetan_text_fixes import fix_qomolangma_ligatures, cleanup_qomolangma_artifacts
    raw_text = fix_qomolangma_ligatures(raw_text)
    raw_text = cleanup_qomolangma_artifacts(raw_text)

    simplified_text = simplify_font_sizes(raw_text)
   

    if ENABLE_NORMALIZATION:
        logger.info("    Applying normalization...")
        normalized_text = normalize_unicode(simplified_text)
    else:
        normalized_text = simplified_text

    from tei_generator import fix_mixed_dedris_patterns

    normalized_text = fix_mixed_dedris_patterns(normalized_text)
    normalized_text = fix_toc_leader_dots(normalized_text)

    if ENABLE_FONT_CLASSIFICATION:
        classifications = classify_font_sizes(normalized_text)
    else:
        classifications = {}

    if classifications:
        marked_text = apply_font_markup(normalized_text, classifications)
    else:
        marked_text = re.sub(r"<fs:\d+>", "", normalized_text)

    tei_body = convert_markup_to_tei(marked_text)
    tei_body = fix_flying_vowels_and_linebreaks(tei_body)

    if ENABLE_NORMALIZATION:
        tei_body = fix_hi_tag_spacing(tei_body)

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
        src_path = f"sources/{ve_id}/{pdf_path.name}"
    else:
        src_path = f"sources/{ve_id}/{source_path.name}"

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
    For a PDF directly in sources/*.pdf (no subfolder): use --ve, or one IE3KG664-VE* in toprocess.
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
            "(e.g. sources/VE1ER1060/) or use --assign-flat-toprocess with IE3KG664-VE* in toprocess."
        )
        return

    logger.info(
        f"PDFs under {SOURCES_DIR}: {total_files} file(s) -> {len(pdf_by_ve)} volume(s): "
        f"{natsorted(pdf_by_ve.keys())}"
    )

    reset_stats()

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

    print_conversion_stats()
    write_stats_file(OUTPUT_DIR / "pdf_conversion_stats.txt")


def main():
    parser = argparse.ArgumentParser(
        description="IE3KG664: Convert sources/*.pdf and sources/<VE>/**/*.pdf to TEI XML (pytiblegenc)"
    )
    parser.add_argument(
        "--single",
        "-s",
        metavar="PATH",
        help="One PDF path under sources/ (e.g. file.pdf or VE1ER1060/file.pdf; --ve if ambiguous)",
    )
    parser.add_argument("--ve", metavar="VE_ID", help="VE ID (e.g. VE3KG664) or filter batch to this VE")
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
        help="Also assign sources/*.pdf (root) across IE3KG664-VE* folders in toprocess (default: ignore root PDFs)",
    )
    parser.add_argument(
        "--crop-top",
        type=float,
        default=0.0,
        metavar="FRAC",
        help=(
            "Fraction of each page height to blank at the TOP (running header). "
            "E.g. 0.08 removes the top 8%%. Requires pymupdf (pip install pymupdf)."
        ),
    )
    parser.add_argument(
        "--crop-bottom",
        type=float,
        default=0.0,
        metavar="FRAC",
        help=(
            "Fraction of each page height to blank at the BOTTOM (running footer). "
            "E.g. 0.07 removes the bottom 7%%. Requires pymupdf (pip install pymupdf)."
        ),
    )
    args = parser.parse_args()

    global ENABLE_FONT_CLASSIFICATION, ENABLE_NORMALIZATION
    global CROP_TOP_FRACTION, CROP_BOTTOM_FRACTION
    if args.no_font_tags:
        ENABLE_FONT_CLASSIFICATION = False
    if args.no_normalization:
        ENABLE_NORMALIZATION = False
    if args.crop_top:
        if not 0.0 <= args.crop_top < 0.5:
            parser.error("--crop-top must be between 0.0 and 0.49")
        CROP_TOP_FRACTION = args.crop_top
    if args.crop_bottom:
        if not 0.0 <= args.crop_bottom < 0.5:
            parser.error("--crop-bottom must be between 0.0 and 0.49")
        CROP_BOTTOM_FRACTION = args.crop_bottom

    if args.single:
        convert_single_file(args.single, args.ve, args.sequence)
    else:
        convert_all_files(args.ve, assign_flat_via_toprocess=args.assign_flat_toprocess)


if __name__ == "__main__":
    main()