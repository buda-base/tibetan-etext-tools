#!/usr/bin/env python3
"""Convert intermediate XML files from IE3KG550 to TEI XML format."""

import sys, re, hashlib, shutil, logging
import xml.etree.ElementTree as ET
from pathlib import Path
from natsort import natsorted

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger(__name__)

IE_ID = "IE3KG550"
W_ID = "W3KG550"
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
INPUT_DIR = BASE_DIR / "xml" / IE_ID / IE_ID
SOURCES_DIR = INPUT_DIR / "sources"
OUTPUT_DIR = BASE_DIR / "xml_output" / IE_ID

def get_volume_data():
    volumes = []
    if SOURCES_DIR.exists():
        for folder in SOURCES_DIR.iterdir():
            if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
                ve_id = folder.name.replace(f'{IE_ID}-', '')
                doc_files = natsorted(list(folder.rglob("*.doc")) + list(folder.rglob("*.docx")), key=lambda p: p.name)
                if doc_files:
                    volumes.append({'ve_id': ve_id, 'doc_files': doc_files})
                    logger.info(f"  Found volume {ve_id}")
    return sorted(volumes, key=lambda v: v['ve_id'])

def get_xml_files():
    return natsorted(list(INPUT_DIR.glob(f"{W_ID}_*_parsed.xml")), key=lambda p: p.name)

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
        logger.error(f"Error: {e}")
        return ""

def convert_xml_to_tei(xml_path, ve_id, ut_id, doc_path, src_path):
    body = extract_content(xml_path)
    sha = calculate_sha256(doc_path)
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
    logger.info(f"=== {IE_ID} XML Conversion ===")
    volumes, xml_files = get_volume_data(), get_xml_files()
    count = min(len(volumes), len(xml_files))
    if count == 0:
        logger.error("No files"); return
    
    success = 0
    for i in range(count):
        v, x = volumes[i], xml_files[i]
        ve_id, doc = v['ve_id'], v['doc_files'][0]
        arch, src = OUTPUT_DIR/"archive"/ve_id, OUTPUT_DIR/"sources"/ve_id
        arch.mkdir(parents=True, exist_ok=True); src.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(doc, src/doc.name); shutil.copy2(x, src/x.name)
            ut_id = get_ut_id(ve_id)
            with open(arch/f"{ut_id}.xml", 'w', encoding='utf-8') as f:
                f.write(convert_xml_to_tei(x, ve_id, ut_id, doc, f"sources/{ve_id}/{doc.name}"))
            logger.info(f"Processed {ve_id}"); success += 1
        except Exception as e:
            logger.error(f"Error {ve_id}: {e}")
    logger.info(f"Done! {success}/{count}")

if __name__ == "__main__":
    convert_all()






