"""
Shared Configuration for IE1AB1 Conversion Pipeline
toprocess/sources
This module contains all path configurations and constants used across
the conversion scripts.
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE1PD192038"

# Base directory for the project
BASE_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/file_convert_4/doc/docx")

# Input: DOCX files in sources folder
TOPROCESS_DIR = BASE_DIR / "IE1ER172" / "sources"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / "IE1ER172_output"

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
    Extract VE ID from folder name like 'IE1AB2-VE3KG59' -> 'VE3KG59'.
    
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
        VE3KG59, 1 -> UT3KG59_0001
        VE3KG59, 2 -> UT3KG59_0002
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{sequence:04d}"
