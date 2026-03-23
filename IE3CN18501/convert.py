#!/usr/bin/env python3
"""
Convert intermediate XML files from IE3CN18501 to TEI XML format.
Type B Flat: sources/ has flat doc files (no volume subfolders), single volume VE1ER540.
"""

import sys, re, hashlib, shutil, logging
import xml.etree.ElementTree as ET
from pathlib import Path
from natsort import natsorted

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

IE_ID = "IE3CN18501"
W_ID = "W3CN18501"
VE_ID = "VE1ER540"  # Hardcoded single volume

BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
INPUT_DIR = BASE_DIR / "xml" / IE_ID / IE_ID
SOURCES_DIR = INPUT_DIR / "sources"
OUTPUT_DIR = BASE_DIR / "xml_output" / IE_ID


def get_doc_files():
    """Get all doc/docx files from flat sources directory."""
    doc_files = list(SOURCES_DIR.glob("*.doc")) + list(SOURCES_DIR.glob("*.docx"))
    return natsorted(doc_files, key=lambda p: p.name)


def get_xml_file():
    """Get the intermediate XML file from root."""
    xml_files = list(INPUT_DIR.glob(f"{W_ID}_*_parsed.xml"))
    return xml_files[0] if xml_files else None


def get_ut_id(ve_id, idx=0):
    return f"UT{ve_id[2:]}_{idx + 1:04d}"


def calculate_sha256(fp):
    h = hashlib.sha256()
    try:
        with open(fp, "rb") as f:
            for b in iter(lambda: f.read(4096), b""):
                h.update(b)
        return h.hexdigest()
    except:
        return "FILE_NOT_FOUND"


def extract_content(xml_path):
    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            root = ET.fromstring(f.read())
        def proc(e):
            r = [e.text.strip() if e.text and e.text.strip() else '']
            for c in e:
                if c.tag == 'lb': r.append('\n<lb/>')
                elif c.tag == 'pb': r.append(f'\n<pb n="{c.get("n", "")}"/>')
                else: r.extend(proc(c))
                if c.tail: r.append(c.tail)
            return r
        body = ''.join(proc(root))
        body = re.sub(r'\n\n+', '\n', body).strip()
        return '\n' + body if body.startswith('<lb/>') else body
    except Exception as e:
        logger.error(f"Error extracting from {xml_path}: {e}")
        return ""


def convert_xml_to_tei(xml_path, ve_id, ut_id, src_path):
    body = extract_content(xml_path)
    sha = calculate_sha256(xml_path)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader><fileDesc>
<titleStmt><title>{xml_path.stem}</title></titleStmt>
<publicationStmt><p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p></publicationStmt>
<sourceDesc><bibl>
<idno type="src_path">{src_path}</idno><idno type="src_sha256">{sha}</idno>
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{IE_ID}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl></sourceDesc>
</fileDesc>
<encodingDesc><p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{IE_ID}">record in the BDRC database</ref>.</p></encodingDesc>
</teiHeader>
<text><body xml:lang="bo"><p>{body}</p></body></text>
</TEI>
'''


def convert_all():
    logger.info(f"=== {IE_ID} XML Conversion (Type B Flat) ===")
    logger.info(f"Volume: {VE_ID}")
    
    doc_files = get_doc_files()
    xml_file = get_xml_file()
    
    logger.info(f"Found {len(doc_files)} doc files")
    for df in doc_files:
        logger.info(f"  - {df.name}")
    
    if not xml_file:
        logger.error("No intermediate XML file found")
        return
    logger.info(f"Found intermediate XML: {xml_file.name}")
    
    # Create output directories
    arch_dir = OUTPUT_DIR / "archive" / VE_ID
    src_dir = OUTPUT_DIR / "sources" / VE_ID
    arch_dir.mkdir(parents=True, exist_ok=True)
    src_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # 1. Copy all doc files to sources/VE1ER540/
        for doc_file in doc_files:
            shutil.copy2(doc_file, src_dir / doc_file.name)
            logger.info(f"  Copied: {doc_file.name}")
        
        # 2. Copy intermediate XML to sources/VE1ER540/
        shutil.copy2(xml_file, src_dir / xml_file.name)
        logger.info(f"  Copied: {xml_file.name}")
        
        # 3. Convert to TEI XML
        ut_id = get_ut_id(VE_ID)
        src_path = f"sources/{VE_ID}/{xml_file.name}"
        tei_xml = convert_xml_to_tei(xml_file, VE_ID, ut_id, src_path)
        
        # 4. Save to archive/VE1ER540/
        output_path = arch_dir / f"{ut_id}.xml"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(tei_xml)
        logger.info(f"  Created TEI: archive/{VE_ID}/{ut_id}.xml")
        
        logger.info(f"\nDone! Successfully processed {VE_ID}")
        
    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    convert_all()






