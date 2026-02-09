#!/usr/bin/env python3
"""
Convert RTF files from IE1PD45495 (Taranatha Gsung Qbum Collection) to TEI XML format.

Input structure:    
    IE1PD45495/sources/{VE_ID}/{collection_name}/{VOL_ID}/*.rtf
    Example: IE1PD45495/sources/VE1PD45495_001/taranatha-gsung-qbum/volume_001/*.rtf

Output structure:
    Archive (flat): IE1PD45495_output/archive/{VE_ID}/UT1PD45495_{VOL_NUM}_{FILE_NUM}.xml
    Example: volume_029_266.rtf -> UT1PD45495_029_266.xml
    Sources (nested): IE1PD45495_output/sources/{VE_ID}/{collection_name}/{VOL_ID}/*.rtf and *.doc

Pipeline:
1. Parse RTF using basic_rtf parser (extracts text with font info)
2. Convert Dedris encoding to Unicode using pytiblegenc
3. Normalize Unicode (Tibetan-specific normalization)
4. Classify font sizes (regular/small/large)
5. Generate TEI XML with proper structure

Usage:
    # Convert all volumes:
    python convert.py --all
    
    # Convert a single volume:
    python convert.py --single VE1PD45495_001
    
    # Adjust worker count:
    python convert.py --all --workers 4
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
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

try:
    from natsort import natsorted
except ImportError:
    # logger not yet defined, will use sorted as fallback
    natsorted = sorted

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

IE_ID = "IE1PD45495"

# Paths - adjust these as needed
# The script expects the following structure created by organizer.py:
# IE1PD45495/sources/VE1PD45495_001/taranatha-gsung-qbum/volume_001/*.rtf
BASE_DIR = Path(__file__).parent  # Script directory (IE1PD45495 folder)
SOURCE_RTF_BASE = BASE_DIR / "IE1PD45495" / "sources"  # Base path for volume sources
OUTPUT_DIR = BASE_DIR / "IE1PD45495_output"

# Number of parallel workers (default: CPU count - 1, min 1)
DEFAULT_WORKERS = max(1, multiprocessing.cpu_count() - 1)

# Global stats for pytiblegenc
STATS = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0
}


# =============================================================================
# VE/UT ID Functions
# =============================================================================

def get_ut_id(ve_id: str, file_index: int) -> str:
    """
    Generate UT ID from VE ID and file index.
    
    VE1PD45495_001, index 0 -> UT1PD45495_001_0001
    VE1PD45495_001, index 1 -> UT1PD45495_001_0002
    """
    # Remove 'VE' prefix
    if ve_id.startswith('VE'):
        ve_suffix = ve_id[2:]
    else:
        ve_suffix = ve_id
    
    return f"UT{ve_suffix}_{file_index + 1:04d}"


def get_volume_folders(source_base: Path = None) -> list:
    """
    Get list of volume folders from sources directory.
    
    Handles structure: {IE_ID}/sources/{VE_ID}/{collection_name}/volume_XXX/*.rtf
    
    Args:
        source_base: Base path for sources (default: SOURCE_RTF_BASE)
    
    Returns:
        List of (ve_id, volume_number, rtf_folder_path, collection_name) tuples
    """
    if source_base is None:
        source_base = SOURCE_RTF_BASE
    
    volumes = []
    
    if not source_base.exists():
        logger.error(f"Sources folder not found at {source_base}")
        return []
    
    # Iterate through VE folders
    for ve_folder in source_base.iterdir():
        if not ve_folder.is_dir():
            continue
        
        ve_id = ve_folder.name
        
        # Look for collection subdirectories that contain volume_XXX folders
        # This handles variable collection names like "taranatha-gsung-qbum"
        for subdir in ve_folder.iterdir():
            if not subdir.is_dir() or subdir.name.startswith('.'):
                continue
            
            collection_name = subdir.name
            # Find all volume_XXX folders directly in the collection folder
            for volume_folder in subdir.iterdir():
                if volume_folder.is_dir() and volume_folder.name.startswith('volume_'):
                    volume_num = volume_folder.name.replace('volume_', '')
                    # Only add if there are RTF files
                    if list(volume_folder.glob("*.rtf")):
                        volumes.append((ve_id, volume_num, volume_folder, collection_name))
    
    return natsorted(volumes, key=lambda x: (x[0], x[1] or ''))


def get_rtf_files(volume_folder: Path) -> list:
    """Get sorted list of RTF files in a volume folder."""
    rtf_files = list(volume_folder.glob("*.rtf"))
    return natsorted(rtf_files, key=lambda p: p.name)


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


def convert_rtf_to_tei(rtf_path: Path, ve_id: str, ut_id: str, src_path: str) -> str:
    """
    Convert RTF file to TEI XML.
    
    Staged conversion:
    - Stage 1: Parse RTF + convert Dedris to Unicode (always enabled)
    - Stage 2: Font size classification (ENABLE_FONT_CLASSIFICATION)
    - Stage 3: Text normalization (ENABLE_NORMALIZATION)
    
    Args:
        rtf_path: Path to RTF file
        ve_id: Volume Entity ID (e.g., "VE1PD45495_001")
        ut_id: Unit Text ID (e.g., "UT1PD45495_001_0001")
        src_path: Relative path to source file in output structure
        
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
    # REMOVE WATERMARK/COPYRIGHT PATTERNS (after Unicode conversion)
    # =========================================================================
    # Remove watermark patterns from converted streams before any further processing
    # These are typically long sequences of repetitive Tibetan characters
    cleaned_streams = []
    for item in converted_streams:
        text = item.get("text", "")
        
        # Check if this is a watermark pattern
        # Criteria: Very long text (>500 chars) with low unique character ratio
        if len(text) > 500:
            # Count unique vs total Tibetan characters (ignoring spaces/newlines)
            chars = [c for c in text if c.strip() and 0x0F00 <= ord(c) <= 0x0FFF]
            if chars:
                unique_ratio = len(set(chars)) / len(chars)
                # If less than 10% unique characters, it's likely a watermark
                if unique_ratio < 0.1:
                    logger.info(f"  Removing watermark stream ({len(text)} chars, {unique_ratio:.2%} unique)")
                    continue  # Skip this stream entirely
        
        cleaned_streams.append(item)
    
    converted_streams = cleaned_streams
    logger.info(f"  After watermark removal: {len(converted_streams)} streams remaining")
    
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
        #body_content = fix_flying_vowels_and_linebreaks(body_content)
        
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
    # Replace newlines with <lb/> tags inline
    body_content = body_content.replace('\n', '<lb/>')
    body_content = re.sub(r' *<lb/> *', '<lb/>', body_content)
    body_content = body_content.strip()
    
    # =========================================================================
    # FIX <hi> TAG PLACEMENT
    # =========================================================================
    # Don't wrap whitespace/lb tags only in <hi> tags
    # Remove <hi> tags that contain only whitespace/lb tags
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', '', body_content)
    
    # Move <hi> from before <lb/> to after it
    # Pattern: <hi...> followed by <lb/>
    body_content = re.sub(r'(<hi rend="[^"]+">)<lb/>', r'<lb/>\1', body_content)
    
    # Move </hi> from after <lb/> to before the newline (end of previous line)
    # Pattern: newline, <lb/>, </hi>
    body_content = re.sub(r'\n<lb/></hi>', r'</hi>\n<lb/>', body_content)
    
    # Remove double newlines
    body_content = re.sub(r'\n\n+', '\n', body_content)
    # Clean up any remaining empty <hi> tags after the moves
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', '', body_content)
    
    # Merge consecutive identical <hi> tags while preserving line breaks
    # Pattern: </hi> followed by <lb/>, then same <hi> tag
    body_content = re.sub(r'</hi><lb/><hi rend="small">', '<lb/>', body_content)
    body_content = re.sub(r'</hi><lb/><hi rend="head">', '<lb/>', body_content)
    
    # Also handle cases without <lb/> tags (with or without whitespace between tags)
    body_content = re.sub(r'</hi>\s*<hi rend="small">', ' ', body_content)
    body_content = re.sub(r'</hi>\s*<hi rend="head">', ' ', body_content)
    
    # Remove duplicate consecutive <lb/> tags (keep only one)
    while re.search(r'<lb/><lb/>', body_content):
        body_content = re.sub(r'<lb/><lb/>', '<lb/>', body_content)
    
    # Final strip
    body_content = body_content.strip()
    
    # =========================================================================
    # GENERATE TEI XML
    # =========================================================================
    sha256 = calculate_sha256(rtf_path)
    
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
# Volume Processing (Worker Function)
# =============================================================================

def process_volume(args: tuple) -> dict:
    """
    Process a single volume (worker function for multiprocessing).
    
    Args:
        args: Tuple of (ve_id, volume_num, volume_folder, output_dir, collection_name, start_index)
        
    Returns:
        dict with results: {ve_id, volume_num, success, failed, errors}
    """
    ve_id, volume_num, volume_folder, output_dir, collection_name, start_index = args
    
    volume_label = f"{ve_id}_vol{volume_num}" if volume_num else ve_id
    
    result = {
        "ve_id": ve_id,
        "volume_num": volume_num,
        "volume_label": volume_label,
        "success": 0,
        "failed": 0,
        "errors": []
    }
    
    try:
        rtf_files = get_rtf_files(volume_folder)
        
        if not rtf_files:
            return result
        
        # Create output directories
        # Archive is always flat: archive/{VE_ID}/UT{suffix}_{index}.xml
        archive_dir = output_dir / "archive" / ve_id
        
        # Sources preserves the nested structure
        if volume_num and collection_name:
            sources_output_dir = output_dir / "sources" / ve_id / collection_name / f"volume_{volume_num}"
        else:
            sources_output_dir = output_dir / "sources" / ve_id
        
        archive_dir.mkdir(parents=True, exist_ok=True)
        sources_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get DOC files for copying to sources
        doc_files = list(volume_folder.glob("*.doc"))
        
        for idx, rtf_path in enumerate(rtf_files):
            # Use global index across all volumes for this VE_ID
            global_idx = start_index + idx
            ut_id = get_ut_id(ve_id, global_idx)
            
            # Build source path relative to output
            if volume_num and collection_name:
                src_path = f"sources/{ve_id}/{collection_name}/volume_{volume_num}/{rtf_path.name}"
            else:
                src_path = f"sources/{ve_id}/{rtf_path.name}"
            
            try:
                # Convert to TEI XML
                tei_xml = convert_rtf_to_tei(rtf_path, ve_id, ut_id, src_path)
                
                # Generate XML filename from RTF filename
                # volume_029_266.rtf -> UT1PD45495_029_266.xml
                rtf_stem = rtf_path.stem  # e.g., "volume_029_266"
                # Extract the volume and file number parts
                if rtf_stem.startswith('volume_'):
                    # volume_029_266 -> 029_266
                    parts = rtf_stem.replace('volume_', '', 1)
                    xml_filename = f"UT1PD45495_{parts}.xml"
                else:
                    # Fallback to using the full stem
                    xml_filename = f"UT1PD45495_{rtf_stem}.xml"
                
                # Write XML to flat archive structure
                xml_path = archive_dir / xml_filename
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(tei_xml)
                
                # Copy RTF to sources
                dest_rtf = sources_output_dir / rtf_path.name
                shutil.copy2(rtf_path, dest_rtf)
                
                result["success"] += 1
                
            except Exception as e:
                result["failed"] += 1
                result["errors"].append(f"{rtf_path.name}: {str(e)}")
        
        # Copy all DOC files to sources (after processing RTFs)
        for doc_file in doc_files:
            try:
                dest_doc = sources_output_dir / doc_file.name
                shutil.copy2(doc_file, dest_doc)
            except Exception as e:
                logger.warning(f"Failed to copy DOC file {doc_file.name}: {e}")
    
    except Exception as e:
        result["errors"].append(f"Volume error: {str(e)}")
    
    return result


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
# Main Processing Functions
# =============================================================================

def process_collection(source_base: Path, output_dir: Path, workers: int) -> tuple:
    """
    Process all volumes in the collection using multiprocessing.
    
    Args:
        source_base: Base path for sources
        output_dir: Output directory
        workers: Number of parallel workers
        
    Returns:
        Tuple of (total_success, total_failed)
    """
    volumes = get_volume_folders(source_base)
    
    if not volumes:
        logger.warning(f"  No volumes found in {source_base}")
        return 0, 0
    
    logger.info(f"  Found {len(volumes)} volumes, processing with {workers} workers...")
    
    # Calculate starting index for each volume to maintain sequential numbering across volumes
    # Group volumes by VE_ID to maintain proper indexing
    ve_index_map = {}  # Maps (ve_id, volume_num) -> starting_index
    current_indices = {}  # Tracks current index for each ve_id
    
    for ve_id, volume_num, volume_folder, collection_name in volumes:
        if ve_id not in current_indices:
            current_indices[ve_id] = 0
        
        rtf_count = len(list(volume_folder.glob("*.rtf")))
        ve_index_map[(ve_id, volume_num)] = current_indices[ve_id]
        current_indices[ve_id] += rtf_count
    
    # Prepare arguments for workers with starting indices
    work_items = [
        (ve_id, volume_num, volume_folder, output_dir, collection_name, ve_index_map[(ve_id, volume_num)])
        for ve_id, volume_num, volume_folder, collection_name in volumes
    ]
    
    total_success = 0
    total_failed = 0
    
    # Use multiprocessing for volumes
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_volume, item): item for item in work_items}
        
        for future in as_completed(futures):
            result = future.result()
            total_success += result["success"]
            total_failed += result["failed"]
            
            status = "[OK]" if result["failed"] == 0 else "[FAIL]"
            logger.info(f"    {status} {result['volume_label']}: {result['success']} success, {result['failed']} failed")
            
            if result["errors"]:
                for error in result["errors"][:3]:  # Show max 3 errors
                    logger.error(f"      - {error}")
    
    return total_success, total_failed


def convert_all_files(output_dir: Path = None, source_base: Path = None, workers: int = None):
    """
    Convert all volume RTF files to TEI XML using multiprocessing.
    
    Args:
        output_dir: Output directory (default: OUTPUT_DIR)
        source_base: Base path for sources (default: SOURCE_RTF_BASE)
        workers: Number of parallel workers (default: DEFAULT_WORKERS)
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    if source_base is None:
        source_base = SOURCE_RTF_BASE
    if workers is None:
        workers = DEFAULT_WORKERS
    
    logger.info("=" * 70)
    logger.info(f"RTF TO TEI XML CONVERTER - {IE_ID}")
    logger.info("=" * 70)
    logger.info(f"Source base: {source_base}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Workers: {workers}")
    logger.info("=" * 70)
    
    success, failed = process_collection(source_base, output_dir, workers)
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("CONVERSION COMPLETE")
    logger.info("=" * 70)
    logger.info(f"  Success: {success}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Output: {output_dir}")
    logger.info("=" * 70)
    
    # Enhanced debug reporting
    _print_conversion_stats(output_dir)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert IE1PD45495 (Taranatha Gsung Qbum) RTF files to TEI XML"
    )
    
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        default=True,
        help="Convert all volumes (default behavior)"
    )
    parser.add_argument(
        "--single", "-s",
        metavar="VE_ID",
        help="Convert a single volume (e.g., VE1PD45495_001)"
    )
    parser.add_argument(
        "--output", "-o",
        metavar="DIR",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})"
    )
    
    args = parser.parse_args()
    
    if args.single:
        # Process single volume
        ve_id = args.single
        volumes = get_volume_folders(SOURCE_RTF_BASE)
        
        # Filter to just this VE ID
        volumes = [(vid, vnum, vfolder, cname) for vid, vnum, vfolder, cname in volumes if vid == ve_id]
        
        if not volumes:
            logger.error(f"No volumes found for {ve_id}")
            return
        
        logger.info(f"Processing {len(volumes)} volume(s) for {ve_id}")
        
        # Calculate indices for this VE ID
        ve_index_map = {}
        current_index = 0
        for vid, vnum, vfolder, cname in volumes:
            rtf_count = len(list(vfolder.glob("*.rtf")))
            ve_index_map[(vid, vnum)] = current_index
            current_index += rtf_count
        
        # Process volumes
        total_success = 0
        total_failed = 0
        for vid, vnum, vfolder, cname in volumes:
            result = process_volume((vid, vnum, vfolder, args.output, cname, ve_index_map[(vid, vnum)]))
            total_success += result["success"]
            total_failed += result["failed"]
            
            status = "[OK]" if result["failed"] == 0 else "[FAIL]"
            logger.info(f"  {status} {result['volume_label']}: {result['success']} success, {result['failed']} failed")
            
            if result["errors"]:
                for error in result["errors"]:
                    logger.error(f"    - {error}")
        
        logger.info(f"\nCompleted: {total_success} success, {total_failed} failed")
    else:
        # Process all volumes
        convert_all_files(args.output, SOURCE_RTF_BASE, args.workers)


if __name__ == "__main__":
    # Set DEBUG_MODE = True to test a single volume, False to run all volumes
    DEBUG_MODE = False
    DEBUG_VOLUME = "VE1PD45495_001"
    
    if DEBUG_MODE:
        logger.info("=== DEBUG MODE ===")
        logger.info(f"Testing with volume: {DEBUG_VOLUME}")
        
        volumes = get_volume_folders(SOURCE_RTF_BASE)
        volumes = [(vid, vnum, vfolder, cname) for vid, vnum, vfolder, cname in volumes if vid == DEBUG_VOLUME]
        
        if not volumes:
            logger.error(f"No volumes found for {DEBUG_VOLUME}")
        else:
            logger.info(f"Found {len(volumes)} volume(s)")
            
            # Calculate indices
            ve_index_map = {}
            current_index = 0
            for vid, vnum, vfolder, cname in volumes:
                rtf_count = len(list(vfolder.glob("*.rtf")))
                ve_index_map[(vid, vnum)] = current_index
                current_index += rtf_count
            
            # Process volumes
            total_success = 0
            total_failed = 0
            for vid, vnum, vfolder, cname in volumes:
                result = process_volume((vid, vnum, vfolder, OUTPUT_DIR, cname, ve_index_map[(vid, vnum)]))
                total_success += result["success"]
                total_failed += result["failed"]
                
                status = "[OK]" if result["failed"] == 0 else "[FAIL]"
                logger.info(f"  {status} {result['volume_label']}: {result['success']} success, {result['failed']} failed")
                
                if result["errors"]:
                    for error in result["errors"]:
                        logger.error(f"    - {error}")
            
            logger.info(f"\nCompleted: {total_success} success, {total_failed} failed")
    else:
        # Run batch conversion for all volumes
        main()