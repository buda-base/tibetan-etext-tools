"""
Shared Configuration for IE3CN18525 Conversion Pipeline

This module contains all path configurations and constants used across
the conversion scripts. IE3CN18525 has DOC and DOCX files directly in
VE folders (no numbered subfolders).
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE3CN18525"

# Base directory for the project
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE3CN18525")

# Input: DOC/DOCX files in toprocess folder (directly in VE folders)
TOPROCESS_DIR = BASE_DIR / "IE3CN18525" / "toprocess"

# Intermediate: DOCX files (after Word conversion from DOC)
DOCX_DIR = BASE_DIR / "IE3CN18525" / "docx"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / "IE3CN18525_output"

# =============================================================================
# Output Subdirectories
# =============================================================================

# archive/{VE_ID}/ - XML files
ARCHIVE_DIR = OUTPUT_DIR / "archive"

# sources/{VE_ID}/ - Copies of DOC/DOCX files
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# =============================================================================
# Logging
# =============================================================================

LOG_DIR = BASE_DIR / "logs"
DOC_TO_DOCX_LOG = LOG_DIR / "doc_to_docx.log"
DOCX_TO_XML_LOG = LOG_DIR / "docx_to_xml.log"

# =============================================================================
# Checkpoint Files (for resumable conversions)
# =============================================================================

CHECKPOINT_DIR = BASE_DIR / "checkpoints"
DOC_TO_DOCX_CHECKPOINT = CHECKPOINT_DIR / "doc_to_docx_checkpoint.txt"
DOCX_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "docx_to_xml_checkpoint.txt"

# =============================================================================
# Word Constants
# =============================================================================

WD_FORMAT_DOCX = 16  # Word constant for DOCX format


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        DOCX_DIR,
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
    Extract VE ID from folder name like 'IE3CN18525-VE5CN976' -> 'VE5CN976'.
    
    Args:
        folder_name: Folder name containing IE_ID and VE_ID
        
    Returns:
        VE ID string or None if pattern doesn't match
    """
    if folder_name.startswith(f'{IE_ID}-'):
        return folder_name.replace(f'{IE_ID}-', '')
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    """
    Generate UT ID from VE ID and sequence number.
    
    Examples:
        VE5CN976, 1 -> UT5CN976_0001
        VE5CN976, 2 -> UT5CN976_0002
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{sequence:04d}"


def get_max_archive_sequence(ve_id: str) -> int:
    """
    Return the maximum sequence number already present in archive/{ve_id}/.
    
    Returns 0 if the directory does not exist or has no UT*.xml files.
    """
    archive_ve = ARCHIVE_DIR / ve_id
    if not archive_ve.exists() or not archive_ve.is_dir():
        return 0
    sequences = []
    for path in archive_ve.glob("UT*.xml"):
        stem = path.stem
        parts = stem.split("_")
        if len(parts) >= 2:
            try:
                sequences.append(int(parts[-1]))
            except ValueError:
                pass
    return max(sequences, default=0)
