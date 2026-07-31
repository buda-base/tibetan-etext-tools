"""
Shared Configuration for IE3CN4059 Conversion Pipeline

This module contains all path configurations and constants used across
the conversion scripts. IE3CN4059 has DOC files in nested subfolders
(subfolder names have .doc extension) that need conversion to PDF,
then to XML with Dedris to Unicode conversion.

Pipeline: DOC -> PDF -> XML (via pytiblegenc pdf_to_txt with Dedris font conversion)
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE3CN4059"

# Base directory for the project
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE3CN4059")

# Input: DOC files in toprocess folder (nested in subfolders with .doc names)
TOPROCESS_DIR = BASE_DIR / "IE3CN4059" / "toprocess"

# Intermediate: PDF files (after Word conversion from DOC)
PDF_DIR = BASE_DIR / "IE3CN4059" / "pdf"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / "IE3CN4059_OUTPUT"

# =============================================================================
# Output Subdirectories
# =============================================================================

# archive/{VE_ID}/ - XML files
ARCHIVE_DIR = OUTPUT_DIR / "archive"

# sources/{VE_ID}/ - Copies of DOC and PDF files
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# =============================================================================
# Logging
# =============================================================================

LOG_DIR = BASE_DIR / "logs"
DOC_TO_PDF_LOG = LOG_DIR / "doc_to_pdf.log"
PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"

# =============================================================================
# Checkpoint Files (for resumable conversions)
# =============================================================================

CHECKPOINT_DIR = BASE_DIR / "checkpoints"
DOC_TO_PDF_CHECKPOINT = CHECKPOINT_DIR / "doc_to_pdf_checkpoint.txt"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"

# =============================================================================
# Word Constants
# =============================================================================

WD_FORMAT_PDF = 17   # Word constant for PDF format


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        PDF_DIR,
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
    Extract VE ID from folder name like 'IE3CN4059-VE5CN1124' -> 'VE5CN1124'.
    
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
        VE5CN1124, 1 -> UT5CN1124_0001
        VE5CN1124, 2 -> UT5CN1124_0002
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
