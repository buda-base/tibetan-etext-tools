#!/usr/bin/env python3
"""
Convert PDF (BOOK FORMAT) files from IE2KG229024 to TEI XML format.
note : conversion files are stored in toprocess
This script implements a 4-step pipeline:
1. PDF to Text - Extract text from PDFs using py-tiblegenc with font size tracking
2. Normalize - Simplify font size markup and apply Unicode normalization
3. Classify Fonts - Auto-classify font sizes as regular/small/large
4. Convert to TEI - Generate TEI XML with proper structure

Usage:
    python pdf_to_xml.py <input_folder> <output_folder>
    
Example:
    python pdf_to_xml.py /path/to/IE2KG229024_INPUT /path/to/IE2KG229024_OUTPUT
"""

import sys
import os
import re
import hashlib
import shutil
from pathlib import Path
from collections import Counter
from natsort import natsorted
import fitz  # PyMuPDF


# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from normalization import normalize_unicode

# =============================================================================
# Configuration
# =============================================================================

IE_ID = "IE2KG229024"
PAGE_BREAK_STR = "ZZZZ"
FONT_SIZE_FORMAT = "<fs:{}>"


# =============================================================================
# Step 1: Text Extraction (PyMuPDF Coordinate Sorting)
# =============================================================================

def extract_pdf_to_text(pdf_path: Path) -> str:
    """Extract text from PDF using X/Y coordinates to guarantee proper reading order."""
    print(f"  Extracting with PyMuPDF: {pdf_path.name}")
    try:
        doc = fitz.open(str(pdf_path))
        full_text = []

        for page in doc:
            page_dict = page.get_text("dict")
            blocks = [b for b in page_dict["blocks"] if b["type"] == 0]
            # Sort primarily by Y (grouped by 15px bands) and secondarily by X
            blocks.sort(key=lambda b: (round(b["bbox"][1] / 15), b["bbox"][0]))

            page_text = []
            for block in blocks:
                for line in block["lines"]:
                    line_text = ""
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            font_size = round(span["size"])
                            line_text += f"<fs:{font_size}>{text} "
                    if line_text.strip():
                        page_text.append(line_text.strip())
            
            full_text.append("\n".join(page_text))
        doc.close()
        return f"\n{PAGE_BREAK_STR}\n".join(full_text)
    except Exception as e:
        print(f"    ERROR extracting {pdf_path.name}: {e}")
        return ""


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
        print(f"    Removed {removed_count} standalone yigmgo lines")
    
    return '\n'.join(result)

def remove_artifact_line(text: str) -> str:
    """
    Enhanced removal of the known print/glyph artifact line.
    Handles potential HTML entities, varying whitespace, and font tags.
    """
    # 1. Handle HTML entities if they exist (e.g., &lt; for <)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    # 2. Define a fuzzy regex pattern
    # This looks for the start of the sequence and allows for flexible spacing/font tags
    # We escape the regex but allow \s* between every character
    #fuzzy_pattern = r"(?:<fs:\d+>)?\s*" + r"\s*".join([re.escape(c) for c in "K$-.0J-:.A-(R?-.A/-.-:2=-o-=?,�5S%-2+<-3A-(R$-0-.$R%?-:)$?-8, "])
    
    # 3. Apply global removal
    #text = re.sub(fuzzy_pattern, "", text, flags=re.IGNORECASE)

    # 4. Clean up resulting empty lines or lines that only contain font tags now
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        # Check if line has actual Tibetan or English content after removing font tags
        content_check = re.sub(r'<fs:\d+>', '', line).strip()
        if content_check:
            cleaned.append(line)
            
    return '\n'.join(cleaned)

def remove_indesign_artifacts(text: str) -> str:
    """Globally delete ANY line containing Adobe InDesign print artifacts."""
    lines = text.split('\n')
    return '\n'.join([l for l in lines if '.indd' not in l.lower()])

def remove_headers_footers(text: str) -> str:
    """Dynamically detect and remove repeating headers, footers, and page numbers."""
    pages = text.split(f"\n{PAGE_BREAK_STR}\n")
    first_lines, last_lines = [], []
    
    for page in pages:
        lines = [l for l in page.split('\n') if l.strip()]
        if lines:
            first_lines.append(re.sub(r'<fs:\d+>', '', lines[0]).strip())
            last_lines.append(re.sub(r'<fs:\d+>', '', lines[-1]).strip())
            
    page_threshold = max(3, len(pages) * 0.2)
    repeating_headers = {l for l, c in Counter(first_lines).items() if c > page_threshold and len(l) > 2}
    repeating_footers = {l for l, c in Counter(last_lines).items() if c > page_threshold and len(l) > 2}

    cleaned_pages = []
    for page in pages:
        lines = page.split('\n')
        while lines and not lines[0].strip(): lines.pop(0)
        while lines and not lines[-1].strip(): lines.pop()
            
        if not lines:
            cleaned_pages.append("")
            continue

        def is_header_or_footer(line, repeating_set):
            clean_line = re.sub(r'<fs:\d+>', '', line).strip()
            if re.match(r'^[\d\s\u0F20-\u0F29]+$', clean_line): return True
            if clean_line in repeating_set: return True
            if re.search(r'\d{1,2}/\d{1,2}/\d{4}', clean_line): return True
            return False

        if lines and is_header_or_footer(lines[0], repeating_headers): lines.pop(0)
        if lines and is_header_or_footer(lines[-1], repeating_footers): lines.pop()
            
        cleaned_pages.append('\n'.join(lines))
    return f"\n{PAGE_BREAK_STR}\n".join(cleaned_pages)

# =============================================================================
# Step 2: Font Size Simplification and Normalization
# =============================================================================

def simplify_font_sizes(text: str) -> str:
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
    Classify font sizes into large, regular, and small categories based purely 
    on total character volume, removing hardcoded size restrictions.
    """
    pattern = r'<fs:(\d+)>([^<]*)'
    matches = re.findall(pattern, text)
    
    if not matches:
        return {}
    
    # Count Tibetan, Latin (English), and CJK (Chinese) characters for each font size
    size_counts = Counter()
    for fs, content in matches:
        char_count = len([c for c in content if 
                         (0x0F00 <= ord(c) <= 0x0FFF) or   # Tibetan
                         (0x0041 <= ord(c) <= 0x007A) or   # Latin
                         (0x4E00 <= ord(c) <= 0x9FFF)])    # Chinese
        if char_count > 0:
            size_counts[int(fs)] += char_count
    
    if not size_counts:
        return {}
    
    sizes = sorted(size_counts.keys())
    
    # The font size with the absolute highest character count is ALWAYS 'regular' body text
    most_common_fs = max(size_counts.items(), key=lambda x: x[1])[0]
    
    classifications = {most_common_fs: 'regular'}
    
    # Compare all other sizes against the established body text baseline
    for fs in sizes:
        if fs == most_common_fs:
            continue
        
        if fs > most_common_fs:
            classifications[fs] = 'large'
        else:
            classifications[fs] = 'small'
            
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
    text = re.sub(r'\n(</hi>)', r'\1\n', text)
    text = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r'\n<lb/>\1', text)
    text = re.sub(r'<lb/> +', r'<lb/>', text)
    text = re.sub(r'\n\n+', r'\n', text)
    text = re.sub(r'  +', r' ', text)
    
    # NEW: Remove standalone page numbers (Arabic, Tibetan, or Roman Numerals) that appear on their own line right before a <pb/>
    page_num_pattern = r'\n(?:<lb/>)?\s*(?:<hi[^>]*>)?\s*(?:[0-9]+|[\u0F20-\u0F29]+|[ivxlcdmIVXLCDM]+)\s*(?:</hi>)?\s*\n(?=<pb)'
    text = re.sub(page_num_pattern, '\n', text)

    # Remove consecutive <pb/> tags (keep only one)
    text = re.sub(r'(<pb/>[\s\n]*)+', r'<pb/>\n', text)

    # Remove orphaned <lb/> left when the artifact was on its own line (collapse empty-line breaks)
    text = re.sub(r'<lb/>\s*\n\s*<lb/>', r'<lb/>', text)

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


def generate_tei_header(pdf_file: Path, ve_id: str, ut_id: str, title: str = "XXX") -> str:
    """Generate TEI header for a file."""
    sha256 = calculate_sha256(pdf_file)
    src_path = pdf_file.name
    
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
# Helper Functions
# =============================================================================

def get_ve_ids_from_toprocess(input_path: Path) -> list:
    """
    Get VE IDs from the toprocess folder structure.
    
    Returns:
        List of VE IDs sorted alphabetically
    """
    toprocess_path = input_path / 'toprocess'
    if not toprocess_path.exists():
        print(f"Warning: toprocess folder not found at {toprocess_path}")
        return []
    
    ve_ids = []
    for folder in toprocess_path.iterdir():
        if folder.is_dir() and folder.name.startswith('VE'):
            # Handle both formats: IE3KG691-VE1ER566 and VE1ER566
            if folder.name.startswith(f'{IE_ID}-'):
                ve_id = folder.name.replace(f'{IE_ID}-', '')
            else:
                ve_id = folder.name
            ve_ids.append(ve_id)
    
    return natsorted(ve_ids)


def get_ut_id(ve_id: str, file_idx: int) -> str:
    """Generate UT ID from VE ID and file index."""
    # Extract the numeric/alpha part after 'VE'
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{file_idx:04d}"


def get_pdf_files(input_path: Path, ve_ids: list) -> list:
    """
    Get all PDF files from either sources folder or toprocess VE folders, naturally sorted.
    
    Args:
        input_path: Path to input folder
        ve_ids: List of VE IDs to look for PDFs in
    
    Returns:
        List of Path objects for PDF files
    """
    # First try sources folder
    sources_path = input_path / 'sources'
    if sources_path.exists():
        pdf_files = list(sources_path.glob('*.pdf'))
        if pdf_files:
            return natsorted(pdf_files, key=lambda p: p.name)
    
    # If no sources folder or no PDFs, look in toprocess VE folders
    toprocess_path = input_path / 'toprocess'
    if not toprocess_path.exists():
        print(f"Error: Neither sources nor toprocess folder found")
        return []
    
    pdf_files = []
    for ve_id in ve_ids:
        # Try both formats: IE3KG691-VE1ER566 and VE1ER566
        ve_folder = toprocess_path / ve_id
        if not ve_folder.exists():
            ve_folder = toprocess_path / f'{IE_ID}-{ve_id}'
        
        if ve_folder.exists():
            ve_pdfs = list(ve_folder.glob('*.pdf'))
            if ve_pdfs:
                # Take the first PDF from each VE folder
                pdf_files.append(natsorted(ve_pdfs, key=lambda p: p.name)[0])
    
    return pdf_files


# =============================================================================
# Main Conversion Function
# =============================================================================

def convert_IE2KG229024(input_path: str, output_path: str):
    """
    Main conversion function for IE2KG229024.
    
    Args:
        input_path: Path to input folder (IE2KG229024_INPUT)
        output_path: Path to output folder (IE2KG229024)
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    
    print(f"=" * 60)
    print(f"Converting {IE_ID}")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"=" * 60)
    
    # Validate input
    if not input_path.exists():
        print(f"Error: Input path does not exist: {input_path}")
        sys.exit(1)
    
    # Get VE IDs and PDF files
    ve_ids = get_ve_ids_from_toprocess(input_path)
    pdf_files = get_pdf_files(input_path, ve_ids)
    
    if not ve_ids:
        print("Error: No VE IDs found in toprocess folder")
        sys.exit(1)
    
    if not pdf_files:
        print("Error: No PDF files found in sources folder")
        sys.exit(1)
    
    print(f"\nFound {len(ve_ids)} VE IDs and {len(pdf_files)} PDF files")
    
    if len(ve_ids) != len(pdf_files):
        print(f"Warning: Number of VE IDs ({len(ve_ids)}) does not match number of PDFs ({len(pdf_files)})")
    
    # Create output directories
    archive_path = output_path / 'archive'
    sources_path = output_path / 'sources'
    archive_path.mkdir(parents=True, exist_ok=True)
    sources_path.mkdir(parents=True, exist_ok=True)
    
    # Process each PDF
    for idx, (ve_id, pdf_file) in enumerate(zip(ve_ids, pdf_files)):
        print(f"\n[{idx + 1}/{len(pdf_files)}] Processing {pdf_file.name} -> {ve_id}")
        
        # Step 1: Extract text from PDF
        raw_text = extract_pdf_to_text(pdf_file)
        if not raw_text:
            print(f"  Skipping {pdf_file.name} - no text extracted")
            continue
        
        # Step 1.5: Remove standalone yigmgo lines (pdfminer artifact)
        raw_text = remove_standalone_yigmgo(raw_text)
        raw_text = remove_artifact_line(raw_text)
        text = remove_indesign_artifacts(raw_text)
        text = remove_headers_footers(text)

        # Step 2: Simplify font sizes and normalize
        print("  Simplifying font sizes...")
        simplified_text = simplify_font_sizes(text)
        print("  Normalizing Unicode...")
        normalized_text = normalize_text(simplified_text)
        
        # Step 3: Classify font sizes
        print("  Classifying font sizes...")
        classifications = classify_font_sizes(normalized_text)
        if classifications:
            print(f"    Classifications: {classifications}")
        
        # Apply font markup
        marked_text = apply_font_markup(normalized_text, classifications)
        
        # Step 4: Convert to TEI
        print("  Converting to TEI...")
        tei_body = convert_markup_to_tei(marked_text)
        
        # Generate TEI document
        ut_id = get_ut_id(ve_id, 1)
        header = generate_tei_header(pdf_file, ve_id, ut_id)
        tei_document = generate_tei_document(tei_body, header)
        
        # Write output
        ve_output_path = archive_path / ve_id
        ve_output_path.mkdir(parents=True, exist_ok=True)
        
        xml_file = ve_output_path / f"{ut_id}.xml"
        with open(xml_file, 'w', encoding='utf-8') as f:
            f.write(tei_document)
        print(f"  Wrote: {xml_file}")
        
        ve_sources_path = sources_path / ve_id
        ve_sources_path.mkdir(parents=True, exist_ok=True)
        dest_pdf = ve_sources_path / pdf_file.name
        shutil.copy2(pdf_file, dest_pdf)
        print(f"  Copied: {dest_pdf}")
    
    # Summary
    print(f"\n{'=' * 60}")
    print(f"Conversion complete!")
    print(f"Processed: {len(pdf_files)} PDF files")
    print(f"Output: {output_path}")
    print(f"{'=' * 60}")


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    if len(sys.argv) != 3:
        print(f"Usage: python {sys.argv[0]} <input_folder> <output_folder>")
        print(f"\nExample:")
        print(f"  python {sys.argv[0]} /path/to/IE3KG691_INPUT /path/to/IE3KG691")
        sys.exit(1)
    
    input_folder = sys.argv[1]
    output_folder = sys.argv[2]
    
    convert_IE2KG229024(input_folder, output_folder)


if __name__ == "__main__":
    main()
