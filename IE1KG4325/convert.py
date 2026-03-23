#!/usr/bin/env python3
"""
Convert RTF files from IE1KG4325 to TEI XML format.
"""

import sys
import re
import hashlib
import shutil
import logging
from pathlib import Path
from natsort import natsorted
from collections import Counter

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from basic_rtf import BasicRTF
from normalization import normalize_unicode

IE_ID = "IE1KG4325"
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1KG4325")
TOPROCESS_DIR = BASE_DIR / "toprocess"
OUTPUT_DIR = BASE_DIR / "IE1KG4325_OUTPUT"


def get_volume_folders() -> list:
    logger.info(f"Looking for volume folders in: {TOPROCESS_DIR}")
    if not TOPROCESS_DIR.exists():
        logger.error(f"toprocess folder not found at {TOPROCESS_DIR}")
        return []
    volumes = []
    for folder in TOPROCESS_DIR.iterdir():
        if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
            ve_id = folder.name.replace(f'{IE_ID}-', '')
            volumes.append((ve_id, folder))
    result = natsorted(volumes, key=lambda x: x[0])
    logger.info(f"Found {len(result)} volume folders")
    return result


def get_rtf_files_in_volume(volume_folder: Path) -> list:
    rtf_files = list(volume_folder.glob("*.rtf"))
    return natsorted(rtf_files, key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int) -> str:
    ve_suffix = ve_id[2:]
    return f"UT{ve_suffix}_{file_index + 1:04d}"


def classify_font_sizes(streams: list) -> dict:
    size_counts = Counter()
    for stream in streams:
        text = stream.get("text", "")
        font_size = stream.get("font", {}).get("size", 12)
        tibetan_chars = len([c for c in text if 0x0F00 <= ord(c) <= 0x0FFF])
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    if not size_counts:
        return {}
    most_common = max(size_counts.items(), key=lambda x: x[1])[0]
    classifications = {}
    for font_size in size_counts.keys():
        if font_size == most_common:
            classifications[font_size] = 'regular'
        elif font_size > most_common:
            classifications[font_size] = 'head'
        else:
            classifications[font_size] = 'small'
    return classifications


def escape_xml(text: str) -> str:
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def clean_rtf_fallback_chars(text: str) -> str:
    tibetan_range = '[\u0F00-\u0FFF]'
    text = re.sub(r'^([a-zA-Z?])(' + tibetan_range + ')', r'\2', text)
    text = re.sub(r'\n([a-zA-Z?])(' + tibetan_range + ')', r'\n\2', text)
    text = re.sub(r'\n([a-zA-Z?]) (' + tibetan_range + ')', r'\n\2', text)
    text = re.sub(r'\n([a-zA-Z?])$', r'\n', text)
    text = re.sub(r'^([a-zA-Z?])$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^([a-zA-Z?]) ', '', text, flags=re.MULTILINE)
    return text


def is_primarily_tibetan(text: str) -> bool:
    if not text.strip():
        return False
    tibetan_count = 0
    latin_count = 0
    for char in text:
        code = ord(char)
        if 0x0F00 <= code <= 0x0FFF:
            tibetan_count += 1
        elif (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
            latin_count += 1
    if tibetan_count == 0:
        return False
    if latin_count > tibetan_count:
        return False
    return True


def calculate_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def convert_rtf_to_tei(rtf_path: Path, ve_id: str, ut_id: str, src_path: str) -> str:
    logger.info(f"  Parsing RTF file: {rtf_path.name}")
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    logger.info(f"  Parsed {len(streams)} text streams")
    
    classifications = classify_font_sizes(streams)
    if classifications:
        logger.info(f"  Font size classifications: {classifications}")
    
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
        if not is_primarily_tibetan(normalized_text):
            continue
        escaped_text = escape_xml(normalized_text)
        classification = classifications.get(font_size, 'regular')
        if classification != current_markup:
            if current_markup == 'small':
                tei_lines.append('</hi>')
            elif current_markup == 'head':
                tei_lines.append('</hi>')
            if classification == 'small':
                tei_lines.append('<hi rend="small">')
            elif classification == 'head':
                tei_lines.append('<hi rend="head">')
            current_markup = classification if classification != 'regular' else None
        tei_lines.append(escaped_text)
    
    if current_markup == 'small':
        tei_lines.append('</hi>')
    elif current_markup == 'head':
        tei_lines.append('</hi>')
    
    body_content = ''.join(tei_lines)
    body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    body_content = re.sub(r'PAGE \* MERGEFORMAT \d+\s*', '', body_content)
    body_content = re.sub(r'\n\n+', '\n', body_content)
    body_content = body_content.replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '\n<lb/>', body_content)
    body_content = body_content.strip()
    body_content = re.sub(r'(<lb/>[\s\n]*)+</hi>', r'</hi>', body_content)
    body_content = re.sub(r'\n\s*(</hi>)', r'\1', body_content)
    body_content = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r'\n<lb/>\1', body_content)
    body_content = re.sub(r'\n<lb/>\s*\n', '\n', body_content)
    body_content = re.sub(r'(<lb/>)\s*(<lb/>)', r'\1', body_content)
    body_content = re.sub(r'\n<lb/>\s*$', '', body_content)
    if body_content.startswith('<lb/>'):
        body_content = '\n' + body_content
    
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


def convert_volume(ve_id: str, volume_folder: Path, output_dir: Path):
    rtf_files = get_rtf_files_in_volume(volume_folder)
    if not rtf_files:
        logger.warning(f"  No RTF files found in {volume_folder}")
        return 0, 0
    logger.info(f"  Found {len(rtf_files)} RTF files")
    
    archive_dir = output_dir / "archive" / ve_id
    sources_dir = output_dir / "sources" / ve_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = 0
    
    for idx, rtf_path in enumerate(rtf_files):
        ut_id = get_ut_id(ve_id, idx)
        src_path = f"sources/{ve_id}/{rtf_path.name}"
        logger.info(f"  [{idx + 1}/{len(rtf_files)}] {rtf_path.name} -> {ut_id}")
        try:
            dest_rtf = sources_dir / rtf_path.name
            shutil.copy2(rtf_path, dest_rtf)
            tei_xml = convert_rtf_to_tei(rtf_path, ve_id, ut_id, src_path)
            xml_path = archive_dir / f"{ut_id}.xml"
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(tei_xml)
            success += 1
        except Exception as e:
            logger.error(f"  Error converting {rtf_path.name}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    return success, failed


def convert_all_volumes(output_dir: Path = None):
    if output_dir is None:
        output_dir = OUTPUT_DIR
    logger.info("=" * 60)
    logger.info(f"Converting all files for {IE_ID}")
    logger.info(f"Input: {TOPROCESS_DIR}")
    logger.info(f"Output: {output_dir}")
    logger.info("=" * 60)
    
    volumes = get_volume_folders()
    if not volumes:
        logger.error("No volume folders found")
        return
    
    total_success = 0
    total_failed = 0
    
    for vol_idx, (ve_id, volume_folder) in enumerate(volumes):
        logger.info(f"\n[Volume {vol_idx + 1}/{len(volumes)}] {ve_id}")
        success, failed = convert_volume(ve_id, volume_folder, output_dir)
        total_success += success
        total_failed += failed
    
    logger.info("\n" + "=" * 60)
    logger.info("Conversion complete!")
    logger.info(f"  Total volumes: {len(volumes)}")
    logger.info(f"  Total success: {total_success}")
    logger.info(f"  Total failed: {total_failed}")
    logger.info(f"  Output: {output_dir}")
    logger.info("=" * 60)


if __name__ == "__main__":
    DEBUG_MODE = False
    DEBUG_VOLUME = "VE1KG4325_001"
    
    if DEBUG_MODE:
        logger.info("=== DEBUG MODE ===")
        volumes = get_volume_folders()
        target_folder = None
        for ve_id, folder in volumes:
            if ve_id == DEBUG_VOLUME:
                target_folder = folder
                break
        if target_folder:
            convert_volume(DEBUG_VOLUME, target_folder, OUTPUT_DIR)
        else:
            logger.error(f"Volume {DEBUG_VOLUME} not found")
    else:
        logger.info("=== BATCH MODE - Converting all volumes ===")
        convert_all_volumes(OUTPUT_DIR)






