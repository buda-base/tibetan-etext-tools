#!/usr/bin/env python3
"""
Script to identify ambiguous cases in outline_imgnums.csv where the end image number
is calculated based on the next text's start page, and extract the relevant pages
from the TEI files to help determine the correct boundary.

The ambiguity occurs when:
- imgnum_end = get_img_num(volumes_data[subfolder], next_page_num) - 1
This assumes the text ends on the page before the next text starts, but if the next
text starts in the middle of a page, the current text might actually extend to that page.
"""

import csv
import xml.etree.ElementTree as ET
from pathlib import Path
from collections import defaultdict


def get_ve_id_from_folder(folder_name):
    """Extract VE ID from folder name (e.g., W3KG218-I3KG693 -> VE1ER13)."""
    i_id = folder_name.split('-')[1]  # I3KG693
    # Extract the numeric suffix (e.g., 693 from I3KG693)
    num = int(i_id[4:])  # 693
    # Convert to VE1ER format (subtract 680)
    ve_num = num - 680  # 693 - 680 = 13
    return f'VE1ER{ve_num}'  # VE1ER13


def build_page_index(tei_dir):
    """
    Build an index mapping (volume_folder, page_num) -> xml_file.
    
    Scans all TEI XML files and extracts the page numbers from <pb n="X"> tags.
    
    Returns:
        dict: {volume_folder: {page_num: xml_file_path}}
    """
    import re
    
    index = {}
    tei_path = Path(tei_dir)
    
    if not tei_path.exists():
        print(f"Warning: TEI directory {tei_dir} not found")
        return index
    
    # Iterate through volume folders (IE3KG218-VE3KG693, etc.)
    for volume_folder in tei_path.iterdir():
        if not volume_folder.is_dir():
            continue
        
        volume_name = volume_folder.name
        index[volume_name] = {}
        
        # Iterate through XML files in the volume
        for xml_file in volume_folder.glob('*.xml'):
            try:
                with open(xml_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Find all page breaks - pattern handles namespace prefix
                pb_pattern = r'<(?:\w+:)?pb\s+n="(\d+)"'
                page_nums = re.findall(pb_pattern, content)
                
                for page_num in page_nums:
                    index[volume_name][int(page_num)] = xml_file
                    
            except Exception as e:
                print(f"Error reading {xml_file}: {e}")
    
    return index


def extract_pages_from_tei(tei_file, num_pages_from_start=None, num_pages_from_end=None):
    """
    Extract text content from specific pages in a TEI file.
    
    Args:
        tei_file: Path to TEI XML file
        num_pages_from_start: Number of pages to extract from the start (None = don't extract from start)
        num_pages_from_end: Number of pages to extract from the end (None = don't extract from end)
    
    Returns:
        Dictionary with 'start_pages' and 'end_pages' lists of (page_num, content) tuples
    """
    try:
        tree = ET.parse(tei_file)
        root = tree.getroot()
        
        # Define namespace
        ns = {'tei': 'http://www.tei-c.org/ns/1.0'}
        
        # Get the body text
        body = root.find('.//tei:body', ns)
        if body is None:
            return {'start_pages': [], 'end_pages': []}
        
        # Get all text content as a string
        p_elem = body.find('.//tei:p', ns)
        if p_elem is None:
            return {'start_pages': [], 'end_pages': []}
        
        # Convert to string to parse manually
        text_content = ET.tostring(p_elem, encoding='unicode', method='xml')
        
        # Split by <pb tags to find pages
        import re
        # Pattern needs to handle namespace prefix (ns0:pb or just pb)
        pb_pattern = r'<(?:\w+:)?pb n="(\d+)"(?:\s*/)?>'
        
        # Find all page breaks with their positions
        parts = re.split(pb_pattern, text_content)
        
        # Parse all pages
        all_pages = []
        # parts will be: [content_before_first_pb, page_num_1, content_1, page_num_2, content_2, ...]
        for i in range(1, len(parts), 2):
            if i < len(parts):
                page_num = int(parts[i])
                content = parts[i + 1] if i + 1 < len(parts) else ""
                
                # Clean up the content - remove XML tags but keep text
                clean_content = re.sub(r'<[^>]+>', '', content)
                clean_content = clean_content.strip()
                all_pages.append((page_num, clean_content))
        
        result = {'start_pages': [], 'end_pages': []}
        
        if num_pages_from_start and len(all_pages) > 0:
            result['start_pages'] = all_pages[:num_pages_from_start]
        
        if num_pages_from_end and len(all_pages) > 0:
            result['end_pages'] = all_pages[-num_pages_from_end:]
        
        return result
        
    except Exception as e:
        print(f"Error reading {tei_file}: {e}")
        return {'start_pages': [], 'end_pages': []}


def load_outline_imgnums(csv_path):
    """
    Load outline_imgnums.csv and return structured data.
    
    Returns:
        List of dictionaries with outline data
    """
    outlines = []
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                outlines.append(row)
    except FileNotFoundError:
        print(f"Error: {csv_path} not found")
        return []
    
    return outlines


def load_blank_pages_csv(csv_path):
    """
    Load blank pages CSV to determine complex cases.
    Returns dict mapping folder -> list of PDF info
    """
    folder_pdfs = defaultdict(list)
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 1:
                    folder = row[0].split('/')[0]
                    folder_pdfs[folder].append(row)
    except FileNotFoundError:
        print(f"Error: {csv_path} not found")
    return folder_pdfs


def identify_ambiguous_cases(outlines, blank_pages_csv='DKCC/blank_pages.csv'):
    """
    Identify ambiguous cases where imgnum_end might be off by one page.
    
    According to outlines_addimgnum.py, ambiguous cases only occur in "complex cases"
    where nb_content_pdfs != nb_texts (i.e., the number of PDF files doesn't match
    the number of texts in the outline).
    
    In these cases, the imgnum_end is calculated as:
        imgnum_end = get_img_num(volumes_data[subfolder], next_page_num) - 1
    
    This assumes the text ends on the page before the next text starts, but if the
    next text starts in the middle of a page, the current text might extend to that page.
    
    Returns:
        List of tuples: (current_row, next_row, ambiguous_page_num)
    """
    ambiguous = []
    
    # Load blank pages to determine which folders have complex cases
    folder_pdfs = load_blank_pages_csv(blank_pages_csv)
    
    # Group outlines by folder
    by_folder = defaultdict(list)
    for row in outlines:
        folder = row['Folder']
        by_folder[folder].append(row)
    
    # Check each folder
    for folder, rows in by_folder.items():
        # Skip karchak (number in outline = 0)
        content_rows = [r for r in rows if r['number in outline'] != '0']
        
        # Count PDFs (excluding karchak which is -0.pdf)
        nb_content_pdfs = len([pdf for pdf in folder_pdfs.get(folder, []) if not pdf[0].endswith('-0.pdf')])
        nb_texts = len(content_rows)
        
        # Only process complex cases where nb_content_pdfs != nb_texts
        if nb_content_pdfs != nb_texts:
            print(f"Complex case for {folder}: {nb_content_pdfs} PDFs vs {nb_texts} texts")
            
            # In complex cases, imgnum_end is calculated based on next text's page number
            for i in range(len(content_rows) - 1):
                current = content_rows[i]
                next_row = content_rows[i + 1]
                
                # Check if they're in the same volume
                if current['volnum_end'] == next_row['volnum_start']:
                    current_end = int(current['imgnum_end'])
                    next_start = int(next_row['imgnum_start'])
                    
                    # If they're adjacent (next_start = current_end + 1), this is ambiguous
                    if next_start == current_end + 1:
                        # The ambiguous page is current_end (could belong to current or next)
                        ambiguous.append((current, next_row, current_end))
    
    return ambiguous


def detect_mid_page_start(page_content):
    """
    Detect if a new text starts in the middle of the page.
    Returns True if ༅ appears on any line after the first line.
    This indicates the page contains the end of one text and the start of another.
    """
    lines = page_content.split('\n')
    for line in lines[1:]:  # Skip first line
        if '༅' in line:
            return True
    return False


def extract_pages_by_pagenum(page_index, volume_folder, page_num, context_pages=1):
    """
    Extract content for a specific page number and surrounding context.
    
    Args:
        page_index: The page index built by build_page_index()
        volume_folder: The volume folder name (e.g., 'IE3KG218-VE3KG693')
        page_num: The page number to extract
        context_pages: Number of pages of context to include before/after
    
    Returns:
        List of (page_num, content, xml_file) tuples
    """
    import re
    
    if volume_folder not in page_index:
        return []
    
    vol_index = page_index[volume_folder]
    results = []
    
    # Get pages around the target page
    for pn in range(page_num - context_pages, page_num + context_pages + 1):
        if pn in vol_index:
            xml_file = vol_index[pn]
            try:
                with open(xml_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Extract content for this specific page
                # Pattern to match content between page breaks
                pb_pattern = r'<(?:\w+:)?pb\s+n="(\d+)"[^>]*/?>([^<]*(?:<(?!(?:\w+:)?pb)[^>]*>[^<]*)*)'
                
                # Find all page content
                for match in re.finditer(pb_pattern, content, re.DOTALL):
                    found_pn = int(match.group(1))
                    if found_pn == pn:
                        page_content = match.group(2) if match.lastindex >= 2 else ""
                        # Clean up content - remove XML tags but keep text
                        clean_content = re.sub(r'<[^>]+>', '', page_content)
                        clean_content = clean_content.strip()
                        results.append((pn, clean_content, xml_file.name))
                        break
                        
            except Exception as e:
                print(f"Error extracting page {pn} from {xml_file}: {e}")
    
    return results


def main():
    """Main function to identify ambiguous cases and extract relevant pages."""
    
    # Paths
    outline_csv = 'outline_imgnums.csv'
    tei_dir = Path('W3KG218-step3_tei')
    output_file = 'DKCC/ambiguous.txt'
    
    print("Loading outline data...")
    outlines = load_outline_imgnums(outline_csv)
    print(f"Loaded {len(outlines)} outline entries")
    
    print("\nBuilding page index from TEI files...")
    page_index = build_page_index(tei_dir)
    total_pages = sum(len(pages) for pages in page_index.values())
    print(f"Indexed {total_pages} pages across {len(page_index)} volumes")
    
    print("\nIdentifying ambiguous cases...")
    ambiguous_cases = identify_ambiguous_cases(outlines, 'DKCC/blank_pages.csv')
    print(f"Found {len(ambiguous_cases)} ambiguous cases")
    
    if not ambiguous_cases:
        print("No ambiguous cases found!")
        return
    
    # Process each ambiguous case
    results = []
    detected_corrections = []  # List of (volnum, old_end_page, new_end_page)
    
    for current, next_row, ambiguous_page in ambiguous_cases:
        folder = current['Folder']
        
        # Skip W3KG218-I3KG749 - special case
        if folder == 'W3KG218-I3KG749':
            continue
        
        ve_id = get_ve_id_from_folder(folder)
        ie_folder = f"IE3KG218-{ve_id}"
        
        # Use imgnum values - these should match <pb n="X"> in XML files
        current_imgnum_end = int(current['imgnum_end'])
        next_imgnum_start = int(next_row['imgnum_start'])
        
        # Extract the boundary page (where next text supposedly starts)
        boundary_pages = extract_pages_by_pagenum(page_index, ie_folder, next_imgnum_start, context_pages=0)
        
        # Check if the next text starts mid-page (i.e., current text extends to next_imgnum_start)
        boundary_page_content = None
        boundary_page_xml = None
        for pn, content, xml_file in boundary_pages:
            if pn == next_imgnum_start:
                boundary_page_content = content
                boundary_page_xml = xml_file
                break
        
        # Skip pages with 2 lines or less - these are title pages, boundary is correct
        if boundary_page_content:
            line_count = len([l for l in boundary_page_content.split('\n') if l.strip()])
            if line_count <= 2:
                print(f"Title page (≤2 lines): {folder} boundary at imgnum {current_imgnum_end}/{next_imgnum_start}")
                continue
        
        mid_page_detected = False
        if boundary_page_content and detect_mid_page_start(boundary_page_content):
            # The current text actually ends on next_imgnum_start, not current_imgnum_end
            volnum = current['volnum_end']
            old_end = current_imgnum_end
            new_end = next_imgnum_start
            detected_corrections.append((volnum, old_end, new_end))
            mid_page_detected = True
        
        # Skip detected cases - only write unresolved ambiguous cases to output
        if mid_page_detected:
            print(f"Detected: {folder} boundary at imgnum {current_imgnum_end}/{next_imgnum_start}")
            continue
        
        # Format results (only for undetected/ambiguous cases)
        volnum = current['volnum_end']
        result_text = f"\n{'='*80}\n"
        result_text += f"AMBIGUOUS CASE:\n"
        result_text += f"Folder: {folder}\n"
        result_text += f"Current text: {current['Title']}\n"
        result_text += f"  imgnum: {current['imgnum_start']}-{current['imgnum_end']}\n"
        result_text += f"Next text: {next_row['Title']}\n"
        result_text += f"  imgnum: {next_row['imgnum_start']}-{next_row['imgnum_end']}\n"
        result_text += f"Ambiguous boundary: imgnum {current_imgnum_end} / {next_imgnum_start}\n"
        result_text += f"Copy to detected.csv if text extends to next page: {volnum},{current_imgnum_end},{next_imgnum_start}\n"
        
        result_text += f"\n--- BOUNDARY PAGE (imgnum {next_imgnum_start}) ---\n"
        if boundary_page_content:
            result_text += f"\n[Page {next_imgnum_start}] (from {boundary_page_xml})\n"
            result_text += boundary_page_content  # Full content
            result_text += "\n"
        else:
            result_text += "[Page not found in TEI files]\n"
        
        result_text += f"\n{'='*80}\n"
        
        results.append(result_text)
        
        # Print progress
        print(f"Ambiguous: {folder} boundary at imgnum {current_imgnum_end}/{next_imgnum_start}")
    
    # Write results to file (only undetected cases)
    print(f"\nWriting unresolved cases to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(f"UNRESOLVED AMBIGUOUS CASES\n")
        f.write(f"Total ambiguous boundaries: {len(ambiguous_cases)}\n")
        f.write(f"Automatically detected: {len(detected_corrections)}\n")
        f.write(f"Remaining unresolved: {len(results)}\n")
        f.write(f"Generated: {Path(__file__).name}\n")
        f.write("\n")
        
        for result in results:
            f.write(result)
    
    print(f"Done! Results written to {output_file}")
    print(f"Total ambiguous cases: {len(ambiguous_cases)}")
    print(f"Automatically detected: {len(detected_corrections)}")
    print(f"Remaining unresolved: {len(results)}")
    
    # Write detected corrections to CSV
    detected_csv = 'DKCC/detected.csv'
    print(f"\nWriting detected corrections to {detected_csv}...")
    with open(detected_csv, 'w', encoding='utf-8') as f:
        f.write("volumenumber,old_end_page,new_end_page\n")
        for volnum, old_end, new_end in detected_corrections:
            f.write(f"{volnum},{old_end},{new_end}\n")
    
    print(f"Detected {len(detected_corrections)} corrections")


if __name__ == "__main__":
    main()
