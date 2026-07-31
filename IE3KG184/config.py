"""
Shared Configuration for IE3KG184 Conversion Pipeline

This module contains all path configurations and constants used across
the conversion scripts. IE3KG184 has DOCX files in VE folders (Unicode source).
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE3KG184"

# Base directory for the project
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE3KG184")

# Input: DOCX files in toprocess folder (in VE folders)
TOPROCESS_DIR = BASE_DIR / "IE3KG184" / "toprocess"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / "IE3KG184_output"

# =============================================================================
# Output Subdirectories
# =============================================================================

# archive/{VE_ID}/ - XML files
ARCHIVE_DIR = OUTPUT_DIR / "archive"

# sources/{VE_ID}/ - Copies of DOCX files
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# =============================================================================
# Logging
# =============================================================================

LOG_DIR = BASE_DIR / "logs"
DOCX_TO_XML_LOG = LOG_DIR / "docx_to_xml.log"

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
    Extract VE ID from folder name like 'IE3KG184-VE5CNxxx' -> 'VE5CNxxx'.
    
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
        VE5CNxxx, 1 -> UT5CNxxx_0001
        VE5CNxxx, 2 -> UT5CNxxx_0002
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
