#!/usr/bin/env python3
"""
Convert intermediate XML files from IE3CN22358 to TEI XML format.
"""

import sys
import re
import hashlib
import shutil
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from natsort import natsorted

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# Configuration
IE_ID = "IE3CN22358"
W_ID = "W3CN22358"

BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
INPUT_DIR = BASE_DIR / "xml" / IE_ID / IE_ID
SOURCES_DIR = INPUT_DIR / "sources"
OUTPUT_DIR = BASE_DIR / "xml_output" / IE_ID


def get_volume_data() -> list:
    logger.info(f"Looking for volume folders in: {SOURCES_DIR}")
    if not SOURCES_DIR.exists():
        return []
    
    volumes = []
    for folder in SOURCES_DIR.iterdir():
        if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
            ve_id = folder.name.replace(f'{IE_ID}-', '')
            doc_files = list(folder.rglob("*.doc")) + list(folder.rglob("*.docx"))
            doc_files = natsorted(doc_files, key=lambda p: p.name)
            if doc_files:
                volumes.append({'ve_id': ve_id, 'folder_path': folder, 'doc_files': doc_files})
                logger.info(f"  Found volume {ve_id} with {len(doc_files)} doc file(s)")
    return sorted(volumes, key=lambda v: v['ve_id'])


def get_xml_files() -> list:
    return natsorted(list(INPUT_DIR.glob(f"{W_ID}_*_parsed.xml")), key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int = 0) -> str:
    return f"UT{ve_id[2:]}_{file_index + 1:04d}"


def calculate_sha256(file_path: Path) -> str:
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except:
        return "FILE_NOT_FOUND"


def escape_xml(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def extract_content_from_xml(xml_path: Path) -> str:
    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        root = ET.fromstring(content)
        
        def process_element(elem):
            result = []
            if elem.text:
                result.append(elem.text.strip() if elem.text.strip() else '')
            for child in elem:
                if child.tag == 'lb':
                    result.append('\n<lb/>')
                elif child.tag == 'pb':
                    result.append(f'\n<pb n="{child.get("n", "")}"/>')
                else:
                    result.extend(process_element(child))
                if child.tail:
                    result.append(child.tail)
            return result
        
        body_content = ''.join(process_element(root))
        body_content = re.sub(r'\n\n+', '\n', body_content).strip()
        return '\n' + body_content if body_content.startswith('<lb/>') else body_content
    except Exception as e:
        logger.error(f"Error processing {xml_path}: {e}")
        return ""


def convert_xml_to_tei(xml_path: Path, ve_id: str, ut_id: str, doc_path: Path, src_path: str) -> str:
    logger.info(f"  Converting: {xml_path.name}")
    body_content = extract_content_from_xml(xml_path)
    sha256 = calculate_sha256(doc_path)
    title = xml_path.stem
    
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
<fileDesc>
<titleStmt><title>{escape_xml(title)}</title></titleStmt>
<publicationStmt><p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p></publicationStmt>
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
<encodingDesc><p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{IE_ID}">record in the BDRC database</ref>.</p></encodingDesc>
</teiHeader>
<text><body xml:lang="bo"><p>{body_content}</p></body></text>
</TEI>
'''


def convert_volume(vol_idx: int, ve_id: str, doc_path: Path, xml_path: Path, output_dir: Path) -> bool:
    logger.info(f"Processing volume {vol_idx + 1}: {ve_id}")
    archive_dir = output_dir / "archive" / ve_id
    sources_dir = output_dir / "sources" / ve_id
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        shutil.copy2(doc_path, sources_dir / doc_path.name)
        shutil.copy2(xml_path, sources_dir / xml_path.name)
        ut_id = get_ut_id(ve_id, 0)
        tei_xml = convert_xml_to_tei(xml_path, ve_id, ut_id, doc_path, f"sources/{ve_id}/{doc_path.name}")
        with open(archive_dir / f"{ut_id}.xml", 'w', encoding='utf-8') as f:
            f.write(tei_xml)
        logger.info(f"  Created TEI XML: archive/{ve_id}/{ut_id}.xml")
        return True
    except Exception as e:
        logger.error(f"  Error: {e}")
        return False


def convert_all_volumes():
    logger.info("=" * 60)
    logger.info(f"Converting all files for {IE_ID}")
    logger.info("=" * 60)
    
    volumes = get_volume_data()
    xml_files = get_xml_files()
    count = min(len(volumes), len(xml_files))
    
    if count == 0:
        logger.error("No files to process")
        return
    
    success = sum(1 for i in range(count) if convert_volume(i, volumes[i]['ve_id'], volumes[i]['doc_files'][0], xml_files[i], OUTPUT_DIR))
    logger.info(f"\nConversion complete! Success: {success}/{count}")


if __name__ == "__main__":
    convert_all_volumes()






