#!/usr/bin/env python3
"""
Convert intermediate XML files from IE21019 to TEI XML format.
Type C: source/ folder contains existing UT XMLs, intermediate XMLs at root.
"""

import sys, re, hashlib, shutil, logging
import xml.etree.ElementTree as ET
from pathlib import Path
from natsort import natsorted

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

IE_ID = "IE21019"
W_ID = "W21019"
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
INPUT_DIR = BASE_DIR / "xml" / IE_ID / IE_ID
SOURCE_DIR = INPUT_DIR / "source"  # Note: 'source' not 'sources'
OUTPUT_DIR = BASE_DIR / "xml_output" / IE_ID


def get_volume_data():
    """Get volumes from source/ directory."""
    volumes = []
    if SOURCE_DIR.exists():
        for folder in SOURCE_DIR.iterdir():
            if folder.is_dir() and folder.name.startswith('VE'):
                ve_id = folder.name
                # Get all XML files in this volume (existing UT files)
                source_xmls = list(folder.glob("*.xml"))
                volumes.append({'ve_id': ve_id, 'folder_path': folder, 'source_xmls': source_xmls})
                logger.info(f"  Found volume {ve_id} with {len(source_xmls)} source XMLs")
    return natsorted(volumes, key=lambda v: v['ve_id'])


def get_xml_files():
    """Get intermediate XML files from root."""
    return natsorted(list(INPUT_DIR.glob(f"{W_ID}_*_parsed.xml")), key=lambda p: p.name)


def get_ut_id(ve_id, idx=0):
    """Generate UT ID - handle both VE21019_001 and VE1ER565 formats."""
    if ve_id.startswith('VE') and '_' in ve_id:
        # Format: VE21019_001 -> UT21019_001_0001
        return f"UT{ve_id[2:]}_{idx + 1:04d}"
    else:
        # Format: VE1ER565 -> UT1ER565_0001
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
    sha = calculate_sha256(xml_path)  # Use intermediate XML for hash since no doc file
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
    logger.info(f"=== {IE_ID} XML Conversion (Type C) ===")
    volumes = get_volume_data()
    xml_files = get_xml_files()
    
    logger.info(f"Found {len(volumes)} volumes, {len(xml_files)} intermediate XMLs")
    
    count = min(len(volumes), len(xml_files))
    if count == 0:
        logger.error("No files to process")
        return
    
    # Print mapping
    logger.info("\nMapping:")
    for i in range(count):
        logger.info(f"  {i+1}. {volumes[i]['ve_id']} <- {xml_files[i].name}")
    
    success = 0
    for i in range(count):
        v = volumes[i]
        x = xml_files[i]
        ve_id = v['ve_id']
        
        arch_dir = OUTPUT_DIR / "archive" / ve_id
        src_dir = OUTPUT_DIR / "sources" / ve_id
        arch_dir.mkdir(parents=True, exist_ok=True)
        src_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Copy all existing source XMLs (UT files) to output sources
            for src_xml in v['source_xmls']:
                shutil.copy2(src_xml, src_dir / src_xml.name)
            logger.info(f"  Copied {len(v['source_xmls'])} source XMLs to {ve_id}")
            
            # Copy intermediate XML to sources
            shutil.copy2(x, src_dir / x.name)
            logger.info(f"  Copied intermediate XML: {x.name}")
            
            # Convert intermediate XML to TEI
            ut_id = get_ut_id(ve_id)
            src_path = f"sources/{ve_id}/{x.name}"
            tei_xml = convert_xml_to_tei(x, ve_id, ut_id, src_path)
            
            with open(arch_dir / f"{ut_id}.xml", 'w', encoding='utf-8') as f:
                f.write(tei_xml)
            logger.info(f"  Created TEI: archive/{ve_id}/{ut_id}.xml")
            success += 1
            
        except Exception as e:
            logger.error(f"  Error processing {ve_id}: {e}")
            import traceback
            traceback.print_exc()
    
    logger.info(f"\nDone! {success}/{count}")


if __name__ == "__main__":
    convert_all()






