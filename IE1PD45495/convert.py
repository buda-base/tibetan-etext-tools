#!/usr/bin/env python3
"""
Batch RTF to TEI XML Converter for IE1PD45495 with Multiprocessing.

Input structure:    
    {IE_ID}/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf

Output structure:
    Archive (flat): {IE_ID}_output/archive/{VE_ID}/UT{suffix}_{index}.xml
    Sources (nested): {IE_ID}_output/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf

Architecture (4-stage pipeline):
    Stage 1: RTF Parsing (basic_rtf.py)
    Stage 2: Dedris → Unicode Conversion (pytiblegenc)
    Stage 3: Normalization (normalization.py, tibetan_text_fixes.py)
    Stage 4: TEI XML Generation (convert_try.py)

Usage:
    # Process all collections:
    python convert_try.py
    
    # Process specific collection:
    python convert_try.py --ie-id IE1PD45495
    
    # Adjust worker count:
    python convert_try.py --workers 4
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

# Stage 1: RTF Parsing
from basic_rtf import BasicRTF

# Stage 3: Normalization
from normalization import normalize_unicode, normalize_spaces
from tibetan_text_fixes import (
    fix_flying_vowels_and_linebreaks,
    fix_hi_tag_spacing,
    count_tibetan_chars,
)

# Text Cleaning
from text_cleaning import remove_page_markers, normalize_guillemets

# Stage 2: Dedris Conversion
try:
    from pytiblegenc import convert_string
except ImportError as e:
    raise ImportError(
        "pytiblegenc is required. Install with:\n"
        "  pip install -U git+https://github.com/buda-base/py-tiblegenc.git"
    ) from e


# =============================================================================
# Configuration
# =============================================================================

# Default input directory containing all IE collections
INPUT_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/file_convert_1/")

# Number of parallel workers (default: CPU count - 1, min 1)
DEFAULT_WORKERS = max(1, multiprocessing.cpu_count() - 1)

# Enable/disable processing stages
ENABLE_FONT_CLASSIFICATION = False   # Stage 4: Font size classification (ENABLED)
ENABLE_NORMALIZATION = True         # Stage 3: Text normalization


# =============================================================================
# Discovery Functions
# =============================================================================

def discover_collections(input_dir: Path) -> list:
    """
    Discover all IE collections in the input directory.
    
    Returns:
        List of (ie_id, sources_dir, output_dir) tuples
    """
    collections = []
    
    for ie_folder in input_dir.iterdir():
        if not ie_folder.is_dir():
            continue
            
        ie_id = ie_folder.name
        
        # Skip output directories
        if ie_id.endswith('_output'):
            continue
        
        # Check for sources directory
        sources_path = ie_folder / "sources"
        if sources_path.exists():
            output_dir = ie_folder / f"{ie_id}_output"
            collections.append((ie_id, sources_path, output_dir))
    
    return natsorted(collections, key=lambda x: x[0])


def discover_volumes(sources_dir: Path) -> list:
    """
    Discover all volumes in a sources directory.
    
    Expected structure:
        sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf
    
    Returns:
        List of (ve_id, collection_name, vol_id, rtf_files) tuples
    """
    volumes = []
    
    for ve_folder in sources_dir.iterdir():
        if not ve_folder.is_dir():
            continue
            
        ve_id = ve_folder.name
        
        # Look for collection folders
        for collection_folder in ve_folder.iterdir():
            if not collection_folder.is_dir():
                continue
                
            collection_name = collection_folder.name
            rtfs_folder = collection_folder / "rtfs"
            
            if not rtfs_folder.exists():
                continue
            
            # Look for volume folders
            for vol_folder in rtfs_folder.iterdir():
                if not vol_folder.is_dir():
                    continue
                    
                vol_id = vol_folder.name
                rtf_files = list(vol_folder.glob("*.rtf"))
                
                if rtf_files:
                    volumes.append((ve_id, collection_name, vol_id, rtf_files))
    
    return natsorted(volumes, key=lambda x: (x[0], x[1], x[2]))


# Text cleaning functions are now imported from text_cleaning module
# See text_cleaning.py for implementation details


# =============================================================================
# Stage 2: Dedris to Unicode Conversion
# =============================================================================

def dedris_to_unicode(text: str, font_name: str, stats: dict) -> str:
    """
    Convert Dedris encoded string to Unicode using pytiblegenc.
    
    Handles both:
    - Dedris legacy fonts (need conversion)
    - Unicode fonts like TibetanMachineUnicode (already Unicode, no conversion needed)
    
    Args:
        text: Text in Dedris encoding or Unicode
        font_name: Font name from RTF (e.g., "Dedris-a", "TibetanMachineUnicode")
        stats: Statistics dictionary for tracking conversion
        
    Returns:
        Unicode text
    """
    if not text or not text.strip():
        return text
    
    # IMPORTANT: Clean text BEFORE conversion
    # Remove page markers like "-PAGE 138-" that would be incorrectly converted to Tibetan
    text = remove_page_markers(text)
    
    # Unicode fonts that don't need conversion
    UNICODE_FONTS = (
        'tibetanmachineunicode', 'tibetan machine unicode',
        'microsoft himalaya', 'jomolhari', 'monlam uni',
        'ddcuchen', 'tibetan unicode'
    )
    
    # Fonts that might contain Dedris-encoded characters due to font attribution errors
    # In mixed files, Times New Roman, Arial, etc. are often used for Dedris text
    SUSPICIOUS_FONTS = (
        'simsun', '@simsun', 'simsun western',
        'times new roman', 'arial', 'courier new'
    )
    
    # Check font type
    font_lower = font_name.lower() if font_name else ''
    is_unicode = any(uf in font_lower for uf in UNICODE_FONTS)
    is_dedris = font_lower.startswith(('dedris', 'ededris'))
    is_suspicious = font_lower in SUSPICIOUS_FONTS
    
    # If it's already Unicode, return as-is
    if is_unicode:
        return text
    
    # Check if text contains ASCII characters that might be Dedris
    # Dedris uses ASCII characters like :)3.0=$>/ for Tibetan
    has_ascii_dedris = any(c in text for c in ':)3.0=$>/eి-,;!?@#%^&*()[]{}')
    
    # If it's not Dedris and not suspicious, and doesn't have Dedris-like ASCII, return as-is
    if not is_dedris and not is_suspicious and not has_ascii_dedris:
        return text
    
    # For suspicious fonts (like SimSun), try converting as Dedris-a
    effective_font = font_name if is_dedris else 'Dedris-a'
    
    try:
        result = convert_string(text, effective_font, stats)
        if result is None:
            return text
        return result
    except Exception as e:
        logger.warning(f"Error converting with font {effective_font}: {e}")
        return text


# =============================================================================
# Stage 4: Font Size Classification (Optional)
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
        tibetan_chars = count_tibetan_chars(text)
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
# RTF to TEI Conversion (4-Stage Pipeline)
# =============================================================================

def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def convert_rtf_to_tei(rtf_path: Path, ve_id: str, ut_id: str, ie_id: str, 
                       sources_dir: Path) -> str:
    """
    Convert RTF file to TEI XML using 4-stage pipeline.
    
    Stage 1: RTF Parsing (basic_rtf.py)
    Stage 2: Dedris → Unicode Conversion (pytiblegenc)
    Stage 3: Normalization (normalization.py, tibetan_text_fixes.py)
    Stage 4: TEI XML Generation
    
    Args:
        rtf_path: Path to RTF file
        ve_id: Volume Entity ID
        ut_id: Unit Text ID
        ie_id: Image Entity ID
        sources_dir: Base sources directory for relative path calculation
        
    Returns:
        TEI XML string
    """
    # =========================================================================
    # STAGE 1: RTF Parsing
    # =========================================================================
    logger.info(f"  Parsing RTF file: {rtf_path.name}")
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    logger.info(f"  Parsed {len(streams)} text streams")
    
    # =========================================================================
    # STAGE 2: Dedris → Unicode Conversion
    # =========================================================================
    stats = {
        "handled_fonts": {},
        "unhandled_fonts": {},
        "unknown_characters": {},
        "diffs_with_utfc": {},
        "error_characters": 0
    }
    
    converted_streams = []
    for stream in streams:
        # Skip special types (headers, footers, images, etc.)
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
            continue
        
        text = stream.get("text", "")
        font_name = stream.get("font", {}).get("name", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        # Convert Dedris to Unicode
        unicode_text = dedris_to_unicode(text, font_name, stats)
        
        if not unicode_text:
            continue
        
        converted_streams.append({
            "text": unicode_text,
            "font_size": font_size
        })
    
    logger.info(f"  Stage 2: Converted {len(converted_streams)} streams to Unicode")
    
    # =========================================================================
    # STAGE 2.4: Normalize guillemet font sizes
    # =========================================================================
    # Treat all guillemet-only streams as regular font to avoid <hi> tags around ««
    if ENABLE_FONT_CLASSIFICATION:
        # First, find the most common font size (this will be "regular")
        from collections import Counter
        size_counts = Counter()
        for item in converted_streams:
            text = item.get("text", "")
            font_size = item.get("font_size", 12)
            tibetan_chars = count_tibetan_chars(text)
            if tibetan_chars > 0:
                size_counts[font_size] += tibetan_chars
        
        if size_counts:
            regular_size = max(size_counts.items(), key=lambda x: x[1])[0]
            
            # Normalize font size for guillemet-only streams
            for item in converted_streams:
                text = item.get("text", "").strip()
                # Check if stream contains only guillemets (and optional whitespace)
                if text and all(c in '«»\n\r\t ' for c in text):
                    item["font_size"] = regular_size
                    logger.debug(f"  Normalized guillemet stream font size to {regular_size}")
    
    # =========================================================================
    # STAGE 2.5: Font Size Classification (optional)
    # =========================================================================
    if ENABLE_FONT_CLASSIFICATION:
        classifications = classify_font_sizes(converted_streams)
        if classifications:
            logger.info(f"  Font classifications: {classifications}")
    else:
        classifications = {}
    
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
    
    # Join all content
    body_content = ''.join(tei_lines)
    
    # Clean up empty hi tags
    if ENABLE_FONT_CLASSIFICATION:
        body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    # =========================================================================
    # STAGE 3: Normalization
    # =========================================================================
    if ENABLE_NORMALIZATION:
        logger.info(f"  Stage 3: Applying normalization...")
        
        # Fix flying vowels and improper line breaks
        body_content = fix_flying_vowels_and_linebreaks(body_content)
        
        # Apply full Unicode normalization (includes Tibetan-specific reordering)
        body_content = normalize_unicode(body_content)
        
        # Normalize spaces (collapse multiple spaces, apply Tibetan-specific rules)
        body_content = normalize_spaces(body_content)
        
        # Normalize guillemets (handles duplicates from RTF parsing/stream joining)
        body_content = normalize_guillemets(body_content)
        
        # Fix spacing around <hi> tags based on Tibetan punctuation rules
        if ENABLE_FONT_CLASSIFICATION:
            body_content = fix_hi_tag_spacing(body_content)
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
    # FIX <hi> TAG PLACEMENT (if font classification enabled)
    # =========================================================================
    if ENABLE_FONT_CLASSIFICATION:
        # Remove <hi> tags that contain only whitespace/newlines/lb tags
        body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', '', body_content)
        
        # Move <hi> from end of line to after <lb/> on next line
        body_content = re.sub(r'(<hi rend="[^"]+">)\s*\n<lb/>', r'\n<lb/>\1', body_content)
        
        # Move </hi> from after <lb/> to before the newline
        body_content = re.sub(r'\n<lb/></hi>', r'</hi>\n<lb/>', body_content)
        
        # Clean up any remaining empty <hi> tags
        body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', '', body_content)
    
    # Remove double newlines
    body_content = re.sub(r'\n\n+', '\n', body_content)
    body_content = body_content.strip()
    
    # =========================================================================
    # STAGE 4: GENERATE TEI XML
    # =========================================================================
    sha256 = calculate_sha256(rtf_path)
    
    # Generate relative source path from sources directory
    try:
        src_path = str(rtf_path.relative_to(sources_dir.parent))
    except ValueError:
        src_path = str(rtf_path)
    
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
# Volume Processing
# =============================================================================

def process_volume(args):
    """
    Process a single volume (worker function for multiprocessing).
    
    Args:
        args: Tuple of (ve_id, collection_name, vol_id, rtf_files, output_dir, ie_id, sources_dir)
        
    Returns:
        Tuple of (vol_id, success_count, failed_count)
    """
    ve_id, collection_name, vol_id, rtf_files, output_dir, ie_id, sources_dir = args
    
    success = 0
    failed = 0
    
    # Create output directories
    archive_dir = output_dir / "archive" / ve_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    
    sources_out_dir = output_dir / "sources" / ve_id / collection_name / "rtfs" / vol_id
    sources_out_dir.mkdir(parents=True, exist_ok=True)
    
    # Process each RTF file
    for rtf_file in natsorted(rtf_files, key=lambda p: p.name):
        try:
            # Generate UT ID from filename
            # Assuming format: {prefix}_{index}.rtf
            stem = rtf_file.stem
            match = re.search(r'_(\d+)$', stem)
            if match:
                index = match.group(1)
            else:
                index = "0001"
            
            # Extract suffix from VE ID (e.g., VE3KG466 -> 3KG466)
            ve_suffix = ve_id[2:] if ve_id.startswith('VE') else ve_id
            ut_id = f"UT{ve_suffix}_{index}"
            
            # Convert RTF to TEI using 4-stage pipeline
            tei_xml = convert_rtf_to_tei(rtf_file, ve_id, ut_id, ie_id, sources_dir)
            
            # Write XML to archive
            xml_path = archive_dir / f"{ut_id}.xml"
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(tei_xml)
            
            # Copy RTF to sources output
            dest_rtf = sources_out_dir / rtf_file.name
            shutil.copy2(rtf_file, dest_rtf)
            
            success += 1
            
        except Exception as e:
            logger.error(f"  Error processing {rtf_file.name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    return (vol_id, success, failed)


# =============================================================================
# Main Processing
# =============================================================================

def process_collection(ie_id: str, sources_dir: Path, output_dir: Path, workers: int):
    """
    Process a single IE collection.
    
    Args:
        ie_id: Image Entity ID
        sources_dir: Path to sources directory
        output_dir: Path to output directory
        workers: Number of parallel workers
    """
    logger.info(f"  Input: {sources_dir}")
    logger.info(f"  Output: {output_dir}")
    
    # Discover volumes
    volumes = discover_volumes(sources_dir)
    
    if not volumes:
        logger.warning(f"  No volumes found in {sources_dir}")
        return
    
    logger.info(f"  Found {len(volumes)} volumes, processing with {workers} workers...")
    
    # Prepare arguments for workers
    worker_args = [
        (ve_id, collection_name, vol_id, rtf_files, output_dir, ie_id, sources_dir)
        for ve_id, collection_name, vol_id, rtf_files in volumes
    ]
    
    # Process volumes in parallel
    total_success = 0
    total_failed = 0
    
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_volume, args): args for args in worker_args}
        
        for future in as_completed(futures):
            try:
                vol_id, success, failed = future.result()
                total_success += success
                total_failed += failed
                
                status = "[OK]" if failed == 0 else "[PARTIAL]"
                logger.info(f"    {status} {vol_id}: {success} success, {failed} failed")
                
            except Exception as e:
                args = futures[future]
                vol_id = args[2]
                logger.error(f"    [ERROR] {vol_id}: {e}")
                total_failed += 1
    
    logger.info(f"  Completed: {total_success} success, {total_failed} failed")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Batch RTF to TEI XML Converter for IE1PD45495"
    )
    parser.add_argument(
        "--ie-id",
        help="Process specific IE collection (e.g., IE1PD45495)"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=INPUT_DIR,
        help=f"Input directory (default: {INPUT_DIR})"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})"
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 70)
    logger.info("BATCH RTF TO TEI XML CONVERTER")
    logger.info("=" * 70)
    logger.info(f"Input directory: {args.input_dir}")
    logger.info(f"Workers: {args.workers}")
    
    # Discover collections
    collections = discover_collections(args.input_dir)
    
    # Filter by IE ID if specified
    if args.ie_id:
        collections = [(ie_id, src, out) for ie_id, src, out in collections if ie_id == args.ie_id]
    
    if not collections:
        logger.error(f"No collections found in {args.input_dir}")
        return
    
    logger.info(f"Found {len(collections)} collections to process")
    logger.info("=" * 70)
    
    # Process each collection
    total_collections = len(collections)
    for idx, (ie_id, sources_dir, output_dir) in enumerate(collections, 1):
        logger.info(f"\n[{idx}/{total_collections}] Processing {ie_id}")
        process_collection(ie_id, sources_dir, output_dir, args.workers)
    
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    for ie_id, _, _ in collections:
        logger.info(f"  [OK] {ie_id}")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
