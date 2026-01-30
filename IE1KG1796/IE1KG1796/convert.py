#!/usr/bin/env python3
"""
Batch RTF to TEI XML Converter with Multiprocessing.

This script processes multiple IE collections in parallel, converting RTF/DOC files
to TEI XML format. It auto-discovers collections and handles various folder structures,
including non-standard layouts.

Input structure (expected):
    rtf/{IE_ID}/{IE_ID}/toprocess/{IE_ID}-{VE_ID}/*.rtf
    rtf/{IE_ID}/toprocess/{IE_ID}-{VE_ID}/*.rtf

Input structure (fallback - will prompt user):
    Any structure with RTF/DOC files found recursively

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
    
    # Skip confirmation prompts:
    python convert.py --yes
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
from collections import Counter, defaultdict
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

# Supported file extensions
SUPPORTED_EXTENSIONS = {'.rtf', '.doc'}


# =============================================================================
# Discovery Functions
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


def extract_ve_id_from_path(file_path: Path, ie_id: str) -> str:
    """
    Try to extract VE ID from file path or folder structure.
    
    Looks for patterns like:
    - {IE_ID}-{VE_ID}/file.rtf
    - VE{ID}/file.rtf
    - folder names containing VE pattern
    - numeric patterns that might be volume numbers
    
    Returns:
        VE ID string, or "UNKNOWN_{hash}" if not found (hash ensures unique grouping)
    """
    parts = file_path.parts
    
    # Look for {IE_ID}-{VE_ID} pattern in path
    for part in parts:
        if part.startswith(f'{ie_id}-'):
            ve_id = part.replace(f'{ie_id}-', '')
            if ve_id:
                return ve_id if ve_id.startswith('VE') else f'VE{ve_id}'
    
    # Look for VE pattern directly
    for part in parts:
        if part.startswith('VE') and len(part) > 2:
            # Validate it looks like a VE ID (has alphanumeric content)
            if any(c.isalnum() for c in part[2:]):
                return part
    
    # Look in parent folder names (check up to 5 levels up)
    parent = file_path.parent
    for _ in range(5):
        if parent.name:
            name = parent.name
            # Check for {IE_ID}-{VE_ID} pattern
            if name.startswith(f'{ie_id}-'):
                ve_id = name.replace(f'{ie_id}-', '')
                if ve_id:
                    return ve_id if ve_id.startswith('VE') else f'VE{ve_id}'
            # Check for VE pattern
            elif name.startswith('VE') and len(name) > 2:
                if any(c.isalnum() for c in name[2:]):
                    return name
            # Check for volume-like patterns (e.g., "vol1", "volume_001")
            elif re.match(r'vol(ume)?[_\s]?(\d+)', name, re.I):
                match = re.search(r'(\d+)', name)
                if match:
                    return f'VE{match.group(1).zfill(3)}'
        parent = parent.parent
        if parent == parent.parent:  # Reached root
            break
    
    # Last resort: use parent folder name as identifier (with hash for uniqueness)
    parent_name = file_path.parent.name
    if parent_name and parent_name not in ('', '.', '..'):
        # Create a simple hash from parent path for grouping
        path_str = str(file_path.parent)
        path_hash = hashlib.md5(path_str.encode()).hexdigest()[:8]
        return f"UNKNOWN_{path_hash}"
    
    # Final fallback
    path_hash = hashlib.md5(str(file_path).encode()).hexdigest()[:8]
    return f"UNKNOWN_{path_hash}"


def group_files_by_volume(files: list, ie_id: str) -> dict:
    """
    Group files by inferred volume ID.
    
    Returns:
        Dictionary mapping ve_id -> list of file paths
    """
    volumes = defaultdict(list)
    
    for file_path in files:
        ve_id = extract_ve_id_from_path(file_path, ie_id)
        volumes[ve_id].append(file_path)
    
    return volumes


def is_standard_structure(ie_folder: Path, ie_id: str) -> bool:
    """
    Check if folder follows standard structure.
    
    Standard structures:
    - {IE_ID}/{IE_ID}/toprocess/{IE_ID}-{VE_ID}/*.rtf
    - {IE_ID}/toprocess/{IE_ID}-{VE_ID}/*.rtf
    """
    nested_path = ie_folder / ie_id / "toprocess"
    direct_path = ie_folder / "toprocess"
    
    if nested_path.exists() or direct_path.exists():
        return True
    
    return False


def prompt_user_confirmation(ie_id: str, file_count: int, structure_info: str) -> bool:
    """
    Prompt user for confirmation when files found in non-standard structure.
    
    Returns:
        True if user confirms, False otherwise
    """
    print("\n" + "=" * 70)
    print(f"⚠️  NON-STANDARD STRUCTURE DETECTED")
    print("=" * 70)
    print(f"Collection: {ie_id}")
    print(f"Files found: {file_count}")
    print(f"\nStructure details:")
    print(structure_info)
    print("\n" + "-" * 70)
    print("The script found RTF/DOC files in a non-standard folder structure.")
    print("It will attempt to process them, but volume IDs may need manual verification.")
    print("-" * 70)
    
    while True:
        response = input("\nContinue processing? [y/N]: ").strip().lower()
        if response in ('y', 'yes'):
            return True
        elif response in ('n', 'no', ''):
            return False
        else:
            print("Please enter 'y' or 'n'")


def discover_collections_fallback(ie_folder: Path, ie_id: str) -> tuple:
    """
    Fallback discovery: recursively find RTF/DOC files when structure is non-standard.
    
    Returns:
        Tuple of (toprocess_info_dict, structure_description) or (None, None) if no files
    """
    # Find all RTF/DOC files recursively
    all_files = find_files_recursive(ie_folder)
    
    if not all_files:
        return None, None
    
    # Filter out files in output directories
    all_files = [f for f in all_files if '_output' not in f.parts]
    
    if not all_files:
        return None, None
    
    # Group by inferred volume
    volumes = group_files_by_volume(all_files, ie_id)
    
    # Build structure description
    structure_info = f"Found files in:\n"
    for ve_id, files in sorted(volumes.items()):
        sample_path = files[0].relative_to(ie_folder)
        structure_info += f"  {ve_id}: {len(files)} files (e.g., {sample_path.parent})\n"
    
    # Create a structure that mimics standard format
    # We'll use the file paths directly, grouping by inferred VE_ID
    toprocess_info = {}
    for ve_id, files in volumes.items():
        # Sort files naturally
        sorted_files = natsorted(files, key=lambda p: p.name)
        toprocess_info[ve_id] = sorted_files
    
    return toprocess_info, structure_info

def discover_collections(input_dir: Path, auto_confirm: bool = False) -> list:
    """
    Discover all IE collections in the input directory.
    Only includes collections that haven't been processed yet (no output directory).
    Handles both standard and non-standard folder structures.
    
    Args:
        input_dir: Directory containing IE collections
        auto_confirm: If True, skip confirmation prompts for non-standard structures
    
    Returns:
        List of (ie_id, toprocess_info, output_dir, is_standard) tuples
        where toprocess_info is either:
        - Path (for standard structure)
        - dict mapping ve_id -> list of file paths (for non-standard)
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
        
        # Check for standard structure first
        nested_path = ie_folder / ie_id / "toprocess"
        direct_path = ie_folder / "toprocess"
        
        if nested_path.exists():
            collections.append((ie_id, nested_path, output_dir, True))
            continue
        
        if direct_path.exists():
            collections.append((ie_id, direct_path, output_dir, True))
            continue
        
        # Fallback: try to find files recursively
        toprocess_info, structure_info = discover_collections_fallback(ie_folder, ie_id)
        
        if toprocess_info:
            # Prompt user for confirmation unless auto_confirm is True
            if not auto_confirm:
                file_count = sum(len(files) for files in toprocess_info.values())
                if not prompt_user_confirmation(ie_id, file_count, structure_info):
                    logger.info(f"Skipping {ie_id} - user declined to process non-standard structure")
                    continue
            
            collections.append((ie_id, toprocess_info, output_dir, False))
    
    if skipped:
        logger.info(f"Skipped {len(skipped)} already-processed collections: {', '.join(skipped)}")
    
    return natsorted(collections, key=lambda x: x[0])


def get_volume_folders(ie_id: str, toprocess_dir: Path) -> list:
    """
    Get list of volume folders from toprocess directory (standard structure).
    
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
    """
    Get sorted list of RTF/DOC files in a volume folder.
    
    Supports both .rtf and .doc files (though .doc files may not parse correctly
    if they're binary Word format rather than RTF format).
    """
    files = []
    for ext in SUPPORTED_EXTENSIONS:
        files.extend(volume_folder.glob(f"*{ext}"))
        files.extend(volume_folder.glob(f"*{ext.upper()}"))
    
    return natsorted(files, key=lambda p: p.name)


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
        args: Tuple of (ie_id, ve_id, file_list_or_folder, output_dir, is_standard)
              where file_list_or_folder is either:
              - Path (folder) for standard structure
              - list of Path (files) for non-standard structure
        
    Returns:
        dict with results: {ie_id, ve_id, success, failed, errors}
    """
    if len(args) == 5:
        ie_id, ve_id, file_list_or_folder, output_dir, is_standard = args
    else:
        # Backward compatibility
        ie_id, ve_id, file_list_or_folder, output_dir = args
        is_standard = True
    
    result = {
        "ie_id": ie_id,
        "ve_id": ve_id,
        "success": 0,
        "failed": 0,
        "errors": []
    }
    
    try:
        # Get file list
        if isinstance(file_list_or_folder, Path):
            # Standard structure: folder path
            rtf_files = get_rtf_files(file_list_or_folder)
        elif isinstance(file_list_or_folder, list):
            # Non-standard structure: list of file paths
            rtf_files = file_list_or_folder
        else:
            result["errors"].append(f"Invalid file_list_or_folder type: {type(file_list_or_folder)}")
            return result
        
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
                
                # Copy source file to sources directory
                dest_file = sources_dir / rtf_path.name
                shutil.copy2(rtf_path, dest_file)
                
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

def process_collection(ie_id: str, toprocess_info, output_dir: Path, workers: int, is_standard: bool = True) -> tuple:
    """
    Process all volumes in a collection using multiprocessing.
    
    Args:
        ie_id: Collection ID
        toprocess_info: Either Path (standard) or dict mapping ve_id -> file list (non-standard)
        output_dir: Output directory
        workers: Number of parallel workers
        is_standard: Whether using standard folder structure
    
    Returns:
        Tuple of (total_success, total_failed)
    """
    if is_standard:
        # Standard structure: toprocess_info is a Path
        toprocess_dir = toprocess_info
        volumes = get_volume_folders(ie_id, toprocess_dir)
        
        if not volumes:
            logger.warning(f"  No volumes found for {ie_id}")
            return 0, 0
        
        logger.info(f"  Found {len(volumes)} volumes, processing with {workers} workers...")
        
        # Prepare arguments for workers
        work_items = [
            (ie_id, ve_id, volume_folder, output_dir, True)
            for ve_id, volume_folder in volumes
        ]
    else:
        # Non-standard structure: toprocess_info is a dict
        volumes_dict = toprocess_info
        
        if not volumes_dict:
            logger.warning(f"  No volumes found for {ie_id}")
            return 0, 0
        
        logger.info(f"  Found {len(volumes_dict)} volumes (non-standard structure), processing with {workers} workers...")
        
        # Prepare arguments for workers
        work_items = [
            (ie_id, ve_id, file_list, output_dir, False)
            for ve_id, file_list in sorted(volumes_dict.items())
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


def process_all_collections(input_dir: Path, workers: int, ie_filter: str = None, auto_confirm: bool = False):
    """
    Process all collections in the input directory.
    
    Args:
        input_dir: Directory containing IE collections
        workers: Number of parallel workers
        ie_filter: Optional IE ID to filter to single collection
        auto_confirm: If True, skip confirmation prompts for non-standard structures
    """
    logger.info("=" * 70)
    logger.info("BATCH RTF TO TEI XML CONVERTER")
    logger.info("=" * 70)
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"Workers: {workers}")
    if auto_confirm:
        logger.info("Auto-confirm mode: skipping prompts for non-standard structures")
    
    # Discover collections
    collections = discover_collections(input_dir, auto_confirm=auto_confirm)
    
    if ie_filter:
        collections = [(ie_id, tp, out, std) for ie_id, tp, out, std in collections if ie_id == ie_filter]
        if not collections:
            logger.error(f"Collection {ie_filter} not found")
            return
    
    logger.info(f"Found {len(collections)} collections to process")
    logger.info("=" * 70)
    
    grand_total_success = 0
    grand_total_failed = 0
    collection_results = []
    
    for idx, (ie_id, toprocess_info, output_dir, is_standard) in enumerate(collections):
        logger.info(f"\n[{idx + 1}/{len(collections)}] Processing {ie_id}")
        
        if is_standard:
            logger.info(f"  Input: {toprocess_info} (standard structure)")
        else:
            logger.info(f"  Input: Non-standard structure (files found recursively)")
            total_files = sum(len(files) for files in toprocess_info.values()) if isinstance(toprocess_info, dict) else 0
            logger.info(f"  Files: {total_files} files in {len(toprocess_info)} volumes")
        
        logger.info(f"  Output: {output_dir}")
        
        success, failed = process_collection(ie_id, toprocess_info, output_dir, workers, is_standard)
        
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
        description="Batch convert RTF/DOC files to TEI XML with multiprocessing. "
                    "Handles both standard and non-standard folder structures."
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
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts for non-standard folder structures"
    )
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        logger.error(f"Input directory not found: {args.input_dir}")
        sys.exit(1)
    
    process_all_collections(args.input_dir, args.workers, args.ie_id, auto_confirm=args.yes)


if __name__ == "__main__":
    main()
