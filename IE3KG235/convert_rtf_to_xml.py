#!/usr/bin/env python3
"""
IE3KG235: RTF to TEI XML Converter

Input: RTF files in IE3KG235/IE3KG235/sources (flat).
Output volume (VE) from toprocess folder names (IE3KG235-VE*).
Output: IE3KG235_output/archive/{VE_ID}/UT*.xml and sources/{VE_ID}/.

Usage:
    python convert_rtf_to_xml.py           # Convert all RTF files
    python convert_rtf_to_xml.py --ve VE3KG205  # Restrict to one VE
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
    IE_ID, SOURCES_DIR, TOPROCESS_DIR, OUTPUT_DIR, ARCHIVE_DIR, SOURCES_OUTPUT_DIR,
    RTF_TO_XML_LOG, RTF_TO_XML_CHECKPOINT, ensure_directories,
    get_ut_id, extract_ve_id_from_folder, get_max_archive_sequence,
)
from basic_rtf import BasicRTF
from normalization import normalize_unicode
from tibetan_text_fixes import fix_hi_tag_spacing, fix_toc_leader_dots
from dedris_converter import (
    dedris_to_unicode, reset_stats, print_conversion_stats, write_stats_file,
)
from tei_generator import (
    classify_font_sizes, build_tei_body, post_process_body,
    generate_tei_xml, calculate_sha256,
)


def setup_logging():
    ensure_directories()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(RTF_TO_XML_LOG, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger(__name__)


logger = setup_logging()
ENABLE_FONT_CLASSIFICATION = True
ENABLE_NORMALIZATION = True


def load_checkpoints() -> set:
    if RTF_TO_XML_CHECKPOINT.exists():
        try:
            content = RTF_TO_XML_CHECKPOINT.read_text(encoding="utf-8").strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error(f"Error reading checkpoint: {e}")
    return set()


def save_checkpoint(file_path: str):
    RTF_TO_XML_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    with open(RTF_TO_XML_CHECKPOINT, "a", encoding="utf-8") as f:
        f.write(f"{file_path}\n")


def get_ve_ids_from_toprocess():
    """Collect VE IDs from toprocess folders named IE3KG235-VE*."""
    ve_ids = []
    if not TOPROCESS_DIR.exists():
        return ve_ids
    for folder in TOPROCESS_DIR.iterdir():
        if folder.is_dir():
            ve_id = extract_ve_id_from_folder(folder.name)
            if ve_id:
                ve_ids.append(ve_id)
    return natsorted(ve_ids)


def get_rtf_files_from_sources():
    """All *.rtf in SOURCES_DIR (flat), natsorted."""
    if not SOURCES_DIR.exists():
        return []
    return natsorted(SOURCES_DIR.glob("*.rtf"), key=lambda p: p.name)


def assign_rtf_to_ve(ve_ids: list, rtf_list: list) -> dict:
    """
    Assign RTF files to VEs. One VE -> all files; multiple VEs -> split in order.
    """
    if not ve_ids or not rtf_list:
        return {}
    if len(ve_ids) == 1:
        return {ve_ids[0]: rtf_list}
    # Split list: first chunk to VE0, next to VE1, ...
    n = len(ve_ids)
    size = len(rtf_list)
    base, extra = divmod(size, n)
    chunks = []
    start = 0
    for i in range(n):
        count = base + (1 if i < extra else 0)
        chunks.append(rtf_list[start : start + count])
        start += count
    return dict(zip(ve_ids, chunks))


def convert_rtf_to_tei(rtf_path: Path, ve_id: str, sequence: int) -> str:
    """Convert one RTF to TEI XML. Use RTF for SHA256 (no DOC)."""
    logger.info(f"Parsing RTF file: {rtf_path.name}")
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
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
        if stream.get("type") in ("pict", "row_break"):
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

        text = stream.get("text", "")
        font_name = stream.get("font", {}).get("name", "")
        font_size = stream.get("font", {}).get("size", 12)
        unicode_text = dedris_to_unicode(text, font_name)
        if not unicode_text:
            continue
        converted_streams.append({"text": unicode_text, "font_size": font_size})
        last_was_page_break = False

    body_content = build_tei_body(converted_streams, ENABLE_FONT_CLASSIFICATION)
    if ENABLE_NORMALIZATION:
        body_content = normalize_unicode(body_content)
        body_content = fix_hi_tag_spacing(body_content)
        body_content = fix_toc_leader_dots(body_content)
    body_content = post_process_body(body_content)

    ut_id = get_ut_id(ve_id, sequence)
    sha256 = calculate_sha256(rtf_path)
    src_path = f"sources/{ve_id}/{rtf_path.name}"

    return generate_tei_xml(
        body_content=body_content,
        title=rtf_path.stem,
        src_path=src_path,
        sha256=sha256,
        ve_id=ve_id,
        ut_id=ut_id,
    )


def copy_sources_to_output(ve_id: str, rtf_files: list):
    """Copy RTF files to output sources/{ve_id}/."""
    sources_ve_dir = SOURCES_OUTPUT_DIR / ve_id
    sources_ve_dir.mkdir(parents=True, exist_ok=True)
    for rtf_path in rtf_files:
        dest = sources_ve_dir / rtf_path.name
        try:
            shutil.copy2(rtf_path, dest)
        except Exception as e:
            logger.warning(f"Failed to copy RTF {rtf_path.name}: {e}")
    logger.info(f"  Copied {len(rtf_files)} RTF file(s) to sources/{ve_id}/")


def convert_all_files(ve_filter: str = None):
    logger.info("=" * 60)
    logger.info(f"RTF to TEI XML Converter for {IE_ID}")
    logger.info(f"RTF Source: {SOURCES_DIR}")
    logger.info(f"Output: {OUTPUT_DIR}")
    logger.info("=" * 60)
    ensure_directories()

    ve_ids = get_ve_ids_from_toprocess()
    if ve_filter:
        ve_ids = [v for v in ve_ids if v == ve_filter]
    if not ve_ids:
        logger.error("No VE folder(s) found under toprocess (IE3KG235-VE*)")
        return

    rtf_list = get_rtf_files_from_sources()
    if not rtf_list:
        logger.error("No RTF files found in sources/")
        return

    rtf_by_ve = assign_rtf_to_ve(ve_ids, rtf_list)
    total = sum(len(files) for files in rtf_by_ve.values())
    logger.info(f"VE IDs from toprocess: {ve_ids}")
    logger.info(f"RTF files in sources: {len(rtf_list)} -> assigned to {len(rtf_by_ve)} VE(s), {total} total")

    checkpoints = load_checkpoints()
    reset_stats()
    success_count = 0
    failed_count = 0

    for ve_id in natsorted(rtf_by_ve.keys()):
        rtf_files = rtf_by_ve[ve_id]
        logger.info(f"\nProcessing {ve_id} ({len(rtf_files)} files)")
        archive_ve_dir = ARCHIVE_DIR / ve_id
        archive_ve_dir.mkdir(parents=True, exist_ok=True)
        max_seq = get_max_archive_sequence(ve_id)
        converted_files = []

        for idx, rtf_path in enumerate(rtf_files, start=1):
            rtf_path_str = str(rtf_path)
            if rtf_path_str in checkpoints:
                logger.info(f"  Skipping (already converted): {rtf_path.name}")
                success_count += 1
                converted_files.append(rtf_path)
                continue

            sequence = max_seq + idx
            ut_id = get_ut_id(ve_id, sequence)
            logger.info(f"  [{idx}/{len(rtf_files)}] {rtf_path.name} -> {ut_id}")

            try:
                tei_xml = convert_rtf_to_tei(rtf_path, ve_id, sequence)
                xml_path = archive_ve_dir / f"{ut_id}.xml"
                with open(xml_path, "w", encoding="utf-8") as f:
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
    write_stats_file(OUTPUT_DIR / "conversion_stats_rtf.txt")


def main():
    parser = argparse.ArgumentParser(description="Convert RTF files to TEI XML (IE3KG235)")
    parser.add_argument("--ve", metavar="VE_ID", help="Process only this VE ID")
    parser.add_argument("--no-font-tags", action="store_true", help="Disable font classification")
    parser.add_argument("--no-normalization", action="store_true", help="Disable Unicode normalization")
    args = parser.parse_args()

    global ENABLE_FONT_CLASSIFICATION, ENABLE_NORMALIZATION
    if args.no_font_tags:
        ENABLE_FONT_CLASSIFICATION = False
    if args.no_normalization:
        ENABLE_NORMALIZATION = False

    convert_all_files(ve_filter=args.ve)


if __name__ == "__main__":
    main()
