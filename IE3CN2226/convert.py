#!/usr/bin/env python3
"""
Convert intermediate XML files from IE3CN2226 to TEI XML format.

This script converts intermediate XML files (with <text>, <pb>, <lb/> tags)
to proper TEI XML format with metadata headers.

Input structure:
    xml/IE3CN2226/IE3CN2226/sources/IE3CN2226-VE5CN658/W3CN2226_1-335.doc
    xml/IE3CN2226/IE3CN2226/W3CN2226_I3CN2228_parsed.xml

Output structure:
    xml_output/IE3CN2226/archive/VE5CN658/UT5CN658_0001.xml
    xml_output/IE3CN2226/sources/VE5CN658/W3CN2226_1-335.doc
    xml_output/IE3CN2226/sources/VE5CN658/W3CN2226_I3CN2228_parsed.xml

Usage:
    python convert.py
"""

import sys
import os
import re
import hashlib
import shutil
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from natsort import natsorted

# Configure logging with immediate output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Ensure stdout is unbuffered for immediate output
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# =============================================================================
# Configuration
# =============================================================================

IE_ID = "IE3CN2226"
W_ID = "W3CN2226"  # Work ID pattern for XML files

# Paths
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944")
INPUT_DIR = BASE_DIR / "xml" / "IE3CN2226" / "IE3CN2226"
SOURCES_DIR = INPUT_DIR / "sources"
OUTPUT_DIR = BASE_DIR / "xml_output" / "IE3CN2226"


# =============================================================================
# Helper Functions
# =============================================================================

def get_volume_data() -> list:
    """
    Get list of volume data from sources directory.
    
    Each folder in sources is named like: IE3CN2226-VE5CN658
    Doc files are inside these volume folders.
    
    Returns:
        List of dicts with keys: ve_id, folder_path, doc_files
    """
    logger.info(f"Looking for volume folders in: {SOURCES_DIR}")
    
    if not SOURCES_DIR.exists():
        logger.error(f"Sources folder not found at {SOURCES_DIR}")
        return []
    
    volumes = []
    for folder in SOURCES_DIR.iterdir():
        if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
            ve_id = folder.name.replace(f'{IE_ID}-', '')  # "VE5CN658"
            
            # Get doc files from this volume folder
            doc_files = list(folder.glob("*.doc")) + list(folder.glob("*.docx"))
            doc_files = natsorted(doc_files, key=lambda p: p.name)
            
            if doc_files:
                volumes.append({
                    've_id': ve_id,
                    'folder_path': folder,
                    'doc_files': doc_files
                })
                logger.info(f"  Found volume {ve_id} with {len(doc_files)} doc file(s)")
            else:
                logger.warning(f"  Volume folder {folder.name} has no doc files")
    
    # Sort naturally by VE ID
    volumes = sorted(volumes, key=lambda v: v['ve_id'])
    logger.info(f"Found {len(volumes)} volumes with doc files")
    return volumes


def get_xml_files() -> list:
    """
    Get sorted list of intermediate XML files.
    
    Returns:
        List of Path objects for XML files, naturally sorted
    """
    xml_files = list(INPUT_DIR.glob(f"{W_ID}_*_parsed.xml"))
    return natsorted(xml_files, key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int = 0) -> str:
    """
    Generate UT ID from VE ID and file index.
    
    VE5CN658, index 0 -> UT5CN658_0001
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix -> "5CN658"
    return f"UT{ve_suffix}_{file_index + 1:04d}"


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


# =============================================================================
# XML Conversion Functions
# =============================================================================

def extract_content_from_xml(xml_path: Path) -> str:
    """
    Extract text content from intermediate XML file.
    
    The input XML has format:
    <text org-lb="false">
        <pb n="1-1-1a"/>
        <lb/>Text content...
        <pb n="1-1-1b"/>
        <lb/>More text...
    </text>
    
    Returns:
        String with text content and <lb/> tags preserved
    """
    try:
        # Read file content
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Parse XML
        root = ET.fromstring(content)
        
        # Build output by iterating through elements
        lines = []
        
        def process_element(elem, include_text=True):
            """Recursively process element and its children."""
            result = []
            
            # Handle element's text
            if include_text and elem.text:
                result.append(elem.text.strip() if elem.text.strip() else '')
            
            # Process children
            for child in elem:
                if child.tag == 'lb':
                    result.append('\n<lb/>')
                elif child.tag == 'pb':
                    # Include page break as a marker (optional - can be removed)
                    n = child.get('n', '')
                    result.append(f'\n<pb n="{n}"/>')
                else:
                    # Recursively process other elements
                    result.extend(process_element(child))
                
                # Handle tail text after element
                if child.tail:
                    result.append(child.tail)
            
            return result
        
        content_parts = process_element(root)
        body_content = ''.join(content_parts)
        
        # Clean up: normalize multiple newlines
        body_content = re.sub(r'\n\n+', '\n', body_content)
        body_content = body_content.strip()
        
        # Ensure content starts with newline if it starts with <lb/>
        if body_content.startswith('<lb/>'):
            body_content = '\n' + body_content
        
        return body_content
        
    except ET.ParseError as e:
        logger.error(f"XML parse error in {xml_path}: {e}")
        # Fallback: read raw and extract text between tags
        return extract_content_fallback(xml_path)
    except Exception as e:
        logger.error(f"Error processing {xml_path}: {e}")
        return ""


def extract_content_fallback(xml_path: Path) -> str:
    """
    Fallback extraction using regex when XML parsing fails.
    """
    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract content between <text...> and </text>
        match = re.search(r'<text[^>]*>(.*?)</text>', content, re.DOTALL)
        if not match:
            return ""
        
        body = match.group(1)
        
        # Keep lb and pb tags, remove other XML tags
        body = re.sub(r'<(?!lb|pb|/lb|/pb)[^>]+>', '', body)
        
        # Clean up whitespace
        body = re.sub(r'\n\n+', '\n', body)
        body = body.strip()
        
        return body
        
    except Exception as e:
        logger.error(f"Fallback extraction error for {xml_path}: {e}")
        return ""


def convert_xml_to_tei(xml_path: Path, ve_id: str, ut_id: str, 
                       doc_path: Path, src_path: str) -> str:
    """
    Convert intermediate XML file to TEI XML format.
    
    Args:
        xml_path: Path to intermediate XML file
        ve_id: Volume Entity ID (e.g., "VE5CN658")
        ut_id: Unit Text ID (e.g., "UT5CN658_0001")
        doc_path: Path to source doc file (for SHA256 calculation)
        src_path: Source path for XML header (e.g., "sources/VE5CN658/W3CN2226_1-335.doc")
        
    Returns:
        TEI XML string
    """
    logger.info(f"  Converting: {xml_path.name}")
    
    # Extract content from intermediate XML
    body_content = extract_content_from_xml(xml_path)
    
    if not body_content:
        logger.warning(f"  No content extracted from {xml_path.name}")
        body_content = ""
    
    # Calculate SHA256 of the source doc file
    sha256 = calculate_sha256(doc_path)
    
    # Get title from XML filename (without _parsed.xml)
    title = xml_path.stem  # W3CN2226_I3CN2228_parsed
    
    # Build TEI XML
    tei_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
<fileDesc>
<titleStmt>
<title>{escape_xml(title)}</title>
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


# =============================================================================
# Main Conversion Functions
# =============================================================================

def convert_volume(vol_idx: int, ve_id: str, doc_path: Path, 
                   xml_path: Path, output_dir: Path) -> bool:
    """
    Process one volume: copy sources and convert XML.
    
    Args:
        vol_idx: Volume index (0-based)
        ve_id: Volume Entity ID (e.g., "VE5CN658")
        doc_path: Path to source doc file
        xml_path: Path to intermediate XML file
        output_dir: Output directory
        
    Returns:
        True if successful, False otherwise
    """
    logger.info(f"Processing volume {vol_idx + 1}: {ve_id}")
    logger.info(f"  Source doc: {doc_path.name}")
    logger.info(f"  Input XML: {xml_path.name}")
    
    # Create output directories
    archive_dir = output_dir / "archive" / ve_id
    sources_dir = output_dir / "sources" / ve_id
    
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Copy doc to sources
        dest_doc = sources_dir / doc_path.name
        shutil.copy2(doc_path, dest_doc)
        logger.info(f"  Copied doc to: {dest_doc.relative_to(output_dir)}")
        
        # Copy original XML to sources
        dest_xml_source = sources_dir / xml_path.name
        shutil.copy2(xml_path, dest_xml_source)
        logger.info(f"  Copied XML to: {dest_xml_source.relative_to(output_dir)}")
        
        # Generate UT ID
        ut_id = get_ut_id(ve_id, 0)  # Index 0 since one XML per volume
        
        # Source path for TEI header (relative path to doc in output structure)
        src_path = f"sources/{ve_id}/{doc_path.name}"
        
        # Convert to TEI XML
        tei_xml = convert_xml_to_tei(xml_path, ve_id, ut_id, doc_path, src_path)
        
        # Write TEI XML to archive
        output_xml_path = archive_dir / f"{ut_id}.xml"
        with open(output_xml_path, 'w', encoding='utf-8') as f:
            f.write(tei_xml)
        logger.info(f"  Created TEI XML: {output_xml_path.relative_to(output_dir)}")
        
        return True
        
    except Exception as e:
        logger.error(f"  Error processing volume {ve_id}: {e}")
        import traceback
        traceback.print_exc()
        return False


def convert_all_volumes(output_dir: Path = None):
    """
    Convert all volumes from input folder to TEI XML.
    """
    if output_dir is None:
        output_dir = OUTPUT_DIR
    
    logger.info("=" * 60)
    logger.info(f"Converting all files for {IE_ID}")
    logger.info(f"Input: {INPUT_DIR}")
    logger.info(f"Output: {output_dir}")
    logger.info("=" * 60)
    
    # Get all inputs
    volumes = get_volume_data()
    xml_files = get_xml_files()
    
    logger.info(f"Found {len(volumes)} volumes")
    logger.info(f"Found {len(xml_files)} XML files")
    
    # Validate counts match
    if len(volumes) != len(xml_files):
        logger.warning(f"Count mismatch! Volumes: {len(volumes)}, XMLs: {len(xml_files)}")
        logger.warning("Will process minimum of available items")
    
    # Use minimum count
    count = min(len(volumes), len(xml_files))
    
    if count == 0:
        logger.error("No files to process")
        return
    
    # Print mapping for verification
    logger.info("\nMapping:")
    for i in range(count):
        vol = volumes[i]
        doc_name = vol['doc_files'][0].name if vol['doc_files'] else "N/A"
        logger.info(f"  {i+1}. {vol['ve_id']} <- {doc_name} <- {xml_files[i].name}")
    logger.info("")
    
    # Process each volume
    success = 0
    failed = 0
    
    for i in range(count):
        vol = volumes[i]
        ve_id = vol['ve_id']
        doc_path = vol['doc_files'][0]  # Take first doc file
        xml_path = xml_files[i]
        
        if convert_volume(i, ve_id, doc_path, xml_path, output_dir):
            success += 1
        else:
            failed += 1
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Conversion complete!")
    logger.info(f"  Total volumes: {count}")
    logger.info(f"  Success: {success}")
    logger.info(f"  Failed: {failed}")
    logger.info(f"  Output: {output_dir}")
    logger.info("=" * 60)


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    logger.info("=== IE3CN2226 XML Conversion ===")
    convert_all_volumes(OUTPUT_DIR)






