import os
from pathlib import Path
from typing import Optional, Union

# Default single-workset layout. Batch driver sets PDF_BULK_BASE_DIR and PDF_BULK_IE_ID.
_DEFAULT_BASE = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5/1-11")
_DEFAULT_IE = "IE1KG25273"

_b = os.environ.get("PDF_BULK_BASE_DIR")
_i = os.environ.get("PDF_BULK_IE_ID")
BASE_DIR = Path(_b).expanduser().resolve() if _b else _DEFAULT_BASE
IE_ID = _i if _i else _DEFAULT_IE

SOURCES_DIR = BASE_DIR / IE_ID / "sources"
TOPROCESS_DIR = BASE_DIR / IE_ID / "toprocess"
OUTPUT_DIR = BASE_DIR / f"{IE_ID}_output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# Flat logs/checkpoints when running convert_pdf_to_xml.py alone; nested per IE when
# bulk_multi_ie.py sets both PDF_BULK_BASE_DIR and PDF_BULK_IE_ID (parallel safety).
_bulk_env = bool(_b and _i)
if _bulk_env:
    LOG_DIR = BASE_DIR / "logs" / IE_ID
    CHECKPOINT_DIR = BASE_DIR / "checkpoints" / IE_ID
else:
    LOG_DIR = BASE_DIR / "logs"
    CHECKPOINT_DIR = BASE_DIR / "checkpoints"

PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"

# ─── Header/footer redaction (physical) ───────────────────────────────────
# 0.0 = none. Typical: 0.07–0.12. Override with --crop-top / --crop-bottom.
CROP_HEADER_FRACTION: float = 0.00   # e.g. 0.08  strips top 8 %
CROP_FOOTER_FRACTION: float = 0.00   # e.g. 0.07  strips bottom 7 %

# ─── Full font files for GSUB-based glyph correction ──────────────────────
# Point FONT_DIR at the full (unsubsetted) Monlam font files so that
# pdf_extract.py can invert the GSUB table and permanently fix mis-decoded
# vowel signs (e.g. ŀ→ོ, Ĳ→ེ, Ĩ→ི).
#
# PDFs may embed multiple fonts (e.g. MonlamUniOuChan2 AND MonlamUniOuChan5).
# Each is looked up by name at runtime, so all required fonts must be present.
#
# Accepted values:
#   None                      — GSUB correction disabled (default)
#   Path to a directory       — ALL .ttf/.otf files inside are used  ← recommended
#   Path to a single .ttf     — only that one font is used
#   List of paths             — mix of files and directories
#
# Recommended setup — put all fonts in one folder:
#   fonts/
#     monlam_uni_ouchan2.ttf   ← fixes MonlamUniOuChan2 glyphs
#     monlam_uni_ouchan5.ttf   ← fixes MonlamUniOuChan5 glyphs
#     (add more as needed)
#   FONT_DIR = BASE_DIR / "fonts"
#
# Also works with a single file (useful during testing):
#   FONT_DIR = Path("/Users/name/Downloads/tibetan-fonts/monlam_uni_ouchan2.ttf")
#
# File naming: underscores/hyphens are ignored when matching, so
#   monlam_uni_ouchan2.ttf  matches PDF basefont  MonlamUniOuChan2  ✓
FONT_DIR = Path("/Users/tenzinmonlam/Downloads/download_temp/tibetan-fonts/")
# Example:
# FONT_DIR = BASE_DIR / "fonts"
# FONT_DIR = Path("/Users/tenzinmonlam/Downloads/download_temp/tibetan-fonts")


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
