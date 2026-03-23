"""
Shared Configuration for IE3CN26475 Conversion Pipeline

Pipeline: DOC -> PDF -> XML (via pytiblegenc pdf_to_txt with Dedris font conversion)
"""

from pathlib import Path

IE_ID = "IE3CN26475"
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE3CN26475")

TOPROCESS_DIR = BASE_DIR / "IE3CN26475" / "toprocess"
PDF_DIR = BASE_DIR / "IE3CN26475" / "pdf"
OUTPUT_DIR = BASE_DIR / "IE3CN26475_OUTPUT"

ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

LOG_DIR = BASE_DIR / "logs"
DOC_TO_PDF_LOG = LOG_DIR / "doc_to_pdf.log"
PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"

CHECKPOINT_DIR = BASE_DIR / "checkpoints"
DOC_TO_PDF_CHECKPOINT = CHECKPOINT_DIR / "doc_to_pdf_checkpoint.txt"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"

WD_FORMAT_PDF = 17


def ensure_directories():
    """Create all necessary directories if they don't exist."""
    for directory in [PDF_DIR, ARCHIVE_DIR, SOURCES_OUTPUT_DIR, LOG_DIR, CHECKPOINT_DIR]:
        directory.mkdir(parents=True, exist_ok=True)


def extract_ve_id_from_folder(folder_name: str) -> str:
    """Extract VE ID from folder name like 'IE3CN26475-VE5CN1176' -> 'VE5CN1176'."""
    if folder_name.startswith(f'{IE_ID}-'):
        return folder_name.replace(f'{IE_ID}-', '')
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    """Generate UT ID from VE ID and sequence number."""
    ve_suffix = ve_id[2:]
    return f"UT{ve_suffix}_{sequence:04d}"


def get_max_archive_sequence(ve_id: str) -> int:
    """Return the maximum sequence number already present in archive/{ve_id}/."""
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
