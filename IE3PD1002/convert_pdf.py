#!/usr/bin/env python3
"""
Convert PDF files from IE3PD1002 to TEI XML format.

This script implements a 4-step pipeline:
1. PDF to Text - Extract text from PDFs using py-tiblegenc with font size tracking
2. Normalize - Simplify font size markup and apply Unicode normalization
3. Classify Fonts - Auto-classify font sizes as regular/small/large
4. Convert to TEI - Generate TEI XML with proper structure

Usage:
    python convert_pdf.py <input_folder> <output_folder>
    
Example:
    python convert_pdf.py /path/to/IE3PD1002_INPUT /path/to/IE3PD1002_OUTPUT
"""

import sys
import os
import re
import hashlib
import shutil
from pathlib import Path
from collections import Counter
from natsort import natsorted

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from normalization import normalize_unicode

# Import py-tiblegenc
try:
    from pytiblegenc import pdf_to_txt
except ImportError:
    print("Error: pytiblegenc not installed. Run: pip install git+https://github.com/buda-base/py-tiblegenc.git")
    sys.exit(1)


# =============================================================================
# Configuration
# =============================================================================

IE_ID = "IE3PD1002"
PAGE_BREAK_STR = "ZZZZ"
FONT_SIZE_FORMAT = "<fs:{}>"


# =============================================================================
# Step 1: PDF to Text Extraction
# =============================================================================

def extract_pdf_to_text(pdf_path: Path) -> str:
    """
    Extract text from a PDF file using py-tiblegenc.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Extracted text with font size markers and page breaks
    """
    print(f"  Extracting: {pdf_path.name}")
    
    try:
        text = pdf_to_txt(
            str(pdf_path),
            page_break_str=f"\n{PAGE_BREAK_STR}\n",
            track_font_size=True,
            font_size_format=FONT_SIZE_FORMAT,
            normalize=False,  # We'll normalize ourselves
            simplify_font_sizes_option=False,  # We'll handle this
        )
        return text
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
    
    classifications = {}
    
    if len(sizes) == 1:
        classifications[sizes[0]] = 'regular'
    
    elif len(sizes) == 2:
        fs1, fs2 = sizes
        pct1, pct2 = size_percentages[fs1], size_percentages[fs2]
        
        if pct1 > pct2:
            classifications[fs1] = 'regular'
            classifications[fs2] = 'large' if fs2 > fs1 else 'small'
        else:
            classifications[fs2] = 'regular'
            classifications[fs1] = 'large' if fs1 > fs2 else 'small'
    
    else:
        # Find the most common size in body text range (18-26)
        body_text_range = [fs for fs in sizes if 18 <= fs <= 26]
        
        if body_text_range:
            most_common_fs = max(body_text_range, key=lambda fs: size_counts[fs])
        else:
            most_common_fs = max(size_counts.items(), key=lambda x: x[1])[0]
        
        classifications[most_common_fs] = 'regular'
        
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
        if folder.is_dir() and folder.name.startswith(f'{IE_ID}-'):
            ve_id = folder.name.replace(f'{IE_ID}-', '')
            ve_ids.append(ve_id)
    
    return natsorted(ve_ids)


def get_ut_id(ve_id: str, file_idx: int) -> str:
    """Generate UT ID from VE ID and file index."""
    # Extract the numeric/alpha part after 'VE'
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{file_idx:04d}"


def get_pdf_files(input_path: Path) -> list:
    """
    Get all PDF files from the sources folder, naturally sorted.
    
    Returns:
        List of Path objects for PDF files
    """
    sources_path = input_path / 'sources'
    if not sources_path.exists():
        print(f"Error: sources folder not found at {sources_path}")
        return []
    
    pdf_files = list(sources_path.glob('*.pdf'))
    return natsorted(pdf_files, key=lambda p: p.name)


# =============================================================================
# Main Conversion Function
# =============================================================================

def convert_ie3pd1002(input_path: str, output_path: str):
    """
    Main conversion function for IE3PD1002.
    
    Args:
        input_path: Path to input folder (IE3PD1002_INPUT)
        output_path: Path to output folder (IE3PD1002)
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
    pdf_files = get_pdf_files(input_path)
    
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
        
        # Step 2: Simplify font sizes and normalize
        print("  Simplifying font sizes...")
        simplified_text = simplify_font_sizes(raw_text)
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
        
        # Copy source PDF
        dest_pdf = sources_path / pdf_file.name
        shutil.copy2(pdf_file, dest_pdf)
    
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
        print(f"  python {sys.argv[0]} /path/to/IE3PD1002_INPUT /path/to/IE3PD1002")
        sys.exit(1)
    
    input_folder = sys.argv[1]
    output_folder = sys.argv[2]
    
    convert_ie3pd1002(input_folder, output_folder)


if __name__ == "__main__":
    main()

