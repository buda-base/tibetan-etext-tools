#!/usr/bin/env python3
"""
Convert RTF files to TEI XML format (Unicode pipeline with multiprocessing).

Input structure:
    {IE_ID}/toprocess/{IE_ID-VE_ID}/*.rtf
    Example: IE1KG4310/toprocess/IE1KG4310-VE1KG4310/*.rtf

Output structure:
    Archive (flat): {IE_ID}_output/archive/{VE_ID}/UT{suffix}_{FILE_NUM}.xml
    Sources (nested): {IE_ID}_output/sources/{IE_ID-VE_ID}/*.rtf

Usage:
    # Process all IE_ID-VE_ID folders in current directory (auto-detects IE_ID):
    python convert_uni.py

    # Process specific directory (auto-detects IE_ID):
    python convert_uni.py /path/to/IE1KG4310

    # Process only a specific VE_ID:
    python convert_uni.py --ve-id VE1KG4310_001

    # Process with explicit IE_ID override:
    python convert_uni.py /path/to/folder --ie-id IE1KG4310

    # Adjust worker count:
    python convert_uni.py --workers 4
"""

import sys
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
from text_cleaning import remove_non_tibetan


# =============================================================================
# Configuration
# =============================================================================

# Number of parallel workers (default: CPU count - 1, min 1)
DEFAULT_WORKERS = max(1, multiprocessing.cpu_count() - 1)


# =============================================================================
# Discovery Functions
# =============================================================================

def get_volume_folders(ie_id: str, toprocess_dir: Path) -> list:
    """
    Get list of volume folders from toprocess directory.

    Structure: {IE_ID}/toprocess/{IE_ID-VE_ID}/*.rtf
    Each subfolder is named {IE_ID-VE_ID}; VE_ID is extracted for UT IDs.

    Returns:
        List of (ve_id, volume_id, rtf_folder_path, collection_name) tuples
    """
    volumes = []

    for folder in toprocess_dir.iterdir():
        if not folder.is_dir() or folder.name.startswith('.'):
            continue

        # Folder name is IE_ID-VE_ID (e.g. IE1KG4310-VE1KG4310_001)
        name = folder.name
        ve_id = name.split("-", 1)[1] if "-" in name else name

        rtf_files = list(folder.glob("*.rtf"))
        if rtf_files:
            volumes.append((ve_id, None, folder, None))

    return natsorted(volumes, key=lambda x: (x[0], x[1] or ''))


def detect_ie_id(base_dir: Path) -> str:
    """
    Auto-detect IE_ID from base directory name.

    Args:
        base_dir: Base directory path

    Returns:
        IE_ID string (e.g., "IE1GS58442")
    """
    dir_name = base_dir.name
    ie_match = re.match(r'(IE[A-Z0-9]+)', dir_name, re.IGNORECASE)
    if ie_match:
        return ie_match.group(1).upper()
    raise ValueError(
        f"Could not detect IE_ID from directory name: {dir_name}\n"
        f"Expected format: IE followed by alphanumeric characters (e.g., IE1GS58442)"
    )


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
    Convert RTF file to TEI XML with noise filtering.
    """
    # Parse RTF
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()

    # Classify font sizes
    classifications = classify_font_sizes(streams)
    # Process streams and build content
    tei_lines = []
    current_markup = None
    
    for stream in streams:
        text = stream.get("text", "")
        font_size = stream.get("font", {}).get("size", 12)
    
        # Skip standard RTF non-text elements
        if stream.get("type") in ("header", "footer", "pict"):
            continue
        cleaned_text = remove_non_tibetan(text)
        normalized_text = normalize_unicode(cleaned_text)
        
        if not normalized_text.strip():
            continue
        
        escaped_text = escape_xml(normalized_text)
        classification = classifications.get(font_size, 'regular')
        
        if classification != current_markup:
            if current_markup in ('small', 'large'):
                tei_lines.append('</hi>')
            
            if classification == 'small':
                tei_lines.append('<hi rend="small">')
            elif classification == 'large':
                tei_lines.append('<hi rend="head">')
            
            current_markup = classification if classification != 'regular' else None
        
        tei_lines.append(escaped_text)
    
    if current_markup in ('small', 'large'):
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
        args: Tuple of (ie_id, ve_id, volume_id, volume_folder, output_dir, collection_name)

    Returns:
        dict with results: {ve_id, volume_label, success, failed, errors}
    """
    ie_id, ve_id, volume_id, volume_folder, output_dir, collection_name = args

    volume_label = f"{ve_id}_{volume_id}" if volume_id else ve_id

    result = {
        "ve_id": ve_id,
        "volume_id": volume_id,
        "volume_label": volume_label,
        "success": 0,
        "failed": 0,
        "errors": []
    }

    try:
        rtf_files = get_rtf_files(volume_folder)

        if not rtf_files:
            return result

        # Archive (flat): archive/{VE_ID}/; sources (nested): sources/{IE_ID-VE_ID}/
        folder_id = f"{ie_id}-{ve_id}"
        archive_dir = output_dir / "archive" / ve_id
        sources_output_dir = output_dir / "sources" / folder_id

        archive_dir.mkdir(parents=True, exist_ok=True)
        sources_output_dir.mkdir(parents=True, exist_ok=True)

        for file_index, rtf_file in enumerate(rtf_files):
            ut_id = get_ut_id(ve_id, file_index)
            src_path = f"{folder_id}/{rtf_file.name}"

            try:
                tei_xml = convert_rtf_to_tei(rtf_file, ie_id, ve_id, ut_id, src_path)

                archive_file = archive_dir / f"{ut_id}.xml"
                archive_file.write_text(tei_xml, encoding='utf-8')

                dest_rtf = sources_output_dir / rtf_file.name
                shutil.copy2(rtf_file, dest_rtf)

                doc_file = rtf_file.with_suffix('.doc')
                if doc_file.exists():
                    dest_doc = sources_output_dir / doc_file.name
                    shutil.copy2(doc_file, dest_doc)
                else:
                    doc_file = rtf_file.with_suffix('.DOC')
                    if doc_file.exists():
                        dest_doc = sources_output_dir / doc_file.name
                        shutil.copy2(doc_file, dest_doc)

                result["success"] += 1

            except Exception as e:
                result["failed"] += 1
                result["errors"].append(f"{rtf_file.name}: {str(e)}")

    except Exception as e:
        result["errors"].append(f"Volume error: {str(e)}")

    return result


# =============================================================================
# Main Processing Functions
# =============================================================================

def process_collection(ie_id: str, base_dir: Path, workers: int, ve_id_filter: str = None) -> tuple:
    """
    Process a single collection (all volumes under toprocess).

    Args:
        ie_id: Image Entity ID
        base_dir: Base directory containing toprocess folder
        workers: Number of parallel workers
        ve_id_filter: Optional VE_ID to process only a specific volume entity

    Returns:
        Tuple of (total_success, total_failed)
    """
    toprocess_dir = base_dir / "toprocess"
    output_dir = base_dir / f"{ie_id}_output"

    volumes = get_volume_folders(ie_id, toprocess_dir)

    if ve_id_filter:
        volumes = [v for v in volumes if v[0] == ve_id_filter]
        if not volumes:
            logger.warning(f"  No volumes found for VE_ID: {ve_id_filter}")
            return 0, 0

    if not volumes:
        logger.warning(f"  No volumes found in {toprocess_dir}")
        return 0, 0

    logger.info(f"  Found {len(volumes)} volumes, processing with {workers} workers...")

    work_items = [
        (ie_id, ve_id, volume_id, volume_folder, output_dir, collection_name)
        for ve_id, volume_id, volume_folder, collection_name in volumes
    ]

    total_success = 0
    total_failed = 0

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_volume, item): item for item in work_items}

        for future in as_completed(futures):
            result = future.result()
            total_success += result["success"]
            total_failed += result["failed"]

            status = "[OK]" if result["failed"] == 0 else "[FAIL]"
            logger.info(f"    {status} {result['volume_label']}: {result['success']} success, {result['failed']} failed")

            if result["errors"]:
                for error in result["errors"][:3]:
                    logger.error(f"      - {error}")

    return total_success, total_failed


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Convert RTF files to TEI XML format (Unicode pipeline with multiprocessing)"
    )
    parser.add_argument(
        "base_dir",
        type=Path,
        nargs='?',
        default=None,
        help="Base directory containing toprocess folder (e.g., /path/to/IE1KG4310)"
    )
    parser.add_argument(
        "--ie-id",
        type=str,
        default=None,
        help="Override IE_ID (auto-detected from directory name if not provided)"
    )
    parser.add_argument(
        "--ve-id",
        type=str,
        default=None,
        help="Process only a specific VE_ID (e.g., VE1PD45495_001)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})"
    )

    args = parser.parse_args()

    if args.base_dir is None:
        base_dir = Path.cwd()
    else:
        base_dir = args.base_dir

    if not base_dir.exists():
        logger.error(f"Base directory not found: {base_dir}")
        sys.exit(1)

    toprocess_dir = base_dir / "toprocess"
    if not toprocess_dir.exists():
        logger.error(f"Toprocess directory not found: {toprocess_dir}")
        logger.error(f"Expected structure: {base_dir}/toprocess/{{IE_ID-VE_ID}}/*.rtf")
        sys.exit(1)

    if args.ie_id:
        ie_id = args.ie_id.upper()
    else:
        try:
            ie_id = detect_ie_id(base_dir)
            logger.info(f"Auto-detected IE_ID: {ie_id}")
        except ValueError as e:
            logger.error(str(e))
            sys.exit(1)

    logger.info("=" * 70)
    logger.info(f"{ie_id} RTF TO TEI XML CONVERTER (Unicode)")
    logger.info("=" * 70)
    logger.info(f"Base directory: {base_dir}")
    logger.info(f"Workers: {args.workers}")
    if args.ve_id:
        logger.info(f"  Filtering for VE_ID: {args.ve_id}")
    logger.info(f"  Input: {toprocess_dir}")
    logger.info(f"  Output: {base_dir / f'{ie_id}_output'}")
    logger.info("")

    success, failed = process_collection(ie_id, base_dir, args.workers, ve_id_filter=args.ve_id)

    logger.info("")
    logger.info(f"Summary for {ie_id}:")
    logger.info(f"  Total files processed: {success + failed}")
    logger.info(f"  Succeeded: {success}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Output: {base_dir / f'{ie_id}_output'}")
    logger.info("")
    logger.info("=" * 70)
    logger.info("CONVERSION COMPLETE")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
