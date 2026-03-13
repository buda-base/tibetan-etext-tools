"""
Shared Configuration for IE21295 Conversion Pipeline.
toprocess/1-30v/
This module contains path configuration and constants used across
the conversion scripts.
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE1PD192038"

# Base directory for the project
BASE_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/file_convert_4/doc/docx")

# Input root:
#   {BASE_DIR}/IE21295/toprocess/
#     - 1v-30v/{number}/*.docx (actual input files)
#     - IE21295-VE...          (often empty, used to identify VE IDs)
TOPROCESS_DIR = BASE_DIR / IE_ID / "toprocess"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / f"{IE_ID}_output"

# =============================================================================
# Output Subdirectories
# =============================================================================

# archive/{VE_ID}/ - XML files
ARCHIVE_DIR = OUTPUT_DIR / "archive"

# sources/{IE_ID-VE_ID}/ - Copies of DOCX files
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# =============================================================================
# Logging
# =============================================================================

LOG_DIR = BASE_DIR / "logs"
DOCX_TO_XML_LOG = LOG_DIR / "docx_to_xml.log"
VALIDATION_LOG = LOG_DIR / "validation.log"

# =============================================================================
# Checkpoint Files (for resumable conversions)
# =============================================================================

CHECKPOINT_DIR = BASE_DIR / "checkpoints"
DOCX_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "docx_to_xml_checkpoint.txt"

# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        OUTPUT_DIR,
        ARCHIVE_DIR,
        SOURCES_OUTPUT_DIR,
        LOG_DIR,
        CHECKPOINT_DIR,
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def extract_ve_id_from_folder(folder_name: str) -> str:
    """
    Extract VE ID from folder name like 'IE21295-VE5CN107' -> 'VE5CN107'.
    """
    if folder_name.startswith(f"{IE_ID}-"):
        return folder_name.replace(f"{IE_ID}-", "")
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    """
    Generate UT ID from VE ID and sequence number.

    Examples:
        VE5CN107, 1 -> UT5CN107_0001
        VE5CN107, 2 -> UT5CN107_0002
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{sequence:04d}"
