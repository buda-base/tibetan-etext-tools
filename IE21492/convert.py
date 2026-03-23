#!/usr/bin/env python3
"""
Convert intermediate XML files from IE21492 to TEI XML format.
Type E: source/ has existing UT XMLs, toprocess/{VE}/ has intermediate XMLs.
"""

import sys, re, hashlib, shutil, logging
import xml.etree.ElementTree as ET
from pathlib import Path
from natsort import natsorted

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

IE_ID = "IE21492"
W_ID = "W21492"
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
INPUT_DIR = BASE_DIR / "xml" / IE_ID / IE_ID
SOURCE_DIR = INPUT_DIR / "source"
TOPROCESS_DIR = INPUT_DIR / "toprocess"
OUTPUT_DIR = BASE_DIR / "xml_output" / IE_ID


def get_volume_data():
    """
    Get volumes by combining source/ and toprocess/ folders.
    Both should have matching VE folders.
    """
    volumes = []
    
    if not SOURCE_DIR.exists() or not TOPROCESS_DIR.exists():
        logger.error("source or toprocess folder not found")
        return []
    
    # Get all VE folders from source
    for folder in SOURCE_DIR.iterdir():
        if folder.is_dir() and folder.name.startswith('VE'):
            ve_id = folder.name
            source_xmls = list(folder.glob("*.xml"))
            
            # Find matching toprocess folder
            toprocess_folder = TOPROCESS_DIR / ve_id
            intermediate_xmls = []
            if toprocess_folder.exists():
                intermediate_xmls = list(toprocess_folder.glob("*.xml"))
            
            if intermediate_xmls:
                volumes.append({
                    've_id': ve_id,
                    'source_folder': folder,
                    'source_xmls': source_xmls,
                    'toprocess_folder': toprocess_folder,
                    'intermediate_xmls': intermediate_xmls
                })
                logger.info(f"  Found volume {ve_id}: {len(source_xmls)} source XMLs, {len(intermediate_xmls)} intermediate XMLs")
            else:
                logger.warning(f"  Volume {ve_id} has no intermediate XMLs in toprocess/")
    
    return natsorted(volumes, key=lambda v: v['ve_id'])


def get_ut_id(ve_id, idx=0):
    """Generate UT ID from VE ID."""
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
    logger.info(f"=== {IE_ID} XML Conversion (Type E) ===")
    volumes = get_volume_data()
    
    if not volumes:
        logger.error("No volumes to process")
        return
    
    logger.info(f"\nFound {len(volumes)} volumes to process")
    
    success = 0
    for v in volumes:
        ve_id = v['ve_id']
        
        arch_dir = OUTPUT_DIR / "archive" / ve_id
        src_dir = OUTPUT_DIR / "sources" / ve_id
        arch_dir.mkdir(parents=True, exist_ok=True)
        src_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 1. Copy all source XMLs (existing UT files) from source/
            for src_xml in v['source_xmls']:
                shutil.copy2(src_xml, src_dir / src_xml.name)
            logger.info(f"  Copied {len(v['source_xmls'])} source XMLs from source/{ve_id}")
            
            # 2. Copy all intermediate XMLs from toprocess/ to sources/
            for int_xml in v['intermediate_xmls']:
                shutil.copy2(int_xml, src_dir / int_xml.name)
            logger.info(f"  Copied {len(v['intermediate_xmls'])} intermediate XMLs from toprocess/{ve_id}")
            
            # 3. Convert each intermediate XML to TEI in archive/
            for idx, int_xml in enumerate(natsorted(v['intermediate_xmls'], key=lambda p: p.name)):
                ut_id = get_ut_id(ve_id, idx)
                src_path = f"sources/{ve_id}/{int_xml.name}"
                tei_xml = convert_xml_to_tei(int_xml, ve_id, ut_id, src_path)
                
                with open(arch_dir / f"{ut_id}.xml", 'w', encoding='utf-8') as f:
                    f.write(tei_xml)
                logger.info(f"  Created TEI: archive/{ve_id}/{ut_id}.xml")
            
            success += 1
            
        except Exception as e:
            logger.error(f"  Error processing {ve_id}: {e}")
            import traceback
            traceback.print_exc()
    
    logger.info(f"\nDone! {success}/{len(volumes)}")


if __name__ == "__main__":
    convert_all()






