#!/usr/bin/env python3
"""
Script to create O3KG218-IE3KG218.csv from O3KG218-W3KG218.csv.

This converts the image-based coordinates (img start, img end) to etext coordinates.
The etext coordinates reference positions within the TEI XML files.
"""

import csv
import re
from pathlib import Path
from collections import defaultdict


def load_tei_page_mappings(tei_dir):
    """
    Load all TEI XML files and build mappings for page numbers to etext numbers.
    
    Returns:
        page_to_etext: dict mapping (volume_num, page_num) -> etext_num
        etext_pages: dict mapping (volume_num, etext_num) -> (first_page, last_page)
        milestones: set of (volume_num, etext_num, milestone_id) tuples
    """
    page_to_etext = {}
    etext_pages = {}
    milestones = set()
    
    tei_path = Path(tei_dir)
    if not tei_path.exists():
        print(f"Warning: TEI directory {tei_dir} not found")
        return page_to_etext, etext_pages, milestones
    
    # Process each volume folder
    for volume_folder in sorted(tei_path.iterdir()):
        if not volume_folder.is_dir():
            continue
        
        # Extract volume number from folder name (IE3KG218-VE1ERXX -> volume number)
        # VE1ER12 = volume 1, VE1ER13 = volume 2, etc.
        # So volume_num = ve_num - 11
        folder_name = volume_folder.name
        match = re.search(r'VE1ER(\d+)$', folder_name)
        if not match:
            continue
        ve_num = int(match.group(1))
        volume_num = ve_num - 11  # VE1ER12 -> vol 1, VE1ER13 -> vol 2, etc.
        
        # Process each XML file in the volume
        for xml_file in sorted(volume_folder.glob('*.xml')):
            # Extract etext number from filename (last 4 chars before .xml)
            # e.g., UT1ER13_0001.xml -> 1
            stem = xml_file.stem
            if len(stem) >= 4:
                try:
                    etext_num = int(stem[-4:])
                except ValueError:
                    continue
            else:
                continue
            
            # Read file and extract page numbers and milestones
            try:
                with open(xml_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Find all <pb n="X"/> tags
                page_nums = [int(m) for m in re.findall(r'<pb n="(\d+)"/>', content)]
                
                if page_nums:
                    first_page = min(page_nums)
                    last_page = max(page_nums)
                    etext_pages[(volume_num, etext_num)] = (first_page, last_page)
                    
                    for page_num in page_nums:
                        page_to_etext[(volume_num, page_num)] = etext_num
                
                # Find all milestone IDs: <milestone xml:id="PXX_B01" unit="section"/>
                milestone_ids = re.findall(r'<milestone[^>]+xml:id="([^"]+)"', content)
                for ms_id in milestone_ids:
                    milestones.add((volume_num, etext_num, ms_id))
                        
            except Exception as e:
                print(f"Error reading {xml_file}: {e}")
    
    return page_to_etext, etext_pages, milestones


def get_level(row):
    """
    Determine the hierarchy level of a row based on Position columns (1-5).
    Returns the 1-based column index of the 'X' marker, or 0 if none found.
    """
    for i in range(1, 6):
        if row[i].strip() == 'X':
            return i
    return 0


def convert_to_etext_coord(volume_num, page_num, is_start, prev_or_next_page, 
                           page_to_etext, etext_pages, milestones, row_label="",
                           tei_dir=""):
    """
    Convert an image page number to an etext coordinate.
    
    Args:
        volume_num: Volume number
        page_num: Image/page number
        is_start: True if this is a start coordinate, False if end
        prev_or_next_page: For start, this is the end page of previous row at same level.
                          For end, this is the start page of next row at same level.
                          None if no previous/next row exists.
        page_to_etext: Mapping of (vol, page) -> etext_num
        etext_pages: Mapping of (vol, etext_num) -> (first_page, last_page)
        milestones: Set of (volume_num, etext_num, milestone_id) tuples
        row_label: Label for the row (for error messages)
        tei_dir: TEI directory path (for error messages)
    
    Returns:
        (etext_coordinate_string, error_message_or_None) tuple
    """
    if not page_num:
        return "", None
    
    try:
        page_num = int(page_num)
    except ValueError:
        return "", None
    
    # Find which etext contains this page
    etext_num = page_to_etext.get((volume_num, page_num))
    if etext_num is None:
        # Page not found in any etext - return empty string and error
        # Determine which XML file would contain this page based on volume
        ve_num = volume_num + 11  # volume 1 -> VE1ER12, volume 2 -> VE1ER13, etc.
        xml_folder = f"IE3KG218-VE1ER{ve_num}"
        xml_path = f"{tei_dir}/{xml_folder}/*.xml"
        error = f"ERROR: Page {page_num} not found in volume {volume_num} ({xml_path}) (row: {row_label})"
        return "", error
    
    # Get the page range of this etext
    etext_range = etext_pages.get((volume_num, etext_num))
    if not etext_range:
        return f"{etext_num}", None
    
    first_page, last_page = etext_range
    
    if is_start:
        # For start coordinate
        is_first_page_of_etext = (page_num == first_page)
        
        # Check if previous row at same level ends on this page
        prev_ends_on_this_page = (prev_or_next_page is not None and prev_or_next_page == page_num)
        
        if is_first_page_of_etext and not prev_ends_on_this_page:
            # Just the etext number
            return f"{etext_num}", None
        else:
            # Page is in the middle of an etext (or shared with previous)
            if prev_ends_on_this_page:
                # Previous row ends on this page - use milestone reference
                milestone_id = f"P{page_num}_B01"
                coord = f"{etext_num}#{milestone_id}"
                # Validate milestone exists
                if (volume_num, etext_num, milestone_id) not in milestones:
                    error = f"ERROR: Milestone '{milestone_id}' not found in volume {volume_num}, etext {etext_num} (row: {row_label})"
                    return coord, error
                return coord, None
            else:
                # Previous row doesn't end on this page - use bop
                return f"{etext_num}#bop:{page_num}", None
    else:
        # For end coordinate
        is_last_page_of_etext = (page_num == last_page)
        
        # Check if next row at same level starts on this page
        next_starts_on_this_page = (prev_or_next_page is not None and prev_or_next_page == page_num)
        
        if is_last_page_of_etext and not next_starts_on_this_page:
            # Just the etext number
            return f"{etext_num}", None
        else:
            # Page is in the middle of an etext (or shared with next)
            if next_starts_on_this_page:
                # Next row starts on this page - use milestone reference
                milestone_id = f"P{page_num}_B01"
                coord = f"{etext_num}#{milestone_id}"
                # Validate milestone exists
                if (volume_num, etext_num, milestone_id) not in milestones:
                    error = f"ERROR: Milestone '{milestone_id}' not found in volume {volume_num}, etext {etext_num} (row: {row_label})"
                    return coord, error
                return coord, None
            else:
                # Next row doesn't start on this page - use eop
                return f"{etext_num}#eop:{page_num}", None


def process_outline(input_csv, output_csv, tei_dir):
    """
    Process the outline CSV and convert image coordinates to etext coordinates.
    """
    print(f"Loading TEI page mappings from {tei_dir}...")
    page_to_etext, etext_pages, milestones = load_tei_page_mappings(tei_dir)
    print(f"Loaded mappings for {len(page_to_etext)} pages across {len(etext_pages)} etexts")
    print(f"Found {len(milestones)} milestones in TEI files")
    
    # Read all rows from input CSV
    print(f"Reading outline from {input_csv}...")
    rows = []
    with open(input_csv, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            rows.append(row)
    print(f"Read {len(rows)} rows")
    
    # Group rows by level to find previous/next at same level
    # For each row, we need to know:
    # - For start: what is the end page of the previous row at the same level (in same volume)?
    # - For end: what is the start page of the next row at the same level (in same volume)?
    
    # Build index of rows by level and volume
    # We process in order and track the previous row at each level per volume
    
    # First pass: collect all rows with their levels and page info
    row_info = []
    for i, row in enumerate(rows):
        level = get_level(row)
        img_start = row[14].strip() if len(row) > 14 else ""
        img_end = row[15].strip() if len(row) > 15 else ""
        vol_start = row[16].strip() if len(row) > 16 else ""
        vol_end = row[17].strip() if len(row) > 17 else ""
        
        row_info.append({
            'index': i,
            'level': level,
            'img_start': img_start,
            'img_end': img_end,
            'vol_start': vol_start,
            'vol_end': vol_end
        })
    
    # Second pass: for each row, find prev/next at same level in same volume
    # prev_at_level[level][volume] = index of most recent row at that level in that volume
    prev_at_level = defaultdict(dict)
    prev_end_page = {}  # Maps row index -> end page of previous row at same level
    
    for i, info in enumerate(row_info):
        level = info['level']
        vol_start = info['vol_start']
        
        if level > 0 and vol_start:
            try:
                vol_num = int(vol_start)
                # Check if there's a previous row at this level in this volume
                if vol_num in prev_at_level[level]:
                    prev_idx = prev_at_level[level][vol_num]
                    prev_info = row_info[prev_idx]
                    # Get the end page of the previous row
                    if prev_info['img_end'] and prev_info['vol_end']:
                        try:
                            prev_vol = int(prev_info['vol_end'])
                            if prev_vol == vol_num:
                                prev_end_page[i] = int(prev_info['img_end'])
                        except ValueError:
                            pass
                
                # Update the most recent row at this level in this volume
                prev_at_level[level][vol_num] = i
            except ValueError:
                pass
    
    # Third pass: find next row's start page at same level
    # Go through in reverse order
    next_at_level = defaultdict(dict)
    next_start_page = {}  # Maps row index -> start page of next row at same level
    
    for i in range(len(row_info) - 1, -1, -1):
        info = row_info[i]
        level = info['level']
        vol_end = info['vol_end']
        
        if level > 0 and vol_end:
            try:
                vol_num = int(vol_end)
                # Check if there's a next row at this level in this volume
                if vol_num in next_at_level[level]:
                    next_idx = next_at_level[level][vol_num]
                    next_info = row_info[next_idx]
                    # Get the start page of the next row
                    if next_info['img_start'] and next_info['vol_start']:
                        try:
                            next_vol = int(next_info['vol_start'])
                            if next_vol == vol_num:
                                next_start_page[i] = int(next_info['img_start'])
                        except ValueError:
                            pass
                
                # Update the most recent (going backwards = next) row at this level in this volume
                next_at_level[level][vol_num] = i
            except ValueError:
                pass
    
    # Fourth pass: convert coordinates and write output
    print(f"Converting coordinates and writing to {output_csv}...")
    output_rows = []
    milestone_errors = []
    page_not_found_errors = []
    
    for i, row in enumerate(rows):
        info = row_info[i]
        
        # Get label for error messages (column 7 is 'label')
        row_label = row[7] if len(row) > 7 else f"row {i+2}"
        
        # Copy all columns except img_start and img_end (indices 14, 15)
        new_row = row[:14]  # Columns 0-13 stay the same
        
        # Convert img_start to etext coordinate
        if info['img_start'] and info['vol_start']:
            try:
                vol_num = int(info['vol_start'])
                prev_page = prev_end_page.get(i)
                etext_start, error = convert_to_etext_coord(
                    vol_num, info['img_start'], is_start=True,
                    prev_or_next_page=prev_page,
                    page_to_etext=page_to_etext, etext_pages=etext_pages,
                    milestones=milestones, row_label=row_label,
                    tei_dir=tei_dir
                )
                new_row.append(etext_start)
                if error:
                    if "not found in volume" in error:
                        page_not_found_errors.append(error)
                    else:
                        milestone_errors.append(error)
            except ValueError:
                new_row.append(info['img_start'])
        else:
            new_row.append(info['img_start'])
        
        # Convert img_end to etext coordinate
        if info['img_end'] and info['vol_end']:
            try:
                vol_num = int(info['vol_end'])
                next_page = next_start_page.get(i)
                etext_end, error = convert_to_etext_coord(
                    vol_num, info['img_end'], is_start=False,
                    prev_or_next_page=next_page,
                    page_to_etext=page_to_etext, etext_pages=etext_pages,
                    milestones=milestones, row_label=row_label,
                    tei_dir=tei_dir
                )
                new_row.append(etext_end)
                if error:
                    if "not found in volume" in error:
                        page_not_found_errors.append(error)
                    else:
                        milestone_errors.append(error)
            except ValueError:
                new_row.append(info['img_end'])
        else:
            new_row.append(info['img_end'])
        
        # Add vol_start and vol_end (same as original)
        if len(row) > 16:
            new_row.append(row[16])
        if len(row) > 17:
            new_row.append(row[17])
        
        output_rows.append(new_row)
    
    # Report page not found errors
    if page_not_found_errors:
        print(f"\n{'='*60}")
        print(f"PAGE NOT FOUND ERRORS: {len(page_not_found_errors)}")
        print(f"{'='*60}")
        for error in page_not_found_errors:
            print(f"  {error}")
        print(f"{'='*60}\n")
    
    # Report milestone validation errors
    if milestone_errors:
        print(f"\n{'='*60}")
        print(f"MILESTONE VALIDATION ERRORS: {len(milestone_errors)}")
        print(f"{'='*60}")
        for error in milestone_errors:
            print(f"  {error}")
        print(f"{'='*60}\n")
    
    # Write output CSV
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        # Write header (same as input, but we could rename img columns if desired)
        writer.writerow(header)
        writer.writerows(output_rows)
    
    print(f"Done! Written {len(output_rows)} rows to {output_csv}")


def main():
    input_csv = 'O3KG218-W3KG218.csv'
    output_csv = 'DKCC/O3KG218-IE3KG218.csv'
    tei_dir = 'W3KG218-step3_tei'
    
    process_outline(input_csv, output_csv, tei_dir)


if __name__ == "__main__":
    main()

