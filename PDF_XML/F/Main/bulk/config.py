"""
Pipeline configuration.

Single-IE workflow
------------------
Edit ``IE_ID`` and ``BASE_DIR`` below, then run ``convert_pdf_to_xml.py``
directly.  Everything else (paths, output, logs, checkpoints) is derived.

Bulk workflow
-------------
``bulk_convert.py`` spawns one ``convert_pdf_to_xml.py`` subprocess per IE
folder and overrides this module's settings through environment variables
so the same config file works in both modes without manual editing:

  PDF_BULK_BASE_DIR     parent directory containing IE*/ worksets
  PDF_BULK_IE_ID        the IE folder to process this run
  PDF_BULK_INPUT_SUBDIR which subfolder under <BASE_DIR>/<IE_ID>/ holds
                        the PDFs (``sources`` or ``to_convert``); the
                        bulk driver auto-detects and sets this
  PDF_BULK_FONT_DIR     override for FONT_DIR (full Tibetan fonts for
                        GSUB resolution); pass an empty string to clear

When BOTH ``PDF_BULK_BASE_DIR`` and ``PDF_BULK_IE_ID`` are set, log and
checkpoint paths are nested under ``<BASE_DIR>/logs/<IE_ID>/`` and
``<BASE_DIR>/checkpoints/<IE_ID>/`` so concurrent workers don't collide.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# ─── Defaults (single-IE workflow) ─────────────────────────────────────────
# Override these for ad-hoc single-IE runs.  The bulk driver replaces them
# at process start via PDF_BULK_BASE_DIR / PDF_BULK_IE_ID.

_DEFAULT_IE_ID = "IE3CN26447"
_DEFAULT_BASE_DIR = Path(
    r"D:\monlam_dharmaduta\task\archive_filtered_pdf\IE3CN26447"
)

# ─── Env-var overrides (bulk workflow) ─────────────────────────────────────

_env_base = os.environ.get("PDF_BULK_BASE_DIR")
_env_ie = os.environ.get("PDF_BULK_IE_ID")
_env_subdir = os.environ.get("PDF_BULK_INPUT_SUBDIR")
_env_font_dir = os.environ.get("PDF_BULK_FONT_DIR")

BASE_DIR: Path = Path(_env_base).expanduser().resolve() if _env_base else _DEFAULT_BASE_DIR
IE_ID: str = _env_ie if _env_ie else _DEFAULT_IE_ID

# Input subfolder: ``sources`` (Unicode-PDF pipeline convention) or
# ``to_convert`` (legacy-font pipeline convention).  Bulk driver auto-detects.
# Default falls back to ``to_convert`` for backwards compatibility.
_INPUT_SUBDIR: str = _env_subdir if _env_subdir else "to_convert"

SOURCES_DIR: Path = BASE_DIR / IE_ID / _INPUT_SUBDIR
TOPROCESS_DIR: Path = BASE_DIR / IE_ID / "toprocess"
OUTPUT_DIR: Path = BASE_DIR / f"{IE_ID}_output"
ARCHIVE_DIR: Path = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR: Path = OUTPUT_DIR / "sources"

# Logs/checkpoints: nest under <IE_ID>/ only when the bulk driver set both
# env vars, so parallel workers can't trample each other's state.
_in_bulk_mode: bool = bool(_env_base and _env_ie)
if _in_bulk_mode:
    LOG_DIR: Path = BASE_DIR / "logs" / IE_ID
    CHECKPOINT_DIR: Path = BASE_DIR / "checkpoints" / IE_ID
else:
    LOG_DIR = BASE_DIR / "logs"
    CHECKPOINT_DIR = BASE_DIR / "checkpoints"

PDF_TO_XML_LOG: Path = LOG_DIR / "pdf_to_xml.log"
PDF_TO_XML_CHECKPOINT: Path = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"

# ─── Header/footer redaction (physical) ────────────────────────────────────
# 0.0 = none.  Typical: 0.07-0.12.  Override per-run with --crop-top /
# --crop-bottom on convert_pdf_to_xml.py, or per-IE via the bulk manifest.
CROP_HEADER_FRACTION: float = 0.08
CROP_FOOTER_FRACTION: float = 0.07

# ─── Full font files for GSUB-based glyph correction ───────────────────────
# Required only for the Unicode-PDF pipeline when MonlamUniOuChan* fonts have
# stripped/wrong ToUnicode CMaps.  Set to a directory holding the full (not
# subsetted) .ttf/.otf files, a single .ttf path, or None to disable.
#
# Per-run override (bulk manifest): PDF_BULK_FONT_DIR=<path> or "" to clear.
FONT_DIR: Optional[Path]
if _env_font_dir is not None:
    FONT_DIR = Path(_env_font_dir).expanduser().resolve() if _env_font_dir else None
else:
    FONT_DIR = None  # edit to a Path() for single-IE runs that need GSUB

# ─── Footnote detection (PyMuPDF extractor only) ───────────────────────────
FOOTNOTE_DETECTION: bool = True
FOOTNOTE_SEPARATOR_MIN_WIDTH_PT: float = 50.0
FOOTNOTE_SEPARATOR_MAX_WIDTH_PT: float = 200.0
FOOTNOTE_MARKER_MAX_FONT_SIZE: float = 10.0
FOOTNOTE_BODY_FONT_SIZE_MAX: float = 11.0

# ─── Helpers ───────────────────────────────────────────────────────────────

def ensure_directories() -> None:
    for d in [
        OUTPUT_DIR,
        ARCHIVE_DIR,
        SOURCES_OUTPUT_DIR,
        LOG_DIR,
        CHECKPOINT_DIR,
    ]:
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