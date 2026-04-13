from pathlib import Path
from typing import Optional

IE_ID = "IE3KG647"

BASE_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5/12-22")

SOURCES_DIR = BASE_DIR / "IE3KG647" / "sources"
TOPROCESS_DIR = BASE_DIR / "IE3KG647" / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE3KG647_output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

LOG_DIR = BASE_DIR / "logs"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"

PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"
# ─── Header/footer redaction (physical) ───────────────────────────────
# 0.0 = none. Typical: 0.07–0.12. Override with --crop-top / --crop-bottom.
CROP_HEADER_FRACTION: float = 0.00   # e.g. 0.08  strips top 8 %
CROP_FOOTER_FRACTION: float = 0.00   # e.g. 0.07  strips bottom 7 %

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
# Point FONT_DIR at the full (unsubsetted) Monlam font files so that
# pdf_extract.py can invert the GSUB table and permanently fix mis-decoded
# vowel signs (e.g. ŀ→ོ, Ĳ→ེ, Ĩ→ི).
#
# Accepted values:
#   None                      — GSUB correction disabled (default)
#   Path to a directory       — all .ttf/.otf files inside are used
#   Path to a single .ttf     — that file is used directly
#   List of paths             — mix of files and directories
#
# Examples:
#   FONT_DIR = BASE_DIR / "fonts"
#   FONT_DIR = Path("/Users/tenzinmonlam/Downloads/download_temp/tibetan-fonts/monlam_uni_ouchan2.ttf")
FONT_DIR = Path("/Users/tenzinmonlam/Downloads/download_temp/tibetan-fonts/")
#   FONT_DIR: Optional[Path] = None