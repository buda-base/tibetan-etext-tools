#!/usr/bin/env python3
"""
Convert RTF files from IE1PD100944 (KAMA Collection) to TEI XML format.

This script converts RTF files with Dedris legacy encoding to Unicode TEI XML.

Pipeline:
1. Strip embedded image groups ({\\pict ... }) from RTF so only text is converted.
2. Parse RTF using basic_rtf parser (extracts text with font info)
3. Convert Dedris encoding to Unicode using pytiblegenc
4. Normalize Unicode (Tibetan-specific normalization)
5. Classify font sizes (regular/small/large)
6. Generate TEI XML with proper structure

Usage:
    # Test on first file (give RTF folder via --ie-id or --rtf-dir):
    python convert.py --ie-id IE1KG4884 --test-first
    python convert.py --rtf-dir ../rtf/IE1KG4884 --test-first

    # Convert a single file by name:
    python convert.py --ie-id IE1KG4884 --single yourfile.rtf

    # Convert all files:
    python convert.py --ie-id IE1KG4884 --all
"""

import sys
import os
import re
import hashlib
import shutil
import tempfile
import argparse
import logging
from pathlib import Path
from collections import Counter, defaultdict
try:
    from natsort import natsorted
except ImportError:
    natsorted = sorted  # fallback if natsort not installed

# Configure logging with immediate output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Ensure stdout is unbuffered for immediate output
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# Add script directory to path (local basic_rtf.py takes priority)
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from basic_rtf import BasicRTF
from normalization import normalize_unicode, normalize_spaces
from tibetan_text_fixes import (
    fix_flying_vowels_and_linebreaks,
    fix_hi_tag_spacing,
    merge_consecutive_hi_tags,
    remove_spaces_between_tibetan_chars,
    ensure_space_after_shad,
    count_tibetan_chars,
)

# Import char_converter directly to avoid pdfminer dependency issues in pytiblegenc.__init__
# This imports the convert_string function without going through __init__.py
import importlib.util
import site

try:
    from pytiblegenc import convert_string
except ImportError as e:
    raise ImportError(
        "a new version of pytiblegenc is required. Install with:\n"
        "  pip install -U git+https://github.com/buda-base/py-tiblegenc.git"
    ) from e

# =============================================================================
# Configuration
# =============================================================================

IE_ID = "IE1PD100944"

# Paths - adjust these as needed (Windows KAMA layout)
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
SOURCE_DOC_DIR = BASE_DIR / "IE1PD100944" / "sources"
RTF_DIR = BASE_DIR / "IE1PD100944_rtf"
TOPROCESS_DIR = BASE_DIR / "IE1PD100944" / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE1PD100944_output"

# Fallback for local testing when Windows path doesn't exist (e.g. on Mac):
# use repo root and rtf/IE1KG4884 so you can test with: --rtf-dir ../rtf/IE1KG4884 --single <file>.rtf
if not BASE_DIR.exists():
    BASE_DIR = script_dir.parent
    IE_ID = "IE1KG4884"
    RTF_DIR = BASE_DIR / "rtf" / "IE1KG4884"
    SOURCE_DOC_DIR = RTF_DIR  # same folder as RTF for single-file test
    TOPROCESS_DIR = RTF_DIR / "toprocess"
    OUTPUT_DIR = RTF_DIR / f"{IE_ID}_output"
    logger.info(f"Using repo-relative paths for {IE_ID}: RTF_DIR={RTF_DIR}")

# Global stats for pytiblegenc
STATS = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0
}

# Supported file extensions for recursive discovery (same as IE1PD104832)
SUPPORTED_EXTENSIONS = {'.rtf', '.doc'}


# =============================================================================
# Recursive file discovery (from IE1PD104832)
# =============================================================================

def find_files_recursive(directory: Path, extensions: set = None) -> list:
    """
    Recursively find all files with given extensions in directory.
    
    Args:
        directory: Directory to search
        extensions: Set of file extensions (e.g., {'.rtf', '.doc'})
        
    Returns:
        List of Path objects
    """
    if extensions is None:
        extensions = SUPPORTED_EXTENSIONS
    
    files = []
    for ext in extensions:
        files.extend(directory.rglob(f"*{ext}"))
        files.extend(directory.rglob(f"*{ext.upper()}"))
    
    return files


def _rtf_pict_keyword_end(s: str, i: int) -> int:
    """Return end index of \\pict control word (\\pict, \\pict0, \\pict-123, etc.)."""
    if i + 5 > len(s) or not s.startswith("\\pict", i):
        return i
    j = i + 5
    while j < len(s) and (s[j] == "-" or s[j].isdigit()):
        j += 1
    if j < len(s) and s[j] in " \n\r\t":
        j += 1
    return j


def strip_rtf_picture_groups(rtf_str: str) -> str:
    """
    Remove RTF picture groups {\\pict ... } from the string so the rest can be parsed as text.
    Uses brace matching: when \\pict (full control word) is seen inside a group, the whole
    group from the opening { to the matching } is removed.
    """
    out = []
    stack = []  # indices into out where we output '{'
    i = 0
    n = len(rtf_str)
    while i < n:
        if rtf_str[i] == "{":
            stack.append(len(out))
            out.append("{")
            i += 1
        elif rtf_str[i] == "}":
            if stack:
                stack.pop()
            out.append("}")
            i += 1
        elif rtf_str[i] == "\\" and rtf_str.startswith("\\pict", i):
            j = _rtf_pict_keyword_end(rtf_str, i)
            if stack:
                open_pos = stack.pop()
                del out[open_pos:]
                level = 1
                while j < n and level > 0:
                    if rtf_str[j] == "{":
                        level += 1
                    elif rtf_str[j] == "}":
                        level -= 1
                    j += 1
                i = j
            else:
                i = j
        else:
            if rtf_str[i] == "\\":
                out.append("\\")
                i += 1
                while i < n and (rtf_str[i].isalnum() or (rtf_str[i] == "-" and i + 1 < n and rtf_str[i + 1].isdigit())):
                    out.append(rtf_str[i])
                    i += 1
                if i < n and rtf_str[i] in " \n\r\t":
                    out.append(rtf_str[i])
                    i += 1
            else:
                out.append(rtf_str[i])
                i += 1
    return "".join(out)


def extract_ve_id_from_path(file_path: Path, ie_id: str) -> str:
    """
    Extract VE ID from file path (from IE1PD104832).
    Looks for {IE_ID}-{VE_ID}, VE pattern, or volume-like folder names.
    """
    parts = file_path.parts
    for part in parts:
        if part.startswith(f'{ie_id}-'):
            ve_id = part.replace(f'{ie_id}-', '')
            if ve_id:
                return ve_id if ve_id.startswith('VE') else f'VE{ve_id}'
    for part in parts:
        if part.startswith('VE') and len(part) > 2 and any(c.isalnum() for c in part[2:]):
            return part
    parent = file_path.parent
    for _ in range(5):
        if parent.name:
            name = parent.name
            if name.startswith(f'{ie_id}-'):
                ve_id = name.replace(f'{ie_id}-', '')
                if ve_id:
                    return ve_id if ve_id.startswith('VE') else f'VE{ve_id}'
            elif name.startswith('VE') and len(name) > 2 and any(c.isalnum() for c in name[2:]):
                return name
            elif re.match(r'vol(ume)?[_\s]?(\d+)', name, re.I):
                match = re.search(r'(\d+)', name)
                if match:
                    # Use same naming as toprocess: VE{IE suffix}_{volume}, e.g. VE1KG4884_001
                    vol_num = match.group(1).zfill(3)
                    ie_suffix = ie_id[2:] if len(ie_id) > 2 else ie_id
                    return f'VE{ie_suffix}_{vol_num}'
        parent = parent.parent
        if parent == parent.parent:
            break
    if file_path.parent.name and file_path.parent.name not in ('', '.', '..'):
        path_hash = hashlib.md5(str(file_path.parent).encode()).hexdigest()[:8]
        return f"UNKNOWN_{path_hash}"
    path_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:8]
    return f"UNKNOWN_{path_hash}"


def group_files_by_volume(files: list, ie_id: str) -> dict:
    """Group files by inferred volume ID (from IE1PD104832). Returns ve_id -> list of Path."""
    volumes = defaultdict(list)
    for file_path in files:
        ve_id = extract_ve_id_from_path(file_path, ie_id)
        volumes[ve_id].append(file_path)
    return volumes


# =============================================================================
# VE/UT ID Functions (from toprocess folder)
# =============================================================================

def _short_ve_id(ve_id: str) -> str:
    """
    Return the short VE part for BDRC URIs and UT IDs.
    IE8CZ266-VE8CZ88 -> VE8CZ88; VE8CZ88 -> VE8CZ88.
    """
    if ve_id.startswith(f"{IE_ID}-"):
        return ve_id[len(IE_ID) + 1:]
    return ve_id


def get_ve_ids_from_toprocess(toprocess_path: Path = None) -> list:
    """
    Get sorted VE IDs from toprocess folder.
    
    Preserves full folder names (e.g. 'IE8CZ266-VE8CZ88') so output paths
    use them. Legacy folders like 'VE1KG4884_001' are returned as-is.
    
    Returns:
        List of volume IDs sorted naturally (full or short form)
    """
    if toprocess_path is None:
        toprocess_path = TOPROCESS_DIR
    
    logger.info(f"Looking for VE IDs in: {toprocess_path}")
    
    if not toprocess_path.exists():
        logger.warning(f"toprocess folder not found at {toprocess_path}")
        return []
    
    ve_ids = []
    for folder in toprocess_path.iterdir():
        if not folder.is_dir():
            continue
        if folder.name.startswith(f'{IE_ID}-'):
            # Keep full name e.g. IE8CZ266-VE8CZ88 for output paths
            ve_ids.append(folder.name)
        elif folder.name.startswith('VE') and len(folder.name) > 2 and any(c.isalnum() or c == '_' for c in folder.name[2:]):
            # e.g. toprocess/VE1KG4884_001/ -> use folder name as ve_id
            ve_ids.append(folder.name)
    
    result = natsorted(ve_ids)
    logger.info(f"Found {len(result)} VE IDs")
    return result


def get_ut_id_from_ve(ve_id: str) -> str:
    """
    Generate UT ID from VE ID.
    
    VE3KG466 -> UT3KG466_0001
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_0001"


def get_ut_id_with_index(ve_id: str, file_index: int) -> str:
    """Generate UT ID from VE ID and file index (for multiple files per volume)."""
    ve_suffix = ve_id[2:] if ve_id.startswith('VE') else ve_id
    return f"UT{ve_suffix}_{file_index + 1:04d}"


def is_volume_file(filename: str) -> bool:
    """
    Check if this is a whole volume file (not a split part).
    
    Volume files (return True):
        - KAMA-001.rtf (basic volume - no suffix)
        - KAMA-017.rtf (basic volume - no suffix)
    
    Split files (return False):
        - KAMA-001-a.rtf (letter suffix = split)
        - KAMA-001-b.rtf (letter suffix = split)
        - KAMA-017-1.rtf (numeric suffix = split)
        - KAMA-017-2.rtf (numeric suffix = split)
        - KAMA-040-1.rtf (numeric suffix = split)
        - KAMA-001-a-1.rtf (has suffix = split)
    
    Logic: Only files matching 'KAMA-NNN.ext' exactly (no suffix) are whole volumes.
    """
    # Only match files like KAMA-001.rtf, KAMA-017.rtf (no suffix after the number)
    # Pattern: KAMA-NNN.ext where NNN is digits only, no additional suffix
    if re.match(r'^KAMA-\d+\.(rtf|doc)$', filename, re.IGNORECASE):
        return True
    return False


def get_volume_rtf_files(rtf_dir: Path = None) -> list:
    """
    Get sorted list of volume RTF files (excluding split files).
    
    Returns:
        List of Path objects for volume RTF files, naturally sorted
    """
    if rtf_dir is None:
        rtf_dir = RTF_DIR
    
    logger.info(f"Looking for RTF files in: {rtf_dir}")
    
    if not rtf_dir.exists():
        logger.error(f"RTF folder not found at {rtf_dir}")
        return []
    
    rtf_files = list(rtf_dir.glob("*.rtf"))
    logger.info(f"Found {len(rtf_files)} total RTF files")
    
    volume_files = [f for f in rtf_files if is_volume_file(f.name)]
    logger.info(f"Filtered to {len(volume_files)} volume files (excluding split files)")
    
    return natsorted(volume_files, key=lambda p: p.name)


def get_volume_rtf_files_from_toprocess(ve_ids: list, toprocess_path: Path = None):
    """
    Get RTF files from toprocess subfolders (one folder per VE ID).
    
    Collects all .rtf from each VE folder, including subdirectories (e.g.
    toprocess/IE1KG4285-VE3KG159/volume-001/*.rtf). Flat layout
    (toprocess/IE1KG4285-VE3KG159/*.rtf) is also supported. No is_volume_file()
    filter so any naming is accepted.
    
    Args:
        ve_ids: List of VE IDs (e.g. from get_ve_ids_from_toprocess())
        toprocess_path: Base toprocess dir (default TOPROCESS_DIR)
    
    Returns:
        List of (ve_id, list of Path) in ve_ids order, or [] if toprocess missing
    """
    if toprocess_path is None:
        toprocess_path = TOPROCESS_DIR
    if not toprocess_path.exists():
        logger.warning(f"toprocess folder not found at {toprocess_path}")
        return []
    result = []
    for ve_id in ve_ids:
        # ve_id may be full (IE8CZ266-VE8CZ88) or short (VE8CZ80)
        folder = toprocess_path / ve_id
        if not folder.exists() and not ve_id.startswith(f"{IE_ID}-"):
            folder = toprocess_path / f"{IE_ID}-{ve_id}"
        if not folder.is_dir():
            logger.warning(f"Volume folder not found: {folder}")
            result.append((ve_id, []))
            continue
        rtf_in_folder = list(folder.rglob("*.rtf")) + list(folder.rglob("*.RTF"))
        files = natsorted(rtf_in_folder, key=lambda x: (x.parent.name, x.name))
        result.append((ve_id, files))
    total = sum(len(files) for _, files in result)
    logger.info(f"Found {total} total RTF files in toprocess ({len(ve_ids)} volume(s))")
    return result


def get_volume_base_name(rtf_path: Path) -> str:
    """
    Extract volume base name from RTF file path.
    
    For whole volume files like KAMA-001.rtf, returns KAMA-001.
    This base name is used to find all related files (the whole file + all splits).
    
    Examples:
        KAMA-001.rtf -> KAMA-001
        KAMA-017.rtf -> KAMA-017
    
    The base name is then used by find_all_related_source_files() to find:
        - KAMA-001.rtf, KAMA-001.doc (whole files)
        - KAMA-001-a.rtf, KAMA-001-a.doc (split a)
        - KAMA-001-1.rtf, KAMA-001-1.doc (split 1)
        - etc.
    """
    return rtf_path.stem  # e.g., "KAMA-001"


def find_all_related_source_files(volume_base: str, rtf_dir: Path = None, doc_dir: Path = None) -> list:
    """
    Find all source files related to a volume (main file + all splits).
    
    For volume "KAMA-001", finds:
        - KAMA-001.rtf, KAMA-001.doc (main files)
        - KAMA-001-a.rtf, KAMA-001-a.doc (split a)
        - KAMA-001-b.rtf, KAMA-001-b.doc (split b)
        - etc.
    
    Args:
        volume_base: Base name of volume (e.g., "KAMA-001", "KAMA-040-1")
        rtf_dir: Directory containing RTF files
        doc_dir: Directory containing DOC files
        
    Returns:
        List of Path objects for all related source files (both DOC and RTF)
    """
    if rtf_dir is None:
        rtf_dir = RTF_DIR
    if doc_dir is None:
        doc_dir = SOURCE_DOC_DIR
    
    related_files = []
    
    # Pattern: volume_base followed by optional suffix (like -a, -b, -a-1)
    # e.g., KAMA-001 matches KAMA-001.rtf, KAMA-001-a.rtf, KAMA-001-a-1.rtf
    # but NOT KAMA-0010.rtf (that would be volume 10, not 001)
    
    # Find RTF files (search recursively so sources in subdirs like sources/volume_001/ are found)
    if rtf_dir.exists():
        for rtf_file in rtf_dir.rglob(f"{volume_base}*.rtf"):
            if "_output" in rtf_file.parts:
                continue
            name_without_ext = rtf_file.stem
            if name_without_ext == volume_base or name_without_ext.startswith(f"{volume_base}-"):
                related_files.append(rtf_file)
    
    # Find DOC files (search recursively)
    if doc_dir.exists():
        for doc_file in doc_dir.rglob(f"{volume_base}*.doc"):
            if "_output" in doc_file.parts:
                continue
            name_without_ext = doc_file.stem
            if name_without_ext == volume_base or name_without_ext.startswith(f"{volume_base}-"):
                related_files.append(doc_file)
    
    return natsorted(related_files, key=lambda p: p.name)


def copy_sources_to_volume_folder(volume_base: str, ve_id: str, output_dir: Path = None,
                                   rtf_dir: Path = None, doc_dir: Path = None,
                                   rtf_path: Path = None, doc_path: Path = None) -> int:
    """
    Copy all source files (DOC and RTF, including splits) to the volume's sources folder.
    
    Creates structure:
        output_dir/sources/{VE_ID}/KAMA-001.doc
        output_dir/sources/{VE_ID}/KAMA-001.rtf
        output_dir/sources/{VE_ID}/KAMA-001-a.doc
        output_dir/sources/{VE_ID}/KAMA-001-a.rtf
        ... (all related files)
    
    Args:
        volume_base: Base name of volume (e.g., "KAMA-001")
        ve_id: Volume Entity ID (e.g., "VE3KG466")
        output_dir: Output directory (default: OUTPUT_DIR)
        rtf_dir: RTF source directory (default: RTF_DIR)
        doc_dir: DOC source directory (default: SOURCE_DOC_DIR)
        rtf_path: Optional path to the RTF file being converted (always copied if given)
        doc_path: Optional path to the DOC file (always copied if given and exists)
        
    Returns:
        Number of files copied
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    if rtf_dir is None:
        rtf_dir = RTF_DIR
    if doc_dir is None:
        doc_dir = SOURCE_DOC_DIR
    
    # Create volume-specific sources folder
    sources_ve_dir = output_dir / "sources" / ve_id
    sources_ve_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all related files (recursive search under rtf_dir / doc_dir)
    related_files = find_all_related_source_files(volume_base, rtf_dir, doc_dir)
    
    # Always include the file(s) being converted so at least they are in output sources
    seen_names = {p.name for p in related_files}
    if rtf_path is not None and rtf_path.exists() and rtf_path.name not in seen_names:
        related_files.append(rtf_path)
        seen_names.add(rtf_path.name)
    if doc_path is not None and doc_path.exists() and doc_path.name not in seen_names:
        related_files.append(doc_path)
    
    copied_count = 0
    for src_file in related_files:
        dest_file = sources_ve_dir / src_file.name
        try:
            shutil.copy2(src_file, dest_file)
            copied_count += 1
        except Exception as e:
            logger.warning(f"Failed to copy {src_file.name}: {e}")
    
    logger.info(f"  Copied {copied_count} source files to sources/{ve_id}/")
    return copied_count


# =============================================================================
# Dedris to Unicode Conversion
# =============================================================================

# Known corruption patterns (wrong font can produce these)
_CORRUPTION_PATTERNS = [
    re.compile(r',ོ'),
    re.compile(r'་\.་'),
    re.compile(r'[{}]'),
]
_ALTERNATE_DEDRIS_FONTS = ['Dedris-vowa', 'Dedris-a', 'Dedris-b', 'Dedris-c']


def _has_corruption(unicode_text: str) -> bool:
    """Return True if text contains known Dedris corruption patterns."""
    return any(p.search(unicode_text) for p in _CORRUPTION_PATTERNS)


def _tibetan_ratio(text: str) -> float:
    """Fraction of characters in Tibetan block U+0F00-U+0FFF."""
    if not text:
        return 0.0
    tibetan_count = sum(1 for c in text if 0x0F00 <= ord(c) <= 0x0FFF)
    return tibetan_count / len(text)


def dedris_to_unicode(text: str, font_name: str) -> str:
    """
    Convert Dedris encoded string to Unicode using pytiblegenc.
    
    Args:
        text: Text in Dedris encoding
        font_name: Font name from RTF (e.g., "Dedris-a", "Dedris-vowa")
        
    Returns:
        Unicode text
    """
    if not text or not text.strip():
        return text
    
    # Fonts that might contain Dedris-encoded characters due to font attribution errors
    # SimSun is a Chinese font, but in these RTFs it sometimes contains Dedris text
    SUSPICIOUS_FONTS = ('simsun', '@simsun', 'simsun western')
    
    # Check if this is a Dedris font
    is_dedris = font_name and font_name.lower().startswith(('dedris', 'ededris'))
    is_suspicious = font_name and font_name.lower() in SUSPICIOUS_FONTS
    
    if not is_dedris and not is_suspicious:
        # Skip truly non-Dedris fonts (e.g., Times New Roman, Arial)
        # Log non-Dedris text that contains potential Dedris characters
        has_suspicious = any(c in text for c in '{}0123456789.,;:!?@#$%^&*()[]<>')
        if has_suspicious and len(text.strip()) > 0:
            preview = text[:50].replace('\n', '\\n')
            if "skipped_non_dedris" not in STATS:
                STATS["skipped_non_dedris"] = []
            if len(STATS["skipped_non_dedris"]) < 100:  # Limit to 100 samples
                STATS["skipped_non_dedris"].append({
                    "font": font_name or "(no font)",
                    "text": preview,
                    "chars": [f"'{c}'({ord(c)})" for c in text[:20] if ord(c) < 128]
                })
        return text
    
    # For suspicious fonts (like SimSun), try converting as Dedris-a
    # This handles font attribution errors in the original RTF
    effective_font = font_name if is_dedris else 'Dedris-a'
    
    try:
        # Pass effective font (handles font attribution errors)
        result = convert_string(text, effective_font, STATS)
        if result is None:
            # Font not in conversion tables
            preview = text[:50].replace('\n', '\\n')
            logger.warning(f"UNHANDLED FONT: '{effective_font}' (original: '{font_name}') | text: '{preview}'")
            return text
        
        # Log when we converted suspicious font text
        if is_suspicious:
            if "converted_suspicious" not in STATS:
                STATS["converted_suspicious"] = []
            if len(STATS["converted_suspicious"]) < 50:
                STATS["converted_suspicious"].append({
                    "font": font_name,
                    "text": text[:30],
                    "result": result[:30]
                })
        
        return result
    except Exception as e:
        logger.warning(f"Error converting with font {effective_font}: {e}")
        return text


# =============================================================================
# Font Size Classification
# =============================================================================

def classify_font_sizes(converted_streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    
    Uses frequency analysis: most common size is regular,
    smaller sizes are 'small', larger sizes are 'large'.
    
    Args:
        converted_streams: List of dicts with 'text' (Unicode), 'font_size'
        
    Returns:
        dict: Mapping of font_size -> classification ('large', 'regular', 'small')
    """
    # Count Tibetan characters for each font size
    size_counts = Counter()
    
    for item in converted_streams:
        text = item.get("text", "")
        font_size = item.get("font_size", 12)
        
        # Count Tibetan characters (U+0F00-U+0FFF)
        tibetan_chars = len([c for c in text if 0x0F00 <= ord(c) <= 0x0FFF])
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    
    if not size_counts:
        return {}
    
    # Find most frequently occurring font size - this is regular (body text)
    most_common = max(size_counts.items(), key=lambda x: x[1])[0]
    
    # Classify all sizes relative to most common
    classifications = {}
    for fs in size_counts.keys():
        if fs == most_common:
            classifications[fs] = 'regular'
        elif fs > most_common:
            classifications[fs] = 'large'
        else:
            classifications[fs] = 'small'
    
    return classifications


# =============================================================================
# RTF to TEI Conversion
# =============================================================================

def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


# =============================================================================
# Staged Conversion Control
# =============================================================================
# Set these flags to control which stages are enabled:
#   Stage 1: RTF parsing + Unicode conversion only (no normalization, no font tags)
#   Stage 2: Add font size classification and <hi> tags
#   Stage 3: Add careful normalization (flying vowels, Unicode normalization)

ENABLE_FONT_CLASSIFICATION = True   # Stage 2: Add <hi rend="small/head"> tags
ENABLE_NORMALIZATION = True         # Stage 3: Apply text normalization


def convert_rtf_to_tei(rtf_path: Path, doc_path: Path, ve_id: str, ut_id: str = None,encoding="unicode") -> str:
    """
    Convert RTF file to TEI XML.
    
    Staged conversion:
    - Stage 1: Parse RTF + convert Dedris to Unicode (always enabled)
    - Stage 2: Font size classification (ENABLE_FONT_CLASSIFICATION)
    - Stage 3: Text normalization (ENABLE_NORMALIZATION)
    
    Args:
        rtf_path: Path to RTF file
        doc_path: Path to original DOC file (for SHA256 and reference)
        ve_id: Volume Entity ID (e.g., "VE3KG466")
        ut_id: Optional UT ID (default: from get_ut_id_from_ve(ve_id))
        encoding: "unicode" (default, pass through) or "dedris" (convert with pytiblegenc)
        
    Returns:
        TEI XML string
    """
    # =========================================================================
    # STAGE 1: Parse RTF and Convert to Unicode
    # =========================================================================
    logger.info(f"Parsing RTF file: {rtf_path.name}")
    with open(rtf_path, encoding="utf-8", errors="ignore") as f:
        rtf_content = f.read()
    rtf_content = strip_rtf_picture_groups(rtf_content)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".rtf", prefix="ie1kg4884_")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as tf:
            tf.write(rtf_content)
        parser = BasicRTF()
        parser.parse_file(tmp_path)
        streams = parser.get_streams()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    
    logger.info(f"Parsed {len(streams)} text streams")
    
    # Convert all Dedris to Unicode
    converted_streams = []
    for stream in streams:
        # Skip special types (headers, footers, images, etc.)
        if stream.get("type") in ("header", "footer", "pict"):
            continue
        
        # Handle paragraph breaks - convert to newline
        if stream.get("type") == "par_break":
            converted_streams.append({
                "text": "\n",
                "font_size": 12,  # Default size for breaks
                "is_break": True
            })
            continue
        
        # Handle line breaks (forced line break inside paragraph)
        if stream.get("type") == "line_break":
            converted_streams.append({
                "text": "\n",
                "font_size": 12,
                "is_break": True
            })
            continue
        
        # Handle table cell breaks
        if stream.get("type") == "cell_break":
            converted_streams.append({
                "text": "\n",  # Just newline for cell breaks
                "font_size": 12,
                "is_break": True
            })
            continue
        
        # Handle table row breaks (end of row)
        if stream.get("type") == "row_break":
            # Row breaks don't add extra newline (cell breaks already did)
            continue
        
        text = stream.get("text", "")
        font_name = stream.get("font", {}).get("name", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        # Convert Dedris to Unicode (or pass through if already Unicode)
        if encoding == "dedris":
            unicode_text = dedris_to_unicode(text, font_name)
            # If output contains known corruption, try alternate Dedris fonts for this run
            if unicode_text and _has_corruption(unicode_text):
                best_text = unicode_text
                best_ratio = _tibetan_ratio(unicode_text)
                for alt_font in _ALTERNATE_DEDRIS_FONTS:
                    if (alt_font or "").lower() == (font_name or "").lower():
                        continue
                    candidate = dedris_to_unicode(text, alt_font)
                    if not candidate:
                        continue
                    if not _has_corruption(candidate):
                        r = _tibetan_ratio(candidate)
                        # Prefer clean result; among clean, prefer higher Tibetan ratio
                        if _has_corruption(best_text) or r > best_ratio:
                            best_text = candidate
                            best_ratio = r
                unicode_text = best_text
        else:
            unicode_text = text
        
        # Keep streams even if they only have whitespace/newlines (for structure)
        if not unicode_text:
            continue
        
        converted_streams.append({
            "text": unicode_text,
            "font_size": font_size
        })
    
    logger.info(f"  Stage 1: Converted {len(converted_streams)} streams to Unicode")
    
    # =========================================================================
    # STAGE 2: Font Size Classification (optional)
    # =========================================================================
    if ENABLE_FONT_CLASSIFICATION:
        classifications = classify_font_sizes(converted_streams)
        if classifications:
            logger.info(f"  Stage 2: Font classifications: {classifications}")
    else:
        classifications = {}
        logger.info(f"  Stage 2: SKIPPED (font classification disabled)")
    
    # =========================================================================
    # BUILD TEI CONTENT
    # =========================================================================
    tei_lines = []
    current_markup = None  # 'small', 'large', or None
    
    for item in converted_streams:
        text = item["text"]
        font_size = item["font_size"]
        
        # Escape XML special characters
        escaped_text = escape_xml(text)
        
        if ENABLE_FONT_CLASSIFICATION and classifications:
            # Determine markup based on font size
            classification = classifications.get(font_size, 'regular')
            
            # Handle markup transitions
            if classification != current_markup:
                # Close previous markup
                if current_markup == 'small':
                    tei_lines.append('</hi>')
                elif current_markup == 'large':
                    tei_lines.append('</hi>')
                
                # Open new markup
                if classification == 'small':
                    tei_lines.append('<hi rend="small">')
                elif classification == 'large':
                    tei_lines.append('<hi rend="head">')
                
                current_markup = classification if classification != 'regular' else None
        
        # Add text content (preserve newlines from RTF \par)
        tei_lines.append(escaped_text)
    
    # Close any open markup
    if current_markup == 'small':
        tei_lines.append('</hi>')
    elif current_markup == 'large':
        tei_lines.append('</hi>')
    
    # Join all content (text already has newlines from RTF \par)
    body_content = ''.join(tei_lines)
    
    # Clean up empty hi tags and merge consecutive same-rend hi tags
    if ENABLE_FONT_CLASSIFICATION:
        body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
        body_content = merge_consecutive_hi_tags(body_content)
    
    # =========================================================================
    # Strip Word field codes (PAGE \* MERGEFORMAT, etc.) from body text
    # =========================================================================
    # Allow optional backslash before * (Word can emit "PAGE \* MERGEFORMAT")
    body_content = re.sub(r'\s*PAGE\s+\\?\s*\*\s*MERGEFORMAT\s*\d*\s*', ' ', body_content)
    body_content = re.sub(r'\s*NUMPAGES\s+\\?\s*\*\s*MERGEFORMAT\s*', ' ', body_content)
    body_content = re.sub(r'\s{2,}', ' ', body_content)  # collapse spaces left by stripping
    
    # =========================================================================
    # STAGE 3: Normalization (optional)
    # =========================================================================
    if ENABLE_NORMALIZATION:
        logger.info(f"  Stage 3: Applying normalization...")
        
        # Remove spaces only inside syllables (preserve space after ། and ་)
        body_content = remove_spaces_between_tibetan_chars(body_content)
        
        # Ensure space after shad ( ། ) when missing so "ལི།བོད་" -> "ལི། བོད་"
        body_content = ensure_space_after_shad(body_content)
        
        # Fix flying vowels and improper line breaks
        body_content = fix_flying_vowels_and_linebreaks(body_content)
        
        # Apply full Unicode normalization (includes Tibetan-specific reordering)
        body_content = normalize_unicode(body_content)
        
        # Final space normalization (commented out for now)
        # body_content = normalize_spaces(body_content, tibetan_specific=True)
        
        # Fix spacing around <hi> tags based on Tibetan punctuation rules
        body_content = fix_hi_tag_spacing(body_content)
        
        # Clean up multiple newlines (commented out for now)
        # body_content = re.sub(r'\n\n+', '\n', body_content)
    else:
        logger.info(f"  Stage 3: SKIPPED (normalization disabled)")
    
    body_content = body_content.strip()
    
    # =========================================================================
    # ADD LINE BREAK TAGS
    # =========================================================================
    # Put <lb/> at beginning of each new line and remove surrounding spaces
    body_content = body_content.replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '\n<lb/>', body_content)
    body_content = body_content.strip()
    
    # =========================================================================
    # FIX <hi> TAG PLACEMENT
    # =========================================================================
    # Don't wrap whitespace/newlines only in <hi> tags
    # Remove <hi> tags that contain only whitespace/newlines/lb tags
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', '', body_content)
    
    # Move <hi> from end of line to after <lb/> on next line
    # Pattern: <hi...> followed by optional whitespace, newline, <lb/>
    body_content = re.sub(r'(<hi rend="[^"]+">)\s*\n<lb/>', r'\n<lb/>\1', body_content)
    
    # Move </hi> from after <lb/> to before the newline (end of previous line)
    # Pattern: newline, <lb/>, </hi>
    body_content = re.sub(r'\n<lb/></hi>', r'</hi>\n<lb/>', body_content)
    
    # Remove double newlines
    body_content = re.sub(r'\n\n+', '\n', body_content)
    
    # Clean up any remaining empty <hi> tags after the moves
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', '', body_content)
    
    # Final strip
    body_content = body_content.strip()
    
    # =========================================================================
    # GENERATE TEI XML
    # =========================================================================
    # ve_id may be full (IE8CZ266-VE8CZ88); use for src_path; short form for UT/bdrc_ve
    short_ve_id = _short_ve_id(ve_id)
    if ut_id is None:
        ut_id = get_ut_id_from_ve(short_ve_id)
    source_file = doc_path if doc_path.exists() else rtf_path
    sha256_ref = calculate_sha256(source_file)
    src_path = f"{ve_id}/{source_file.name}"
    
    tei_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
<fileDesc>
<titleStmt>
<title>{escape_xml(rtf_path.stem)}</title>
</titleStmt>
<publicationStmt>
<p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p>
</publicationStmt>
<sourceDesc>
<bibl>
<idno type="src_path">{src_path}</idno>
<idno type="sha256">{sha256_ref}</idno>
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{IE_ID}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{short_ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl>
</sourceDesc>
</fileDesc>
<encodingDesc>
<p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{IE_ID}">record in the BDRC database</ref>.</p>
</encodingDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p>{body_content}</p>
</body>
</text>
</TEI>
'''
    
    return tei_xml


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


# =============================================================================
# Single File Conversion
# =============================================================================

def convert_single_file(rtf_path: Path, ve_id: str, output_dir: Path = None, rtf_dir: Path = None, doc_dir: Path = None, ut_id: str = None,encoding = "unicode"):
    """
    Convert a single RTF file to TEI XML.
    
    Args:
        rtf_path: Path to the RTF file
        ve_id: Volume Entity ID (e.g., "VE3KG466")
        output_dir: Output directory (default: OUTPUT_DIR)
        rtf_dir: Optional RTF/source directory (for doc and copy lookups; default: RTF_DIR)
        doc_dir: Optional DOC directory (default: SOURCE_DOC_DIR or rtf_dir)
        ut_id: Optional UT ID (default: from get_ut_id_from_ve(ve_id); use for multi-file-per-volume)
        
    Returns:
        Path to the generated XML file, or None if failed
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    if rtf_dir is None:
        rtf_dir = RTF_DIR
    if doc_dir is None:
        doc_dir = SOURCE_DOC_DIR
    
    if not rtf_path.exists():
        logger.error(f"RTF file not found: {rtf_path}")
        return None
    
    # Get corresponding DOC file
    doc_filename = rtf_path.stem + ".doc"
    doc_path = doc_dir / doc_filename
    
    if not doc_path.exists():
        logger.warning(f"Original DOC file not found: {doc_path}")
        # Continue anyway, SHA256 will show FILE_NOT_FOUND
    
    # Full ve_id used for output paths (archive/sources); short form for UT and BDRC idno
    short_ve_id = _short_ve_id(ve_id)
    if ut_id is None:
        ut_id = get_ut_id_from_ve(short_ve_id)
    
    logger.info(f"Converting: {rtf_path.name}")
    logger.info(f"  VE ID: {ve_id}")
    logger.info(f"  UT ID: {ut_id}")
    
    # Convert (full ve_id for TEI src_path; short for bdrc_ve idno inside)
    try:
        tei_xml = convert_rtf_to_tei(rtf_path, doc_path, ve_id, ut_id=ut_id,encoding = encoding)
    except Exception as e:
        logger.error(f"Error converting {rtf_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Create output directory (full ve_id e.g. IE8CZ266-VE8CZ88 for paths)
    archive_dir = output_dir / "archive" / ve_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    # Write XML
    xml_path = archive_dir / f"{ut_id}.xml"
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(tei_xml)
    
    logger.info(f"  Output: {xml_path}")
    
    # Copy all related source files (DOC + RTF, including splits) to output sources/{VE_ID}/
    volume_base = get_volume_base_name(rtf_path)
    copy_sources_to_volume_folder(volume_base, ve_id, output_dir, rtf_dir=rtf_dir, doc_dir=doc_dir,
                                   rtf_path=rtf_path, doc_path=doc_path if doc_path.exists() else None)
    
    return xml_path


# =============================================================================
# Debug Reporting
# =============================================================================

def _print_conversion_stats(output_dir: Path):
    """
    Print comprehensive debug information about the conversion.
    
    Outputs:
    - Fonts that were handled (successfully converted)
    - Fonts that were NOT handled (not in pytiblegenc tables)
    - Unknown characters per font with sample context
    - Writes a summary file to output directory
    """
    logger.info("")
    logger.info("=" * 60)
    logger.info("CONVERSION STATISTICS")
    logger.info("=" * 60)
    
    # 1. Handled fonts
    if STATS["handled_fonts"]:
        logger.info("")
        logger.info("HANDLED FONTS (successfully converted):")
        for font, count in sorted(STATS["handled_fonts"].items()):
            logger.info(f"  {font}: {count} characters")
    else:
        logger.info("")
        logger.info("HANDLED FONTS: None recorded")
    
    # 2. Unhandled fonts (fonts not in conversion tables)
    if STATS["unhandled_fonts"]:
        logger.info("")
        logger.info("UNHANDLED FONTS (not in pytiblegenc tables):")
        for font, count in sorted(STATS["unhandled_fonts"].items()):
            logger.info(f"  {font}: {count} characters NOT converted")
    else:
        logger.info("")
        logger.info("UNHANDLED FONTS: None (all fonts were handled)")
    
    # 3. Unknown characters per font (chars that couldn't be mapped)
    if STATS["unknown_characters"]:
        logger.info("")
        logger.info("UNKNOWN CHARACTERS BY FONT:")
        logger.info("(Characters in handled fonts that have no mapping)")
        for font, chars in sorted(STATS["unknown_characters"].items()):
            # Show up to 20 sample characters with their codes
            sample_chars = list(chars)[:20]
            char_info = []
            for c in sample_chars:
                code = ord(c) if len(c) == 1 else 'multi'
                char_info.append(f"'{c}'({code})")
            sample_str = ", ".join(char_info)
            if len(chars) > 20:
                sample_str += f", ... (+{len(chars) - 20} more)"
            logger.info(f"  {font}: {len(chars)} unknown chars")
            logger.info(f"    Samples: {sample_str}")
    else:
        logger.info("")
        logger.info("UNKNOWN CHARACTERS: None (all characters were mapped)")
    
    # 4. Skipped non-Dedris text with suspicious characters
    if "skipped_non_dedris" in STATS and STATS["skipped_non_dedris"]:
        logger.info("")
        logger.info("SKIPPED NON-DEDRIS TEXT (potential wrong font context):")
        logger.info("(ASCII chars in non-Dedris fonts that might be legacy encoding)")
        for item in STATS["skipped_non_dedris"][:20]:  # Show first 20
            logger.info(f"  Font: '{item['font']}'")
            logger.info(f"    Text: '{item['text']}'")
            logger.info(f"    ASCII chars: {', '.join(item['chars'][:10])}")
        if len(STATS["skipped_non_dedris"]) > 20:
            logger.info(f"  ... and {len(STATS['skipped_non_dedris']) - 20} more")
    
    # 5. Diffs with UTFC (for debugging pytiblegenc)
    if STATS["diffs_with_utfc"]:
        logger.info("")
        logger.info(f"DIFFS WITH UTFC: {len(STATS['diffs_with_utfc'])} differences found")
    
    # 6. Error characters count
    if STATS["error_characters"] > 0:
        logger.info("")
        logger.info(f"ERROR CHARACTERS: {STATS['error_characters']} conversion errors")
    
    logger.info("")
    logger.info("=" * 60)
    
    # Write summary file to output directory
    summary_path = output_dir / "conversion_stats.txt"
    try:
        with open(summary_path, 'w', encoding='utf-8') as f:
            f.write("CONVERSION STATISTICS\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("HANDLED FONTS:\n")
            if STATS["handled_fonts"]:
                for font, count in sorted(STATS["handled_fonts"].items()):
                    f.write(f"  {font}: {count} characters\n")
            else:
                f.write("  None recorded\n")
            
            f.write("\nUNHANDLED FONTS (not in pytiblegenc tables):\n")
            if STATS["unhandled_fonts"]:
                for font, count in sorted(STATS["unhandled_fonts"].items()):
                    f.write(f"  {font}: {count} characters NOT converted\n")
            else:
                f.write("  None (all fonts were handled)\n")
            
            f.write("\nUNKNOWN CHARACTERS BY FONT:\n")
            if STATS["unknown_characters"]:
                for font, chars in sorted(STATS["unknown_characters"].items()):
                    f.write(f"  {font}: {len(chars)} unknown characters\n")
                    # Write all unknown chars for this font
                    for c in sorted(chars, key=lambda x: ord(x) if len(x) == 1 else 0):
                        code = ord(c) if len(c) == 1 else 'multi'
                        f.write(f"    '{c}' (code {code})\n")
            else:
                f.write("  None (all characters were mapped)\n")
            
            f.write("\nSKIPPED NON-DEDRIS TEXT (potential wrong font context):\n")
            if "skipped_non_dedris" in STATS and STATS["skipped_non_dedris"]:
                for item in STATS["skipped_non_dedris"]:
                    f.write(f"  Font: '{item['font']}'\n")
                    f.write(f"    Text: '{item['text']}'\n")
                    f.write(f"    ASCII chars: {', '.join(item['chars'][:10])}\n")
            else:
                f.write("  None\n")
            
            f.write(f"\nERROR CHARACTERS: {STATS['error_characters']}\n")
            
        logger.info(f"Stats written to: {summary_path}")
    except Exception as e:
        logger.warning(f"Could not write stats file: {e}")


# =============================================================================
# Batch Conversion
# =============================================================================

def convert_all_files(output_dir: Path = None, encoding = "unicode"):
    """
    Convert all volume RTF files to TEI XML using sequential VE ID mapping.
    
    - Reads VE IDs from toprocess folder
    - Gets sorted list of volume RTF files (excluding split files)
    - Pairs them sequentially
    - Puts unmatched files in 'other/' folder
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    
    logger.info("=" * 60)
    logger.info(f"Converting all files for {IE_ID}")
    logger.info(f"RTF Source: {RTF_DIR}")
    logger.info(f"Output: {output_dir}")
    logger.info("=" * 60)
    
    # Get VE IDs from toprocess folder (if present)
    ve_ids = get_ve_ids_from_toprocess()
    
    if not ve_ids:
        # Fallback: recursively find RTF files and group by inferred volume (same as IE1PD104832)
        logger.info("No toprocess folder; discovering RTF files recursively")
        if not RTF_DIR.exists():
            logger.error(f"RTF directory not found: {RTF_DIR}")
            return
        all_rtf = find_files_recursive(RTF_DIR, {'.rtf'})
        all_rtf = [f for f in all_rtf if '_output' not in f.parts]
        if not all_rtf:
            logger.error(f"No RTF files found under {RTF_DIR}")
            return
        volumes = group_files_by_volume(all_rtf, IE_ID)
        total_files = sum(len(files) for files in volumes.values())
        logger.info(f"Found {total_files} RTF file(s) in {len(volumes)} volume(s) (recursive discovery)")
        
        archive_dir = output_dir / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "sources").mkdir(parents=True, exist_ok=True)
        success = 0
        failed = 0
        file_num = 0
        for ve_id in natsorted(volumes.keys()):
            files = natsorted(volumes[ve_id], key=lambda p: p.name)
            for idx, rtf_path in enumerate(files):
                file_num += 1
                ut_id = get_ut_id_with_index(ve_id, idx)
                pct = round(100 * file_num / total_files)
                logger.info(f"[{file_num}/{total_files}] ({pct}%) {rtf_path.name} -> {ve_id} ({ut_id})")
                result = convert_single_file(rtf_path, ve_id, output_dir, ut_id=ut_id, encoding=encoding)
                if result:
                    success += 1
                else:
                    failed += 1
        logger.info("=" * 60)
        logger.info("Conversion complete!")
        logger.info(f"  Success: {success}")
        logger.info(f"  Failed: {failed}")
        logger.info(f"  Output: {output_dir}")
        logger.info("=" * 60)
        _print_conversion_stats(output_dir)
        return
    
    # Standard path: toprocess folder present
    logger.info(f"VE IDs from: {TOPROCESS_DIR}")
    # Collect RTF files from toprocess subfolders (IE_ID-VExxx/ or VExxx/)
    ve_id_to_files = get_volume_rtf_files_from_toprocess(ve_ids)
    total_files = sum(len(files) for _, files in ve_id_to_files)
    if total_files == 0:
        # Fallback: flat list from RTF_DIR (KAMA-style top-level *.rtf)
        volume_files = get_volume_rtf_files()
        if not volume_files:
            logger.error("No volume RTF files found")
            return
        ve_id_to_files = [(ve_ids[i], [volume_files[i]]) for i in range(min(len(ve_ids), len(volume_files)))]
        total_files = len(volume_files)
        volume_files_for_other = volume_files
        from_toprocess = False
    else:
        logger.info(f"Found {len(ve_ids)} VE IDs (from toprocess)")
        logger.info(f"Found {total_files} volume RTF files")
        volume_files_for_other = [p for _, files in ve_id_to_files for p in files]
        from_toprocess = True
    
    archive_dir = output_dir / "archive"
    sources_dir = output_dir / "sources"
    other_dir = output_dir / "other"
    
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = 0
    other_count = 0
    
    file_num = 0
    for ve_id, files in ve_id_to_files:
        for file_index, rtf_path in enumerate(files):
            file_num += 1
            ut_id = get_ut_id_with_index(_short_ve_id(ve_id), file_index)
            pct = round(100 * file_num / total_files)
            logger.info(f"[{file_num}/{total_files}] ({pct}%) {rtf_path.name} -> {ve_id} ({ut_id})")
            result = convert_single_file(rtf_path, ve_id, output_dir, ut_id=ut_id,encoding = encoding)
            if result:
                success += 1
            else:
                failed += 1
    
    # Only create "other" for unmatched files when using fallback (flat RTF_DIR).
    # When from toprocess, all sources stay in sources/ per volume; no "other".
    if not from_toprocess and len(volume_files_for_other) > len(ve_ids):
        other_dir.mkdir(parents=True, exist_ok=True)
        extra_files = volume_files_for_other[len(ve_ids):]
        logger.info(f"Copying {len(extra_files)} unmatched RTF files to 'other/'")
        
        for rtf_path in extra_files:
            dest = other_dir / rtf_path.name
            shutil.copy2(rtf_path, dest)
            logger.info(f"  Copied to other/: {rtf_path.name}")
            other_count += 1
    
    if len(ve_ids) > len(volume_files_for_other):
        extra_ve_ids = ve_ids[len(volume_files_for_other):]
        logger.warning(f"{len(extra_ve_ids)} VE IDs have no matching RTF file:")
        for ve_id in extra_ve_ids[:10]:
            logger.warning(f"  {ve_id}")
        if len(extra_ve_ids) > 10:
            logger.warning(f"  ... and {len(extra_ve_ids) - 10} more")
    
    logger.info("=" * 60)
    logger.info("Conversion complete!")
    logger.info(f"  Success: {success}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Other (unmatched): {other_count}")
    logger.info(f"  Output: {output_dir}")
    logger.info("=" * 60)
    
    _print_conversion_stats(output_dir)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    global IE_ID, RTF_DIR, TOPROCESS_DIR, OUTPUT_DIR, SOURCE_DOC_DIR
    parser = argparse.ArgumentParser(
        description="Convert IE1PD100944 RTF files to TEI XML"
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--test-first", "-t",
        action="store_true",
        help="Find RTF files recursively, convert only the first one (no filename needed). Requires --ie-id or --rtf-dir."
    )
    group.add_argument(
        "--single", "-s",
        metavar="FILENAME",
        help="Convert a single RTF file by name (e.g., KAMA-001.rtf) - uses first VE ID for testing"
    )
    group.add_argument(
        "--all", "-a",
        action="store_true",
        help="Convert all volume RTF files using sequential VE ID mapping"
    )
    
    parser.add_argument(
        "--ie-id",
        metavar="ID",
        help="Collection ID (e.g. IE1KG4884). Sets RTF dir to rtf/{ID} under repo root. Use with --test-first, --single, or --all."
    )
    parser.add_argument(
        "--output", "-o",
        metavar="DIR",
        help=f"Output directory (default: {OUTPUT_DIR})"
    )
    parser.add_argument(
        "--rtf-dir",
        metavar="DIR",
        help="RTF folder path (required for --test-first if --ie-id not set). E.g. ../rtf/IE1KG4884. Overrides --ie-id when both given."
    )

    parser.add_argument(
        "--encoding",
        choices=["unicode", "dedris"],
        default="unicode",
        help="RTF encoding: unicode (default, skip Dedris conversion) or dedris (convert with pytiblegenc)"
    )
    
    args = parser.parse_args()
    
    # Apply --ie-id: set IE_ID and paths from rtf/{ie_id} under repo root
    if args.ie_id:
        base = script_dir.parent
        IE_ID = args.ie_id
        RTF_DIR = base / "rtf" / args.ie_id
        TOPROCESS_DIR = RTF_DIR / "toprocess"
        OUTPUT_DIR = RTF_DIR / f"{args.ie_id}_output"
        SOURCE_DOC_DIR = RTF_DIR
        logger.info(f"Using --ie-id {args.ie_id}: RTF_DIR={RTF_DIR}")
    
    output_dir = Path(args.output) if args.output else OUTPUT_DIR
    rtf_dir = Path(args.rtf_dir) if args.rtf_dir else RTF_DIR
    
    if args.test_first:
        # --test-first requires the RTF folder via --ie-id or --rtf-dir
        if not args.rtf_dir and not args.ie_id:
            logger.error("--test-first requires --ie-id (e.g. IE1KG4884) or --rtf-dir (e.g. ../rtf/IE1KG4884)")
            return
        # Recursively find RTF files, convert only the first one (no filename needed)
        if not rtf_dir.exists():
            logger.error(f"RTF directory not found: {rtf_dir}")
            return
        all_rtf = find_files_recursive(rtf_dir, {'.rtf'})
        # Exclude files inside output directories
        all_rtf = [f for f in all_rtf if '_output' not in f.parts]
        if not all_rtf:
            logger.error(f"No RTF files found under {rtf_dir}")
            return
        all_rtf = natsorted(all_rtf, key=lambda p: (p.parent.name, p.name))
        rtf_path = all_rtf[0]
        logger.info(f"Found {len(all_rtf)} RTF file(s) recursively; converting first: {rtf_path.relative_to(rtf_dir)}")
        
        ve_ids = get_ve_ids_from_toprocess()
        if ve_ids:
            ve_id = ve_ids[0]
            logger.info(f"NOTE: Using first VE ID ({ve_id}) for single file test")
        else:
            ve_id = f"VE{IE_ID[2:]}_0001"
            logger.info(f"NOTE: No toprocess folder; using default VE ID {ve_id} for single file test")
        
        convert_single_file(rtf_path, ve_id, output_dir, rtf_dir=rtf_dir, encoding=args.encoding)
    elif args.single:
        # Resolve single file: allow path or filename under rtf_dir
        single_path = Path(args.single)
        if single_path.is_absolute():
            rtf_path = single_path
        else:
            rtf_path = rtf_dir / args.single
        if not rtf_path.exists():
            logger.error(f"RTF file not found: {rtf_path}")
            return
        
        ve_ids = get_ve_ids_from_toprocess()
        if ve_ids:
            ve_id = ve_ids[0]
            logger.info(f"NOTE: Using first VE ID ({ve_id}) for single file test")
        else:
            ve_id = f"VE{IE_ID[2:]}_0001"
            logger.info(f"NOTE: No toprocess folder; using default VE ID {ve_id} for single file test")
        
        # Pass custom rtf_dir so source lookups use it when testing
        convert_single_file(rtf_path, ve_id, output_dir, rtf_dir=rtf_dir if args.rtf_dir else None, encoding = args.encoding)
    else:
        convert_all_files(output_dir, encoding = args.encoding)


if __name__ == "__main__":
    main()