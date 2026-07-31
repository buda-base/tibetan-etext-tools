"""
Shared Configuration for IE2PD17467 Conversion Pipeline

This module contains all path configurations and constants used across
the conversion scripts.
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE2PD17467"

# Base directory for the project
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE2PD17467")

# Input: DOC files in toprocess folder
TOPROCESS_DIR = BASE_DIR / "IE2PD17467" / "toprocess"

# Intermediate: RTF files (after Word conversion)
RTF_DIR = BASE_DIR / "IE2PD17467" / "rtf"

# Intermediate: DOCX files (after Word conversion from DOC)
DOCX_DIR = BASE_DIR / "IE2PD17467" / "docx"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / "IE2PD17467_output"

# =============================================================================
# Output Subdirectories
# =============================================================================

# archive/{VE_ID}/ - XML files
ARCHIVE_DIR = OUTPUT_DIR / "archive"

# sources/{VE_ID}/ - Copies of DOC and RTF files
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# =============================================================================
# Logging
# =============================================================================

LOG_DIR = BASE_DIR / "logs"
DOC_TO_RTF_LOG = LOG_DIR / "doc_to_rtf.log"
DOC_TO_DOCX_LOG = LOG_DIR / "doc_to_docx.log"
DOCX_TO_XML_LOG = LOG_DIR / "docx_to_xml.log"
DOCX_DEDRIS_TO_XML_LOG = LOG_DIR / "docx_dedris_to_xml.log"
RTF_TO_XML_LOG = LOG_DIR / "rtf_to_xml.log"
VALIDATION_LOG = LOG_DIR / "validation.log"

# =============================================================================
# Checkpoint Files (for resumable conversions)
# =============================================================================

CHECKPOINT_DIR = BASE_DIR / "checkpoints"
DOC_TO_RTF_CHECKPOINT = CHECKPOINT_DIR / "doc_to_rtf_checkpoint.txt"
DOC_TO_DOCX_CHECKPOINT = CHECKPOINT_DIR / "doc_to_docx_checkpoint.txt"
DOCX_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "docx_to_xml_checkpoint.txt"
DOCX_DEDRIS_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "docx_dedris_to_xml_checkpoint.txt"
RTF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "rtf_to_xml_checkpoint.txt"

# =============================================================================
# Word Constants
# =============================================================================

WD_FORMAT_RTF = 6   # Word constant for RTF format
WD_FORMAT_DOCX = 16  # Word constant for DOCX format


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        RTF_DIR,
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
    Extract VE ID from folder name like 'IE2PD17467-VE5CN239' -> 'VE5CN239'.
    
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
        VE5CN239, 1 -> UT5CN239_0001
        VE5CN239, 2 -> UT5CN239_0002
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{sequence:04d}"


def get_max_archive_sequence(ve_id: str) -> int:
    """
    Return the maximum sequence number already present in archive/{ve_id}/.
    Used so DOCX conversion can append after existing RTF-derived XMLs.
    
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
