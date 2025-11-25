#!/usr/bin/env python3
"""
Script to convert marked-up text files to TEI XML format.
Reads files from W3KG218-step2_fsmarkup and writes to W3KG218-step3_tei.
"""

import re
import hashlib
from pathlib import Path
from natsort import natsorted


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


def convert_markup_to_tei(text):
    """
    Convert markup to TEI format.
    
    - <large> -> <hi rend="head">
    - <small> -> <hi rend="small">
    - Line breaks -> <lb/>
    - ZZZZ -> <pb n="X"/>
    - First line break + ZZZZ is ignored (conversion artifact)
    - First page starts with <pb n="1"/>
    - No <lb/> before <pb/>
    - No <lb/> on empty pages
    """
    # Remove the first line break + ZZZZ if present (conversion artifact)
    if text.startswith('\nZZZZ\n'):
        text = text[6:]  # Remove '\nZZZZ\n'
    elif text.startswith('ZZZZ\n'):
        text = text[5:]  # Remove 'ZZZZ\n'
    elif text.startswith('\nZZZZ'):
        text = text[5:]  # Remove '\nZZZZ'
    
    # Track page numbers
    page_num = 1
    
    # Replace ZZZZ with a placeholder that includes page number
    def replace_page_break(match):
        nonlocal page_num
        placeholder = f'<<<PB{page_num}>>>'
        page_num += 1
        return placeholder
    
    # Replace ZZZZ with placeholders
    text = re.sub(r'ZZZZ', replace_page_break, text)
    
    # Add first page break at the beginning
    text = '<<<PB0>>>\n' + text
    
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
    text = re.sub(r'<<<PB(\d+)>>>', r'<pb n="\1"/>', text)
    
    # Fix page numbering (we added PB0, now renumber starting from 1)
    def renumber_pages(match):
        old_num = int(match.group(1))
        return f'<pb n="{old_num + 1}"/>'
    text = re.sub(r'<pb n="(\d+)"/>', renumber_pages, text)
    
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


def process_file(txt_file, output_file, pdf_file, folder_name, file_position):
    """Process a single file and convert to TEI XML."""
    
    # Read input file
    with open(txt_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # Convert markup
    text = convert_markup_to_tei(text)
    
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


def process_files(input_dir='../W3KG218-step2_fsmarkup',
                  output_dir='../W3KG218-step3_tei',
                  pdf_dir='../W3KG218'):
    """Process all files and convert to TEI XML."""
    
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    pdf_path = Path(pdf_dir)
    
    if not input_path.exists():
        print(f"Error: Input directory not found: {input_dir}")
        return
    
    # Create output directory
    output_path.mkdir(exist_ok=True)
    
    # Process each folder
    folders = sorted([d for d in input_path.iterdir() if d.is_dir()])
    
    print(f"Processing {len(folders)} folders...")
    
    total_processed = 0
    total_errors = 0
    
    for folder in folders:
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
        
        processed = 0
        errors = 0
        
        for idx, txt_file in enumerate(txt_files, start=1):
            try:
                # Construct paths
                pdf_file = pdf_path / folder_name / txt_file.name.replace('.txt', '.pdf')
                
                # Generate UT ID for output filename
                ut_id = get_ut_id(ve_id, idx)
                output_file = output_path / output_folder_name / f"{ut_id}.xml"
                
                # Process file
                process_file(txt_file, output_file, pdf_file, folder_name, idx)
                
                processed += 1
                
            except Exception as e:
                print(f"  Error processing {txt_file.name}: {e}")
                errors += 1
        
        print(f"  Processed: {processed} files, Errors: {errors}")
        total_processed += processed
        total_errors += errors
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Processing complete!")
    print(f"Total processed: {total_processed} files")
    print(f"Total errors: {total_errors} files")
    print(f"Output directory: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    process_files()
