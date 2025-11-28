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


def load_outline_csv(csv_path):
    """
    Load outline CSV and return a dictionary mapping (volume, page) to title.
    
    CSV format: level1,level2,level3,parttype,label,title,vol start,vol end,page start,page end
    Returns: dict mapping (vol_start, page_start) -> title
    """
    outline = {}
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header row
            for row in reader:
                if len(row) >= 10:
                    title = row[5]  # title column
                    vol_start = row[6]  # vol start column
                    page_start = row[8]  # page start column
                    
                    # Only add entries that have both vol_start and page_start
                    if vol_start and page_start:
                        try:
                            vol_num = int(vol_start)
                            page_num = int(page_start)
                            outline[(vol_num, page_num)] = title
                        except ValueError:
                            # Skip rows with non-numeric values
                            pass
    except FileNotFoundError:
        print(f"Warning: outline_full.csv not found at {csv_path}")
    return outline


def load_outline_boundaries_csv(csv_path):
    """
    Load O3KG218-W3KG218.csv and find pages where text boundaries occur mid-page.
    
    A mid-page boundary occurs when the img_end of one text equals the img_start of the next text.
    
    CSV format: RID,Position*5,part type,label,titles,work,notes,colophon,authorshipStatement,identifiers,img start,img end,vol start,vol end
    
    Returns: dict mapping volume_num -> set of boundary page numbers
    """
    boundaries = {}
    
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header row
            
            # Collect all texts with their page ranges
            # We need: (vol_start, vol_end, img_start, img_end)
            texts = []
            for row in reader:
                if len(row) >= 18:
                    img_start = row[14].strip()
                    img_end = row[15].strip()
                    vol_start = row[16].strip()
                    vol_end = row[17].strip()
                    
                    # Skip rows without page numbers
                    if img_start and img_end and vol_start and vol_end:
                        try:
                            texts.append({
                                'img_start': int(img_start),
                                'img_end': int(img_end),
                                'vol_start': int(vol_start),
                                'vol_end': int(vol_end)
                            })
                        except ValueError:
                            pass
            
            # Find cases where img_end of one text == img_start of the next text
            # and they're in the same volume
            for i in range(len(texts) - 1):
                current = texts[i]
                next_text = texts[i + 1]
                
                # Check if they're in the same volume and share a page
                if (current['vol_end'] == next_text['vol_start'] and 
                    current['img_end'] == next_text['img_start']):
                    vol_num = current['vol_end']
                    boundary_page = current['img_end']
                    
                    if vol_num not in boundaries:
                        boundaries[vol_num] = set()
                    boundaries[vol_num].add(boundary_page)
    
    except FileNotFoundError:
        print(f"Warning: {csv_path} not found")
    
    return boundaries


def insert_milestone_in_page(page_content, page_num):
    """
    Insert a milestone at text boundary position in page content.
    
    Rules (in order of priority):
    1. Before at least one Tibetan digit ༠-༩ followed by ༽
    2. Else before ༄ at character position 5+ on first line (ignoring XML) or anywhere on subsequent lines
    3. Else before ༈
    4. Else after a sequence of 3+ ། (with only spaces in between)
    5. Else return failure
    
    Returns:
        (modified_content, success, rule_used) tuple
    """
    milestone = f'<milestone xml:id="P{page_num}_B01" unit="section"/>'
    
    # Rule 1: At least one Tibetan digit followed by ༽
    match = re.search(r'[༠-༩]+༽', page_content)
    if match:
        return (page_content[:match.start()] + milestone + page_content[match.start():], True, 1)
    
    # Rule 2: ༄ at position 5+ on first line (ignoring XML) or anywhere on subsequent lines
    # The first line starts WITH <lb/>, so we split by <lb/> to get lines
    # lb_parts[0] = content before first <lb/> (typically empty/whitespace after <pb/>)
    # lb_parts[1] = first line content (after first <lb/>)
    # lb_parts[2:] = subsequent lines
    
    lb_parts = page_content.split('<lb/>')
    
    # Check first line (lb_parts[1]) - ༄ at position 5+ (ignoring XML tags)
    if len(lb_parts) >= 2:
        first_line = lb_parts[1]
        if '༄' in first_line:
            clean_first = re.sub(r'<[^>]+>', '', first_line)
            clean_pos = clean_first.find('༄')
            if clean_pos >= 5:
                # Find actual position in page_content
                offset = len(lb_parts[0]) + 5  # 5 = len('<lb/>')
                actual_pos = offset + first_line.find('༄')
                return (page_content[:actual_pos] + milestone + page_content[actual_pos:], True, 2)
    
    # Check subsequent lines (lb_parts[2:]) - ༄ anywhere
    for i in range(2, len(lb_parts)):
        line = lb_parts[i]
        if '༄' in line:
            # Calculate offset: sum of (part + '<lb/>') for all previous parts
            offset = sum(len(lb_parts[j]) + 5 for j in range(i))  # 5 = len('<lb/>')
            actual_pos = offset + line.find('༄')
            return (page_content[:actual_pos] + milestone + page_content[actual_pos:], True, 2)
    
    # Rule 3: ༈ anywhere
    if '༈' in page_content:
        pos = page_content.find('༈')
        return (page_content[:pos] + milestone + page_content[pos:], True, 3)
    
    # Rule 4: Sequence of 3+ ། with only spaces in between
    match = re.search(r'(།[ ]*){3,}', page_content)
    if match:
        return (page_content[:match.end()] + milestone + page_content[match.end():], True, 4)
    
    # Rule 5: Not found
    return (page_content, False, 0)


def insert_milestones_in_text(text, volume_num, boundary_pages_dict):
    """
    Insert milestone markers at text boundaries that occur mid-page.
    
    Args:
        text: TEI-converted text with <pb n="X"/> markers
        volume_num: Volume number (for looking up boundaries)
        boundary_pages_dict: Dict mapping volume_num -> set of boundary page numbers
    
    Returns:
        (modified_text, unresolved_pages) tuple
        unresolved_pages is a list of (page_num, page_content_preview) for pages where no boundary was found
    """
    unresolved = []
    
    # Get boundary pages for this volume
    boundary_pages = boundary_pages_dict.get(volume_num, set())
    if not boundary_pages:
        return text, []
    
    # Split text by page breaks, keeping the delimiters
    # Use non-capturing group for the page number to avoid including it in the split result
    parts = re.split(r'(<pb n="\d+"/>)', text)
    
    # parts will be: [content_before, <pb n="X"/>, content_X, <pb n="Y"/>, content_Y, ...]
    # Even indices: content, Odd indices: <pb> tags
    result = []
    
    for i, part in enumerate(parts):
        if i % 2 == 1:
            # This is a <pb n="X"/> tag
            result.append(part)
            # Extract page number from the tag
            page_match = re.match(r'<pb n="(\d+)"/>', part)
            if page_match:
                page_num = int(page_match.group(1))
                
                # Check if this page needs a milestone (process the next part which is content)
                if page_num in boundary_pages and i + 1 < len(parts):
                    page_content = parts[i + 1]
                    modified_content, success, rule = insert_milestone_in_page(page_content, page_num)
                    if success:
                        parts[i + 1] = modified_content  # Replace content in parts array
                    else:
                        # Create a preview of the content (first 200 chars, cleaned)
                        preview = re.sub(r'<[^>]+>', '', page_content)[:200]
                        unresolved.append((page_num, preview))
        else:
            # This is content
            result.append(part)
    
    return ''.join(result), unresolved


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
    - Adds <pb/> tags for pages 1 to start_page_num-1 at the beginning (one per line)
    
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
    
    # Add <pb/> tags for pages 1 to start_page_num-1 at the beginning (one per line)
    initial_pbs = []
    for i in range(1, start_page_num):
        initial_pbs.append(f'<pb n="{i}"/>')
    
    # Add first page break at the beginning with the starting page number
    if initial_pbs:
        text = '\n'.join(initial_pbs) + '\n<pb n="' + str(start_page_num) + '"/>\n' + text
    else:
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
    
    # Normalize double (or more) spaces into single spaces
    text = re.sub(r'  +', r' ', text)
    
    # Ensure each <pb/> tag is on its own line (no two on the same line)
    # Replace any <pb/> tag immediately followed by another <pb/> tag on the same line
    # with the first one on its own line, then the second one
    while re.search(r'<pb n="\d+"/>[^\n]*<pb n="\d+"/>', text):
        text = re.sub(r'(<pb n="\d+"/>)([^\n]*?)(<pb n="\d+"/>)', r'\1\n\3', text)
    
    return text


def generate_tei_header(txt_file, pdf_file, folder_name, file_position, title="XXX"):
    """
    Generate TEI header for a file.
    
    Args:
        txt_file: Path to the txt file (e.g., W3KG218-I3KG693/1-1-0.txt)
        pdf_file: Path to the PDF file (e.g., W3KG218/W3KG218-I3KG693/1-1-0.pdf)
        folder_name: Folder name (e.g., W3KG218-I3KG693)
        file_position: Position in natsorted list (1-indexed, 4-digit padded)
        title: Title for the document (default "XXX")
    """
    # Extract VE ID from folder name (e.g., I3KG693 -> VE1ER13)
    ve_id = get_ve_id_from_folder(f"X-{folder_name.split('-')[1]}")  # Reuse the function
    
    # Compute SHA256 of PDF
    sha256 = compute_sha256(pdf_file)
    
    # Construct relative path for src_path
    src_path = f"{folder_name}/{txt_file.name.replace('.txt', '.pdf')}"
    
    # Construct UT ID
    ut_id = f"UT{ve_id[2:]}_{file_position:04d}"
    
    header = f"""<teiHeader>
<fileDesc>
<titleStmt>
<title>{title}</title>
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
    """Extract VE ID from folder name (e.g., W3KG218-I3KG693 -> VE1ER13)."""
    i_id = folder_name.split('-')[1]  # I3KG693
    # Extract the numeric suffix (e.g., 693 from I3KG693)
    num = int(i_id[4:])  # 693
    # Convert to VE1ER format (subtract 680)
    ve_num = num - 680  # 693 - 680 = 13
    return f'VE1ER{ve_num}'  # VE1ER13


def get_ut_id(ve_id, file_position):
    """Generate UT ID (e.g., VE3KG693, 1 -> UT3KG693_0001)."""
    return f"UT{ve_id[2:]}_{file_position:04d}"


def count_pb_tags(text):
    """
    Count the number of <pb/> tags in the converted TEI text.
    This gives us the actual number of pages in the output.
    """
    return text.count('<pb n=')


def process_file(txt_file, output_file, pdf_file, folder_name, file_position, blank_pages_dict, start_page_num, outline_dict, volume_num, boundary_pages_dict):
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
        outline_dict: Dictionary mapping (volume, page) to title
        volume_num: Volume number
        boundary_pages_dict: Dictionary mapping volume_num -> set of boundary page numbers
    
    Returns:
        Tuple of (errors, num_pages, unresolved_milestones) where:
        - num_pages is the count of pages in this file (excluding type2 blanks)
        - unresolved_milestones is a list of (page_num, preview) for pages where milestone couldn't be placed
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
    
    # Insert milestones at text boundaries (mid-page)
    text, unresolved_milestones = insert_milestones_in_text(text, volume_num, boundary_pages_dict)
    
    # Look up title from outline CSV based on volume and starting page
    title = outline_dict.get((volume_num, start_page_num))
    
    # Generate UT ID for use as fallback title if needed
    ve_id = get_ve_id_from_folder(folder_name)
    ut_id = get_ut_id(ve_id, file_position)
    
    if title is None:
        errors.append(f"ERROR: {txt_file.name} - No title found in outline for volume {volume_num}, page {start_page_num}")
        title = ut_id  # Use UT id as fallback title
    
    # Generate TEI header
    tei_header = generate_tei_header(txt_file, pdf_file, folder_name, file_position, title)
    
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
    
    return errors, num_pages, unresolved_milestones


def process_files(input_dir='W3KG218-step2_fsmarkup',
                  output_dir='W3KG218-step3_tei',
                  pdf_dir='W3KG218',
                  blank_pages_csv='DKCC/blank_pages.csv',
                  outline_csv='outline_full.csv',
                  outline_boundaries_csv='O3KG218-W3KG218.csv'):
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
    
    # Load outline CSV
    print(f"Loading outline CSV from {outline_csv}...")
    outline_dict = load_outline_csv(outline_csv)
    print(f"Loaded {len(outline_dict)} entries from outline_full.csv")
    
    # Load outline boundaries CSV to find mid-page text boundaries
    print(f"Loading outline boundaries CSV from {outline_boundaries_csv}...")
    boundary_pages_dict = load_outline_boundaries_csv(outline_boundaries_csv)
    total_boundaries = sum(len(pages) for pages in boundary_pages_dict.values())
    print(f"Found {total_boundaries} mid-page boundaries across {len(boundary_pages_dict)} volumes")
    
    # Create output directory
    output_path.mkdir(exist_ok=True)
    
    # Process each folder
    folders = sorted([d for d in input_path.iterdir() if d.is_dir()])
    
    print(f"Processing {len(folders)} folders...")
    
    total_processed = 0
    total_errors = 0
    all_removal_errors = []
    all_unresolved_milestones = []  # List of (volume_num, page_num, xml_file, preview)
    
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
                file_errors, num_pages, unresolved = process_file(
                    txt_file, output_file, pdf_file, folder_name, idx, 
                    blank_pages_dict, current_page_num, outline_dict, volume_num,
                    boundary_pages_dict
                )
                
                # Track unresolved milestones
                for page_num, preview in unresolved:
                    all_unresolved_milestones.append((volume_num, page_num, output_file, preview))
                
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
    
    # Report milestone statistics
    milestones_inserted = total_boundaries - len(all_unresolved_milestones)
    print(f"\nMilestone insertion:")
    print(f"  Total boundary pages: {total_boundaries}")
    print(f"  Milestones inserted: {milestones_inserted}")
    print(f"  Unresolved (no pattern found): {len(all_unresolved_milestones)}")
    
    if all_unresolved_milestones:
        print(f"\nUnresolved milestone pages (could not find boundary pattern):")
        for vol_num, page_num, xml_file, preview in all_unresolved_milestones:
            print(f"  Volume {vol_num}, Page {page_num}, File: {xml_file}")
            print(f"    Preview: {preview[:100]}...")
    
    print(f"\nOutput directory: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    process_files()
