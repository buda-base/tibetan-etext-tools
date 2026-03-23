"""
Shared Configuration for IE3CN8142 Conversion Pipeline

This module contains all path configurations and constants used across
the conversion scripts. IE3CN8142 has DOC files that need conversion to PDF,
then to XML.

Supports three pipelines:
1. DOC -> DOCX -> XML
2. DOC -> RTF -> XML
3. DOC -> PDF -> XML (recommended for Dedris fonts - uses pytiblegenc)
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE3CN8142"

# Base directory for the project
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE3CN8142")

# Input: DOC files in toprocess folder (in VE folders)
TOPROCESS_DIR = BASE_DIR / "IE3CN8142" / "toprocess"
SOURCE_DIR = TOPROCESS_DIR  # Alias for RTF pipeline compatibility

# Intermediate: DOCX files (after Word conversion from DOC)
DOCX_DIR = BASE_DIR / "IE3CN8142" / "docx"

# Intermediate: RTF files (after Word conversion from DOC) - for Dedris-heavy files
RTF_DIR = BASE_DIR / "IE3CN8142" / "rtf"

# Intermediate: PDF files (after Word conversion from DOC) - recommended for Dedris
PDF_DIR = BASE_DIR / "IE3CN8142" / "pdf"

# Output: Final XML files and source copies
OUTPUT_DIR = BASE_DIR / "IE3CN8142_output"

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
DOC_TO_RTF_LOG = LOG_DIR / "doc_to_rtf.log"
RTF_TO_XML_LOG = LOG_DIR / "rtf_to_xml.log"
DOC_TO_PDF_LOG = LOG_DIR / "doc_to_pdf.log"
PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"

# =============================================================================
# Checkpoint Files (for resumable conversions)
# =============================================================================

CHECKPOINT_DIR = BASE_DIR / "checkpoints"
DOC_TO_DOCX_CHECKPOINT = CHECKPOINT_DIR / "doc_to_docx_checkpoint.txt"
DOCX_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "docx_to_xml_checkpoint.txt"
DOC_TO_RTF_CHECKPOINT = CHECKPOINT_DIR / "doc_to_rtf_checkpoint.txt"
RTF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "rtf_to_xml_checkpoint.txt"
DOC_TO_PDF_CHECKPOINT = CHECKPOINT_DIR / "doc_to_pdf_checkpoint.txt"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"

# =============================================================================
# Word Constants
# =============================================================================

WD_FORMAT_DOCX = 16  # Word constant for DOCX format
WD_FORMAT_RTF = 6    # Word constant for RTF format
WD_FORMAT_PDF = 17   # Word constant for PDF format


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    directories = [
        DOCX_DIR,
        RTF_DIR,
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
    Extract VE ID from folder name like 'IE3CN8142-VE5CN123' -> 'VE5CN123'.
    
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
        VE5CN123, 1 -> UT5CN123_0001
        VE5CN123, 2 -> UT5CN123_0002
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
