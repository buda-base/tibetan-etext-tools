from pathlib import Path
from typing import Optional

IE_ID = "IE8LS76787"

BASE_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5")

SOURCES_DIR = BASE_DIR / "IE8LS76787" / "sources"
TOPROCESS_DIR = BASE_DIR / "IE8LS76787" / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE8LS76787_output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

LOG_DIR = BASE_DIR / "logs"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"

PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"

# ─── Header/footer redaction (physical) ───────────────────────────────────────
# 0.0 = none. Typical: 0.07–0.12. Override with --crop-top / --crop-bottom.
CROP_HEADER_FRACTION: float = 0.00
CROP_FOOTER_FRACTION: float = 0.00


def ensure_directories():
    for d in [OUTPUT_DIR, ARCHIVE_DIR, SOURCES_OUTPUT_DIR, LOG_DIR, CHECKPOINT_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def extract_ve_id_from_folder(folder_name: str) -> Optional[str]:
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


# ─── Full font files for GSUB-based glyph correction ──────────────────────────
# Accepted values:
#   None                  — GSUB correction disabled (default)
#   Path to a directory   — all .ttf/.otf files inside are used
#   Path to a .ttf file   — that file is used directly
#   List of paths         — mix of files and directories
FONT_DIR = Path("/Users/tenzinmonlam/tibetan-fonts")

# ─── Footnote detection (PyMuPDF extractor only) ──────────────────────────────
FOOTNOTE_DETECTION: bool = True

FOOTNOTE_SEPARATOR_MIN_WIDTH_PT: float = 50.0
FOOTNOTE_SEPARATOR_MAX_WIDTH_PT: float = 200.0
FOOTNOTE_MARKER_MAX_FONT_SIZE: float = 10.0
FOOTNOTE_BODY_FONT_SIZE_MAX: float = 11.0
