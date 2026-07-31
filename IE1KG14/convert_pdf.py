#!/usr/bin/env python3
"""
Convert PDF files from IE1KG14 (Terdzo Collection) to TEI XML format.

This script implements a 4-step pipeline:
1. PDF to Text - Extract text from PDFs using py-tiblegenc with font size tracking
2. Normalize - Simplify font size markup and apply Unicode normalization
3. Classify Fonts - Auto-classify font sizes as regular/small/large
4. Convert to TEI - Generate TEI XML with proper structure

Input structure:
    IE1KG14/
      sources/
        1-KA PDF/
          Terdzo-ka KARCHAK P.pdf
          Terdzo-ka P1.pdf
          ...
        2-KHA-PDF/
          ...
      toprocess/
        IE1KG14-VE1ER489/
        IE1KG14-VE1ER490/
        ...

Output structure:
    IE1KG14_OUTPUT/
      archive/
        VE1ER489/
          UT1ER489_0001.xml
          UT1ER489_0002.xml
          ...
        VE1ER490/
          ...
      sources/
        VE1ER489/
          Terdzo-ka KARCHAK P.pdf
          ...

Usage:
    python convert_pdf.py
    
    # Or with custom paths:
    python convert_pdf.py <input_folder> <output_folder>
"""

import sys
import os
import re
import hashlib
import shutil
import logging
from pathlib import Path
from collections import Counter
from natsort import natsorted

# Configure logging (will be set up in main with file handler)
logger = logging.getLogger(__name__)

def setup_logging(log_file: Path = None):
    """
    Set up logging to both console and file.
    
    Args:
        log_file: Path to log file. If None, only console logging is used.
    """
    # Clear any existing handlers
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(console_handler)
    
    # File handler (if log_file provided)
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
        logger.info(f"Logging to: {log_file}")

# Ensure stdout is unbuffered for immediate output
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# Add script directory to path for imports
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from normalization import normalize_unicode

# Import py-tiblegenc and pdfminer for page-by-page region extraction
from io import StringIO
try:
    from pytiblegenc import pdf_to_txt
    from pytiblegenc import DuffedTextConverter, get_glyph_db_path, build_font_hash_index_from_csv, identify_pdf_fonts_from_db
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
except ImportError:
    print("Error: pytiblegenc not installed. Run: pip install git+https://github.com/buda-base/py-tiblegenc.git")
    sys.exit(1)


# =============================================================================
# Configuration
# =============================================================================

IE_ID = "IE1KG14"
PAGE_BREAK_STR = "ZZZZ"
FONT_SIZE_FORMAT = "<fs:{}>"

# Default paths
BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1KG14")
TOPROCESS_DIR = BASE_DIR / "IE1KG14" / "toprocess"
SOURCES_DIR = BASE_DIR / "IE1KG14" / "sources"
OUTPUT_DIR = BASE_DIR / "IE1KG14_OUTPUT"


# =============================================================================
# Step 1: PDF to Text Extraction (with pecha page region masks)
# =============================================================================

# Region masks for pecha-format PDFs (2 pecha pages per PDF page)
# Format: [x, y, width, height] where values 0-1 are relative to page size
# PDF coordinates have y=0 at bottom, so:
#   - Top pecha page: y starts at ~0.5 (middle), height ~0.5 (upper half)
#   - Bottom pecha page: y starts at ~0 (bottom), height ~0.5 (lower half)
# Calibrated for IE1KG14 PDFs with 2 pecha pages per PDF page
REGION_TOP = [0.05, 0.52, 0.9, 0.46]     # Top half: x=5%, y=52%, w=90%, h=46%
REGION_BOTTOM = [0.05, 0.02, 0.9, 0.46]  # Bottom half: x=5%, y=2%, w=90%, h=46%

# Set to True to enable pecha page splitting (2 pecha pages per PDF page)
ENABLE_PECHA_SPLIT = True

# Minimum Tibetan characters to consider a region as having content
MIN_TIBETAN_CHARS = 50


def extract_pdf_to_text(pdf_path: Path) -> str:
    """
    Extract text from a PDF file using py-tiblegenc with pecha page support.
    
    Uses page-by-page processing with DuffedTextConverter to efficiently
    extract 2 pecha pages per PDF page. If a region is empty/minimal,
    it's automatically skipped (auto-detection for single pecha pages).
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Extracted text with font size markers and page breaks (one per pecha page)
    """
    logger.info(f"    Extracting: {pdf_path.name}")
    
    try:
        if ENABLE_PECHA_SPLIT:
            return extract_pdf_with_pecha_regions(pdf_path)
        else:
            # Single extraction per PDF page (no region mask)
            text = pdf_to_txt(
                str(pdf_path),
                page_break_str=f"\n{PAGE_BREAK_STR}\n",
                track_font_size=True,
                font_size_format=FONT_SIZE_FORMAT,
                normalize=False,
                simplify_font_sizes_option=False,
            )
            return text
            
    except Exception as e:
        logger.error(f"    ERROR extracting {pdf_path.name}: {e}")
        import traceback
        traceback.print_exc()
        return ""


def extract_pdf_with_pecha_regions(pdf_path: Path) -> str:
    """
    Extract text using pdf_to_txt with region masks for top and bottom pecha pages.
    
    Calls pdf_to_txt twice (once per region) then interleaves the results.
    Empty regions are automatically detected and filtered.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Extracted text with interleaved pecha pages
    """
    # Extract top half of each PDF page (upper pecha page)
    top_text = pdf_to_txt(
        str(pdf_path),
        region=REGION_TOP,
        page_break_str=f"\n{PAGE_BREAK_STR}\n",
        track_font_size=True,
        font_size_format=FONT_SIZE_FORMAT,
        normalize=False,
        simplify_font_sizes_option=False,
    )
    
    # Extract bottom half of each PDF page (lower pecha page)
    bottom_text = pdf_to_txt(
        str(pdf_path),
        region=REGION_BOTTOM,
        page_break_str=f"\n{PAGE_BREAK_STR}\n",
        track_font_size=True,
        font_size_format=FONT_SIZE_FORMAT,
        normalize=False,
        simplify_font_sizes_option=False,
    )
    
    # Interleave top and bottom halves with auto-detection
    text = interleave_pecha_pages(top_text, bottom_text)
    return text


def interleave_pecha_pages(top_text: str, bottom_text: str) -> str:
    """
    Interleave top and bottom pecha page extractions.
    
    Each PDF page has 2 pecha pages (top and bottom). This function
    interleaves them so output is: top1, bottom1, top2, bottom2, etc.
    Empty/minimal content pages are automatically filtered.
    
    Args:
        top_text: Text extracted from top half of all pages
        bottom_text: Text extracted from bottom half of all pages
        
    Returns:
        Interleaved text with one page break per pecha page
    """
    # Split by page breaks
    top_pages = top_text.split(PAGE_BREAK_STR)
    bottom_pages = bottom_text.split(PAGE_BREAK_STR)
    
    logger.debug(f"    Top pages: {len(top_pages)}, Bottom pages: {len(bottom_pages)}")
    
    # Interleave: for each PDF page, output top pecha page then bottom pecha page
    result_pages = []
    max_pages = max(len(top_pages), len(bottom_pages))
    
    for i in range(max_pages):
        # Add top page if it has content
        if i < len(top_pages):
            page_content = top_pages[i]
            tibetan_chars = len([c for c in page_content if ord(c) >= 0x0F00 and ord(c) <= 0x0FFF])
            if tibetan_chars >= MIN_TIBETAN_CHARS:
                result_pages.append(page_content)
        
        # Add bottom page if it has content
        if i < len(bottom_pages):
            page_content = bottom_pages[i]
            tibetan_chars = len([c for c in page_content if ord(c) >= 0x0F00 and ord(c) <= 0x0FFF])
            if tibetan_chars >= MIN_TIBETAN_CHARS:
                result_pages.append(page_content)
    
    # Join with page break markers
    return f"\n{PAGE_BREAK_STR}\n".join(result_pages)


# =============================================================================
# Step 1.5: Remove Standalone Yigmgo (pdfminer artifact fix)
# =============================================================================

def remove_standalone_yigmgo(text: str) -> str:
    """
    Remove lines that contain only ༄༅། ། (standalone yigmgo).
    
    These are artifacts from pdfminer's incorrect line ordering where the
    decorative header mark gets placed in a separate text box due to slight
    differences in vertical positioning.
    """
    lines = text.split('\n')
    result = []
    removed_count = 0
    
    # Regex pattern for standalone yigmgo lines (with optional font markers and spaces)
    # Matches: optional font markers, then ༄༅ followed by various shad combinations
    yigmgo_pattern = re.compile(r'^(?:<fs:\d+>)?\s*༄༅[། ༎]+\s*$')
    
    for line in lines:
        # Check if this line is just yigmgo
        if yigmgo_pattern.match(line):
            removed_count += 1
            continue
        
        result.append(line)
    
    if removed_count > 0:
        logger.info(f"    Removed {removed_count} standalone yigmgo lines")
    
    return '\n'.join(result)


# =============================================================================
# Step 1.6: Fix PDF Encoding Errors
# =============================================================================

def fix_pdf_encoding_errors(text: str) -> str:
    """
    Fix common PDF encoding errors where characters are incorrectly mapped.
    
    Some Tibetan PDFs have font encoding issues where certain Tibetan characters
    are mapped to Greek or other Unicode characters due to incorrect ToUnicode CMaps.
    
    Known issues in IE1KG14:
    - Greek mu (μ, U+03BC) should be Tibetan ga (ག, U+0F42)
      Example: μུ་རུ -> གུ་རུ (Guru)
    """
    # Greek mu (μ) -> Tibetan ga (ག)
    # μ (U+03BC) appears instead of ག (U+0F42)
    text = text.replace('μ', 'ག')
    
    # Add other common encoding errors here as discovered
    
    return text


# =============================================================================
# Step 2: Font Size Simplification and Normalization
# =============================================================================

def simplify_font_sizes(text: str) -> str:
    """
    Simplify font size markup by removing layout-related changes.
    
    Rules:
    1. Remove font size changes without tsheg (་) or shad (།) before next change
    2. Merge parentheses ༼ and ༽ with adjacent font sizes
    
    Adapted from DKCC/step1_fs.py
    """
    # Split by <fs:xx> tags
    pattern = r'<fs:(\d+)>'
    parts = re.split(pattern, text)
    
    # Build list of (font_size, content) tuples
    segments = []
    current_fs = None
    
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # This is content
            if part:
                segments.append((current_fs, part))
        else:
            # This is a font size number
            current_fs = part
    
    if not segments:
        return text
    
    # Process segments to handle parentheses
    processed_segments = []
    
    for i, (fs, content) in enumerate(segments):
        if not content:
            continue
            
        # Handle opening parenthesis ༼ - only if it's standalone
        if content == '༼' and i + 1 < len(segments):
            next_fs, next_content = segments[i + 1]
            processed_segments.append((next_fs, '༼' + next_content))
            segments[i + 1] = (None, '')
        # Handle closing parenthesis ༽
        elif content.startswith('༽') and processed_segments:
            prev_fs, prev_content = processed_segments[-1]
            processed_segments[-1] = (prev_fs, prev_content + content)
        elif content == '༽' and processed_segments:
            prev_fs, prev_content = processed_segments[-1]
            processed_segments[-1] = (prev_fs, prev_content + '༽')
        else:
            processed_segments.append((fs, content))
    
    segments = [(fs, c) for fs, c in processed_segments if c]
    
    # Merge segments without tsheg/shad with previous segments
    merged_segments = []
    
    for i, (fs, content) in enumerate(segments):
        has_separator = '་' in content or '།' in content or content.endswith('༽')
        
        if not has_separator and merged_segments:
            prev_fs, prev_content = merged_segments[-1]
            merged_segments[-1] = (prev_fs, prev_content + content)
        elif not has_separator and not merged_segments and not content.strip():
            merged_segments.append((None, content))
        else:
            merged_segments.append((fs, content))
    
    # Remove consecutive segments with same font size
    final_segments = []
    for fs, content in merged_segments:
        if final_segments and final_segments[-1][0] == fs:
            prev_fs, prev_content = final_segments[-1]
            final_segments[-1] = (fs, prev_content + content)
        else:
            final_segments.append((fs, content))
    
    # Rebuild text
    result = []
    for fs, content in final_segments:
        if fs is not None:
            result.append(f'<fs:{fs}>{content}')
        else:
            result.append(content)
    
    return ''.join(result)


def normalize_text(text: str) -> str:
    """
    Apply Unicode normalization to the text.
    """
    return normalize_unicode(text)


# =============================================================================
# Step 3: Font Size Classification
# =============================================================================

def classify_font_sizes(text: str) -> dict:
    """
    Classify font sizes in text into large, regular, and small categories.
    
    Uses a combination of character count and font size to determine classification.
    Body text is typically 20-26pt, yigchung (small text) is typically 14-18pt.
    
    Special handling: If the most common font size (by character count) is smaller
    than other significant sizes, it's likely yigchung, not body text - in this case
    we use the larger font size as "regular".
    
    Returns:
        dict: Mapping of font_size -> classification ('large', 'regular', 'small')
    """
    # Extract all font sizes and their character counts
    pattern = r'<fs:(\d+)>([^<]*)'
    matches = re.findall(pattern, text)
    
    if not matches:
        return {}
    
    # Count Tibetan characters for each font size
    size_counts = Counter()
    for fs, content in matches:
        char_count = len([c for c in content if ord(c) >= 0x0F00 and ord(c) <= 0x0FFF])
        if char_count > 0:
            size_counts[int(fs)] += char_count
    
    if not size_counts:
        return {}
    
    sizes = sorted(size_counts.keys())
    total_chars = sum(size_counts.values())
    size_percentages = {fs: (count / total_chars * 100) for fs, count in size_counts.items()}
    
    logger.debug(f"    Font sizes: {dict(size_counts)}")
    logger.debug(f"    Font percentages: {size_percentages}")
    
    classifications = {}
    
    if len(sizes) == 1:
        classifications[sizes[0]] = 'regular'
    
    elif len(sizes) == 2:
        fs1, fs2 = sizes  # fs1 < fs2 (sorted)
        pct1, pct2 = size_percentages[fs1], size_percentages[fs2]
        
        # If smaller font has more chars but both have significant share (>10%),
        # the larger font is likely body text and smaller is yigchung
        if pct1 > pct2 and pct2 > 10:
            # Smaller font (fs1) has more chars, but larger (fs2) has >10%
            # This suggests fs2 is body text and fs1 is yigchung
            classifications[fs2] = 'regular'
            classifications[fs1] = 'small'
            logger.info(f"    Inverted classification detected: {fs1}pt (yigchung) vs {fs2}pt (body)")
        elif pct1 > pct2:
            # Smaller font dominates and larger is insignificant - smaller is regular
            classifications[fs1] = 'regular'
            classifications[fs2] = 'large'
        else:
            # Larger font has more chars - it's regular
            classifications[fs2] = 'regular'
            classifications[fs1] = 'small'
    
    else:
        # Multiple sizes - find body text size
        # Priority: largest font size in body text range (20-26) with significant share
        body_text_range = [fs for fs in sizes if 20 <= fs <= 26 and size_percentages[fs] > 5]
        
        if body_text_range:
            # Use the largest in body text range as regular
            most_common_fs = max(body_text_range)
        else:
            # Fallback: find the largest font size with >10% share
            significant_sizes = [fs for fs in sizes if size_percentages[fs] > 10]
            if significant_sizes:
                most_common_fs = max(significant_sizes)
            else:
                # Last fallback: most common by character count
                most_common_fs = max(size_counts.items(), key=lambda x: x[1])[0]
        
        classifications[most_common_fs] = 'regular'
        
        for fs in sizes:
            if fs == most_common_fs:
                continue
            
            if fs > most_common_fs:
                classifications[fs] = 'large'
            else:
                classifications[fs] = 'small'
    
    logger.debug(f"    Classifications: {classifications}")
    return classifications


def apply_font_markup(text: str, classifications: dict) -> str:
    """
    Apply <large> and <small> markup based on font size classifications.
    
    Args:
        text: Input text with <fs:xx> tags
        classifications: dict of {font_size -> classification}
        
    Returns:
        Text with <large>/<small> tags and <fs:xx> removed
    """
    # Replace <fs:xx> with temporary markers
    def replace_fs(match):
        fs = int(match.group(1))
        classification = classifications.get(fs, 'regular')
        
        if classification == 'large':
            return '<LARGE_START>'
        elif classification == 'small':
            return '<SMALL_START>'
        else:
            return '<REGULAR_START>'
    
    text = re.sub(r'<fs:(\d+)>', replace_fs, text)
    
    # Convert markers to actual tags with proper closing
    result = []
    current_state = 'regular'
    
    parts = re.split(r'(<(?:LARGE|SMALL|REGULAR)_START>)', text)
    
    for part in parts:
        if part == '<LARGE_START>':
            if current_state == 'small':
                result.append('</small>')
            if current_state != 'large':
                result.append('<large>')
                current_state = 'large'
        
        elif part == '<SMALL_START>':
            if current_state == 'large':
                result.append('</large>')
            if current_state != 'small':
                result.append('<small>')
                current_state = 'small'
        
        elif part == '<REGULAR_START>':
            if current_state == 'large':
                result.append('</large>')
            elif current_state == 'small':
                result.append('</small>')
            current_state = 'regular'
        
        else:
            result.append(part)
    
    # Close any open tags at the end
    if current_state == 'large':
        result.append('</large>')
    elif current_state == 'small':
        result.append('</small>')
    
    text = ''.join(result)
    
    # Clean up whitespace around tags
    text = re.sub(r'(<(?:large|small)>)(\s)', r'\2\1', text)
    text = re.sub(r'(\s)(</(?:large|small)>)', r'\2\1', text)
    
    # Remove empty tags
    text = re.sub(r'<large></large>', '', text)
    text = re.sub(r'<small></small>', '', text)
    
    return text


# =============================================================================
# Step 4: TEI XML Generation
# =============================================================================

def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def convert_markup_to_tei(text: str) -> str:
    """
    Convert markup to TEI format.
    
    - <large> -> <hi rend="head">
    - <small> -> <hi rend="small">
    - Line breaks -> <lb/>
    - ZZZZ -> <pb/>
    """
    # First, escape XML special characters in text content (not tags)
    # We need to preserve our markup tags, so escape before they're converted
    # but after font markup has been applied
    def escape_content(text_part):
        """Escape XML special characters but preserve our temporary markup."""
        # Temporarily replace our markup
        text_part = text_part.replace('<large>', '\x00LARGE\x00')
        text_part = text_part.replace('</large>', '\x00/LARGE\x00')
        text_part = text_part.replace('<small>', '\x00SMALL\x00')
        text_part = text_part.replace('</small>', '\x00/SMALL\x00')
        
        # Escape XML special characters
        text_part = text_part.replace('&', '&amp;')
        text_part = text_part.replace('<', '&lt;')
        text_part = text_part.replace('>', '&gt;')
        
        # Restore our markup
        text_part = text_part.replace('\x00LARGE\x00', '<large>')
        text_part = text_part.replace('\x00/LARGE\x00', '</large>')
        text_part = text_part.replace('\x00SMALL\x00', '<small>')
        text_part = text_part.replace('\x00/SMALL\x00', '</small>')
        
        return text_part
    
    text = escape_content(text)
    
    # Remove the first page break if present (conversion artifact)
    if text.startswith(f'\n{PAGE_BREAK_STR}\n'):
        text = text[len(PAGE_BREAK_STR) + 2:]
    elif text.startswith(f'{PAGE_BREAK_STR}\n'):
        text = text[len(PAGE_BREAK_STR) + 1:]
    
    # Replace page breaks with placeholder
    text = re.sub(PAGE_BREAK_STR, '<<<PB>>>', text)
    
    # Add first page break
    text = '<pb/>\n' + text
    
    # Replace line breaks with <lb/>
    lines = text.split('\n')
    result = []
    
    for i, line in enumerate(lines):
        # Strip trailing whitespace from each line
        line = line.rstrip()
        if i > 0:
            result.append('\n<lb/>')
        result.append(line)
    
    text = ''.join(result)
    
    # Replace page break placeholders
    text = re.sub(r'<<<PB>>>', '<pb/>', text)
    
    # Remove <lb/> before <pb/>
    text = re.sub(r'\n<lb/>\s*(?=<pb)', r'\n', text)
    text = re.sub(r'<lb/>\s*\n\s*(?=<pb)', r'', text)
    
    # Remove trailing <lb/>
    text = re.sub(r'\n<lb/>\s*$', '', text)
    
    # Replace markup tags
    text = text.replace('<large>', '<hi rend="head">')
    text = text.replace('<small>', '<hi rend="small">')
    text = text.replace('</large>', '</hi>')
    text = text.replace('</small>', '</hi>')
    
    # Clean up
    text = re.sub(r'(<lb/>[\s\n]*)+</hi>', r'</hi>', text)
    text = re.sub(r'<lb/>[\s\n]*<pb', r'<pb', text)
    # Move </hi> from after <pb/> to end of previous line (pb should be alone on its line)
    text = re.sub(r'(\n)<pb/>[\s]*</hi>', r'</hi>\1<pb/>', text)
    text = re.sub(r'\n(</hi>)', r'\1\n', text)
    text = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r'\n<lb/>\1', text)
    text = re.sub(r'<lb/> +', r'<lb/>', text)
    text = re.sub(r'\n\n+', r'\n', text)
    text = re.sub(r'  +', r' ', text)
    
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


def generate_tei_header(pdf_file: Path, ve_id: str, ut_id: str, src_path: str, title: str = "XXX") -> str:
    """Generate TEI header for a file."""
    sha256 = calculate_sha256(pdf_file)
    
    header = f"""<teiHeader>
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
</teiHeader>"""
    
    return header


def generate_tei_document(body_content: str, header: str) -> str:
    """Generate complete TEI document."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
{header}
<text>
<body xml:lang="bo">
<p xml:space="preserve">
{body_content}</p>
</body>
</text>
</TEI>
"""


# =============================================================================
# Helper Functions for Folder Structure
# =============================================================================

def get_source_subfolders(sources_path: Path) -> list:
    """
    Get source subfolders sorted by numeric prefix.
    
    Folder names are like: "1-KA PDF", "2-KHA-PDF", "10-THA PDF"
    Sort by the leading number.
    
    Returns:
        List of (index, folder_path) tuples sorted by index
    """
    subfolders = []
    
    for folder in sources_path.iterdir():
        if not folder.is_dir():
            continue
        
        # Extract numeric prefix (e.g., "1" from "1-KA PDF")
        match = re.match(r'^(\d+)', folder.name)
        if match:
            index = int(match.group(1))
            subfolders.append((index, folder))
    
    # Sort by numeric index
    return sorted(subfolders, key=lambda x: x[0])


def get_ve_ids_from_toprocess(toprocess_path: Path) -> list:
    """
    Get VE IDs from the toprocess folder structure.
    
    Folder names are like: "IE1KG14-VE1ER489", "IE1KG14-VE1KG14_001"
    
    Volume ordering for IE1KG14:
    - VE1KG14_001 to VE1KG14_054 are volumes 1-54
    - VE1ER489 to VE1ER505 are volumes 55-71
    
    Returns:
        List of VE IDs sorted in correct volume order
    """
    ve_kg14 = []  # VE1KG14_* volumes (1-54)
    ve_er = []    # VE1ER* volumes (55-71)
    
    for folder in toprocess_path.iterdir():
        if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
            ve_id = folder.name.replace(f'{IE_ID}-', '')  # "VE1ER489" or "VE1KG14_001"
            
            if ve_id.startswith('VE1KG14_'):
                ve_kg14.append(ve_id)
            elif ve_id.startswith('VE1ER'):
                ve_er.append(ve_id)
            else:
                logger.warning(f"Unknown VE ID format: {ve_id}")
    
    # Sort each group naturally, then combine (KG14 first, then ER)
    return natsorted(ve_kg14) + natsorted(ve_er)


def get_pdf_files_in_folder(folder_path: Path) -> list:
    """
    Get PDF files in a folder, naturally sorted, excluding Thumbs.db.
    
    Returns:
        List of Path objects for PDF files
    """
    pdf_files = [f for f in folder_path.glob('*.pdf') if f.name.lower() != 'thumbs.db']
    return natsorted(pdf_files, key=lambda p: p.name)


def get_ut_id(ve_id: str, file_index: int) -> str:
    """
    Generate UT ID from VE ID and file index.
    
    VE1ER489, index 0 -> UT1ER489_0001
    VE1KG14_001, index 0 -> UT1KG14_001_0001
    """
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{file_index + 1:04d}"


def build_volume_mapping(sources_path: Path, toprocess_path: Path) -> list:
    """
    Build mapping between source subfolders and VE IDs.
    
    - Natural sort source subfolders by prefix number (1, 2, ..., 71)
    - Natural sort toprocess folders by VE ID
    - Match by index position
    
    Returns:
        List of (source_folder, ve_id, [pdf_files])
    """
    source_subfolders = get_source_subfolders(sources_path)
    ve_ids = get_ve_ids_from_toprocess(toprocess_path)
    
    logger.info(f"Found {len(source_subfolders)} source subfolders")
    logger.info(f"Found {len(ve_ids)} VE IDs in toprocess")
    
    if len(source_subfolders) != len(ve_ids):
        logger.warning(f"Mismatch: {len(source_subfolders)} source folders vs {len(ve_ids)} VE IDs")
    
    mapping = []
    for (idx, source_folder), ve_id in zip(source_subfolders, ve_ids):
        pdf_files = get_pdf_files_in_folder(source_folder)
        mapping.append((source_folder, ve_id, pdf_files))
        logger.debug(f"  {idx}: {source_folder.name} -> {ve_id} ({len(pdf_files)} PDFs)")
    
    return mapping


# =============================================================================
# Main Conversion Functions
# =============================================================================

def convert_pdf_file(pdf_path: Path, ve_id: str, ut_id: str, src_path: str) -> str:
    """
    Convert a single PDF file to TEI XML.
    
    Args:
        pdf_path: Path to PDF file
        ve_id: Volume Entity ID (e.g., "VE1ER489")
        ut_id: Unit Text ID (e.g., "UT1ER489_0001")
        src_path: Source path for XML header
        
    Returns:
        TEI XML string
    """
    # Step 1: Extract text from PDF
    raw_text = extract_pdf_to_text(pdf_path)
    if not raw_text:
        raise ValueError(f"No text extracted from {pdf_path.name}")
    
    # Step 1.5: Remove standalone yigmgo lines (pdfminer artifact)
    raw_text = remove_standalone_yigmgo(raw_text)
    
    # Step 1.6: Fix PDF encoding errors (e.g., Greek μ -> Tibetan ག)
    raw_text = fix_pdf_encoding_errors(raw_text)
    
    # Step 2: Simplify font sizes and normalize
    simplified_text = simplify_font_sizes(raw_text)
    normalized_text = normalize_text(simplified_text)
    
    # Step 3: Classify font sizes
    classifications = classify_font_sizes(normalized_text)
    if classifications:
        logger.debug(f"    Classifications: {classifications}")
    
    # Apply font markup
    marked_text = apply_font_markup(normalized_text, classifications)
    
    # Step 4: Convert to TEI
    tei_body = convert_markup_to_tei(marked_text)
    
    # Generate TEI document
    header = generate_tei_header(pdf_path, ve_id, ut_id, src_path, title=pdf_path.stem)
    tei_document = generate_tei_document(tei_body, header)
    
    return tei_document


def convert_volume(source_folder: Path, ve_id: str, pdf_files: list, output_dir: Path, failed_files: list = None):
    """
    Convert all PDF files in a volume to TEI XML.
    
    Args:
        source_folder: Path to source subfolder containing PDFs
        ve_id: Volume Entity ID (e.g., "VE1ER489")
        pdf_files: List of PDF file paths
        output_dir: Output directory root
        failed_files: List to append failed file info (modified in place)
        
    Returns:
        Tuple of (success_count, failed_count)
    """
    logger.info(f"  Processing {len(pdf_files)} PDF files")
    
    if failed_files is None:
        failed_files = []
    
    # Create output directories
    archive_dir = output_dir / "archive" / ve_id
    sources_dir = output_dir / "sources" / ve_id
    
    archive_dir.mkdir(parents=True, exist_ok=True)
    sources_dir.mkdir(parents=True, exist_ok=True)
    
    success = 0
    failed = 0
    
    for idx, pdf_path in enumerate(pdf_files):
        ut_id = get_ut_id(ve_id, idx)
        src_path = f"sources/{ve_id}/{pdf_path.name}"
        
        logger.info(f"    [{idx + 1}/{len(pdf_files)}] {pdf_path.name} -> {ut_id}")
        
        # Always copy PDF to sources (even if conversion fails)
        dest_pdf = sources_dir / pdf_path.name
        try:
            shutil.copy2(pdf_path, dest_pdf)
        except Exception as copy_err:
            logger.error(f"    Failed to copy PDF: {copy_err}")
        
        try:
            # Convert to TEI XML
            tei_xml = convert_pdf_file(pdf_path, ve_id, ut_id, src_path)
            
            # Write XML
            xml_path = archive_dir / f"{ut_id}.xml"
            with open(xml_path, 'w', encoding='utf-8') as f:
                f.write(tei_xml)
            
            success += 1
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"    Error converting {pdf_path.name}: {error_msg}")
            import traceback
            traceback.print_exc()
            
            # Track failed file info
            failed_files.append({
                'volume': ve_id,
                'source_folder': source_folder.name,
                'pdf_name': pdf_path.name,
                'pdf_path': str(pdf_path),
                'ut_id': ut_id,
                'error': error_msg
            })
            failed += 1
    
    return success, failed


def write_failed_files_report(failed_files: list, output_path: Path):
    """
    Write a report of failed files to a text file.
    
    Args:
        failed_files: List of dicts with failed file info
        output_path: Output directory for the report
    """
    if not failed_files:
        return
    
    report_path = output_path / "failed_conversions.txt"
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write(f"FAILED CONVERSIONS REPORT\n")
        f.write(f"Total failed: {len(failed_files)}\n")
        f.write("=" * 80 + "\n\n")
        
        for i, info in enumerate(failed_files, 1):
            f.write(f"[{i}] {info['pdf_name']}\n")
            f.write(f"    Volume: {info['volume']} ({info['source_folder']})\n")
            f.write(f"    Expected UT ID: {info['ut_id']}\n")
            f.write(f"    Source path: {info['pdf_path']}\n")
            f.write(f"    Error: {info['error']}\n")
            f.write("\n")
    
    logger.info(f"Failed files report written to: {report_path}")


def convert_all(sources_path: Path = None, toprocess_path: Path = None, output_path: Path = None):
    """
    Convert all PDF files from IE1KG14 to TEI XML.
    
    Args:
        sources_path: Path to sources folder (default: SOURCES_DIR)
        toprocess_path: Path to toprocess folder (default: TOPROCESS_DIR)
        output_path: Path to output folder (default: OUTPUT_DIR)
    """
    from datetime import datetime
    
    if sources_path is None:
        sources_path = SOURCES_DIR
    if toprocess_path is None:
        toprocess_path = TOPROCESS_DIR
    if output_path is None:
        output_path = OUTPUT_DIR
    
    # Create output directory first (needed for log file)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Set up logging to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = output_path / f"conversion_log_{timestamp}.txt"
    setup_logging(log_file)
    
    logger.info("=" * 70)
    logger.info(f"Converting {IE_ID}")
    logger.info(f"Sources:   {sources_path}")
    logger.info(f"Toprocess: {toprocess_path}")
    logger.info(f"Output:    {output_path}")
    logger.info("=" * 70)
    
    # Validate input paths
    if not sources_path.exists():
        logger.error(f"Sources folder not found: {sources_path}")
        return
    if not toprocess_path.exists():
        logger.error(f"Toprocess folder not found: {toprocess_path}")
        return
    
    # Build volume mapping
    mapping = build_volume_mapping(sources_path, toprocess_path)
    
    if not mapping:
        logger.error("No volumes to process")
        return
    
    # Track failed files
    failed_files = []
    
    # Process each volume
    total_success = 0
    total_failed = 0
    total_pdfs = sum(len(pdfs) for _, _, pdfs in mapping)
    
    logger.info(f"\nTotal: {len(mapping)} volumes, {total_pdfs} PDF files")
    
    for vol_idx, (source_folder, ve_id, pdf_files) in enumerate(mapping):
        logger.info(f"\n[Volume {vol_idx + 1}/{len(mapping)}] {source_folder.name} -> {ve_id}")
        
        if not pdf_files:
            logger.warning(f"  No PDF files found, skipping")
            continue
        
        success, failed = convert_volume(source_folder, ve_id, pdf_files, output_path, failed_files)
        total_success += success
        total_failed += failed
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("CONVERSION COMPLETE!")
    logger.info(f"  Total volumes: {len(mapping)}")
    logger.info(f"  Total PDFs processed: {total_success + total_failed}")
    logger.info(f"  Success: {total_success}")
    logger.info(f"  Failed: {total_failed}")
    logger.info(f"  Output: {output_path}")
    logger.info(f"  Log file: {log_file}")
    logger.info("=" * 70)
    
    # Write failed files report
    if failed_files:
        logger.info("\n" + "-" * 70)
        logger.info("FAILED FILES SUMMARY:")
        logger.info("-" * 70)
        for info in failed_files:
            logger.info(f"  {info['volume']}/{info['pdf_name']}: {info['error']}")
        
        write_failed_files_report(failed_files, output_path)
    else:
        logger.info("\nNo failed conversions!")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    # Initialize console logging first
    setup_logging()
    
    if len(sys.argv) == 3:
        # Custom paths provided
        input_folder = Path(sys.argv[1])
        output_folder = Path(sys.argv[2])
        
        sources_path = input_folder / "sources"
        toprocess_path = input_folder / "toprocess"
        
        convert_all(sources_path, toprocess_path, output_folder)
    elif len(sys.argv) == 1:
        # Use default paths
        convert_all()
    else:
        print(f"Usage: python {sys.argv[0]} [<input_folder> <output_folder>]")
        print(f"\nDefault paths:")
        print(f"  Sources:   {SOURCES_DIR}")
        print(f"  Toprocess: {TOPROCESS_DIR}")
        print(f"  Output:    {OUTPUT_DIR}")
        sys.exit(1)


if __name__ == "__main__":
    main()

