#!/usr/bin/env python3
"""
DOCX to TEI XML Converter for IE3CN3334 (with Dedris font conversion)

This script converts DOCX files to TEI XML format using the BasicDOCX parser.
It applies Dedris font conversion for files with Dedris fonts.

IE3CN3334 reads DOCX files from:
1. Intermediate DOCX files in docx/{VE_ID}/ (converted from DOC)
2. Original DOCX files in toprocess/{IE_ID}-{VE_ID}/ (if any)

Usage:
    python convert_docx_to_xml.py                          # Convert all DOCX files
    python convert_docx_to_xml.py --single VE5CN1/file.docx  # Convert single file
"""

import sys
import shutil
import argparse
import logging
from pathlib import Path
from natsort import natsorted

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from config import (
    IE_ID, TOPROCESS_DIR, DOCX_DIR, OUTPUT_DIR, ARCHIVE_DIR, SOURCES_OUTPUT_DIR,
    DOCX_TO_XML_LOG, DOCX_TO_XML_CHECKPOINT, ensure_directories, get_ut_id,
    extract_ve_id_from_folder
)
from basic_docx import BasicDOCX
from normalization import normalize_unicode
from tibetan_text_fixes import fix_hi_tag_spacing, fix_toc_leader_dots
from dedris_converter import (
    dedris_to_unicode, reset_stats, print_conversion_stats, write_stats_file
)
from tei_generator import (
    classify_font_sizes, build_tei_body, post_process_body,
    generate_tei_xml, calculate_sha256, escape_xml
)


def setup_logging():
    """Configure logging with file and console output."""
    ensure_directories()
    
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(DOCX_TO_XML_LOG, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

ENABLE_FONT_CLASSIFICATION = True
ENABLE_NORMALIZATION = True


def load_checkpoints() -> set:
    """Load previously converted files from checkpoint."""
    if DOCX_TO_XML_CHECKPOINT.exists():
        try:
            content = DOCX_TO_XML_CHECKPOINT.read_text(encoding='utf-8').strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error(f"Error reading checkpoint file: {e}")
    return set()


def save_checkpoint(file_path: str):
    """Save a converted file to checkpoint."""
    DOCX_TO_XML_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with open(DOCX_TO_XML_CHECKPOINT, "a", encoding='utf-8') as f:
        f.write(f"{file_path}\n")


def get_all_docx_files() -> dict:
    """Get all DOCX files organized by VE ID from both sources.
    
    Sources:
    1. Intermediate DOCX in docx/{VE_ID}/ (converted from DOC)
    2. Original DOCX in toprocess/{IE_ID}-{VE_ID}/
    
    Returns:
        Dict mapping VE ID to list of (docx_path, source_type) tuples
        where source_type is 'intermediate' or 'original'
    """
    docx_by_ve = {}
    
    # Source 1: Intermediate DOCX files (converted from DOC)
    if DOCX_DIR.exists():
        for ve_folder in DOCX_DIR.iterdir():
            if ve_folder.is_dir() and ve_folder.name.startswith("VE"):
                ve_id = ve_folder.name
                docx_files = list(ve_folder.glob("*.docx"))
                if docx_files:
                    if ve_id not in docx_by_ve:
                        docx_by_ve[ve_id] = []
                    for f in docx_files:
                        docx_by_ve[ve_id].append((f, 'intermediate'))
    
    # Source 2: Original DOCX files from toprocess
    if TOPROCESS_DIR.exists():
        for ve_folder in TOPROCESS_DIR.iterdir():
            if ve_folder.is_dir() and ve_folder.name.startswith(f"{IE_ID}-"):
                ve_id = extract_ve_id_from_folder(ve_folder.name)
                if ve_id:
                    docx_files = list(ve_folder.glob("*.docx"))
                    if docx_files:
                        if ve_id not in docx_by_ve:
                            docx_by_ve[ve_id] = []
                        for f in docx_files:
                            docx_by_ve[ve_id].append((f, 'original'))
    
    # Sort files within each VE by name
    for ve_id in docx_by_ve:
        docx_by_ve[ve_id] = natsorted(docx_by_ve[ve_id], key=lambda x: x[0].name)
    
    return docx_by_ve


def find_source_doc_file(docx_path: Path, ve_id: str) -> Path:
    """Find the source DOC file in toprocess folder structure.
    
    Args:
        docx_path: Path to DOCX file
        ve_id: VE ID (e.g., "VE5CN1")
        
    Returns:
        Path to DOC file or None if not found
    """
    base_name = docx_path.stem
    ve_folder_name = f"{IE_ID}-{ve_id}"
    ve_folder = TOPROCESS_DIR / ve_folder_name
    
    if not ve_folder.exists():
        return None
    
    doc_path = ve_folder / f"{base_name}.doc"
    if doc_path.exists():
        return doc_path
    
    return None


def convert_docx_to_tei(docx_path: Path, ve_id: str, sequence: int, source_type: str) -> str:
    """Convert DOCX file to TEI XML.
    
    IE3CN3334 DOCX files are already Unicode - no Dedris conversion needed.
    
    Args:
        docx_path: Path to the DOCX file
        ve_id: Volume ID
        sequence: Sequence number for UT ID
        source_type: 'intermediate' (converted from DOC) or 'original' (native DOCX)
    """
    # For SHA256, use the original source file if available
    if source_type == 'intermediate':
        source_path = find_source_doc_file(docx_path, ve_id)
        if not source_path:
            logger.warning(f"Source DOC file not found for {docx_path.name}, using DOCX for SHA256")
            source_path = docx_path
    else:
        source_path = docx_path
    
    logger.info(f"Parsing DOCX file: {docx_path.name}")
    parser = BasicDOCX()
    parser.parse_file(str(docx_path))
    streams = parser.get_streams()
    
    logger.info(f"  Parsed {len(streams)} text streams")
    
    converted_streams = []
    last_was_page_break = False
    
    for stream in streams:
        if stream.get("type") == "footer":
            if not last_was_page_break:
                converted_streams.append({"type": "page_break"})
                last_was_page_break = True
            continue
        
        if stream.get("type") == "sect_break":
            if not last_was_page_break:
                converted_streams.append({"type": "page_break"})
                last_was_page_break = True
            continue
        
        if stream.get("type") == "header":
            if not last_was_page_break:
                converted_streams.append({"type": "page_break"})
                last_was_page_break = True
            continue
        
        if stream.get("type") == "pict":
            continue
        
        if stream.get("type") == "par_break":
            converted_streams.append({"text": "\n", "font_size": 12, "is_break": True})
            continue
        
        if stream.get("type") == "line_break":
            converted_streams.append({"text": "\n", "font_size": 12, "is_break": True})
            continue
        
        if stream.get("type") == "cell_break":
            converted_streams.append({"text": "\n", "font_size": 12, "is_break": True})
            continue
        
        if stream.get("type") == "row_break":
            continue
        
        text = stream.get("text", "")
        font_name = stream.get("font", {}).get("name", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        unicode_text = dedris_to_unicode(text, font_name)
        
        if not unicode_text:
            continue
        
        converted_streams.append({"text": unicode_text, "font_size": font_size})
        last_was_page_break = False
    
    logger.info(f"  Processed {len(converted_streams)} text streams")
    
    body_content = build_tei_body(converted_streams, ENABLE_FONT_CLASSIFICATION)
    
    if ENABLE_NORMALIZATION:
        logger.info(f"  Applying normalization...")
        body_content = normalize_unicode(body_content)
        body_content = fix_hi_tag_spacing(body_content)
        body_content = fix_toc_leader_dots(body_content)
    
    body_content = post_process_body(body_content)
    
    ut_id = get_ut_id(ve_id, sequence)
    sha256 = calculate_sha256(source_path)
    src_path = f"sources/{ve_id}/{source_path.name}"
    
    tei_xml = generate_tei_xml(
        body_content=body_content,
        title=docx_path.stem,
        src_path=src_path,
        sha256=sha256,
        ve_id=ve_id,
        ut_id=ut_id,
    )
    
    return tei_xml


def copy_sources_to_output(ve_id: str, docx_files: list):
    """Copy source files (DOC and DOCX) to output directory.
    
    Args:
        ve_id: Volume ID
        docx_files: List of (docx_path, source_type) tuples
    """
    sources_ve_dir = SOURCES_OUTPUT_DIR / ve_id
    sources_ve_dir.mkdir(parents=True, exist_ok=True)
    
    copied_count = 0
    
    for docx_path, source_type in docx_files:
        # Copy the DOCX file
        docx_dest = sources_ve_dir / docx_path.name
        try:
            shutil.copy2(docx_path, docx_dest)
            copied_count += 1
        except Exception as e:
            logger.warning(f"Failed to copy DOCX {docx_path.name}: {e}")
        
        # For intermediate files, also copy the source DOC
        if source_type == 'intermediate':
            doc_path = find_source_doc_file(docx_path, ve_id)
            if doc_path and doc_path.exists():
                doc_dest = sources_ve_dir / doc_path.name
                try:
                    shutil.copy2(doc_path, doc_dest)
                    copied_count += 1
                except Exception as e:
                    logger.warning(f"Failed to copy source file {doc_path.name}: {e}")
    
    logger.info(f"  Copied {copied_count} source files to sources/{ve_id}/")


def convert_single_file(relative_path: str, sequence: int = 1):
    """Convert a single DOCX file to TEI XML.
    
    Args:
        relative_path: Path to DOCX file relative to docx/ folder
                      e.g., "VE5CN1/file.docx"
        sequence: Sequence number for UT ID (default: 1)
    """
    docx_path = DOCX_DIR / relative_path
    
    if not docx_path.exists():
        logger.error(f"DOCX file not found: {docx_path}")
        return
    
    ve_id = docx_path.parent.name
    if not ve_id.startswith("VE"):
        logger.error(f"Could not determine VE ID from path: {relative_path}")
        return
    
    ut_id = get_ut_id(ve_id, sequence)
    
    logger.info(f"Converting: {docx_path.name}")
    logger.info(f"  VE ID: {ve_id}")
    logger.info(f"  UT ID: {ut_id}")
    
    try:
        tei_xml = convert_docx_to_tei(docx_path, ve_id, sequence, 'intermediate')
    except Exception as e:
        logger.error(f"Error converting {docx_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return
    
    archive_ve_dir = ARCHIVE_DIR / ve_id
    archive_ve_dir.mkdir(parents=True, exist_ok=True)
    
    xml_path = archive_ve_dir / f"{ut_id}.xml"
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(tei_xml)
    
    logger.info(f"  Output: {xml_path}")
    
    copy_sources_to_output(ve_id, [(docx_path, 'intermediate')])


def convert_all_files():
    """Convert all DOCX files to TEI XML."""
    logger.info("=" * 60)
    logger.info(f"DOCX to TEI XML Converter for {IE_ID}")
    logger.info(f"DOCX Source 1 (intermediate): {DOCX_DIR}")
    logger.info(f"DOCX Source 2 (original): {TOPROCESS_DIR}")
    logger.info(f"Output: {OUTPUT_DIR}")
    logger.info("=" * 60)
    
    ensure_directories()
    
    reset_stats()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    docx_by_ve = get_all_docx_files()
    
    if not docx_by_ve:
        logger.error("No DOCX files found")
        return
    
    total_files = sum(len(files) for files in docx_by_ve.values())
    logger.info(f"Found {len(docx_by_ve)} VE folders with {total_files} DOCX files")
    
    success_count = 0
    failed_count = 0
    
    for ve_id in natsorted(docx_by_ve.keys()):
        docx_files = docx_by_ve[ve_id]
        
        logger.info(f"\nProcessing {ve_id} ({len(docx_files)} files)")
        
        archive_ve_dir = ARCHIVE_DIR / ve_id
        archive_ve_dir.mkdir(parents=True, exist_ok=True)
        
        converted_files = []
        for idx, (docx_path, source_type) in enumerate(docx_files):
            sequence = idx + 1
            
            docx_path_str = str(docx_path)
            
            if docx_path_str in checkpoints:
                logger.info(f"  Skipping (already converted): {docx_path.name}")
                success_count += 1
                converted_files.append((docx_path, source_type))
                continue
            
            ut_id = get_ut_id(ve_id, sequence)
            logger.info(f"  [{idx + 1}/{len(docx_files)}] {docx_path.name} ({source_type}) -> {ut_id}")
            
            try:
                tei_xml = convert_docx_to_tei(docx_path, ve_id, sequence, source_type)
                
                xml_path = archive_ve_dir / f"{ut_id}.xml"
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(tei_xml)
                
                save_checkpoint(docx_path_str)
                success_count += 1
                converted_files.append((docx_path, source_type))
                
            except Exception as e:
                logger.error(f"  Error converting {docx_path.name}: {e}")
                import traceback
                traceback.print_exc()
                failed_count += 1
        
        if converted_files:
            copy_sources_to_output(ve_id, converted_files)
    
    logger.info("\n" + "=" * 60)
    logger.info("CONVERSION COMPLETE!")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Failed: {failed_count}")
    logger.info(f"  Output: {OUTPUT_DIR}")
    logger.info("=" * 60)
    
    print_conversion_stats()
    write_stats_file(OUTPUT_DIR / "conversion_stats.txt")


def main():
    parser = argparse.ArgumentParser(description="Convert DOCX files to TEI XML (Unicode source)")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single file (path relative to docx/)")
    parser.add_argument("--sequence", type=int, default=1, metavar="N", help="Sequence number for single file UT ID (default: 1)")
    parser.add_argument("--no-font-tags", action="store_true", help="Disable font classification")
    parser.add_argument("--no-normalization", action="store_true", help="Disable Unicode normalization")
    args = parser.parse_args()
    
    global ENABLE_FONT_CLASSIFICATION, ENABLE_NORMALIZATION
    if args.no_font_tags:
        ENABLE_FONT_CLASSIFICATION = False
    if args.no_normalization:
        ENABLE_NORMALIZATION = False
    
    if args.single:
        convert_single_file(args.single, sequence=args.sequence)
    else:
        convert_all_files()


if __name__ == "__main__":
    main()
