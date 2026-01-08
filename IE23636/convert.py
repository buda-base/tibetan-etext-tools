#!/usr/bin/env python3
"""
Batch RTF to TEI XML Converter with Multiprocessing.

This script processes multiple IE collections in parallel, converting RTF files
to TEI XML format. It auto-discovers collections and handles various folder structures.

Input structure:
    rtf/{IE_ID}/{IE_ID}/toprocess/{IE_ID}-{VE_ID}/*.rtf

Output structure:
    rtf/{IE_ID}/{IE_ID}_output/archive/{VE_ID}/UT{suffix}_{index}.xml
    rtf/{IE_ID}/{IE_ID}_output/sources/{VE_ID}/*.rtf

Usage:
    # Process all collections:
    python convert.py
    
    # Process specific collection:
    python convert.py --ie-id IE1KG17189
    
    # Adjust worker count:
    python convert.py --workers 4
"""

import sys
import os
import re
import hashlib
import shutil
import logging
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
import multiprocessing

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Ensure stdout is unbuffered
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# Add script directory to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

try:
    from natsort import natsorted
except ImportError:
    logger.warning("natsort not installed, using basic sorting")
    natsorted = sorted

from basic_rtf import BasicRTF
from normalization import normalize_unicode


# =============================================================================
# Configuration
# =============================================================================

# Default input directory containing all IE collections
INPUT_DIR = Path(__file__).parent.parent / "rtf"

# Number of parallel workers (default: CPU count - 1, min 1)
DEFAULT_WORKERS = max(1, multiprocessing.cpu_count() - 1)


# =============================================================================
# Discovery Functions
# =============================================================================

def discover_collections(input_dir: Path) -> list:
    """
    Discover all IE collections in the input directory.
    Only includes collections that haven't been processed yet (no output directory).
    
    Returns:
        List of (ie_id, toprocess_dir, output_dir) tuples
    """
    collections = []
    skipped = []
    
    for ie_folder in input_dir.iterdir():
        if not ie_folder.is_dir():
            continue
            
        ie_id = ie_folder.name
        output_dir = ie_folder / f"{ie_id}_output"
        archive_dir = output_dir / "archive"
        
        # Skip collections that already have output directories with XML files
        if archive_dir.exists() and archive_dir.is_dir():
            xml_files = list(archive_dir.rglob("*.xml"))
            if xml_files:
                skipped.append(ie_id)
                logger.info(f"Skipping {ie_id} - already processed ({len(xml_files)} XML files found)")
                continue
        
        # Check for nested structure: {IE_ID}/{IE_ID}/toprocess
        nested_path = ie_folder / ie_id / "toprocess"
        if nested_path.exists():
            toprocess_dir = nested_path
            collections.append((ie_id, toprocess_dir, output_dir))
            continue
        
        # Check for direct structure: {IE_ID}/toprocess
        direct_path = ie_folder / "toprocess"
        if direct_path.exists():
            toprocess_dir = direct_path
            collections.append((ie_id, toprocess_dir, output_dir))
    
    if skipped:
        logger.info(f"Skipped {len(skipped)} already-processed collections: {', '.join(skipped)}")
    
    return natsorted(collections, key=lambda x: x[0])


def get_volume_folders(ie_id: str, toprocess_dir: Path) -> list:
    """
    Get list of volume folders from toprocess directory.
    
    Returns:
        List of (ve_id, folder_path) tuples
    """
    volumes = []
    
    for folder in toprocess_dir.iterdir():
        if folder.is_dir() and folder.name.startswith(f'{ie_id}-'):
            ve_id = folder.name.replace(f'{ie_id}-', '')
            volumes.append((ve_id, folder))
    
    return natsorted(volumes, key=lambda x: x[0])


def get_rtf_files(volume_folder: Path) -> list:
    """Get sorted list of RTF files in a volume folder."""
    rtf_files = list(volume_folder.glob("*.rtf"))
    return natsorted(rtf_files, key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int) -> str:
    """
    Generate UT ID from VE ID and file index.
    
    VE3KG253, index 0 -> UT3KG253_0001
    VE1KG11901_001, index 0 -> UT1KG11901_001_0001
    """
    # Remove 'VE' prefix
    if ve_id.startswith('VE'):
        ve_suffix = ve_id[2:]
    else:
        ve_suffix = ve_id
    
    return f"UT{ve_suffix}_{file_index + 1:04d}"


# =============================================================================
# Font Size Classification
# =============================================================================

def classify_font_sizes(streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    
    The font size with the MOST Tibetan characters is always classified as "regular".
    Larger sizes -> "large" (wrapped in <hi rend="head">)
    Smaller sizes -> "small" (wrapped in <hi rend="small">)
    """
    size_counts = Counter()
    
    for stream in streams:
        text = stream.get("text", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        tibetan_chars = len([c for c in text if 0x0F00 <= ord(c) <= 0x0FFF])
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    
    if not size_counts:
        return {}
    
    # Find the font size with the most Tibetan characters - that's "regular"
    most_common_size = max(size_counts.items(), key=lambda x: x[1])[0]
    
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
# RTF to TEI Conversion
# =============================================================================

def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def clean_rtf_fallback_chars(text: str) -> str:
    """Remove RTF Unicode fallback characters."""
    tibetan_range = '[\u0F00-\u0FFF]'
    text = re.sub(r'^([a-zA-Z?])(' + tibetan_range + ')', r'\2', text)
    text = re.sub(r'\n([a-zA-Z?])(' + tibetan_range + ')', r'\n\2', text)
    text = re.sub(r'\n([a-zA-Z?]) (' + tibetan_range + ')', r'\n\2', text)
    text = re.sub(r'\n([a-zA-Z?])$', r'\n', text)
    text = re.sub(r'^([a-zA-Z?])$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^([a-zA-Z?]) ', '', text, flags=re.MULTILINE)
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
    """
    # Parse RTF
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    logger.info(f"  Parsed {len(streams)} text streams")
    
    # Classify font sizes
    classifications = classify_font_sizes(streams)
    
    # Process streams and build content
    tei_lines = []
    current_markup = None
    
    for stream in streams:
        text = stream.get("text", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        if stream.get("type") in ("header", "footer", "pict"):
            continue
        
        cleaned_text = clean_rtf_fallback_chars(text)
        normalized_text = normalize_unicode(cleaned_text)
        
        if not normalized_text.strip():
            continue
        
        escaped_text = escape_xml(normalized_text)
        classification = classifications.get(font_size, 'regular')
        
        if classification != current_markup:
            if current_markup == 'small':
                tei_lines.append('</hi>')
            elif current_markup == 'large':
                tei_lines.append('</hi>')
            
            if classification == 'small':
                tei_lines.append('<hi rend="small">')
            elif classification == 'large':
                tei_lines.append('<hi rend="head">')
            
            current_markup = classification if classification != 'regular' else None
        
        tei_lines.append(escaped_text)
    
    if current_markup == 'small':
        tei_lines.append('</hi>')
    elif current_markup == 'large':
        tei_lines.append('</hi>')
    
    body_content = ''.join(tei_lines)
    body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    body_content = re.sub(r'\n\n+', '\n', body_content)
    body_content = body_content.replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '\n<lb/>', body_content)
    body_content = body_content.strip()
    
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
# Volume Processing (Worker Function)
# =============================================================================

def process_volume(args: tuple) -> dict:
    """
    Process a single volume (worker function for multiprocessing).
    
    Args:
        args: Tuple of (ie_id, ve_id, volume_folder, output_dir)
        
    Returns:
        dict with results: {ie_id, ve_id, success, failed, errors}
    """
    ie_id, ve_id, volume_folder, output_dir = args
    
    result = {
        "ie_id": ie_id,
        "ve_id": ve_id,
        "success": 0,
        "failed": 0,
        "errors": []
    }
    
    try:
        rtf_files = get_rtf_files(volume_folder)
        
        if not rtf_files:
            return result
        
        # Create output directories
        archive_dir = output_dir / "archive" / ve_id
        sources_dir = output_dir / "sources" / ve_id
        
        archive_dir.mkdir(parents=True, exist_ok=True)
        sources_dir.mkdir(parents=True, exist_ok=True)
        
        for idx, rtf_path in enumerate(rtf_files):
            ut_id = get_ut_id(ve_id, idx)
            src_path = f"sources/{ve_id}/{rtf_path.name}"
            
            try:
                # Convert to TEI XML
                tei_xml = convert_rtf_to_tei(rtf_path, ie_id, ve_id, ut_id, src_path)
                
                # Write XML
                xml_path = archive_dir / f"{ut_id}.xml"
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(tei_xml)
                
                # Copy RTF to sources
                dest_rtf = sources_dir / rtf_path.name
                shutil.copy2(rtf_path, dest_rtf)
                
                result["success"] += 1
                
            except Exception as e:
                result["failed"] += 1
                result["errors"].append(f"{rtf_path.name}: {str(e)}")
    
    except Exception as e:
        result["errors"].append(f"Volume error: {str(e)}")
    
    return result


# =============================================================================
# Main Processing Functions
# =============================================================================

def process_collection(ie_id: str, toprocess_dir: Path, output_dir: Path, workers: int) -> tuple:
    """
    Process all volumes in a collection using multiprocessing.
    
    Returns:
        Tuple of (total_success, total_failed)
    """
    volumes = get_volume_folders(ie_id, toprocess_dir)
    
    if not volumes:
        logger.warning(f"  No volumes found for {ie_id}")
        return 0, 0
    
    logger.info(f"  Found {len(volumes)} volumes, processing with {workers} workers...")
    
    # Prepare arguments for workers
    work_items = [
        (ie_id, ve_id, volume_folder, output_dir)
        for ve_id, volume_folder in volumes
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
            logger.info(f"    {status} {result['ve_id']}: {result['success']} success, {result['failed']} failed")
            
            if result["errors"]:
                for error in result["errors"][:3]:  # Show max 3 errors
                    logger.error(f"      - {error}")
    
    return total_success, total_failed


def process_all_collections(input_dir: Path, workers: int, ie_filter: str = None):
    """
    Process all collections in the input directory.
    """
    logger.info("=" * 70)
    logger.info("BATCH RTF TO TEI XML CONVERTER")
    logger.info("=" * 70)
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"Workers: {workers}")
    
    # Discover collections
    collections = discover_collections(input_dir)
    
    if ie_filter:
        collections = [(ie_id, tp, out) for ie_id, tp, out in collections if ie_id == ie_filter]
        if not collections:
            logger.error(f"Collection {ie_filter} not found")
            return
    
    logger.info(f"Found {len(collections)} collections to process")
    logger.info("=" * 70)
    
    grand_total_success = 0
    grand_total_failed = 0
    collection_results = []
    
    for idx, (ie_id, toprocess_dir, output_dir) in enumerate(collections):
        logger.info(f"\n[{idx + 1}/{len(collections)}] Processing {ie_id}")
        logger.info(f"  Input: {toprocess_dir}")
        logger.info(f"  Output: {output_dir}")
        
        success, failed = process_collection(ie_id, toprocess_dir, output_dir, workers)
        
        grand_total_success += success
        grand_total_failed += failed
        collection_results.append((ie_id, success, failed))
        
        logger.info(f"  Completed: {success} success, {failed} failed")
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    
    for ie_id, success, failed in collection_results:
        status = "[OK]" if failed == 0 else "[FAIL]"
        logger.info(f"  {status} {ie_id}: {success} success, {failed} failed")
    
    logger.info("-" * 70)
    logger.info(f"TOTAL: {grand_total_success} success, {grand_total_failed} failed")
    logger.info("=" * 70)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Batch convert RTF files to TEI XML with multiprocessing"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=INPUT_DIR,
        help=f"Input directory containing IE collections (default: {INPUT_DIR})"
    )
    parser.add_argument(
        "--ie-id",
        type=str,
        default=None,
        help="Process only this specific IE collection"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})"
    )
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        logger.error(f"Input directory not found: {args.input_dir}")
        sys.exit(1)
    
    process_all_collections(args.input_dir, args.workers, args.ie_id)


if __name__ == "__main__":
    main()
