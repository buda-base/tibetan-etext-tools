#!/usr/bin/env python3
"""
Convert Derge Kangyur (IE1ER199) text files to TEI XML.

Usage: convert_derge.py <input_folder> <output_folder>

Input folder should contain:
  - sources/text/*.txt files with [page], [page.line] markers
  - toprocess/IE1ER199-VE*/ folders (VE identifiers from BDRC)

Output folder will contain:
  - archive/{ve_id}/{ut_id}.xml (TEI XML)
  - sources/{ve_id}/{filename}.txt (copied source files)
  - IE1ER199.csv (outline)
"""

import os
import sys
import csv
import hashlib
import re
import shutil
from pathlib import Path

# Add parent directory to path for normalization module
sys.path.insert(0, str(Path(__file__).parent.parent))
from normalization import normalize_unicode


# =============================================================================
# VE ID Functions
# =============================================================================

def get_ve_ids_from_toprocess(toprocess_path: Path) -> list:
    """
    Get VE identifiers from the toprocess/ folder structure.
    
    The toprocess folder contains subfolders named IE1ER199-VE1ER###
    Returns list of dicts with 've_id' and 'volume_number' keys.
    """
    volumes = []
    
    if not toprocess_path.exists():
        return []
    
    # Find all IE1ER199-VE* folders
    ve_folders = sorted([
        d for d in toprocess_path.iterdir() 
        if d.is_dir() and d.name.startswith('IE1ER199-VE')
    ])
    
    for i, folder in enumerate(ve_folders):
        # Extract VE ID from folder name (e.g., IE1ER199-VE1ER148 -> VE1ER148)
        ve_id = folder.name.split('-')[-1]
        volumes.append({
            've_id': ve_id,
            'volume_number': i + 1
        })
    
    return volumes


def get_ut_id(ve_id: str) -> str:
    """
    Generate UT identifier from VE identifier.
    
    Per BDRC spec: Replace 'VE' with 'UT' and add '_0001' suffix.
    """
    ut_prefix = 'UT' + ve_id[2:]
    return f"{ut_prefix}_0001"


# =============================================================================
# Source File Parsing
# =============================================================================

def calculate_sha256(file_path: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for byte_block in iter(lambda: f.read(4096), b''):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def parse_derge_file(file_path: str) -> dict:
    """
    Parse a Derge Kangyur source file.
    
    Returns dict with:
      - 'pages': list of page dicts with 'page_num', 'lines' (list of line content)
      - 'milestones': list of Derge catalog markers (D1, D1-1, etc.)
      - 'raw_content': original file content
    """
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    pages = []
    milestones = []
    current_page = None
    current_lines = []
    
    # Process line by line
    for line in content.split('\n'):
        # Check for page marker [1a], [1b], [2a], etc.
        page_match = re.match(r'^\[(\d+[abx]+)\]$', line.strip())
        if page_match:
            # Save previous page
            if current_page is not None:
                pages.append({
                    'page_num': current_page,
                    'lines': current_lines
                })
            current_page = page_match.group(1)
            current_lines = []
            continue
        
        # Check for line marker [1a.1], [1a.2], etc.
        line_match = re.match(r'^\[(\d+[abx]+)\.(\d+)\](.*)$', line)
        if line_match:
            page_num = line_match.group(1)
            line_num = line_match.group(2)
            line_content = line_match.group(3)
            
            # If page changed via line marker
            if current_page != page_num:
                if current_page is not None:
                    pages.append({
                        'page_num': current_page,
                        'lines': current_lines
                    })
                current_page = page_num
                current_lines = []
            
            # Extract Derge milestones {D###} from line content
            milestone_matches = re.findall(r'\{(D\d+(?:-\d+)?)\}', line_content)
            for m in milestone_matches:
                milestones.append({
                    'id': m,
                    'page': page_num,
                    'line': line_num
                })
            
            current_lines.append({
                'line_num': line_num,
                'content': line_content
            })
            continue
        
        # Regular content line (shouldn't happen in proper format)
        if line.strip() and current_page is not None:
            current_lines.append({
                'line_num': None,
                'content': line
            })
    
    # Save last page
    if current_page is not None:
        pages.append({
            'page_num': current_page,
            'lines': current_lines
        })
    
    return {
        'pages': pages,
        'milestones': milestones,
        'raw_content': content
    }


def process_annotations(text: str) -> str:
    """
    Process inline annotations in text:
      - (X,Y) errors -> <choice><orig>X</orig><corr>Y</corr></choice>
      - {X,Y} variants -> <choice><orig>X</orig><reg>Y</reg></choice>
      - {D###} milestones -> <milestone xml:id="D###" unit="section"/>
      - [X] error candidates (with Tibetan text) -> <unclear reason="illegible">X</unclear>
    
    Returns TEI-formatted text.
    """
    result = text
    
    # Process Derge milestones {D###} or {D###-#}
    # These should become milestones, not choice elements
    result = re.sub(
        r'\{(D\d+(?:-\d+)?)\}',
        r'<milestone xml:id="\1" unit="section"/>',
        result
    )
    
    # Process variant annotations {X,Y} (with comma, but NOT Derge markers)
    # Must be careful not to match already processed milestones
    def replace_variant(match):
        orig = match.group(1)
        reg = match.group(2)
        orig_escaped = escape_xml(orig)
        reg_escaped = escape_xml(reg)
        return f'<choice><orig>{orig_escaped}</orig><reg>{reg_escaped}</reg></choice>'
    
    result = re.sub(
        r'\{([^}D][^},]*),([^}]+)\}',
        replace_variant,
        result
    )
    
    # Also handle {X,Y} where X starts with a Tibetan character (not D)
    result = re.sub(
        r'\{([^\x00-\x7F][^},]*),([^}]+)\}',
        replace_variant,
        result
    )
    
    # Process error annotations (X,Y)
    def replace_error(match):
        orig = match.group(1)
        corr = match.group(2)
        orig_escaped = escape_xml(orig)
        corr_escaped = escape_xml(corr)
        return f'<choice><orig>{orig_escaped}</orig><corr>{corr_escaped}</corr></choice>'
    
    result = re.sub(
        r'\(([^)]+),([^)]+)\)',
        replace_error,
        result
    )
    
    # Process [X] error candidates - brackets containing Tibetan/non-ASCII text
    # These are inline error markers, NOT page markers (which are handled earlier)
    # Match [content] where content contains Tibetan Unicode (U+0F00-U+0FFF)
    def replace_unclear(match):
        content = match.group(1)
        content_escaped = escape_xml(content)
        return f'<unclear reason="illegible">{content_escaped}</unclear>'
    
    # Match brackets containing Tibetan characters (U+0F00-U+0FFF range)
    # This will NOT match page markers like [1a] which only have ASCII
    result = re.sub(
        r'\[([^\[\]]*[\u0F00-\u0FFF][^\[\]]*)\]',
        replace_unclear,
        result
    )
    
    # Remove # (peydurma notes re-insertion points)
    result = result.replace('#', '')
    
    # Collapse any resulting multiple spaces to single space
    result = re.sub(r' {2,}', ' ', result)
    
    return result


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
            .replace("'", '&apos;'))


# =============================================================================
# TEI XML Generation
# =============================================================================

def generate_tei_header(title: str, ve_id: str, ie_id: str, ut_id: str, 
                        src_path: str, sha256: str) -> str:
    """Generate TEI header as string."""
    return f'''  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>{escape_xml(title)}</title>
      </titleStmt>
      <publicationStmt>
        <p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p>
      </publicationStmt>
      <sourceDesc>
        <bibl>
          <idno type="src_path">{escape_xml(src_path)}</idno>
          <idno type="src_sha256">{sha256}</idno>
          <idno type="bdrc_ie">http://purl.bdrc.io/resource/{ie_id}</idno>
          <idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
          <idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
        </bibl>
      </sourceDesc>
    </fileDesc>
    <encodingDesc>
      <p>
        The TEI header does not contain any bibliographical data. It is instead accessible through the 
        <ref target="http://purl.bdrc.io/resource/{ie_id}">record in the BDRC database</ref>.
      </p>
    </encodingDesc>
  </teiHeader>'''


def generate_tei_body(parsed_data: dict) -> str:
    """
    Generate TEI body content with xml:space="preserve".
    
    Format per spec:
    <pb n="1a"/>
    <lb/>line content...
    <pb n="1b"/>
    <lb/>more content...
    
    Rules:
    - no empty lines (<lb/>\n) - skip lines with no content
    - empty <pb/> are allowed
    - <pb/> should be the only thing on a file line
    - each file line must start with <lb/> or <pb/>
    """
    lines = []
    
    for page in parsed_data['pages']:
        page_num = page['page_num']
        
        # Add page break (empty pages are allowed)
        lines.append(f'<pb n="{page_num}"/>')
        
        for line_data in page['lines']:
            line_content = line_data['content']
            
            # Normalize and process annotations
            normalized = normalize_unicode(line_content)
            processed = process_annotations(normalized)
            
            # Strip leading and trailing whitespace from line
            processed = processed.strip()
            
            # Skip empty lines (spec says no empty <lb/>\n)
            if not processed:
                continue
            
            # Add line break and content
            lines.append(f'<lb/>{processed}')
    
    return '\n'.join(lines)


def generate_tei_xml(parsed_data: dict, title: str, ve_id: str, ie_id: str, 
                     ut_id: str, src_path: str, sha256: str) -> str:
    """Generate complete TEI XML document."""
    header = generate_tei_header(title, ve_id, ie_id, ut_id, src_path, sha256)
    body_content = generate_tei_body(parsed_data)
    
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
{header}
  <text>
    <body xml:lang="bo">
      <p xml:space="preserve">
{body_content}
</p>
    </body>
  </text>
</TEI>
'''


# =============================================================================
# CSV Outline Generation
# =============================================================================

def generate_csv_outline(all_milestones: list, output_path: str):
    """
    Generate CSV outline from Derge catalog milestones.
    
    all_milestones is a list of dicts with:
      - 'id': Derge ID (D1, D1-1, etc.)
      - 'page': page number
      - 'line': line number
      - 'volume': volume number
      - 've_id': VE identifier
    """
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Write header
        header = ['RID', 'Position', 'Position', 'Position', 'Position', 'part type',
                  'label', 'titles', 'work', 'notes', 'colophon', 'authorshipStatement',
                  'identifiers', 'etext start', 'etext end', 'img grp start', 'img grp end']
        writer.writerow(header)
        
        # Group milestones by volume
        volumes = {}
        for m in all_milestones:
            vol = m['volume']
            if vol not in volumes:
                volumes[vol] = []
            volumes[vol].append(m)
        
        # Write entries
        for vol_num in sorted(volumes.keys()):
            vol_milestones = volumes[vol_num]
            
            # Write volume row
            vol_row = ['', 'X'] + [''] * 3 + ['V', f'Volume {vol_num}'] + [''] * 6 + ['', '', str(vol_num), str(vol_num)]
            writer.writerow(vol_row)
            
            # Write text entries
            for i, m in enumerate(vol_milestones):
                derge_id = m['id']
                page = m['page']
                line = m['line']
                
                # Start reference
                start_ref = f"{vol_num}#{derge_id}"
                
                # End reference (next milestone or empty)
                end_ref = ''
                if i + 1 < len(vol_milestones):
                    next_m = vol_milestones[i + 1]
                    end_ref = f"{vol_num}#{next_m['id']}"
                
                # Text row
                pos_cols = ['', 'X', '', '']
                row = [''] + pos_cols + ['T', derge_id] + [''] * 6 + [start_ref, end_ref, str(vol_num), str(vol_num)]
                writer.writerow(row)


# =============================================================================
# Main Conversion Logic
# =============================================================================

def convert_ie1er199(input_path: str, output_path: str):
    """
    Main conversion function for IE1ER199 Derge Kangyur.
    
    Args:
        input_path: Path to IE1ER199 folder containing sources/text/*.txt and toprocess/
        output_path: Path where output folder will be created (e.g., ../IE1ER199/)
    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    ie_id = 'IE1ER199'
    
    # Input paths
    source_text_path = input_path / 'sources' / 'text'
    toprocess_path = input_path / 'toprocess'
    
    # Output paths
    output_sources_path = output_path / 'sources'
    output_archive_path = output_path / 'archive'
    
    # Create output directories
    output_path.mkdir(parents=True, exist_ok=True)
    output_sources_path.mkdir(parents=True, exist_ok=True)
    output_archive_path.mkdir(parents=True, exist_ok=True)
    
    # Get list of source files
    source_files = sorted(source_text_path.glob('*.txt'))
    num_volumes = len(source_files)
    
    print(f"Found {num_volumes} source files")
    
    # Get VE identifiers from toprocess folder
    print("Getting VE identifiers from toprocess folder...")
    volumes = get_ve_ids_from_toprocess(toprocess_path)
    
    if not volumes:
        print("Error: Could not find VE identifiers in toprocess folder")
        sys.exit(1)
    
    print(f"Got {len(volumes)} VE identifiers from toprocess folder")
    
    # Check volume count matches
    if len(volumes) != num_volumes:
        print(f"Warning: {len(volumes)} VE folders but {num_volumes} source files")
        print("Will process min of the two")
    
    # Collect all milestones for CSV
    all_milestones = []
    
    # Process each file
    process_count = min(len(volumes), num_volumes)
    for i in range(process_count):
        source_file = source_files[i]
        vol_info = volumes[i]
        ve_id = vol_info['ve_id']
        vol_num = vol_info.get('volume_number', i + 1)
        ut_id = get_ut_id(ve_id)
        
        print(f"Processing {source_file.name} -> {ve_id}/{ut_id}.xml")
        
        # Parse source file
        parsed = parse_derge_file(str(source_file))
        
        # Calculate SHA256
        sha256 = calculate_sha256(str(source_file))
        
        # Extract title from filename
        title = source_file.stem
        
        # Source path relative to sources/
        src_relative_path = f"{ve_id}/{source_file.name}"
        
        # Generate TEI XML
        tei_xml = generate_tei_xml(
            parsed, title, ve_id, ie_id, ut_id, 
            src_relative_path, sha256
        )
        
        # Create VE directories in output
        ve_sources_path = output_sources_path / ve_id
        ve_archive_path = output_archive_path / ve_id
        ve_sources_path.mkdir(parents=True, exist_ok=True)
        ve_archive_path.mkdir(parents=True, exist_ok=True)
        
        # Copy source file to output sources/{ve_id}/
        shutil.copy(str(source_file), ve_sources_path / source_file.name)
        
        # Write XML file
        xml_output_path = ve_archive_path / f"{ut_id}.xml"
        with open(xml_output_path, 'w', encoding='utf-8') as f:
            f.write(tei_xml)
        
        # Collect milestones for CSV
        for m in parsed['milestones']:
            m['volume'] = vol_num
            m['ve_id'] = ve_id
            all_milestones.append(m)
        
        print(f"  -> Wrote {xml_output_path}")
        print(f"  -> Found {len(parsed['milestones'])} text markers")
    
    # Generate CSV outline
    csv_output_path = output_path / f"{ie_id}.csv"
    generate_csv_outline(all_milestones, str(csv_output_path))
    print(f"Generated CSV outline: {csv_output_path}")
    
    # Copy non-volume files from sources/ directory
    # README.md goes to sources root, other non-.txt files go to other_files/
    sources_parent = input_path / 'sources'
    if sources_parent.exists():
        for f in sources_parent.iterdir():
            if f.is_file():
                if f.name == 'README.md':
                    # Copy README.md to sources root
                    shutil.copy(str(f), output_sources_path / f.name)
                    print(f"Copied {f.name} to sources/")
                elif f.suffix != '.txt' and f.name != '.DS_Store':
                    # Copy other non-.txt files to other_files/
                    other_files_path = output_sources_path / 'other_files'
                    other_files_path.mkdir(exist_ok=True)
                    shutil.copy(str(f), other_files_path / f.name)
                    print(f"Copied {f.name} to sources/other_files/")
    
    print(f"\nConversion complete!")
    print(f"  - Processed {process_count} volumes")
    print(f"  - Found {len(all_milestones)} text markers total")
    print(f"  - Output directory: {output_path}")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: convert_derge.py <input_folder> <output_folder>")
        print("Example: convert_derge.py ./IE1ER199 ../output")
        print()
        print("Input folder should contain:")
        print("  - sources/text/*.txt (source text files)")
        print("  - toprocess/IE1ER199-VE*/ (VE folders from BDRC)")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    
    if not input_path.exists():
        print(f"Error: Input folder does not exist: {input_path}")
        sys.exit(1)
    
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print()
    
    convert_ie1er199(str(input_path), str(output_path))


if __name__ == '__main__':
    main()
