"""
TEI XML Generator Module

Builds TEI P5 documents with BDRC-oriented header metadata and post-processes
TEI body fragments produced by convert_pdf_to_xml.py.
"""

import re
import hashlib
import logging
from pathlib import Path

from config import IE_ID

logger = logging.getLogger(__name__)

# Tibetan cluster: base letter followed by combining/subjoined tail marks
_TIB_BASE = r"[\u0F40-\u0F6C]"
_TIB_CLUSTER_TAIL = r"[\u0F71-\u0F84\u0F90-\u0FBC]"
_HI_SPLIT_FIX_RE = re.compile(
    rf"({_TIB_BASE})</hi>((?:{_TIB_CLUSTER_TAIL})+)(?!{_TIB_CLUSTER_TAIL})"
)


def repair_hi_tibetan_cluster_splits(body_content: str) -> str:
    """
    Move ``</hi>`` inserted between a Tibetan base letter and its combining tail
    (font-size boundary artefact from PyMuPDF).

    E.g. ``<hi rend="small">…ཨ</hi>ོཾ`` → ``…ཨོཾ</hi>``
    """
    prev = None
    while prev != body_content:
        prev = body_content
        body_content = _HI_SPLIT_FIX_RE.sub(r"\1\2</hi>", body_content)
    return body_content


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA-256 hash of a file."""
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def post_process_body(body_content: str) -> str:
    """Post-process TEI body content: inject ``<lb/>`` line breaks and fix tag placement.

    Handles ``<hi rend="…">`` spans for font-size markup and
    ``<note n="N" place="foot">…</note>`` footnote elements.
    """
    # Match both bare <pb/> and attributed <pb n="…"/> in all patterns.
    _PB = r"<pb(?:\s[^/]*)*/>"

    body_content = body_content.strip()
    # Inline <hi> must close before any page break.
    body_content = re.sub(r"(" + _PB + r")\s*</hi>", r"</hi>\n\1", body_content)

    body_content = body_content.replace("\n", "\n<lb/>")
    body_content = re.sub(r" *<lb/> *", "\n<lb/>", body_content)
    body_content = re.sub(r"<lb/>\s*(" + _PB + r")", r"\1", body_content)
    body_content = re.sub(r"(" + _PB + r"\s*){2,}", "<pb/>\n", body_content)
    body_content = body_content.strip()

    # Fold stray </hi> that ends up on its own <lb/> line onto the prior line.
    body_content = re.sub(r"(<lb/>[^\n]+)\n+<lb/></hi>", r"\1</hi>", body_content)
    # Remove spurious <lb/> between </hi> and <pb/>.
    body_content = re.sub(r"(</hi>)\s*\n\s*<lb/>\s*\n*\s*(" + _PB + r")", r"\1\n\2", body_content)

    body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', "", body_content)
    body_content = re.sub(r'(<hi rend="[^"]+">)\s*\n<lb/>', r"\n<lb/>\1", body_content)
    body_content = re.sub(r"\n<lb/></hi>", r"</hi>\n<lb/>", body_content)
    body_content = re.sub(r"(" + _PB + r")\s*\n\s*<lb/>\s*\n\s*<lb/>", r"\1\n<lb/>", body_content)
    body_content = re.sub(r"\n\n+", "\n", body_content)
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', "", body_content)
    body_content = body_content.strip()

    # Fix numbered list markers where ) was incorrectly converted to འ
    body_content = re.sub(r"\((\d+)འ", r"(\1)", body_content)

    # Font-size markup must not split Tibetan grapheme clusters.
    body_content = repair_hi_tibetan_cluster_splits(body_content)

    return body_content


def generate_tei_xml(
    body_content: str,
    title: str,
    src_path: str,
    sha256: str,
    ve_id: str,
    ut_id: str,
) -> str:
    """Generate a complete TEI P5 XML document."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
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
<p xml:space="preserve">
{body_content}
</p>
</body>
</text>
</TEI>
'''