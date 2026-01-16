#!/usr/bin/env python3
"""
Convert RTF files from IE1PD100944 (KAMA Collection) to TEI XML format.

This script converts RTF files with Dedris legacy encoding to Unicode TEI XML.

Pipeline:
1. Parse RTF using basic_rtf parser (extracts text with font info)
2. Convert Dedris encoding to Unicode using pytiblegenc
3. Normalize Unicode (Tibetan-specific normalization)
4. Classify font sizes (regular/small/large)
5. Generate TEI XML with proper structure

Usage:
    # Convert a single file:
    python convert.py --single KAMA-001.rtf
    
    # Convert all files:
    python convert.py --all
"""

import sys
import os
import re
import hashlib
import shutil
import argparse
import logging
from pathlib import Path
from collections import Counter
from natsort import natsorted

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

# Paths - adjust these as needed
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
SOURCE_DOC_DIR = BASE_DIR / "IE1PD100944" / "sources"
RTF_DIR = BASE_DIR / "IE1PD100944_rtf"
TOPROCESS_DIR = BASE_DIR / "IE1PD100944" / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE1PD100944_output"

# Global stats for pytiblegenc
STATS = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0
}


# =============================================================================
# VE/UT ID Functions (from toprocess folder)
# =============================================================================

def get_ve_ids_from_toprocess(toprocess_path: Path = None) -> list:
    """
    Get sorted VE IDs from toprocess folder.
    
    Reads folder names like 'IE1PD100944-VE3KG466' and extracts 'VE3KG466'.
    
    Returns:
        List of VE IDs sorted naturally (e.g., ['VE3KG466', 'VE3KG467', ...])
    """
    if toprocess_path is None:
        toprocess_path = TOPROCESS_DIR
    
    logger.info(f"Looking for VE IDs in: {toprocess_path}")
    
    if not toprocess_path.exists():
        logger.warning(f"toprocess folder not found at {toprocess_path}")
        return []
    
    ve_ids = []
    for folder in toprocess_path.iterdir():
        if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
            ve_id = folder.name.replace(f'{IE_ID}-', '')  # "VE3KG466"
            ve_ids.append(ve_id)
    
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
    
    # Find RTF files
    if rtf_dir.exists():
        for rtf_file in rtf_dir.glob(f"{volume_base}*.rtf"):
            # Make sure it's an exact base match (not a different volume number)
            # e.g., KAMA-001 should match KAMA-001-a but not KAMA-0010
            name_without_ext = rtf_file.stem
            if name_without_ext == volume_base or name_without_ext.startswith(f"{volume_base}-"):
                related_files.append(rtf_file)
    
    # Find DOC files
    if doc_dir.exists():
        for doc_file in doc_dir.glob(f"{volume_base}*.doc"):
            name_without_ext = doc_file.stem
            if name_without_ext == volume_base or name_without_ext.startswith(f"{volume_base}-"):
                related_files.append(doc_file)
    
    return natsorted(related_files, key=lambda p: p.name)


def copy_sources_to_volume_folder(volume_base: str, ve_id: str, output_dir: Path = None,
                                   rtf_dir: Path = None, doc_dir: Path = None) -> int:
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
    
    # Find all related files
    related_files = find_all_related_source_files(volume_base, rtf_dir, doc_dir)
    
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
    
    # Skip non-Dedris fonts (e.g., Times New Roman, Arial)
    # These fonts don't have Tibetan character mappings
    if not font_name or not font_name.lower().startswith(('dedris', 'ededris')):
        # Log non-Dedris text that contains potential Dedris characters
        # (ASCII chars that might be legacy encoding in wrong font context)
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
    
    try:
        # DEBUG: Check if text contains brace characters BEFORE conversion
        if '}' in text or '{' in text:
            has_brace_before = True
            brace_chars_before = [(c, ord(c)) for c in text if c in '{}']
        else:
            has_brace_before = False
        
        # Pass exact font name extracted from RTF - no fallback
        result = convert_string(text, font_name, STATS)
        if result is None:
            # Font not in conversion tables
            preview = text[:50].replace('\n', '\\n')
            logger.warning(f"UNHANDLED FONT: '{font_name}' | text: '{preview}'")
            return text
        
        # DEBUG: Check if braces remain AFTER conversion (should be converted to Tibetan)
        if has_brace_before and ('}' in result or '{' in result):
            preview_in = text[:30].replace('\n', '\\n')
            preview_out = result[:30].replace('\n', '\\n')
            logger.warning(f"BRACE NOT CONVERTED: font='{font_name}' | in='{preview_in}' | out='{preview_out}'")
        
        return result
    except Exception as e:
        logger.warning(f"Error converting with font {font_name}: {e}")
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


def convert_rtf_to_tei(rtf_path: Path, doc_path: Path, ve_id: str) -> str:
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
        
    Returns:
        TEI XML string
    """
    # =========================================================================
    # STAGE 1: Parse RTF and Convert to Unicode
    # =========================================================================
    logger.info(f"Parsing RTF file: {rtf_path.name}")
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    logger.info(f"Parsed {len(streams)} text streams")
    
    # DEBUG: Log streams containing brace characters (} or {)
    # These are important for Dedris fonts where } = སྔ (char 125)
    brace_count = 0
    for stream in streams:
        text = stream.get("text", "")
        font_name = stream.get("font", {}).get("name", "")
        if '}' in text or '{' in text:
            brace_count += 1
            # Only log first 10 to avoid spam
            if brace_count <= 10:
                preview = text[:80].replace('\n', '\\n')
                logger.info(f"DEBUG BRACE: font='{font_name}', text='{preview}...'")
    if brace_count > 0:
        logger.info(f"DEBUG: Found {brace_count} streams with brace characters")
    
    # Convert all Dedris to Unicode
    converted_streams = []
    for stream in streams:
        # Skip special types (headers, footers, etc.)
        if stream.get("type") in ("header", "footer", "pict"):
            continue
        
        text = stream.get("text", "")
        font_name = stream.get("font", {}).get("name", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        # Convert Dedris to Unicode
        unicode_text = dedris_to_unicode(text, font_name)
        
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
    
    # Clean up empty hi tags
    if ENABLE_FONT_CLASSIFICATION:
        body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    # =========================================================================
    # STAGE 3: Normalization (optional)
    # =========================================================================
    if ENABLE_NORMALIZATION:
        logger.info(f"  Stage 3: Applying normalization...")
        
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
    # GENERATE TEI XML
    # =========================================================================
    ut_id = get_ut_id_from_ve(ve_id)
    sha256 = calculate_sha256(doc_path)
    src_path = f"sources/{ve_id}/{doc_path.name}"
    
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
<idno type="src_sha256">{sha256}</idno>
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{IE_ID}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
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

def convert_single_file(rtf_path: Path, ve_id: str, output_dir: Path = None):
    """
    Convert a single RTF file to TEI XML.
    
    Args:
        rtf_path: Path to the RTF file
        ve_id: Volume Entity ID (e.g., "VE3KG466")
        output_dir: Output directory (default: OUTPUT_DIR)
        
    Returns:
        Path to the generated XML file, or None if failed
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    
    if not rtf_path.exists():
        logger.error(f"RTF file not found: {rtf_path}")
        return None
    
    # Get corresponding DOC file
    doc_filename = rtf_path.stem + ".doc"
    doc_path = SOURCE_DOC_DIR / doc_filename
    
    if not doc_path.exists():
        logger.warning(f"Original DOC file not found: {doc_path}")
        # Continue anyway, SHA256 will show FILE_NOT_FOUND
    
    # Generate UT ID
    ut_id = get_ut_id_from_ve(ve_id)
    
    logger.info(f"Converting: {rtf_path.name}")
    logger.info(f"  VE ID: {ve_id}")
    logger.info(f"  UT ID: {ut_id}")
    
    # Convert
    try:
        tei_xml = convert_rtf_to_tei(rtf_path, doc_path, ve_id)
    except Exception as e:
        logger.error(f"Error converting {rtf_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return None
    
    # Create output directory
    archive_dir = output_dir / "archive" / ve_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    # Write XML
    xml_path = archive_dir / f"{ut_id}.xml"
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(tei_xml)
    
    logger.info(f"  Output: {xml_path}")
    
    # Copy all related source files (DOC + RTF, including splits) to sources/{VE_ID}/
    volume_base = get_volume_base_name(rtf_path)
    copy_sources_to_volume_folder(volume_base, ve_id, output_dir)
    
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

def convert_all_files(output_dir: Path = None):
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
    logger.info(f"VE IDs from: {TOPROCESS_DIR}")
    logger.info(f"Output: {output_dir}")
    logger.info("=" * 60)
    
    # Get VE IDs from toprocess folder
    ve_ids = get_ve_ids_from_toprocess()
    if not ve_ids:
        logger.error("No VE IDs found in toprocess folder")
        return
    
    # Get volume RTF files (excluding split files)
    volume_files = get_volume_rtf_files()
    if not volume_files:
        logger.error("No volume RTF files found")
        return
    
    logger.info(f"Found {len(ve_ids)} VE IDs (from toprocess)")
    logger.info(f"Found {len(volume_files)} volume RTF files")
    
    if len(ve_ids) != len(volume_files):
        logger.warning(f"Count mismatch! VE IDs: {len(ve_ids)}, RTF files: {len(volume_files)}")
    
    # Create output directories
    archive_dir = output_dir / "archive"
    sources_dir = output_dir / "sources"
    other_dir = output_dir / "other"
    
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = 0
    other_count = 0
    
    # Process matched pairs
    num_pairs = min(len(ve_ids), len(volume_files))
    
    for idx in range(num_pairs):
        ve_id = ve_ids[idx]
        rtf_path = volume_files[idx]
        
        logger.info(f"[{idx + 1}/{num_pairs}] {rtf_path.name} -> {ve_id}")
        
        result = convert_single_file(rtf_path, ve_id, output_dir)
        if result:
            success += 1
        else:
            failed += 1
    
    # Handle extra RTF files (more RTFs than VE IDs)
    if len(volume_files) > len(ve_ids):
        other_dir.mkdir(parents=True, exist_ok=True)
        extra_files = volume_files[len(ve_ids):]
        logger.info(f"Copying {len(extra_files)} unmatched RTF files to 'other/'")
        
        for rtf_path in extra_files:
            dest = other_dir / rtf_path.name
            shutil.copy2(rtf_path, dest)
            logger.info(f"  Copied to other/: {rtf_path.name}")
            other_count += 1
    
    # Warn about extra VE IDs
    if len(ve_ids) > len(volume_files):
        extra_ve_ids = ve_ids[len(volume_files):]
        logger.warning(f"{len(extra_ve_ids)} VE IDs have no matching RTF file:")
        for ve_id in extra_ve_ids[:10]:  # Show first 10
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
    
    # Enhanced debug reporting
    _print_conversion_stats(output_dir)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert IE1PD100944 RTF files to TEI XML"
    )
    
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--single", "-s",
        metavar="FILENAME",
        help="Convert a single RTF file (e.g., KAMA-001.rtf) - uses first VE ID for testing"
    )
    group.add_argument(
        "--all", "-a",
        action="store_true",
        help="Convert all volume RTF files using sequential VE ID mapping"
    )
    
    parser.add_argument(
        "--output", "-o",
        metavar="DIR",
        help=f"Output directory (default: {OUTPUT_DIR})"
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.output) if args.output else OUTPUT_DIR
    
    if args.single:
        # For single file testing, get the first VE ID
        ve_ids = get_ve_ids_from_toprocess()
        if not ve_ids:
            logger.error("No VE IDs found in toprocess folder")
            return
        
        rtf_path = RTF_DIR / args.single
        if not rtf_path.exists():
            logger.error(f"RTF file not found: {rtf_path}")
            return
        
        # Use first VE ID for testing
        logger.info(f"NOTE: Using first VE ID ({ve_ids[0]}) for single file test")
        convert_single_file(rtf_path, ve_ids[0], output_dir)
    else:
        convert_all_files(output_dir)


if __name__ == "__main__":
    # Set DEBUG_MODE = True to test a single file, False to run all files
    DEBUG_MODE = False
    DEBUG_FILE = "KAMA-001.rtf"
    
    if DEBUG_MODE:
        logger.info("=== DEBUG MODE ===")
        logger.info(f"Testing with: {DEBUG_FILE}")
        
        # Get VE IDs and RTF files
        ve_ids = get_ve_ids_from_toprocess()
        rtf_files = get_volume_rtf_files()
        
        if not ve_ids:
            logger.error("No VE IDs found")
        elif not rtf_files:
            logger.error("No volume RTF files found")
        else:
            # Find the RTF file in the list
            rtf_path = RTF_DIR / DEBUG_FILE
            if rtf_path in rtf_files:
                idx = rtf_files.index(rtf_path)
                ve_id = ve_ids[idx] if idx < len(ve_ids) else ve_ids[0]
                logger.info(f"RTF file index: {idx}")
                logger.info(f"Assigned VE ID: {ve_id}")
                convert_single_file(rtf_path, ve_id, OUTPUT_DIR)
            else:
                logger.warning(f"{DEBUG_FILE} not in volume files list, using first VE ID")
                convert_single_file(rtf_path, ve_ids[0], OUTPUT_DIR)
    else:
        # Run batch conversion for all files
        logger.info("=== BATCH MODE - Converting all volume files ===")
        convert_all_files(OUTPUT_DIR)