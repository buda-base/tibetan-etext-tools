from pathlib import Path
from tokenize import triple_quoted
from typing import Optional

IE_ID = "IE3KG697"

BASE_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5/pymupdf_resolve/pecha")

SOURCES_DIR = BASE_DIR / "IE3KG697" / "sources"
TOPROCESS_DIR = BASE_DIR / "IE3KG697" / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE3KG697_output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

LOG_DIR = BASE_DIR / "logs"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"

PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"
# ─── Margin redaction — preserve rect (physical, all four sides) ──────────
#
# None  → auto-detect from the PDF (recommended default).
#         margin_detector.py samples the PDF, finds the repeating body column,
#         and returns a fraction rect automatically.
#
# Tuple → manual override as (x0, y0, x1, y1) fractions of page dimensions
#         (0.0–1.0), matching the buddhist.tools/pdf-cropper output exactly.
#
#         Workflow:
#           1. Open https://buddhist.tools/pdf-cropper
#           2. Upload a representative page from your PDF.
#           3. Draw a rectangle around the area you want to KEEP.
#           4. Copy the 4 coordinates shown in the top-right corner.
#           5. Paste them here, e.g.:
#              PRESERVE_RECT = (0.12, 0.19, 0.88, 0.78)
#
#         Meaning of values (all fractions 0.0–1.0):
#           x0 = left edge of keep-rect  (fraction of page width)
#           y0 = top edge of keep-rect   (fraction of page height)
#           x1 = right edge of keep-rect (fraction of page width)
#           y1 = bottom edge of keep-rect(fraction of page height)
#
#         Everything outside that rectangle is physically redacted before
#         text extraction (header, footer, side columns all at once).
#
PRESERVE_RECT: Optional[tuple[float, float, float, float]] = None

def ensure_directories():
    for d in [
        OUTPUT_DIR,
        ARCHIVE_DIR,
        SOURCES_OUTPUT_DIR,
        LOG_DIR,
        CHECKPOINT_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def extract_ve_id_from_folder(folder_name: str) -> str:
    if folder_name.startswith(f"{IE_ID}-"):
        return folder_name.replace(f"{IE_ID}-", "")
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    ve_suffix = ve_id[2:]
    return f"UT{ve_suffix}_{sequence:04d}"


def get_max_archive_sequence(ve_id: str) -> int:
    archive_ve = ARCHIVE_DIR / ve_id
    if not archive_ve.exists():
        return 0
    sequences = []
    for path in archive_ve.glob("UT*.xml"):
        parts = path.stem.split("_")
        if len(parts) >= 2:
            try:
                sequences.append(int(parts[-1]))
            except ValueError:
                pass
    return max(sequences, default=0)

# ─── Full font files for GSUB-based glyph correction ──────────────────────
# Accepted values:
#   None                      — GSUB correction disabled (default)
#   Path to a directory       — all .ttf/.otf files inside are used
#   Path to a single .ttf     — that file is used directly
#   List of paths             — mix of files and directories

# Examples:
#   FONT_DIR = BASE_DIR / "fonts"
#   FONT_DIR = Path("/Users/tenzinmonlam/Downloads/download_temp/tibetan-fonts/monlam_uni_ouchan2.ttf")
FONT_DIR = Path("/Users/tenzinmonlam/tibetan-fonts")
#   FONT_DIR: Optional[Path] = None

# ─── Footnote detection (PyMuPDF extractor only) ──────────────────────────
# Set FOOTNOTE_DETECTION = True to enable automatic footnote detection and
# extraction into <note n="N" place="foot"> TEI elements.
#
# Calibrated for TI1458-01-001.pdf (648pt page height, Monlam font):
#   - Footnote separator: narrow horizontal line ~141pt wide, y = 444–564
#   - In-text markers: standalone digit span, font size ≈ 7.9pt (body = 13.5pt)
#   - Footnote body: font size = 9.0pt, below separator
#
# Tune these thresholds when processing PDFs with different layouts.

FOOTNOTE_DETECTION: bool = True

# Minimum width (pts) a horizontal rule must have to be a footnote separator.
# The wide footer rule (~317pt) is excluded by the max-width check below.
FOOTNOTE_SEPARATOR_MIN_WIDTH_PT: float = 50.0

# Maximum width (pts) for a footnote separator (excludes the page-wide footer rule).
FOOTNOTE_SEPARATOR_MAX_WIDTH_PT: float = 200.0

# Maximum font size (pts, inclusive) for an in-text footnote marker span.
# Monlam superscript markers are ~7.9pt on a 13.5pt body.
FOOTNOTE_MARKER_MAX_FONT_SIZE: float = 10.0

# Font size (pts) of the footnote body text. Used to distinguish footnote body
# rows (9.0pt) from the page-number footer (12.5pt) below the wide separator.
FOOTNOTE_BODY_FONT_SIZE_MAX: float = 11.0