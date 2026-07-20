"""
TEI XML Generator Module

Builds TEI body markup from converted streams, post-processes TEI fragments,
and emits full TEI P5 documents with BDRC-oriented header metadata.
"""

import re
import hashlib
from pathlib import Path
from config import IE_ID


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


