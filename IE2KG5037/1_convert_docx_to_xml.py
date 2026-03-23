#!/usr/bin/env python3
"""
DOCX to TEI XML Converter for IE2KG5037

This script converts DOCX files from the toprocess folder to TEI XML format.
Files are already in Unicode, so no Dedris conversion is needed.

Usage:
    python 1_convert_docx_to_xml.py           # Convert all DOCX files
    python 1_convert_docx_to_xml.py --single IE2KG5037-VE3KG1/file.docx  # Convert single file
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
    IE_ID, TOPROCESS_DIR, OUTPUT_DIR, ARCHIVE_DIR, SOURCES_OUTPUT_DIR,
    DOCX_TO_XML_LOG, DOCX_TO_XML_CHECKPOINT, ensure_directories,
    get_ut_id, extract_ve_id_from_folder
)
from basic_docx import BasicDOCX
from normalization import normalize_unicode
from tibetan_text_fixes import fix_hi_tag_spacing, fix_toc_leader_dots
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
    """Get all DOCX files organized by VE ID from toprocess folder."""
    docx_by_ve = {}
    
    if not TOPROCESS_DIR.exists():
        logger.error(f"toprocess directory not found: {TOPROCESS_DIR}")
        return {}
    
    for ve_folder in TOPROCESS_DIR.iterdir():
        if ve_folder.is_dir():
            ve_id = extract_ve_id_from_folder(ve_folder.name)
            if ve_id:
                docx_files = list(ve_folder.glob("*.docx"))
                if docx_files:
                    docx_by_ve[ve_id] = natsorted(docx_files, key=lambda p: p.name)
    
    return docx_by_ve


def convert_docx_to_tei(docx_path: Path, ve_id: str, sequence: int) -> str:
    """Convert DOCX file to TEI XML."""
    logger.info(f"Parsing DOCX file: {docx_path.name}")
    parser = BasicDOCX()
    parser.parse_file(str(docx_path))
    streams = parser.get_streams()
    
    logger.info(f"  Parsed {len(streams)} text streams")
    
    # Skip Dedris conversion - text is already Unicode
    converted_streams = []
    
    for stream in streams:
        # Include headers and footers (they may contain actual content like TOC)
        stream_type = stream.get("type")
        
        text = stream.get("text", "")
        font_size = stream.get("font", {}).get("size", 12)
        
        # Direct normalization (no dedris_to_unicode call)
        normalized_text = normalize_unicode(text)
        
        if not normalized_text.strip():
            continue
        
        converted_streams.append({
            "text": normalized_text,
            "font_size": font_size
        })
    
    logger.info(f"  Stage 1: Processed {len(converted_streams)} streams (already Unicode)")
    
    body_content = build_tei_body(converted_streams, ENABLE_FONT_CLASSIFICATION)
    
    if ENABLE_NORMALIZATION:
        logger.info(f"  Stage 2: Applying normalization...")
        body_content = normalize_unicode(body_content)
        body_content = fix_hi_tag_spacing(body_content)
        body_content = fix_toc_leader_dots(body_content)
    
    body_content = post_process_body(body_content)
    
    ut_id = get_ut_id(ve_id, sequence)
    sha256 = calculate_sha256(docx_path)
    src_path = f"sources/{ve_id}/{docx_path.name}"
    
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
    """Copy source DOCX files to output directory."""
    sources_ve_dir = SOURCES_OUTPUT_DIR / ve_id
    sources_ve_dir.mkdir(parents=True, exist_ok=True)
    
    copied_count = 0
    
    for docx_path in docx_files:
        docx_dest = sources_ve_dir / docx_path.name
        try:
            shutil.copy2(docx_path, docx_dest)
            copied_count += 1
        except Exception as e:
            logger.warning(f"Failed to copy DOCX {docx_path.name}: {e}")
    
    logger.info(f"  Copied {copied_count} source files to sources/{ve_id}/")


def convert_single_file(relative_path: str):
    """Convert a single DOCX file to TEI XML."""
    # Parse relative path: IE2KG5037-VE3KG1/file.docx
    parts = Path(relative_path).parts
    if len(parts) < 2:
        logger.error(f"Invalid path format. Expected: IE2KG5037-VE3KG1/file.docx")
        return
    
    folder_name = parts[0]
    filename = parts[-1]
    
    ve_id = extract_ve_id_from_folder(folder_name)
    if not ve_id:
        logger.error(f"Could not extract VE ID from folder name: {folder_name}")
        return
    
    docx_path = TOPROCESS_DIR / folder_name / filename
    
    if not docx_path.exists():
        logger.error(f"DOCX file not found: {docx_path}")
        return
    
    sequence = 1
    ut_id = get_ut_id(ve_id, sequence)
    
    logger.info(f"Converting: {docx_path.name}")
    logger.info(f"  VE ID: {ve_id}")
    logger.info(f"  UT ID: {ut_id}")
    
    try:
        tei_xml = convert_docx_to_tei(docx_path, ve_id, sequence)
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
    
    copy_sources_to_output(ve_id, [docx_path])


def convert_all_files():
    """Convert all DOCX files to TEI XML."""
    logger.info("=" * 60)
    logger.info(f"DOCX to TEI XML Converter for {IE_ID}")
    logger.info(f"DOCX Source: {TOPROCESS_DIR}")
    logger.info(f"Output: {OUTPUT_DIR}")
    logger.info("=" * 60)
    
    ensure_directories()
    
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
        for sequence, docx_path in enumerate(docx_files, start=1):
            docx_path_str = str(docx_path)
            
            if docx_path_str in checkpoints:
                logger.info(f"  Skipping (already converted): {docx_path.name}")
                success_count += 1
                converted_files.append(docx_path)
                continue
            
            ut_id = get_ut_id(ve_id, sequence)
            logger.info(f"  [{sequence}/{len(docx_files)}] {docx_path.name} -> {ut_id}")
            
            try:
                tei_xml = convert_docx_to_tei(docx_path, ve_id, sequence)
                
                xml_path = archive_ve_dir / f"{ut_id}.xml"
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(tei_xml)
                
                save_checkpoint(docx_path_str)
                success_count += 1
                converted_files.append(docx_path)
                
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


def main():
    parser = argparse.ArgumentParser(description="Convert DOCX files to TEI XML")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single file (path relative to toprocess/, e.g., IE2KG5037-VE3KG1/file.docx)")
    parser.add_argument("--no-font-tags", action="store_true", help="Disable font classification")
    parser.add_argument("--no-normalization", action="store_true", help="Disable Unicode normalization")
    args = parser.parse_args()
    
    global ENABLE_FONT_CLASSIFICATION, ENABLE_NORMALIZATION
    if args.no_font_tags:
        ENABLE_FONT_CLASSIFICATION = False
    if args.no_normalization:
        ENABLE_NORMALIZATION = False
    
    if args.single:
        convert_single_file(args.single)
    else:
        convert_all_files()


if __name__ == "__main__":
    main()

