#!/usr/bin/env python3
"""
Convert RTF files from IE00EGS1016703 (Zuchen Collection) to TEI XML format.

This script converts RTF files that already contain Unicode (TibetanMachineUnicode font)
to TEI XML format. No Dedris conversion is needed - just RTF parsing and normalization.

Key differences from IE1PD100944:
- RTF files already contain Unicode (RTF unicode escape sequences)
- Multiple files per volume (each gets sequential UT ID)
- VE ID extracted from folder name

Pipeline:
1. Parse RTF using basic_rtf parser
2. Extract Unicode from RTF Unicode escape sequences (already Unicode, no font conversion)
3. Normalize Unicode (Tibetan-specific normalization)
4. Generate TEI XML with proper structure

Input structure:
    toprocess/IE00EGS1016703-VE00EGS1016703_001/ZUCN001A.rtf
    toprocess/IE00EGS1016703-VE00EGS1016703_001/ZUCN001B.rtf
    ...

Output structure:
    archive/VE00EGS1016703_001/UT00EGS1016703_001_0001.xml
    archive/VE00EGS1016703_001/UT00EGS1016703_001_0002.xml
    sources/VE00EGS1016703_001/ZUCN001A.rtf
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

IE_ID = "IE00EGS1016703"

# Paths
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE00EGS1016703")
TOPROCESS_DIR = BASE_DIR / "IE00EGS1016703" / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE00EGS1016703_output"


# =============================================================================
# VE/UT ID Functions
# =============================================================================

def get_volume_folders() -> list:
    """
    Get list of volume folders from toprocess directory.
    
    Each folder is named like: IE00EGS1016703-VE00EGS1016703_001
    
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
            ve_id = folder.name.replace(f'{IE_ID}-', '')  # "VE00EGS1016703_001"
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
    
    VE00EGS1016703_001, index 0 -> UT00EGS1016703_001_0001
    VE00EGS1016703_001, index 1 -> UT00EGS1016703_001_0002
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix -> "00EGS1016703_001"
    return f"UT{ve_suffix}_{file_index + 1:04d}"


# =============================================================================
# Font Size Classification
# =============================================================================

def classify_font_sizes(streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    
    Uses frequency analysis: most common size is regular,
    smaller sizes are 'small', larger sizes are 'large'.
    
    Args:
        streams: List of stream dicts from BasicRTF parser
        
    Returns:
        dict: Mapping of font_size -> classification ('large', 'regular', 'small')
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
    
    sizes = sorted(size_counts.keys())
    
    classifications = {}
    
    if len(sizes) == 1:
        classifications[sizes[0]] = 'regular'
    elif len(sizes) == 2:
        # More common size is regular
        fs1, fs2 = sizes
        if size_counts[fs1] > size_counts[fs2]:
            classifications[fs1] = 'regular'
            classifications[fs2] = 'large' if fs2 > fs1 else 'small'
        else:
            classifications[fs2] = 'regular'
            classifications[fs1] = 'large' if fs1 > fs2 else 'small'
    else:
        # Multiple sizes: find most common in body text range (10-14 pt = 20-28 half-points)
        body_range = [fs for fs in sizes if 10 <= fs <= 14]
        
        if body_range:
            most_common = max(body_range, key=lambda fs: size_counts[fs])
        else:
            most_common = max(size_counts.items(), key=lambda x: x[1])[0]
        
        classifications[most_common] = 'regular'
        
        for fs in sizes:
            if fs == most_common:
                continue
            if fs > most_common:
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
    
    The RTF files already contain Unicode text (TibetanMachineUnicode font),
    so we just need to parse and normalize - no Dedris conversion needed.
    
    Args:
        rtf_path: Path to RTF file
        ve_id: Volume Entity ID (e.g., "VE00EGS1016703_001")
        ut_id: Unit Text ID (e.g., "UT00EGS1016703_001_0001")
        src_path: Source path for XML header (e.g., "sources/VE00EGS1016703_001/ZUCN001A.rtf")
        
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
    current_markup = None  # 'small', 'large', or None
    
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
    
    # Clean up: normalize multiple newlines to single
    body_content = re.sub(r'\n\n+', '\n', body_content)
    
    # Convert newlines (from RTF \par) to <lb/> elements
    body_content = body_content.replace('\n', '<lb/>\n')
    body_content = body_content.strip()
    
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
        ve_id: Volume Entity ID (e.g., "VE00EGS1016703_001")
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
            # Convert to TEI XML
            tei_xml = convert_rtf_to_tei(rtf_path, ve_id, ut_id, src_path)
            
            # Write XML
            xml_path = archive_dir / f"{ut_id}.xml"
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(tei_xml)
            
            # Copy RTF to sources
            dest_rtf = sources_dir / rtf_path.name
            shutil.copy2(rtf_path, dest_rtf)
            
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
    DEBUG_VOLUME = "VE00EGS1016703_001"  # First volume for testing
    
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

