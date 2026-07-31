"""
Shared Configuration for IE3KG235 RTF to XML Pipeline

IE3KG235: RTF files in a flat sources/ folder; VE ID(s) from toprocess/IE3KG235-VE* folders.
Output: archive/{VE_ID}/UT*.xml and sources/{VE_ID}/ (same structure as other projects).
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "IE3KG235"

BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE3KG235")

# Input: flat folder of RTF files
SOURCES_DIR = BASE_DIR / "IE3KG235" / "sources"

# Used only to get VE ID(s) from folder names IE3KG235-VE*
TOPROCESS_DIR = BASE_DIR / "IE3KG235" / "toprocess"

# Output
OUTPUT_DIR = BASE_DIR / "IE3KG235_output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# Logging and checkpoints
LOG_DIR = BASE_DIR / "logs"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"
RTF_TO_XML_LOG = LOG_DIR / "rtf_to_xml.log"
RTF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "rtf_to_xml_checkpoint.txt"


# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    for directory in [
        OUTPUT_DIR,
        ARCHIVE_DIR,
        SOURCES_OUTPUT_DIR,
        LOG_DIR,
        CHECKPOINT_DIR,
    ]:
        directory.mkdir(parents=True, exist_ok=True)


def extract_ve_id_from_folder(folder_name: str) -> str:
    """Extract VE ID from folder name like 'IE3KG235-VE3KG205' -> 'VE3KG205'."""
    if folder_name.startswith(f"{IE_ID}-"):
        return folder_name.replace(f"{IE_ID}-", "")
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    """Generate UT ID from VE ID and sequence, e.g. VE3KG205, 1 -> UT3KG205_0001."""
    ve_suffix = ve_id[2:]
    return f"UT{ve_suffix}_{sequence:04d}"


def get_max_archive_sequence(ve_id: str) -> int:
    """Return max sequence already in archive/{ve_id}/ (UT*.xml). Returns 0 if none."""
    archive_ve = ARCHIVE_DIR / ve_id
    if not archive_ve.exists() or not archive_ve.is_dir():
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
