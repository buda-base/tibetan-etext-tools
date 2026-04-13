"""
TEI XML Generator Module

Builds TEI body markup from converted streams, post-processes TEI fragments,
and emits full TEI P5 documents with BDRC-oriented header metadata.
"""

import re
import hashlib
from pathlib import Path
from collections import Counter
import logging

from config import IE_ID

logger = logging.getLogger(__name__)


def classify_font_sizes(converted_streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    """
    size_counts = Counter()
    
    for item in converted_streams:
        text = item.get("text", "")
        font_size = item.get("font_size", 12)
        tibetan_chars = len([c for c in text if 0x0F00 <= ord(c) <= 0x0FFF])
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    
    if not size_counts:
        return {}
    
    most_common = max(size_counts.items(), key=lambda x: x[1])[0]
    
    classifications = {}
    for fs in size_counts.keys():
        if fs == most_common:
            classifications[fs] = 'regular'
        elif fs > most_common:
            classifications[fs] = 'large'
        else:
            classifications[fs] = 'small'
    
    return classifications


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


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


def build_tei_body(converted_streams: list, enable_font_classification: bool = True) -> str:
    """Build the body content for TEI XML from converted streams."""
    tei_lines = []
    current_markup = None
    
    # Skip leading breaks (newlines and page_breaks) at the start
    # These can occur from RTF structure between header/footer definitions
    start_idx = 0
    for i, item in enumerate(converted_streams):
        if item.get("type") == "page_break":
            continue  # Skip leading page_breaks
        if item.get("text", "").strip() == "":
            continue  # Skip empty/whitespace-only items
        start_idx = i
        break
    
    # Always add initial page break at start
    tei_lines.append('<pb/>\n')
    
    # Process from start_idx
    if start_idx > 0:
        converted_streams = converted_streams[start_idx:]
    
    if enable_font_classification:
        classifications = classify_font_sizes(converted_streams)
        if classifications:
            logger.info(f"  Font classifications: {classifications}")
    else:
        classifications = {}
    
    for item in converted_streams:
        # Handle page break markers (from footer detection)
        if item.get("type") == "page_break":
            # Close any open markup tags before page break
            if current_markup == 'small':
                tei_lines.append('</hi>')
            elif current_markup == 'large':
                tei_lines.append('</hi>')
            current_markup = None
            tei_lines.append('\n<pb/>\n')
            continue
        
        # Skip items without text
        if "text" not in item:
            continue
        
        text = item["text"]
        font_size = item.get("font_size", 12)
        escaped_text = escape_xml(text)
        
        if enable_font_classification and classifications:
            classification = classifications.get(font_size, 'regular')
            
            if classification != current_markup:
                if current_markup == 'small':
                    tei_lines.append('</hi>')
                elif current_markup == 'large':
                    tei_lines.append('</hi>')
                
                if classification == 'small':
                    tei_lines.append('<hi rend="small">')
                elif classification == 'large':
                    tei_lines.append('<hi rend="head">')
                
                current_markup = classification if classification != 'regular' else None
        
        tei_lines.append(escaped_text)
    
    if current_markup == 'small':
        tei_lines.append('</hi>')
    elif current_markup == 'large':
        tei_lines.append('</hi>')
    
    body_content = ''.join(tei_lines)
    
    if enable_font_classification:
        body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    return body_content


def post_process_body(body_content: str) -> str:
    """Post-process TEI body content with line breaks and tag fixes."""
    body_content = body_content.strip()
    body_content = re.sub(r"<pb/>\s*</hi>", r"</hi>\n<pb/>", body_content)

    body_content = body_content.replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '\n<lb/>', body_content)
    body_content = re.sub(r'<lb/>\s*<pb/>', '<pb/>', body_content)
    body_content = re.sub(r'(<pb/>\s*){2,}', '<pb/>\n', body_content)
    body_content = body_content.strip()
    # Blanket \n -> \n<lb/> can leave </hi> on its own line as <lb/></hi>; fold onto prior <lb/> line.
    body_content = re.sub(r'(<lb/>[^\n]+)\n+<lb/></hi>', r'\1</hi>', body_content)
    # Remove spurious <lb/> between </hi> and <pb/> (inline hi must end before page break).
    body_content = re.sub(r"(</hi>)\s*\n\s*<lb/>\s*\n*\s*(<pb/>)", r"\1\n\2", body_content)

    body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', '', body_content)
    body_content = re.sub(r'(<hi rend="[^"]+">)\s*\n<lb/>', r'\n<lb/>\1', body_content)
    body_content = re.sub(r'\n<lb/></hi>', r'</hi>\n<lb/>', body_content)
    # Newline injection can stack <lb/> right after <pb/>; keep a single source line break.
    body_content = re.sub(r"(<pb/>)\s*\n\s*<lb/>\s*\n\s*<lb/>", r"\1\n<lb/>", body_content)
    body_content = re.sub(r'\n\n+', '\n', body_content)
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', '', body_content)
    body_content = body_content.strip()
    
    
    # Fix numbered list markers where ) was incorrectly converted to འ
    # Pattern: (1འ → (1), (2འ → (2), etc.
    # This happens when numbered lists like (1), (2) were typed in Dedris font
    # and the ) character got converted to Tibetan a-chung འ
    body_content = re.sub(r'\((\d+)འ', r'(\1)', body_content)
    
    return body_content


def generate_tei_xml(
    body_content: str,
    title: str,
    src_path: str,
    sha256: str,
    ve_id: str,
    ut_id: str,
) -> str:
    """Generate complete TEI XML document."""
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
<p>
{body_content}
</p>
</body>
</text>
</TEI>
'''
    
    return tei_xml


