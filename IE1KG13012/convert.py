#!/usr/bin/env python3
"""
Convert RTF files to TEI XML format.

Usage:
    # Process current directory (auto-detects IE_ID from folder name):
    python convert.py
    
    # Process specific directory (auto-detects IE_ID):
    python convert.py /path/to/IE1GS58442
    
    # Process with explicit IE_ID override:
    python convert.py /path/to/folder --ie-id IE1GS58442
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
    remove_repeated_tseg_pattern,
)

# Import char_converter directly to avoid pdfminer dependency issues in pytiblegenc.__init__
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

# Processing stages - can be enabled/disabled
ENABLE_FONT_CLASSIFICATION = True   
ENABLE_NORMALIZATION = True        

# Global stats for pytiblegenc
STATS = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0
}

# =============================================================================
# Discovery Functions
# =============================================================================

def get_volume_folders(ie_id: str, sources_dir: Path) -> list:
    """
    Get list of volume folders from sources directory.
    
    Handles multiple structures:
    1. Direct RTF files in VE folder: {IE_ID}/sources/{VE_ID}/*.rtf
    2. Nested rtfs folder: {IE_ID}/sources/{VE_ID}/{collection_name}/rtfs/volume_XXX/*.rtf
    
    Returns:
        List of (ve_id, volume_number, rtf_folder_path, collection_name) tuples
    """
    volumes = []
    
    # Check if this is the new structure (has VE folders directly in sources)
    for ve_folder in sources_dir.iterdir():
        if not ve_folder.is_dir():
            continue
        
        ve_id = ve_folder.name
        
        # Look for any subdirectory that contains an "rtfs" folder
        for subdir in ve_folder.iterdir():
            if not subdir.is_dir() or subdir.name.startswith('.'):
                continue
            
            rtfs_base = subdir / "rtfs"
            if rtfs_base.exists() and rtfs_base.is_dir():
                collection_name = subdir.name
                # Find all volume_XXX folders
                for volume_folder in rtfs_base.iterdir():
                    if volume_folder.is_dir() and volume_folder.name.startswith('volume_'):
                        volume_num = volume_folder.name.replace('volume_', '')
                        # Only add if there are RTF files
                        if list(volume_folder.glob("*.rtf")):
                            volumes.append((ve_id, volume_num, volume_folder, collection_name))
                break  # Found rtfs folder, no need to check other subdirs
        
        # Check for direct RTF files in VE folder
        if not any(v[0] == ve_id for v in volumes):  # Only if we haven't found nested structure
            rtf_files = list(ve_folder.glob("*.rtf"))
            if rtf_files:
                volumes.append((ve_id, None, ve_folder, None))
    
    return natsorted(volumes, key=lambda x: (x[0], x[1] or ''))


def get_rtf_files(volume_folder: Path) -> list:
    """Get sorted list of RTF files in a volume folder."""
    rtf_files = list(volume_folder.glob("*.rtf"))
    return natsorted(rtf_files, key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int) -> str:
    """
    Generate UT ID from VE ID and file index.
    
    VE3KG253, index 0 -> UT3KG253_0001
    VE1ER664, index 0 -> UT1ER664_0001
    """
    # Remove 'VE' prefix
    if ve_id.startswith('VE'):
        ve_suffix = ve_id[2:]
    else:
        ve_suffix = ve_id
    
    return f"UT{ve_suffix}_{file_index + 1:04d}"


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
    SUSPICIOUS_FONTS = ('simsun', '@simsun', 'simsun western')
    
    # Check if this is a Dedris font
    is_dedris = font_name and font_name.lower().startswith(('dedris', 'ededris'))
    is_suspicious = font_name and font_name.lower() in SUSPICIOUS_FONTS
    
    if not is_dedris and not is_suspicious:
        return text
    
    try:
        # Use pytiblegenc to convert
        unicode_text = convert_string(text, font_name, STATS)
        # If conversion returns None or empty, return original text
        if unicode_text is None or unicode_text == '':
            return text
        return unicode_text
    except Exception as e:
        logger.warning(f"Failed to convert text with font {font_name}: {e}")
        STATS["error_characters"] += len(text)
        return text


# =============================================================================
# Font Size Classification
# =============================================================================

def classify_font_sizes_from_converted(converted_streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    
    Uses frequency analysis: the font size with the MOST Tibetan characters 
    is classified as "regular" (body text). Larger sizes become "large" (headers),
    smaller sizes become "small" (footnotes).
    
    IMPORTANT: This function must be called AFTER Dedris to Unicode conversion,
    otherwise Tibetan character counting will return 0.
    
    Args:
        converted_streams: List of dicts with 'text' (Unicode), 'font_size', 'is_break'
        
    Returns:
        dict: Mapping of font_size -> classification ('large', 'regular', 'small')
        
    Example:
        Input streams with font sizes: 10 (200 chars), 12 (5000 chars), 16 (50 chars)
        Returns: {10: 'small', 12: 'regular', 16: 'large'}
    """
    size_counts = Counter()
    
    for item in converted_streams:
        text = item.get("text", "")
        font_size = item.get("font_size", 12)
        is_break = item.get("is_break", False)
        
        # Skip break streams
        if is_break:
            continue
        
        # Count Tibetan characters (U+0F00-U+0FFF)
        tibetan_chars = count_tibetan_chars(text)
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    
    if not size_counts:
        return {}
    
    # Find the font size with the most Tibetan characters - that's "regular" (body text)
    most_common_size = max(size_counts.items(), key=lambda x: x[1])[0]
    
    # Classify all sizes relative to most common
    classifications = {}
    for fs in size_counts.keys():
        if fs == most_common_size:
            classifications[fs] = 'regular'
        elif fs > most_common_size:
            classifications[fs] = 'large'
        else:
            classifications[fs] = 'small'
    
    return classifications


# =============================================================================
# TEI XML Generation
# =============================================================================

def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
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


def convert_rtf_to_tei(rtf_path: Path, ie_id: str, ve_id: str, ut_id: str, src_path: str) -> str:
    """
    Convert RTF file to TEI XML.
    
    Args:
        rtf_path: Path to RTF file
        ie_id: Image Entity ID
        ve_id: Volume Entity ID
        ut_id: Unit Text ID
        src_path: Relative source path for metadata
        
    Returns:
        TEI XML string
    """
    # =========================================================================
    # STAGE 1: Parse RTF and Convert Dedris to Unicode
    # =========================================================================
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    # Convert all text streams to Unicode first
    converted_streams = []
    
    for stream in streams:
        # Skip standard RTF non-text elements
        if stream.get("type") in ("header", "footer", "pict"):
            continue
        
        # Handle paragraph breaks - convert to newline
        if stream.get("type") == "par_break":
            converted_streams.append({
                "text": "\n",
                "font_size": 12,
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
                "text": "\n",
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
        
        # Store converted stream
        converted_streams.append({
            "text": unicode_text,
            "font_size": font_size,
            "is_break": False
        })
    
    # =========================================================================
    # STAGE 2: Font Size Classification (optional)
    # =========================================================================
    if ENABLE_FONT_CLASSIFICATION:
        classifications = classify_font_sizes_from_converted(converted_streams)
    else:
        classifications = {}
    
    # =========================================================================
    # STAGE 3: Process Converted Streams and Build Content
    # =========================================================================
    tei_lines = []
    current_markup = None
    
    for item in converted_streams:
        text = item["text"]
        font_size = item["font_size"]
        is_break = item.get("is_break", False)
        
        # If it's a break, just add the newline
        if is_break:
            tei_lines.append(text)
            continue
        
        # Apply normalization if enabled
        if ENABLE_NORMALIZATION:
            # Normalize Unicode
            normalized_text = normalize_unicode(text)
            normalized_text = normalize_spaces(normalized_text)
            
            if not normalized_text.strip():
                continue
            
            # Apply Tibetan-specific fixes
            fixed_text = fix_flying_vowels_and_linebreaks(normalized_text)
            
            # Remove inverted exclamation mark (¡) that appears with ellipsis in some fonts
            fixed_text = fixed_text.replace('¡', '')
        else:
            fixed_text = text
            if not fixed_text.strip():
                continue
        
        # Skip lines that contain only dashes and spaces (e.g., "- - - - -")
        # But preserve ellipsis characters (U+2026: …)
        if re.match(r'^[\s\-]+$', fixed_text) and '…' not in fixed_text:
            continue
        
        # Escape XML
        escaped_text = escape_xml(fixed_text)
        
        # Apply font size classification if enabled
        if ENABLE_FONT_CLASSIFICATION and classifications:
            classification = classifications.get(font_size, 'regular')
            
            # Handle markup changes
            if classification != current_markup:
                if current_markup in ('small', 'large'):
                    tei_lines.append('</hi>')
                
                if classification == 'small':
                    tei_lines.append('<hi rend="small">')
                elif classification == 'large':
                    tei_lines.append('<hi rend="head">')
                
                current_markup = classification if classification != 'regular' else None
        
        tei_lines.append(escaped_text)
    
    # Close any open markup
    if current_markup in ('small', 'large'):
        tei_lines.append('</hi>')
    
    # Join and clean up
    body_content = ''.join(tei_lines)
    
    # Apply final Unicode normalization to handle cross-stream character ordering
    # This fixes cases where ༔ and vowels are in separate RTF streams
    if ENABLE_NORMALIZATION:
        body_content = normalize_unicode(body_content)
    
    # Remove unwanted patterns (e.g., repeated tseg at beginning)
    body_content = remove_repeated_tseg_pattern(body_content)
    
    # Fix hi tag spacing and remove empty hi tags (only if font classification is enabled)
    if ENABLE_FONT_CLASSIFICATION:
        body_content = fix_hi_tag_spacing(body_content)
        body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    body_content = body_content.strip()
    
    # Put <lb/> at beginning of each new line and remove surrounding spaces
    body_content = body_content.replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '<lb/>', body_content)
    body_content = body_content.strip()
    
    # Remove <hi> tags that contain only whitespace/newlines/lb tags
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', '', body_content)
    
    # Move <hi> from end of line to after <lb/> on next line
    body_content = re.sub(r'(<hi rend="[^"]+">)\s*<lb/>', r'<lb/>\1', body_content)
    
    # Move </hi> from after <lb/> to its own line, then <lb/> on next line
    body_content = re.sub(r'<lb/></hi>', r'</hi>\n<lb/>', body_content)
    
    # Remove multiple consecutive <lb/> tags around </hi>, keeping only one after </hi>
    body_content = re.sub(r'(<lb/>\s*)+</hi>\s*(<lb/>\s*)+', r'</hi>\n<lb/>', body_content)
    
    # Remove double newlines
    body_content = re.sub(r'\n\n+', '\n', body_content)
    
    # Clean up any remaining empty <hi> tags after the moves
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', '', body_content)
    
    # Remove multiple consecutive <lb/> tags, keeping only one
    body_content = re.sub(r'(<lb/>)+', '<lb/>', body_content)
    
    # Final strip
    body_content = body_content.strip()
    
    # Calculate SHA256
    sha256 = calculate_sha256(rtf_path)
    
    # Generate TEI XML
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
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{ie_id}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl>
</sourceDesc>
</fileDesc>
<encodingDesc>
<p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{ie_id}">record in the BDRC database</ref>.</p>
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
# Volume Processing
# =============================================================================

def process_volume(ie_id: str, ve_id: str, volume_num: str, volume_folder: Path, 
                   output_dir: Path, collection_name: str) -> dict:
    """
    Process a single volume.

    Args:
        ie_id: Image Entity ID
        ve_id: Volume Entity ID
        volume_num: Volume number (or None for direct files)
        volume_folder: Path to folder containing RTF files
        output_dir: Output directory
        collection_name: Collection name (or None for direct files)
        
    Returns:
        dict with results: {ve_id, volume_num, success, failed, errors}
    """
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
        
        logger.info(f"  Processing {volume_label}: {len(rtf_files)} RTF files")
        
        # Create output directories
        # Archive is always flat: archive/{VE_ID}/UT{suffix}_{index}.xml
        archive_dir = output_dir / "archive" / ve_id
        
        # Sources preserves the nested structure
        if volume_num and collection_name:
            sources_output_dir = output_dir / "sources" / ve_id / collection_name / "rtfs" / f"volume_{volume_num}"
        else:
            sources_output_dir = output_dir / "sources" / ve_id
        
        archive_dir.mkdir(parents=True, exist_ok=True)
        sources_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Process each RTF file
        for file_index, rtf_file in enumerate(rtf_files):
            try:
                # Generate UT ID
                ut_id = get_ut_id(ve_id, file_index)
                
                # Build source path for metadata
                if volume_num and collection_name:
                    src_path = f"{ve_id}/{collection_name}/rtfs/volume_{volume_num}/{rtf_file.name}"
                else:
                    src_path = f"{ve_id}/{rtf_file.name}"
                
                # Convert to TEI
                tei_xml = convert_rtf_to_tei(rtf_file, ie_id, ve_id, ut_id, src_path)
                
                # Write to archive (flat structure)
                archive_file = archive_dir / f"{ut_id}.xml"
                archive_file.write_text(tei_xml, encoding='utf-8')
                
                # Copy source RTF to sources output
                dest_rtf = sources_output_dir / rtf_file.name
                shutil.copy2(rtf_file, dest_rtf)
                
                # Also copy corresponding DOC file if it exists
                doc_file = rtf_file.with_suffix('.doc')
                if doc_file.exists():
                    dest_doc = sources_output_dir / doc_file.name
                    shutil.copy2(doc_file, dest_doc)
                else:
                    # Try uppercase extension
                    doc_file = rtf_file.with_suffix('.DOC')
                    if doc_file.exists():
                        dest_doc = sources_output_dir / doc_file.name
                        shutil.copy2(doc_file, dest_doc)
                
                result["success"] += 1
                
            except Exception as e:
                logger.error(f"  Failed to process {rtf_file.name}: {e}")
                result["failed"] += 1
                result["errors"].append(f"{rtf_file.name}: {str(e)}")
        
        logger.info(f"  {volume_label}: {result['success']} succeeded, {result['failed']} failed")
        
    except Exception as e:
        logger.error(f"  Failed to process {volume_label}: {e}")
        result["errors"].append(str(e))
    
    return result


def detect_ie_id(base_dir: Path) -> str:
    """
    Auto-detect IE_ID from base directory name.
    
    Args:
        base_dir: Base directory path
        
    Returns:
        IE_ID string (e.g., "IE1GS58442")
    """
    # Try to extract IE_ID from the directory name
    dir_name = base_dir.name
    
    # Check if directory name matches IE pattern (IE followed by alphanumeric)
    ie_match = re.match(r'(IE[A-Z0-9]+)', dir_name, re.IGNORECASE)
    if ie_match:
        return ie_match.group(1).upper()
    
    # If not found in directory name, raise error
    raise ValueError(
        f"Could not detect IE_ID from directory name: {dir_name}\n"
        f"Expected format: IE followed by alphanumeric characters (e.g., IE1GS58442)"
    )


def process_collection(ie_id: str, base_dir: Path) -> dict:
    """
    Process a single collection.
    
    Args:
        ie_id: Image Entity ID
        base_dir: Base directory containing sources folder
        
    Returns:
        dict with summary statistics
    """
    sources_dir = base_dir / "sources"
    output_dir = base_dir / f"{ie_id}_output"
    
    logger.info(f"Processing {ie_id}")
    logger.info(f"  Input: {sources_dir}")
    logger.info(f"  Output: {output_dir}")
    
    # Discover volumes
    volumes = get_volume_folders(ie_id, sources_dir)
    
    if not volumes:
        logger.warning(f"  No volumes found in {sources_dir}")
        return {"success": 0, "failed": 0}
    
    logger.info(f"  Found {len(volumes)} volumes")
    
    # Process each volume
    total_success = 0
    total_failed = 0
    
    for ve_id, volume_num, volume_folder, collection_name in volumes:
        result = process_volume(ie_id, ve_id, volume_num, volume_folder, output_dir, collection_name)
        total_success += result["success"]
        total_failed += result["failed"]
    
    logger.info(f"")
    logger.info(f"Summary for {ie_id}:")
    logger.info(f"  Total files processed: {total_success + total_failed}")
    logger.info(f"  Succeeded: {total_success}")
    logger.info(f"  Failed: {total_failed}")
    logger.info(f"  Output: {output_dir}")
    
    return {"success": total_success, "failed": total_failed}


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert RTF files to TEI XML format"
    )
    
    parser.add_argument(
        "base_dir",
        type=Path,
        nargs='?',
        default=None,
        help="Base directory containing sources folder (e.g., /path/to/IE1GS58442)"
    )
    
    parser.add_argument(
        "--ie-id",
        type=str,
        default=None,
        help="Override IE_ID (auto-detected from directory name if not provided)"
    )
    
    args = parser.parse_args()
    
    # Determine base directory
    if args.base_dir is None:
        # Use current working directory
        base_dir = Path.cwd()
    else:
        base_dir = args.base_dir
    
    if not base_dir.exists():
        logger.error(f"Base directory not found: {base_dir}")
        return
    
    sources_dir = base_dir / "sources"
    if not sources_dir.exists():
        logger.error(f"Sources directory not found: {sources_dir}")
        logger.error(f"Expected structure: {base_dir}/sources/{{VE_ID}}/...")
        return
    
    # Auto-detect or use provided IE_ID
    if args.ie_id:
        ie_id = args.ie_id.upper()
    else:
        try:
            ie_id = detect_ie_id(base_dir)
            logger.info(f"Auto-detected IE_ID: {ie_id}")
        except ValueError as e:
            logger.error(str(e))
            return
    
    logger.info("=" * 70)
    logger.info(f"{ie_id} RTF TO TEI XML CONVERTER")
    logger.info("=" * 70)
    logger.info(f"Base directory: {base_dir}")
    logger.info("")
    
    # Process the collection
    process_collection(ie_id, base_dir)
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("CONVERSION COMPLETE")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
