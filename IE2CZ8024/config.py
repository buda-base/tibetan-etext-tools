"""
Shared Configuration for IE2CZ8024 Conversion Pipeline

This module contains all path configurations and constants used across
the conversion scripts.
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE2CZ8024"

# Base directory for the project
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE2CZ8024")

# Input: DOC files organized by VE folder
SOURCE_DIR = BASE_DIR / "IE2CZ8024" / "sources"

# Intermediate: RTF files (after Word conversion)
RTF_DIR = BASE_DIR / "IE2CZ8024" / "rtf"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / "IE2CZ8024_output"

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
RTF_TO_XML_LOG = LOG_DIR / "rtf_to_xml.log"
VALIDATION_LOG = LOG_DIR / "validation.log"

# =============================================================================
# Checkpoint Files (for resumable conversions)
# =============================================================================

CHECKPOINT_DIR = BASE_DIR / "checkpoints"
DOC_TO_RTF_CHECKPOINT = CHECKPOINT_DIR / "doc_to_rtf_checkpoint.txt"
RTF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "rtf_to_xml_checkpoint.txt"

# =============================================================================
# Word Constants
# =============================================================================

WD_FORMAT_RTF = 6  # Word constant for RTF format


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        RTF_DIR,
        OUTPUT_DIR,
        ARCHIVE_DIR,
        SOURCES_OUTPUT_DIR,
        LOG_DIR,
        CHECKPOINT_DIR,
    ]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)


def get_ve_id_from_path(path: Path) -> str:
    """
    Extract VE ID from a path.
    
    Examples:
        .../sources/VE1ER619/file.doc -> VE1ER619
        .../rtf/VE1ER619/file.rtf -> VE1ER619
    """
    # Look for VE folder in parents
    for parent in path.parents:
        if parent.name.startswith("VE"):
            return parent.name
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    """
    Generate UT ID from VE ID and sequence number.
    
    Examples:
        VE1ER619, 1 -> UT1ER619_0001
        VE1ER619, 2 -> UT1ER619_0002
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{sequence:04d}"

