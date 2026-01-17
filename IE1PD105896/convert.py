#!/usr/bin/env python3
"""
Batch RTF to TEI XML Converter
Final Version: Robust Noise Filtering with ISBN exclusion.
"""

import sys
import re
import hashlib
import shutil
import logging
import argparse
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter
import multiprocessing

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

try:
    from natsort import natsorted
except ImportError:
    logger.warning("natsort not installed, using basic sorting")
    natsorted = sorted

from basic_rtf import BasicRTF
from normalization import normalize_unicode


# =============================================================================
# Configuration
# =============================================================================

INPUT_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/file_convert")
DEFAULT_WORKERS = max(1, multiprocessing.cpu_count() - 1)


# =============================================================================
# Discovery Functions
# =============================================================================

def discover_collections(input_dir: Path) -> list:
    """Discover all IE collections in the input directory."""
    collections = []
    for ie_folder in input_dir.iterdir():
        if not ie_folder.is_dir(): continue
        ie_id = ie_folder.name
        
        if (ie_folder / ie_id / "sources").exists():
            collections.append((ie_id, ie_folder / ie_id / "sources", ie_folder / f"{ie_id}_output"))
        elif (ie_folder / "sources").exists():
            collections.append((ie_id, ie_folder / "sources", ie_folder / f"{ie_id}_output"))
        elif (ie_folder / ie_id / "toprocess").exists():
            collections.append((ie_id, ie_folder / ie_id / "toprocess", ie_folder / f"{ie_id}_output"))
        elif (ie_folder / "toprocess").exists():
            collections.append((ie_id, ie_folder / "toprocess", ie_folder / f"{ie_id}_output"))
    
    return natsorted(collections, key=lambda x: x[0])


def get_volume_folders(ie_id: str, sources_dir: Path) -> list:
    """Get list of volume folders."""
    volumes = []
    for ve_folder in sources_dir.iterdir():
        if not ve_folder.is_dir(): continue
        ve_id = ve_folder.name
        
        # Nested structure check
        for subdir in ve_folder.iterdir():
            if subdir.is_dir() and not subdir.name.startswith('.'):
                rtfs_base = subdir / "rtfs"
                if rtfs_base.exists():
                    collection_name = subdir.name
                    for vol_folder in rtfs_base.iterdir():
                        if vol_folder.name.startswith('volume_') and list(vol_folder.glob("*.rtf")):
                            volumes.append((ve_id, vol_folder.name.replace('volume_', ''), vol_folder, collection_name))
                    break
        
        # Direct structure check
        if not any(v[0] == ve_id for v in volumes):
            if list(ve_folder.glob("*.rtf")):
                volumes.append((ve_id, None, ve_folder, None))
                
    if not volumes:
        for folder in sources_dir.iterdir():
            if folder.name.startswith(f'{ie_id}-'):
                volumes.append((folder.name.replace(f'{ie_id}-', ''), None, folder, None))
    
    return natsorted(volumes, key=lambda x: (x[0], x[1] or ''))


def get_rtf_files(volume_folder: Path) -> list:
    return natsorted(list(volume_folder.glob("*.rtf")), key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int) -> str:
    ve_suffix = ve_id[2:] if ve_id.startswith('VE') else ve_id
    return f"UT{ve_suffix}_{file_index + 1:04d}"


def classify_font_sizes(streams: list) -> dict:
    size_counts = Counter()
    for stream in streams:
        text = stream.get("text", "")
        tibetan_chars = len([c for c in text if 0x0F00 <= ord(c) <= 0x0FFF])
        if tibetan_chars > 0:
            size_counts[stream.get("font", {}).get("size", 12)] += tibetan_chars
            
    if not size_counts: return {}
    most_common = max(size_counts.items(), key=lambda x: x[1])[0]
    
    return {fs: ('regular' if fs == most_common else 'large' if fs > most_common else 'small') for fs in size_counts}


# =============================================================================
# FILTERING LOGIC
# =============================================================================

def remove_non_tibetan(text: str) -> str:
    """
    Final Smart Filter:
    1. Removes RTF/ISBN/Dimension noise.
    2. Keeps Tibetan Text.
    3. Keeps valid years (600-2100), excluding ISBN prefixes (978/979).
    """
    # 1. Clean RTF noise
    text = re.sub(r"PAGE\s*\*?\s*MERGEFORMAT\s*\d*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"-?\s*PAGE\s+\d+\s*-+", "", text, flags=re.IGNORECASE)

    # 2. Pre-clean Metadata Artifacts
    text = re.sub(r"ISBN\s*[\d-]+", "", text, flags=re.IGNORECASE) # ISBN labels
    text = re.sub(r"\d+\s*[xX×]\s*\d+", "", text)                   # Dimensions
    text = re.sub(r"\d+\.\d+", "", text)                            # Decimals (prices)

    # 3. Positive Selection
    # Group 1: Tibetan
    # Group 2: Potential Years (3-4 digits)
    # Group 3: Whitespace
    pattern = r"([\u0F00-\u0FFF]+)|(\b\d{3,4}\b)|(\s+)"
    
    matches = re.findall(pattern, text)
    
    cleaned_parts = []
    
    for tibetan, year_candidate, space in matches:
        if tibetan:
            cleaned_parts.append(tibetan)
        elif year_candidate:
            # RANGE CHECK: 600 to 2100 AD
            try:
                val = int(year_candidate)
                # Check range AND exclude common ISBN prefixes (978, 979)
                if 600 < val <= 2100 and val not in [978, 979]:
                    cleaned_parts.append(year_candidate)
            except ValueError:
                pass
        elif space:
            cleaned_parts.append(space)
            
    return "".join(cleaned_parts)#.strip()


# =============================================================================
# RTF to TEI Conversion
# =============================================================================

def escape_xml(text: str) -> str:
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

def calculate_sha256(file_path: Path) -> str:
    sha = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for b in iter(lambda: f.read(4096), b""): sha.update(b)
        return sha.hexdigest()
    except FileNotFoundError: return "FILE_NOT_FOUND"

def convert_rtf_to_tei(rtf_path: Path, ie_id: str, ve_id: str, ut_id: str, src_path: str) -> str:
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    
    logger.info(f"  Parsed {len(streams)} text streams")
    classifications = classify_font_sizes(streams)
    tei_lines = []
    current_markup = None
    
    for stream in streams:
        if stream.get("type") in ("header", "footer", "pict"): continue
        
        raw_text = stream.get("text", "")
        cleaned_text = remove_non_tibetan(raw_text)
        normalized_text = normalize_unicode(cleaned_text)
        
        if not normalized_text.strip(): continue
        
        escaped_text = escape_xml(normalized_text)
        classification = classifications.get(stream.get("font", {}).get("size", 12), 'regular')
        
        if classification != current_markup:
            if current_markup in ('small', 'large'): tei_lines.append('</hi>')
            if classification == 'small': tei_lines.append('<hi rend="small">')
            elif classification == 'large': tei_lines.append('<hi rend="head">')
            current_markup = classification if classification != 'regular' else None
        
        tei_lines.append(escaped_text)
    
    if current_markup in ('small', 'large'): tei_lines.append('</hi>')
    
    body_content = ''.join(tei_lines)
    body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    body_content = re.sub(r'\n\n+', '\n', body_content).replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '\n<lb/>', body_content).strip()
    
    sha256 = calculate_sha256(rtf_path)
    
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
<fileDesc>
<titleStmt><title>{escape_xml(rtf_path.stem)}</title></titleStmt>
<publicationStmt><p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p></publicationStmt>
<sourceDesc>
<bibl>
<idno type="src_path">{src_path}</idno>
<idno type="src_sha256">{sha256}</idno>
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{ie_id}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl>
</sourceDesc>
</fileDesc>
<encodingDesc>
<p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{ie_id}">record in the BDRC database</ref>.</p>
</encodingDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p>{body_content}</p>
</body>
</text>
</TEI>
'''

def process_volume(args: tuple) -> dict:
    ie_id, ve_id, vol_num, vol_folder, out_dir, coll_name = args
    res = {"ie_id": ie_id, "ve_id": ve_id, "volume_label": f"{ve_id}_vol{vol_num}" if vol_num else ve_id, "success": 0, "failed": 0, "errors": []}
    
    try:
        rtf_files = get_rtf_files(vol_folder)
        if not rtf_files: return res
        
        path_suffix = f"/{coll_name}/xml/volume_{vol_num}" if vol_num and coll_name else ""
        xml_out = out_dir / "archive" / ve_id / (f"{coll_name}/xml/volume_{vol_num}" if vol_num and coll_name else "")
        rtf_out = out_dir / "sources" / ve_id / (f"{coll_name}/rtfs/volume_{vol_num}" if vol_num and coll_name else "")
        
        xml_out.mkdir(parents=True, exist_ok=True)
        rtf_out.mkdir(parents=True, exist_ok=True)
        
        for idx, rtf_path in enumerate(rtf_files):
            ut_id = get_ut_id(ve_id, idx)
            src_rel = f"sources/{ve_id}{path_suffix}/{rtf_path.name}"
            
            try:
                tei_xml = convert_rtf_to_tei(rtf_path, ie_id, ve_id, ut_id, src_rel)
                with open(xml_out / f"{ut_id}.xml", 'w', encoding='utf-8') as f: f.write(tei_xml)
                shutil.copy2(rtf_path, rtf_out / rtf_path.name)
                res["success"] += 1
            except Exception as e:
                res["failed"] += 1
                res["errors"].append(f"{rtf_path.name}: {str(e)}")
                
    except Exception as e: res["errors"].append(f"Volume error: {str(e)}")
    return res

def process_all_collections(input_dir: Path, workers: int, ie_filter: str = None):
    logger.info(f"BATCH RTF TO TEI XML | Workers: {workers}")
    collections = discover_collections(input_dir)
    if ie_filter: collections = [c for c in collections if c[0] == ie_filter]
    
    total_suc = total_fail = 0
    for ie_id, src, out in collections:
        logger.info(f"Processing {ie_id}...")
        vols = get_volume_folders(ie_id, src)
        work_items = [(ie_id, v[0], v[1], v[2], out, v[3]) for v in vols]
        
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for f in as_completed({ex.submit(process_volume, i): i for i in work_items}):
                r = f.result()
                total_suc += r["success"]
                total_fail += r["failed"]
                if r["failed"] > 0 or r["errors"]: logger.info(f"  {r['volume_label']}: {r['success']} OK, {r['failed']} FAIL")

    logger.info(f"DONE. Total Success: {total_suc}, Total Failed: {total_fail}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", type=Path, default=INPUT_DIR)
    p.add_argument("--ie-id", type=str)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    args = p.parse_args()
    if args.input_dir.exists(): process_all_collections(args.input_dir, args.workers, args.ie_id)
    else: logger.error("Input dir not found")

if __name__ == "__main__":
    main()