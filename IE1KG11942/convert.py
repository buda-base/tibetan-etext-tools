#!/usr/bin/env python3
"""
Convert RTF files from IE1KG11942 to TEI XML format.

This script converts RTF files that already contain Unicode to TEI XML format.
No Dedris conversion is needed - just RTF parsing and normalization.

Key features:
- RTF files already contain Unicode (RTF unicode escape sequences)
- Multiple files per volume (each gets sequential UT ID)
- VE ID extracted from folder name

Pipeline:
1. Parse RTF using basic_rtf parser
2. Extract Unicode from RTF Unicode escape sequences (already Unicode, no font conversion)
3. Normalize Unicode (Tibetan-specific normalization)
4. Generate TEI XML with proper structure

Input structure:
    toprocess/IE1KG11942-VE1KG11942_001/NGAL000.rtf
    toprocess/IE1KG11942-VE1KG11942_001/NGAL001_xxx.rtf
    ...

Output structure:
    IE1KG11942_OUTPUT/archive/VE1KG11942_001/UT1KG11942_001_0001.xml
    IE1KG11942_OUTPUT/archive/VE1KG11942_001/UT1KG11942_001_0002.xml
    IE1KG11942_OUTPUT/sources/VE1KG11942_001/NGAL000.rtf
    ...

Usage:
    # Convert all files:
    python convert.py
    
    # Debug mode (single volume):
    Set DEBUG_MODE = True and DEBUG_VOLUME in the script
"""

import sys
import os
import re
import hashlib
import shutil
import logging
from pathlib import Path
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

# Add script directory to path (use local copies of basic_rtf and normalization)
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from collections import Counter
from basic_rtf import BasicRTF
from normalization import normalize_unicode

# =============================================================================
# Configuration
# =============================================================================

IE_ID = "IE1KG11942"

# Paths
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1KG11942")
TOPROCESS_DIR = BASE_DIR / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE1KG11942_OUTPUT"


# =============================================================================
# VE/UT ID Functions
# =============================================================================

def get_volume_folders() -> list:
    """
    Get list of volume folders from toprocess directory.
    
    Each folder is named like: IE1KG11942-VE1KG11942_001
    
    Returns:
        List of (ve_id, folder_path) tuples, naturally sorted by VE ID
    """
    logger.info(f"Looking for volume folders in: {TOPROCESS_DIR}")
    
    if not TOPROCESS_DIR.exists():
        logger.error(f"toprocess folder not found at {TOPROCESS_DIR}")
        return []
    
    volumes = []
    for folder in TOPROCESS_DIR.iterdir():
        if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
            ve_id = folder.name.replace(f'{IE_ID}-', '')  # "VE1KG11942_001"
            volumes.append((ve_id, folder))
    
    # Sort naturally by VE ID
    result = natsorted(volumes, key=lambda x: x[0])
    logger.info(f"Found {len(result)} volume folders")
    return result


def get_rtf_files_in_volume(volume_folder: Path) -> list:
    """
    Get sorted list of RTF files in a volume folder.
    
    Returns:
        List of Path objects for RTF files, naturally sorted
    """
    rtf_files = list(volume_folder.glob("*.rtf"))
    return natsorted(rtf_files, key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int) -> str:
    """
    Generate UT ID from VE ID and file index.
    
    VE1KG11942_001, index 0 -> UT1KG11942_001_0001
    VE1KG11942_001, index 1 -> UT1KG11942_001_0002
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix -> "1KG11942_001"
    return f"UT{ve_suffix}_{file_index + 1:04d}"


# =============================================================================
# Font Size Classification
# =============================================================================

def classify_font_sizes(streams: list) -> dict:
    """
    Classify font sizes into head, regular, and small categories.
    
    Uses frequency analysis: most common size (by Tibetan character count) is 'regular',
    larger sizes are 'head', smaller sizes are 'small'.
    
    Args:
        streams: List of stream dicts from BasicRTF parser
        
    Returns:
        dict: Mapping of font_size -> classification ('head', 'regular', 'small')
    """
    # Count Tibetan characters for each font size
    size_counts = Counter()
    
    for stream in streams:
        text = stream.get("text", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        # Count Tibetan characters (U+0F00-U+0FFF)
        tibetan_chars = len([c for c in text if 0x0F00 <= ord(c) <= 0x0FFF])
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    
    if not size_counts:
        return {}
    
    # Find the most common font size by character count (this is 'regular')
    most_common = max(size_counts.items(), key=lambda x: x[1])[0]
    
    classifications = {}
    
    for font_size in size_counts.keys():
        if font_size == most_common:
            classifications[font_size] = 'regular'
        elif font_size > most_common:
            classifications[font_size] = 'head'
        else:
            classifications[font_size] = 'small'
    
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


def clean_rtf_fallback_chars(text: str) -> str:
    """
    Remove RTF Unicode fallback characters.
    
    RTF uses a format where a fallback character follows Unicode escapes.
    The BasicRTF parser decodes the Unicode but may keep the fallback character.
    This function removes lone ASCII characters that appear before Tibetan text.
    """
    # Remove single ASCII characters (often 'd', '?', etc.) that appear 
    # before Tibetan Unicode characters (U+0F00-U+0FFF)
    # Pattern: single ASCII char followed by Tibetan
    tibetan_range = '[\u0F00-\u0FFF]'
    text = re.sub(r'^([a-zA-Z?])(' + tibetan_range + ')', r'\2', text)
    text = re.sub(r'\n([a-zA-Z?])(' + tibetan_range + ')', r'\n\2', text)
    text = re.sub(r'\n([a-zA-Z?]) (' + tibetan_range + ')', r'\n\2', text)
    text = re.sub(r'\n([a-zA-Z?])$', r'\n', text)  # lone char at end of line
    text = re.sub(r'^([a-zA-Z?])$', '', text, flags=re.MULTILINE)  # lone char lines
    text = re.sub(r'^([a-zA-Z?]) ', '', text, flags=re.MULTILINE)  # char + space at start
    return text


def is_primarily_tibetan(text: str) -> bool:
    """
    Check if text is primarily Tibetan (not English/Latin).
    
    Returns True if the text contains Tibetan characters and is primarily Tibetan,
    False if it's primarily English/Latin text.
    """
    if not text.strip():
        return False
    
    # Count character types
    tibetan_count = 0
    latin_count = 0
    
    for char in text:
        code = ord(char)
        # Tibetan range: U+0F00-U+0FFF
        if 0x0F00 <= code <= 0x0FFF:
            tibetan_count += 1
        # Latin letters (A-Z, a-z)
        elif (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
            latin_count += 1
    
    # If no Tibetan characters, it's not Tibetan content
    if tibetan_count == 0:
        return False
    
    # If primarily Latin letters (more than Tibetan), filter it out
    if latin_count > tibetan_count:
        return False
    
    return True


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


def convert_rtf_to_tei(rtf_path: Path, ve_id: str, ut_id: str, src_path: str) -> str:
    """
    Convert RTF file to TEI XML.
    
    The RTF files already contain Unicode text,
    so we just need to parse and normalize - no Dedris conversion needed.
    
    Args:
        rtf_path: Path to RTF file
        ve_id: Volume Entity ID (e.g., "VE1KG11942_001")
        ut_id: Unit Text ID (e.g., "UT1KG11942_001_0001")
        src_path: Source path for XML header (e.g., "sources/VE1KG11942_001/NGAL000.rtf")
        
    Returns:
        TEI XML string
    """
    # Parse RTF
    logger.info(f"  Parsing RTF file: {rtf_path.name}")
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    logger.info(f"  Parsed {len(streams)} text streams")
    
    # Classify font sizes
    classifications = classify_font_sizes(streams)
    if classifications:
        logger.info(f"  Font size classifications: {classifications}")
    
    # Process streams and build content
    # The RTF parser already decodes \uNNNN? sequences to actual Unicode
    tei_lines = []
    current_markup = None  # 'small', 'head', or None
    
    for stream in streams:
        text = stream.get("text", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        # Skip special types (headers, footers, etc.)
        if stream.get("type") in ("header", "footer", "pict"):
            continue
        
        # The text is already Unicode from the RTF parser
        # Clean up RTF fallback characters and normalize
        cleaned_text = clean_rtf_fallback_chars(text)
        normalized_text = normalize_unicode(cleaned_text)
        
        if not normalized_text.strip():
            continue
        
        # Filter out text that is primarily English/Latin (not Tibetan)
        if not is_primarily_tibetan(normalized_text):
            continue
        
        # Escape XML
        escaped_text = escape_xml(normalized_text)
        
        # Determine markup based on font size
        classification = classifications.get(font_size, 'regular')
        
        # Handle markup transitions
        if classification != current_markup:
            # Close previous markup
            if current_markup == 'small':
                tei_lines.append('</hi>')
            elif current_markup == 'head':
                tei_lines.append('</hi>')
            
            # Open new markup
            if classification == 'small':
                tei_lines.append('<hi rend="small">')
            elif classification == 'head':
                tei_lines.append('<hi rend="head">')
            
            current_markup = classification if classification != 'regular' else None
        
        # Add text content (keep newlines as-is for non-paginated format)
        tei_lines.append(escaped_text)
    
    # Close any open markup
    if current_markup == 'small':
        tei_lines.append('</hi>')
    elif current_markup == 'head':
        tei_lines.append('</hi>')
    
    # Build body content - join with no separator (text already has newlines)
    body_content = ''.join(tei_lines)
    
    # Clean up: remove empty hi tags
    body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    # Clean up: remove RTF page field codes (PAGE * MERGEFORMAT N)
    body_content = re.sub(r'PAGE \* MERGEFORMAT \d+\s*', '', body_content)
    
    # Clean up: normalize multiple newlines to single
    body_content = re.sub(r'\n\n+', '\n', body_content)
    
    # Convert newlines (from RTF \par) to <lb/> elements
    # Put <lb/> at beginning of next line and remove surrounding spaces
    body_content = body_content.replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '\n<lb/>', body_content)
    body_content = body_content.strip()
    
    # Clean up: remove <lb/> tags that appear right before </hi> (move </hi> before the <lb/>)
    body_content = re.sub(r'(<lb/>[\s\n]*)+</hi>', r'</hi>', body_content)
    
    # Clean up: move </hi> that appears at start of a line to end of previous line (remove the newline before it)
    body_content = re.sub(r'\n\s*(</hi>)', r'\1', body_content)
    
    # Clean up: move <hi> opening tags from end of line to start of next line with <lb/>
    body_content = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r'\n<lb/>\1', body_content)
    
    # Clean up: remove empty lb lines (lines with only <lb/> and whitespace)
    body_content = re.sub(r'\n<lb/>\s*\n', '\n', body_content)
    body_content = re.sub(r'(<lb/>)\s*(<lb/>)', r'\1', body_content)
    
    # Clean up: remove trailing <lb/> before </p>
    body_content = re.sub(r'\n<lb/>\s*$', '', body_content)
    
    # Ensure <p> and <lb/> are not on the same line - if body starts with <lb/>, add newline before it
    if body_content.startswith('<lb/>'):
        body_content = '\n' + body_content
    
    # Calculate SHA256 of RTF file (the source)
    sha256 = calculate_sha256(rtf_path)
    
    # Build TEI XML (minimal non-paginated format)
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


# =============================================================================
# Conversion Functions
# =============================================================================

def convert_volume(ve_id: str, volume_folder: Path, output_dir: Path):
    """
    Convert all RTF files in a volume folder to TEI XML.
    
    Args:
        ve_id: Volume Entity ID (e.g., "VE1KG11942_001")
        volume_folder: Path to volume folder containing RTF files
        output_dir: Output directory
        
    Returns:
        Tuple of (success_count, failed_count)
    """
    rtf_files = get_rtf_files_in_volume(volume_folder)
    
    if not rtf_files:
        logger.warning(f"  No RTF files found in {volume_folder}")
        return 0, 0
    
    logger.info(f"  Found {len(rtf_files)} RTF files")
    
    # Create output directories
    archive_dir = output_dir / "archive" / ve_id
    sources_dir = output_dir / "sources" / ve_id
    
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = 0
    
    for idx, rtf_path in enumerate(rtf_files):
        ut_id = get_ut_id(ve_id, idx)
        src_path = f"sources/{ve_id}/{rtf_path.name}"
        
        logger.info(f"  [{idx + 1}/{len(rtf_files)}] {rtf_path.name} -> {ut_id}")
        
        try:
            # Copy RTF to sources first (even if conversion fails)
            dest_rtf = sources_dir / rtf_path.name
            shutil.copy2(rtf_path, dest_rtf)
            
            # Convert to TEI XML
            tei_xml = convert_rtf_to_tei(rtf_path, ve_id, ut_id, src_path)
            
            # Write XML
            xml_path = archive_dir / f"{ut_id}.xml"
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(tei_xml)
            
            success += 1
            
        except Exception as e:
            logger.error(f"  Error converting {rtf_path.name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    return success, failed


def convert_all_volumes(output_dir: Path = None):
    """
    Convert all volumes from toprocess folder to TEI XML.
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    
    logger.info("=" * 60)
    logger.info(f"Converting all files for {IE_ID}")
    logger.info(f"Input: {TOPROCESS_DIR}")
    logger.info(f"Output: {output_dir}")
    logger.info("=" * 60)
    
    # Get volume folders
    volumes = get_volume_folders()
    if not volumes:
        logger.error("No volume folders found")
        return
    
    total_success = 0
    total_failed = 0
    
    for vol_idx, (ve_id, volume_folder) in enumerate(volumes):
        logger.info(f"\n[Volume {vol_idx + 1}/{len(volumes)}] {ve_id}")
        
        success, failed = convert_volume(ve_id, volume_folder, output_dir)
        total_success += success
        total_failed += failed
    
    logger.info("\n" + "=" * 60)
    logger.info("Conversion complete!")
    logger.info(f"  Total volumes: {len(volumes)}")
    logger.info(f"  Total success: {total_success}")
    logger.info(f"  Total failed: {total_failed}")
    logger.info(f"  Output: {output_dir}")
    logger.info("=" * 60)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Set DEBUG_MODE = True to test a single volume, False to run all
    DEBUG_MODE = False
    DEBUG_VOLUME = "VE1KG11942_001"  # First volume for testing
    
    if DEBUG_MODE:
        logger.info("=== DEBUG MODE ===")
        logger.info(f"Testing with volume: {DEBUG_VOLUME}")
        
        # Find the volume folder
        volumes = get_volume_folders()
        target_folder = None
        
        for ve_id, folder in volumes:
            if ve_id == DEBUG_VOLUME:
                target_folder = folder
                break
        
        if target_folder:
            convert_volume(DEBUG_VOLUME, target_folder, OUTPUT_DIR)
        else:
            logger.error(f"Volume {DEBUG_VOLUME} not found")
    else:
        # Run batch conversion for all volumes
        logger.info("=== BATCH MODE - Converting all volumes ===")
        convert_all_volumes(OUTPUT_DIR)






