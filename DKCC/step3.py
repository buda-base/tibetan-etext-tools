#!/usr/bin/env python3
"""
Script to convert marked-up text files to TEI XML format.
Reads files from W3KG218-step2_fsmarkup and writes to W3KG218-step3_tei.
"""

import re
import hashlib
import csv
from pathlib import Path
from natsort import natsorted


def load_blank_pages_csv(csv_path):
    """
    Load blank pages CSV and return a dictionary mapping file paths to number of type2 blank pages.
    
    CSV format: filename,total_pages,type2_blank_pages,pages_by_pdf
    Returns: dict mapping filename -> number of type2 blank pages at end
    """
    blank_pages = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 3:
                    filename = row[0]  # e.g., W3KG218-I3KG693/1-1-11.pdf
                    type2_blank_count = int(row[2])  # number of type2 blank pages at end
                    blank_pages[filename] = type2_blank_count
    except FileNotFoundError:
        print(f"Warning: blank_pages.csv not found at {csv_path}")
    return blank_pages


def compute_sha256(file_path):
    """Compute SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def escape_xml(text):
    """Escape XML special characters in text."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def is_page_blank(page_content):
    """
    Check if a page is blank (contains only whitespace and markup tags).
    A blank page should have no actual text content.
    """
    # Remove all markup tags and whitespace
    cleaned = re.sub(r'<[^>]+>', '', page_content)
    cleaned = cleaned.strip()
    return len(cleaned) == 0


def remove_trailing_pages(text, num_pages_to_remove, filename):
    """
    Remove a specified number of pages from the end of the text.
    Returns the modified text and a list of errors if any non-blank pages were removed.
    
    Args:
        text: The text content with ZZZZ page markers
        num_pages_to_remove: Number of pages to remove from the end
        filename: Name of the file being processed (for error messages)
    
    Returns:
        (modified_text, errors) tuple
    """
    if num_pages_to_remove == 0:
        return text, []
    
    errors = []
    
    # Split text by ZZZZ to get pages
    pages = text.split('ZZZZ')
    
    if len(pages) <= num_pages_to_remove:
        errors.append(f"ERROR: {filename} - Cannot remove {num_pages_to_remove} pages, file only has {len(pages)} pages")
        return text, errors
    
    # Check if the pages to be removed are blank
    pages_to_remove = pages[-num_pages_to_remove:]
    for i, page in enumerate(pages_to_remove):
        page_num = len(pages) - num_pages_to_remove + i
        if not is_page_blank(page):
            errors.append(f"ERROR: {filename} - Page {page_num} (to be removed) is not blank: {page[:100]}")
    
    # Remove the pages
    pages = pages[:-num_pages_to_remove]
    
    # Rejoin with ZZZZ
    modified_text = 'ZZZZ'.join(pages)
    
    return modified_text, errors


def clean_empty_markup_lines(text):
    """
    Remove lines and pages that only contain font size markers (no actual content).
    
    This handles cases like:
    - <hi rend="small"><lb/><lb/></hi> -> should be removed
    - Pages with only <hi rend="small"></hi> or similar -> should be removed
    
    The goal is to remove <lb/> tags that appear inside <hi> tags when there's no actual text.
    """
    # Remove <lb/> tags that are inside <hi> tags with no actual text content
    # Pattern: <hi rend="...">content</hi> where content is only <lb/> tags and whitespace
    def clean_hi_tag(match):
        rend = match.group(1)
        content = match.group(2)
        # Check if content only contains <lb/>, whitespace, and newlines
        cleaned_content = re.sub(r'<lb/>|\s|\n', '', content)
        if not cleaned_content:
            # Content is empty, remove the entire <hi> tag
            return ''
        # Keep the tag as is
        return match.group(0)
    
    text = re.sub(r'<hi rend="([^"]+)">(.*?)</hi>', clean_hi_tag, text, flags=re.DOTALL)
    
    # Remove multiple consecutive newlines that may have been created
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    return text


def convert_markup_to_tei(text, start_page_num=1):
    """
    Convert markup to TEI format.
    
    - <large> -> <hi rend="head">
    - <small> -> <hi rend="small">
    - Line breaks -> <lb/>
    - ZZZZ -> <pb n="X"/>
    - First line break + ZZZZ is ignored (conversion artifact)
    - First page starts with the provided start_page_num
    - No <lb/> before <pb/>
    - No <lb/> on empty pages
    
    Args:
        text: Input text with markup
        start_page_num: Starting page number for this file (default 1)
    
    Returns:
        Converted text with TEI markup
    """
    # Remove the first line break + ZZZZ if present (conversion artifact)
    if text.startswith('\nZZZZ\n'):
        text = text[6:]  # Remove '\nZZZZ\n'
    elif text.startswith('ZZZZ\n'):
        text = text[5:]  # Remove 'ZZZZ\n'
    elif text.startswith('\nZZZZ'):
        text = text[5:]  # Remove '\nZZZZ'
    
    # Track page numbers starting from the provided start_page_num
    # The first page starts at start_page_num, and each ZZZZ marks the start of the next page
    page_num = start_page_num + 1
    
    # Replace ZZZZ with a placeholder that includes page number
    def replace_page_break(match):
        nonlocal page_num
        placeholder = f'<<<PB{page_num}>>>'
        page_num += 1
        return placeholder
    
    # Replace ZZZZ with placeholders
    text = re.sub(r'ZZZZ', replace_page_break, text)
    
    # Add first page break at the beginning with the starting page number
    text = f'<pb n="{start_page_num}"/>\n' + text
    
    # Replace line breaks with <lb/>
    # Each newline becomes <lb/> at the start of the new line
    lines = text.split('\n')
    result = []
    
    for i, line in enumerate(lines):
        if i > 0:  # Don't add <lb/> before the first line
            result.append('\n<lb/>')
        result.append(line)
    
    text = ''.join(result)
    
    # Replace page break placeholders with actual <pb/> tags
    # No need to renumber since we're using the correct page numbers from the start
    text = re.sub(r'<<<PB(\d+)>>>', r'<pb n="\1"/>', text)
    
    # Remove <lb/> before <pb/>
    text = re.sub(r'\n<lb/>\s*(?=<pb)', r'\n', text)
    
    # Remove <lb/> on empty lines before <pb/>
    text = re.sub(r'<lb/>\s*\n\s*(?=<pb)', r'', text)
    
    # Remove trailing <lb/> at the end
    text = re.sub(r'\n<lb/>\s*$', '', text)
    
    # Replace markup tags
    text = text.replace('<large>', '<hi rend="head">')
    text = text.replace('<small>', '<hi rend="small">')
    text = text.replace('</large>', '</hi>')
    text = text.replace('</small>', '</hi>')
    
    # Clean up empty markup lines (lines/pages with only font markers)
    text = clean_empty_markup_lines(text)
    
    # Remove ALL <lb/> tags before closing </hi> tags (with or without whitespace/newlines)
    text = re.sub(r'(<lb/>[\s\n]*)+</hi>', r'</hi>', text)
    
    # Remove spurious <lb/> right before <pb/> tags (if any remain)
    text = re.sub(r'<lb/>[\s\n]*<pb', r'<pb', text)
    
    # Transform \n</hi> into </hi>\n (move newlines after closing tags)
    text = re.sub(r'\n(</hi>)', r'\1\n', text)
    
    # Transform <hi rend="...">\n<lb/> into \n<lb/><hi rend="...">
    # This moves opening <hi> tags after <lb/> tags
    text = re.sub(r'(<hi rend="[^"]+">)\n<lb/>', r'\n<lb/>\1', text)
    
    # Remove all spaces after <lb/> tags
    text = re.sub(r'<lb/> +', r'<lb/>', text)
    
    # Clean up any double newlines that may have been created
    text = re.sub(r'\n\n+', r'\n', text)
    
    return text


def generate_tei_header(txt_file, pdf_file, folder_name, file_position):
    """
    Generate TEI header for a file.
    
    Args:
        txt_file: Path to the txt file (e.g., W3KG218-I3KG693/1-1-0.txt)
        pdf_file: Path to the PDF file (e.g., W3KG218/W3KG218-I3KG693/1-1-0.pdf)
        folder_name: Folder name (e.g., W3KG218-I3KG693)
        file_position: Position in natsorted list (1-indexed, 4-digit padded)
    """
    # Extract VE ID from folder name (e.g., I3KG693 -> VE3KG693)
    ve_id = folder_name.split('-')[1]  # I3KG693
    ve_id = 'VE' + ve_id[1:]  # VE3KG693
    
    # Compute SHA256 of PDF
    sha256 = compute_sha256(pdf_file)
    
    # Construct relative path for src_path
    src_path = f"{folder_name}/{txt_file.name.replace('.txt', '.pdf')}"
    
    # Construct UT ID
    ut_id = f"UT{ve_id[2:]}_{file_position:04d}"
    
    header = f"""<teiHeader>
<fileDesc>
<titleStmt>
<title>XXX</title>
</titleStmt>
<publicationStmt>
<p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p>
</publicationStmt>
<sourceDesc>
<bibl>
<idno type="src_path">{src_path}</idno>
<idno type="src_sha256">{sha256}</idno>
<idno type="bdrc_ie">http://purl.bdrc.io/resource/IE3KG218</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl>
</sourceDesc>
</fileDesc>
<encodingDesc>
<p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/IE3KG218">record in the BDRC database</ref>.</p>
</encodingDesc>
</teiHeader>"""
    
    return header


def get_ve_id_from_folder(folder_name):
    """Extract VE ID from folder name (e.g., W3KG218-I3KG693 -> VE3KG693)."""
    ve_id = folder_name.split('-')[1]  # I3KG693
    return 'VE' + ve_id[1:]  # VE3KG693


def get_ut_id(ve_id, file_position):
    """Generate UT ID (e.g., VE3KG693, 1 -> UT3KG693_0001)."""
    return f"UT{ve_id[2:]}_{file_position:04d}"


def count_pb_tags(text):
    """
    Count the number of <pb/> tags in the converted TEI text.
    This gives us the actual number of pages in the output.
    """
    return text.count('<pb n=')


def process_file(txt_file, output_file, pdf_file, folder_name, file_position, blank_pages_dict, start_page_num):
    """
    Process a single file and convert to TEI XML.
    
    Args:
        txt_file: Path to input txt file
        output_file: Path to output XML file
        pdf_file: Path to PDF file (for SHA256)
        folder_name: Folder name
        file_position: Position in file list
        blank_pages_dict: Dictionary mapping PDF filenames to number of type2 blank pages
        start_page_num: Starting page number for this file in the volume
    
    Returns:
        Tuple of (errors, num_pages) where num_pages is the count of pages in this file (excluding type2 blanks)
    """
    errors = []
    
    # Read input file
    with open(txt_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # Check if this file has type2 blank pages to remove
    pdf_filename = f"{folder_name}/{txt_file.stem}.pdf"
    num_pages_to_remove = blank_pages_dict.get(pdf_filename, 0)
    
    # Remove trailing pages if needed
    if num_pages_to_remove > 0:
        text, removal_errors = remove_trailing_pages(text, num_pages_to_remove, txt_file.name)
        errors.extend(removal_errors)
    
    # Convert markup with the correct starting page number
    text = convert_markup_to_tei(text, start_page_num)
    
    # Count the actual number of <pb/> tags in the output
    # This is the accurate count of pages in this file
    num_pages = count_pb_tags(text)
    
    # Generate TEI header
    tei_header = generate_tei_header(txt_file, pdf_file, folder_name, file_position)
    
    # Construct full TEI document
    tei_doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
{tei_header}
<text>
<body xml:lang="bo">
<p xml:space="preserve">
{text}</p>
</body>
</text>
</TEI>
"""
    
    # Write output file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(tei_doc)
    
    return errors, num_pages


def process_files(input_dir='W3KG218-step2_fsmarkup',
                  output_dir='W3KG218-step3_tei',
                  pdf_dir='W3KG218',
                  blank_pages_csv='DKCC/blank_pages.csv'):
    """Process all files and convert to TEI XML."""
    
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    pdf_path = Path(pdf_dir)
    
    if not input_path.exists():
        print(f"Error: Input directory not found: {input_dir}")
        return
    
    # Load blank pages CSV
    print(f"Loading blank pages CSV from {blank_pages_csv}...")
    blank_pages_dict = load_blank_pages_csv(blank_pages_csv)
    print(f"Loaded {len(blank_pages_dict)} entries from blank_pages.csv")
    
    # Create output directory
    output_path.mkdir(exist_ok=True)
    
    # Process each folder
    folders = sorted([d for d in input_path.iterdir() if d.is_dir()])
    
    print(f"Processing {len(folders)} folders...")
    
    total_processed = 0
    total_errors = 0
    all_removal_errors = []
    
    for folder_idx, folder in enumerate(folders):
        folder_name = folder.name
        print(f"\nProcessing folder: {folder_name}")
        
        # Get all txt files in folder, natsorted
        txt_files = natsorted(list(folder.glob('*.txt')))
        
        if not txt_files:
            print(f"  No txt files found")
            continue
        
        # Extract VE ID and create output folder name
        ve_id = get_ve_id_from_folder(folder_name)
        output_folder_name = f"IE3KG218-{ve_id}"
        
        # Determine starting page number for this volume
        # Volume number is based on folder order (alphabetically sorted)
        # folder_idx 0 = volume 1, folder_idx 1 = volume 2, etc.
        volume_num = folder_idx + 1
        
        # Volume 1 starts at page 6, all others start at page 4
        if volume_num == 1:
            current_page_num = 6
        else:
            current_page_num = 4
        
        print(f"  Volume {volume_num}, starting pagination at page {current_page_num}")
        
        processed = 0
        errors = 0
        
        for idx, txt_file in enumerate(txt_files, start=1):
            try:
                # Construct paths
                pdf_file = pdf_path / folder_name / txt_file.name.replace('.txt', '.pdf')
                
                # Generate UT ID for output filename
                ut_id = get_ut_id(ve_id, idx)
                output_file = output_path / output_folder_name / f"{ut_id}.xml"
                
                # Process file with current page number
                file_errors, num_pages = process_file(
                    txt_file, output_file, pdf_file, folder_name, idx, 
                    blank_pages_dict, current_page_num
                )
                
                # Update page number for next file
                current_page_num += num_pages
                
                if file_errors:
                    all_removal_errors.extend(file_errors)
                    for error in file_errors:
                        print(f"  {error}")
                
                processed += 1
                
            except Exception as e:
                print(f"  Error processing {txt_file.name}: {e}")
                errors += 1
        
        print(f"  Processed: {processed} files, Errors: {errors}")
        print(f"  Final page number: {current_page_num - 1}")
        total_processed += processed
        total_errors += errors
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Processing complete!")
    print(f"Total processed: {total_processed} files")
    print(f"Total errors: {total_errors} files")
    print(f"Total page removal errors: {len(all_removal_errors)}")
    if all_removal_errors:
        print(f"\nPage removal errors:")
        for error in all_removal_errors:
            print(f"  {error}")
    print(f"Output directory: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    process_files()
