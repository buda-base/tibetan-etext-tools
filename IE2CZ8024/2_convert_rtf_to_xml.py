#!/usr/bin/env python3
"""
Step 2: RTF to TEI XML Converter

This script converts RTF files to TEI XML format using the BasicRTF parser.

Usage:
    python 2_convert_rtf_to_xml.py           # Convert all RTF files
    python 2_convert_rtf_to_xml.py --single VE1ER619/file.rtf  # Convert single file
"""

import sys
import re
import shutil
import argparse
import logging
from pathlib import Path
from natsort import natsorted

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from config import (
    IE_ID, SOURCE_DIR, RTF_DIR, OUTPUT_DIR, ARCHIVE_DIR, SOURCES_OUTPUT_DIR,
    RTF_TO_XML_LOG, RTF_TO_XML_CHECKPOINT, ensure_directories, get_ut_id
)
from basic_rtf import BasicRTF
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
            logging.FileHandler(RTF_TO_XML_LOG, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

ENABLE_FONT_CLASSIFICATION = True
ENABLE_NORMALIZATION = True


def load_checkpoints() -> set:
    """Load previously converted files from checkpoint."""
    if RTF_TO_XML_CHECKPOINT.exists():
        try:
            content = RTF_TO_XML_CHECKPOINT.read_text(encoding='utf-8').strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error(f"Error reading checkpoint file: {e}")
    return set()


def save_checkpoint(file_path: str):
    """Save a converted file to checkpoint."""
    RTF_TO_XML_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with open(RTF_TO_XML_CHECKPOINT, "a", encoding='utf-8') as f:
        f.write(f"{file_path}\n")


def get_all_rtf_files() -> dict:
    """Get all RTF files organized by VE ID."""
    rtf_by_ve = {}
    
    if not RTF_DIR.exists():
        logger.error(f"RTF directory not found: {RTF_DIR}")
        return {}
    
    for ve_folder in RTF_DIR.iterdir():
        if ve_folder.is_dir() and ve_folder.name.startswith("VE"):
            ve_id = ve_folder.name
            rtf_files = list(ve_folder.glob("*.rtf"))
            if rtf_files:
                rtf_by_ve[ve_id] = natsorted(rtf_files, key=lambda p: p.name)
    
    return rtf_by_ve


def convert_rtf_to_tei(rtf_path: Path, ve_id: str, sequence: int) -> str:
    """Convert RTF file to TEI XML."""
    doc_filename = rtf_path.stem + ".doc"
    doc_path = SOURCE_DIR / ve_id / doc_filename
    
    logger.info(f"Parsing RTF file: {rtf_path.name}")
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    logger.info(f"  Parsed {len(streams)} text streams")
    
    converted_streams = []
    last_was_page_break = False  # Track to avoid duplicate page breaks
    
    for stream in streams:
        # Footer marks end of page - insert page break marker
        if stream.get("type") == "footer":
            if not last_was_page_break:
                converted_streams.append({"type": "page_break"})
                last_was_page_break = True
            continue
        
        # Section break marks page/section boundary
        if stream.get("type") == "sect_break":
            if not last_was_page_break:
                converted_streams.append({"type": "page_break"})
                last_was_page_break = True
            continue
        
        # Header also marks page boundary (new page has new header)
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
    
    logger.info(f"  Stage 1: Converted {len(converted_streams)} streams to Unicode")
    
    body_content = build_tei_body(converted_streams, ENABLE_FONT_CLASSIFICATION)
    
    if ENABLE_NORMALIZATION:
        logger.info(f"  Stage 3: Applying normalization...")
        body_content = normalize_unicode(body_content)
        body_content = fix_hi_tag_spacing(body_content)
        body_content = fix_toc_leader_dots(body_content)
    
    body_content = post_process_body(body_content)
    
    ut_id = get_ut_id(ve_id, sequence)
    sha256 = calculate_sha256(doc_path)
    src_path = f"sources/{ve_id}/{doc_path.name}"
    
    tei_xml = generate_tei_xml(
        body_content=body_content,
        title=rtf_path.stem,
        src_path=src_path,
        sha256=sha256,
        ve_id=ve_id,
        ut_id=ut_id,
    )
    
    return tei_xml


def copy_sources_to_output(ve_id: str, rtf_files: list):
    """Copy source files (DOC and RTF) to output directory."""
    sources_ve_dir = SOURCES_OUTPUT_DIR / ve_id
    sources_ve_dir.mkdir(parents=True, exist_ok=True)
    
    copied_count = 0
    
    for rtf_path in rtf_files:
        rtf_dest = sources_ve_dir / rtf_path.name
        try:
            shutil.copy2(rtf_path, rtf_dest)
            copied_count += 1
        except Exception as e:
            logger.warning(f"Failed to copy RTF {rtf_path.name}: {e}")
        
        doc_filename = rtf_path.stem + ".doc"
        doc_path = SOURCE_DIR / ve_id / doc_filename
        
        if doc_path.exists():
            doc_dest = sources_ve_dir / doc_filename
            try:
                shutil.copy2(doc_path, doc_dest)
                copied_count += 1
            except Exception as e:
                logger.warning(f"Failed to copy DOC {doc_filename}: {e}")
    
    logger.info(f"  Copied {copied_count} source files to sources/{ve_id}/")


def convert_single_file(relative_path: str):
    """Convert a single RTF file to TEI XML."""
    rtf_path = RTF_DIR / relative_path
    
    if not rtf_path.exists():
        logger.error(f"RTF file not found: {rtf_path}")
        return
    
    ve_id = rtf_path.parent.name
    if not ve_id.startswith("VE"):
        logger.error(f"Could not determine VE ID from path: {relative_path}")
        return
    
    sequence = 1
    ut_id = get_ut_id(ve_id, sequence)
    
    logger.info(f"Converting: {rtf_path.name}")
    logger.info(f"  VE ID: {ve_id}")
    logger.info(f"  UT ID: {ut_id}")
    
    reset_stats()
    
    try:
        tei_xml = convert_rtf_to_tei(rtf_path, ve_id, sequence)
    except Exception as e:
        logger.error(f"Error converting {rtf_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return
    
    archive_ve_dir = ARCHIVE_DIR / ve_id
    archive_ve_dir.mkdir(parents=True, exist_ok=True)
    
    xml_path = archive_ve_dir / f"{ut_id}.xml"
    with open(xml_path, 'w', encoding='utf-8') as f:
        f.write(tei_xml)
    
    logger.info(f"  Output: {xml_path}")
    
    copy_sources_to_output(ve_id, [rtf_path])
    print_conversion_stats()


def convert_all_files():
    """Convert all RTF files to TEI XML."""
    logger.info("=" * 60)
    logger.info(f"RTF to TEI XML Converter for {IE_ID}")
    logger.info(f"RTF Source: {RTF_DIR}")
    logger.info(f"Output: {OUTPUT_DIR}")
    logger.info("=" * 60)
    
    ensure_directories()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    rtf_by_ve = get_all_rtf_files()
    
    if not rtf_by_ve:
        logger.error("No RTF files found")
        return
    
    total_files = sum(len(files) for files in rtf_by_ve.values())
    logger.info(f"Found {len(rtf_by_ve)} VE folders with {total_files} RTF files")
    
    reset_stats()
    
    success_count = 0
    failed_count = 0
    
    for ve_id in natsorted(rtf_by_ve.keys()):
        rtf_files = rtf_by_ve[ve_id]
        
        logger.info(f"\nProcessing {ve_id} ({len(rtf_files)} files)")
        
        archive_ve_dir = ARCHIVE_DIR / ve_id
        archive_ve_dir.mkdir(parents=True, exist_ok=True)
        
        converted_files = []
        for sequence, rtf_path in enumerate(rtf_files, start=1):
            rtf_path_str = str(rtf_path)
            
            if rtf_path_str in checkpoints:
                logger.info(f"  Skipping (already converted): {rtf_path.name}")
                success_count += 1
                converted_files.append(rtf_path)
                continue
            
            ut_id = get_ut_id(ve_id, sequence)
            logger.info(f"  [{sequence}/{len(rtf_files)}] {rtf_path.name} -> {ut_id}")
            
            try:
                tei_xml = convert_rtf_to_tei(rtf_path, ve_id, sequence)
                
                xml_path = archive_ve_dir / f"{ut_id}.xml"
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(tei_xml)
                
                save_checkpoint(rtf_path_str)
                success_count += 1
                converted_files.append(rtf_path)
                
            except Exception as e:
                logger.error(f"  Error converting {rtf_path.name}: {e}")
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
    parser = argparse.ArgumentParser(description="Convert RTF files to TEI XML")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single file (path relative to rtf/)")
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





