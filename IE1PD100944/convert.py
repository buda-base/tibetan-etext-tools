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
from normalization import normalize_unicode

# Import char_converter directly to avoid pdfminer dependency issues in pytiblegenc.__init__
# This imports the convert_string function without going through __init__.py
import importlib.util
import site

def _import_char_converter():
    """Import char_converter module directly."""
    search_paths = []
    try:
        search_paths.extend(site.getsitepackages())
    except AttributeError:
        pass
    try:
        user_site = site.getusersitepackages()
        if user_site:
            search_paths.append(user_site)
    except AttributeError:
        pass
    
    for site_dir in search_paths:
        if site_dir is None:
            continue
        char_converter_path = Path(site_dir) / "pytiblegenc" / "char_converter.py"
        if char_converter_path.exists():
            spec = importlib.util.spec_from_file_location("pytiblegenc_char_converter", str(char_converter_path))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module.convert_string
    
    raise ImportError("pytiblegenc.char_converter not found. Install with: pip install git+https://github.com/buda-base/py-tiblegenc.git")

logger.info("Loading pytiblegenc char_converter...")
convert_string = _import_char_converter()
logger.info("char_converter loaded successfully")

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
    Check if this is a volume file (not a split part).
    
    Volume files (return True):
        - KAMA-001.rtf (basic volume)
        - KAMA-040-1.rtf (volume with integer suffix)
        - KAMA-132-1.rtf (volume with integer suffix)
    
    Split files (return False):
        - KAMA-001-a.rtf (letter suffix = split)
        - KAMA-001-b.rtf (letter suffix = split)
        - KAMA-001-a-1.rtf (has letter in suffix = split)
    
    Logic: If filename contains any '-[a-zA-Z]' pattern, it's a split file.
    """
    # Exclude if contains any letter suffix pattern (like -a, -b, -a-1, etc.)
    if re.search(r'-[a-zA-Z]', filename):
        return False
    return True


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


# =============================================================================
# Dedris to Unicode Conversion
# =============================================================================

def dedris_to_unicode(text: str, font_name: str) -> str:
    """
    Convert Dedris encoded string to Unicode using pytiblegenc.
    
    Args:
        text: Text in Dedris encoding
        font_name: Font name from RTF (e.g., "Dedris", "Ededris-sym")
        
    Returns:
        Unicode text
    """
    if not text or not text.strip():
        return text
    
    if not font_name:
        font_name = "Ededris"  # Default fallback
    
    try:
        result = convert_string(text, font_name, STATS)
        if result is None:
            # Font not in conversion tables, try with default Ededris
            result = convert_string(text, "Ededris", STATS)
        return result if result is not None else text
    except Exception as e:
        logger.warning(f"Error converting with font {font_name}: {e}")
        return text


# =============================================================================
# Font Size Classification
# =============================================================================

def classify_font_sizes(converted_streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    
    Uses frequency analysis: the font size with the most Tibetan characters
    is classified as 'regular' (body text). Larger sizes are 'large' (headings),
    smaller sizes are 'small' (annotations/notes).
    
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
    
    sizes = sorted(size_counts.keys())
    total_chars = sum(size_counts.values())
    
    # Find the most common font size by Tibetan character count - this is the body text
    most_common = max(size_counts.items(), key=lambda x: x[1])[0]
    
    # Log the distribution for debugging
    logger.info(f"  Font size distribution (Tibetan chars): {dict(size_counts)}")
    logger.info(f"  Most common size (body text): {most_common}pt with {size_counts[most_common]} chars ({100*size_counts[most_common]/total_chars:.1f}%)")
    
    classifications = {}
    for fs in sizes:
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


def convert_rtf_to_tei(rtf_path: Path, doc_path: Path, ve_id: str) -> str:
    """
    Convert RTF file to TEI XML.
    
    Args:
        rtf_path: Path to RTF file
        doc_path: Path to original DOC file (for SHA256 and reference)
        ve_id: Volume Entity ID (e.g., "VE3KG466")
        
    Returns:
        TEI XML string
    """
    # Parse RTF
    logger.info(f"Parsing RTF file: {rtf_path.name}")
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    logger.info(f"Parsed {len(streams)} text streams")
    
    # STEP 1: Convert all Dedris to Unicode first
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
        
        # Normalize
        normalized_text = normalize_unicode(unicode_text)
        
        if not normalized_text.strip():
            continue
        
        converted_streams.append({
            "text": normalized_text,
            "font_size": font_size
        })
    
    # STEP 2: Classify font sizes based on Unicode text
    classifications = classify_font_sizes(converted_streams)
    if classifications:
        logger.info(f"Font size classifications: {classifications}")
    
    # STEP 3: Build TEI content
    tei_lines = []
    current_markup = None  # 'small', 'large', or None
    
    for item in converted_streams:
        normalized_text = item["text"]
        font_size = item["font_size"]
        
        # Escape XML
        escaped_text = escape_xml(normalized_text)
        
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
        
        # Add text content (keep newlines as-is for non-paginated format)
        tei_lines.append(escaped_text)
    
    # Close any open markup
    if current_markup == 'small':
        tei_lines.append('</hi>')
    elif current_markup == 'large':
        tei_lines.append('</hi>')
    
    # Build body content - join with no separator (text already has newlines)
    body_content = ''.join(tei_lines)
    
    # Clean up: remove empty hi tags
    body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    # Clean up: normalize multiple newlines
    body_content = re.sub(r'\n\n+', '\n', body_content)
    body_content = body_content.strip()
    
    # Generate UT ID from VE ID
    ut_id = get_ut_id_from_ve(ve_id)
    
    # Calculate SHA256 of original DOC file
    sha256 = calculate_sha256(doc_path)
    
    # Source path (reference to original .doc)
    src_path = f"sources/{doc_path.name}"
    
    # Build TEI XML
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
    
    # Copy RTF to sources
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    dest_rtf = sources_dir / rtf_path.name
    shutil.copy2(rtf_path, dest_rtf)
    logger.info(f"  Copied RTF to: {dest_rtf}")
    
    return xml_path


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
    
    # Print stats
    if STATS["unhandled_fonts"]:
        logger.info(f"Unhandled fonts: {STATS['unhandled_fonts']}")
    if STATS["unknown_characters"]:
        logger.info("Unknown characters by font:")
        for font, chars in STATS["unknown_characters"].items():
            logger.info(f"  {font}: {len(chars)} unknown chars")


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
