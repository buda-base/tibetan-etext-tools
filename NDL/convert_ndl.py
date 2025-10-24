#!/usr/bin/env python3
"""Convert NDL txt files to TEI XML and generate CSV outlines."""

import os
import sys
import csv
import hashlib
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from normalization import normalize_unicode

def parse_txt_file(txt_path):
    """Parse txt file and extract metadata and content sections."""
    with open(txt_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    lines = content.split('\n')
    metadata = {}
    text_lines = []
    in_metadata = True
    
    for line in lines:
        if in_metadata:
            if line.startswith('#'):
                in_metadata = False
                text_lines.append(line)
            elif '=' in line:
                key, value = line.split('=', 1)
                metadata[key.strip()] = value.strip()
            else:
                text_lines.append(line)
        else:
            text_lines.append(line)
    
    return metadata, '\n'.join(text_lines)


def parse_divisions(text_content):
    """Parse text content into hierarchical divisions."""
    lines = text_content.split('\n')
    divisions = []
    current_div = None
    current_content = []
    
    for line in lines:
        if line.startswith('#div'):
            # Save previous division
            if current_div is not None:
                current_div['content'] = '\n'.join(current_content).strip()
                divisions.append(current_div)
            
            # Parse division header
            match = re.match(r'#div(\d+)\s+(.*)', line)
            if match:
                level = int(match.group(1))
                title = match.group(2).strip()
                current_div = {
                    'level': level,
                    'title': title,
                    'content': ''
                }
                current_content = []
        else:
            if line.strip():
                current_content.append(line)
    
    # Save last division
    if current_div is not None:
        current_div['content'] = '\n'.join(current_content).strip()
        divisions.append(current_div)
    
    return divisions


def calculate_sha256(file_path):
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for byte_block in iter(lambda: f.read(4096), b''):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def split_into_paragraphs(content):
    """Split content into paragraphs."""
    paragraphs = []
    current_para = []
    
    for line in content.split('\n'):
        line = line.strip()
        if line:
            current_para.append(line)
        elif current_para:
            paragraphs.append(' '.join(current_para))
            current_para = []
    
    if current_para:
        paragraphs.append(' '.join(current_para))
    
    return paragraphs


def create_xml(metadata, divisions, ve_lname, file_id, ie_lname, ut_lname, sha256_hash):
    """Create TEI XML structure."""
    # Create namespaces
    TEI_NS = "http://www.tei-c.org/ns/1.0"
    XML_NS = "http://www.w3.org/XML/1998/namespace"
    ET.register_namespace('', TEI_NS)
    ET.register_namespace('xml', XML_NS)
    
    # Create root element
    tei = ET.Element(f'{{{TEI_NS}}}TEI')
    
    # Create TEI Header
    header = ET.SubElement(tei, f'{{{TEI_NS}}}teiHeader')
    
    # File description
    file_desc = ET.SubElement(header, f'{{{TEI_NS}}}fileDesc')
    
    # Title statement
    title_stmt = ET.SubElement(file_desc, f'{{{TEI_NS}}}titleStmt')
    title = ET.SubElement(title_stmt, f'{{{TEI_NS}}}title')
    title.text = normalize_unicode(metadata.get('Title', ''))
    
    # Publication statement
    pub_stmt = ET.SubElement(file_desc, f'{{{TEI_NS}}}publicationStmt')
    pub_p = ET.SubElement(pub_stmt, f'{{{TEI_NS}}}p')
    pub_p.text = 'File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.'
    
    # Source description
    source_desc = ET.SubElement(file_desc, f'{{{TEI_NS}}}sourceDesc')
    bibl = ET.SubElement(source_desc, f'{{{TEI_NS}}}bibl')
    
    idno_path = ET.SubElement(bibl, f'{{{TEI_NS}}}idno', type='src_path')
    idno_path.text = f'{ve_lname}/{file_id}.txt'
    
    idno_sha = ET.SubElement(bibl, f'{{{TEI_NS}}}idno', type='src_sha256')
    idno_sha.text = sha256_hash
    
    idno_ie = ET.SubElement(bibl, f'{{{TEI_NS}}}idno', type='bdrc_ie')
    idno_ie.text = f'http://purl.bdrc.io/resource/{ie_lname}'
    
    idno_ve = ET.SubElement(bibl, f'{{{TEI_NS}}}idno', type='bdrc_ve')
    idno_ve.text = f'http://purl.bdrc.io/resource/{ve_lname}'
    
    idno_ut = ET.SubElement(bibl, f'{{{TEI_NS}}}idno', type='bdrc_ut')
    idno_ut.text = f'http://purl.bdrc.io/resource/{ut_lname}'
    
    # Encoding description
    encoding_desc = ET.SubElement(header, f'{{{TEI_NS}}}encodingDesc')
    enc_p = ET.SubElement(encoding_desc, f'{{{TEI_NS}}}p')
    enc_p.text = 'The TEI header does not contain any bibliographical data. It is instead accessible through the '
    ref = ET.SubElement(enc_p, f'{{{TEI_NS}}}ref', target=f'http://purl.bdrc.io/resource/{ie_lname}')
    ref.text = 'record in the BDRC database'
    ref.tail = '.'
    
    # Create text body
    text = ET.SubElement(tei, f'{{{TEI_NS}}}text')
    body = ET.SubElement(text, f'{{{TEI_NS}}}body')
    body.set(f'{{{XML_NS}}}lang', 'bo')
    
    # Add divisions with global counter
    global_counter = 0
    current_div1 = None
    current_div2 = None
    
    for div_data in divisions:
        level = div_data['level']
        title_text = normalize_unicode(div_data['title'])
        content = normalize_unicode(div_data['content'])
        
        # Increment global counter
        global_counter += 1
        div_id = f"div{level}_{global_counter:04d}"
        
        if level == 1:
            # Create milestone and div for level 1
            milestone = ET.SubElement(body, f'{{{TEI_NS}}}milestone')
            milestone.set(f'{{{XML_NS}}}id', div_id)
            milestone.set('unit', "section")
            current_div1 = ET.SubElement(body, f'{{{TEI_NS}}}div')
            
            # Add head
            head = ET.SubElement(current_div1, f'{{{TEI_NS}}}head')
            head.text = title_text
            
            # Add paragraphs
            paragraphs = split_into_paragraphs(content)
            for para_text in paragraphs:
                p = ET.SubElement(current_div1, f'{{{TEI_NS}}}p')
                p.text = para_text
            
            current_div2 = None
            
        elif level == 2:
            # Create milestone and div for level 2
            if current_div1 is not None:
                milestone = ET.SubElement(current_div1, f'{{{TEI_NS}}}milestone')
                milestone.set(f'{{{XML_NS}}}id', div_id)
                milestone.set('unit', "section")
                current_div2 = ET.SubElement(current_div1, f'{{{TEI_NS}}}div')
                
                # Add head
                head = ET.SubElement(current_div2, f'{{{TEI_NS}}}head')
                head.text = title_text
                
                # Add paragraphs
                paragraphs = split_into_paragraphs(content)
                for para_text in paragraphs:
                    p = ET.SubElement(current_div2, f'{{{TEI_NS}}}p')
                    p.text = para_text
        
        elif level >= 3:
            # Add deeper levels inside current div2 or div1
            parent = current_div2 if current_div2 is not None else current_div1
            if parent is not None:
                milestone = ET.SubElement(parent, f'{{{TEI_NS}}}milestone')
                milestone.set(f'{{{XML_NS}}}id', div_id)
                milestone.set('unit', "section")
                sub_div = ET.SubElement(parent, f'{{{TEI_NS}}}div')
                
                # Add head
                head = ET.SubElement(sub_div, f'{{{TEI_NS}}}head')
                head.text = title_text
                
                # Add paragraphs
                paragraphs = split_into_paragraphs(content)
                for para_text in paragraphs:
                    p = ET.SubElement(sub_div, f'{{{TEI_NS}}}p')
                    p.text = para_text
    
    return tei


def format_xml(element):
    """Format XML with proper indentation."""
    from xml.dom import minidom
    rough_string = ET.tostring(element, encoding='utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding='UTF-8')


def collect_divisions_for_csv(divisions, volume_number):
    """Collect division information for CSV output."""
    csv_rows = []
    global_counter = 0
    
    for i, div_data in enumerate(divisions):
        level = div_data['level']
        title_text = normalize_unicode(div_data['title'])
        
        # Increment global counter for all divisions
        global_counter += 1
        div_id = f"div{level}_{global_counter:04d}"
        
        if level > 2:
            continue
        
        # Determine end milestone
        end_id = ""
        if level == 1:
            # Find next div1
            next_global_counter = global_counter
            for j in range(i + 1, len(divisions)):
                next_global_counter += 1
                if divisions[j]['level'] == 1:
                    end_id = f"1#div{divisions[j]['level']}_{next_global_counter:04d}"
                    break
        
        csv_rows.append({
            'level': level,
            'title': title_text,
            'start_id': f"1#{div_id}",
            'end_id': end_id,
            'volume': volume_number
        })
    
    return csv_rows


def generate_csv(ie_data, output_path):
    """Generate CSV outline file."""
    # Determine if multi-volume
    multi_volume = len(ie_data) > 1
    
    with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        
        # Write header
        header = ['RID', 'Position', 'Position', 'Position', 'Position', 'part type', 
                  'label', 'titles', 'work', 'notes', 'colophon', 'authorshipStatement', 
                  'identifiers', 'etext start', 'etext end', 'img grp start', 'img grp end']
        writer.writerow(header)
        
        # Process each volume
        for vol_num, (ve_lname, csv_rows) in enumerate(sorted(ie_data.items()), start=1):
            if multi_volume:
                # Write volume row
                vol_row = ['', 'X'] + [''] * 3 + ['V', f'Volume {vol_num}'] + [''] * 6 + ['', '', str(vol_num), str(vol_num)]
                writer.writerow(vol_row)
            
            # Write texts and chapters
            for row_data in csv_rows:
                level = row_data['level']
                title = row_data['title']
                start_id = row_data['start_id']
                end_id = row_data['end_id']
                volume = row_data['volume']
                
                if level == 1:
                    # Text row
                    if multi_volume:
                        pos_cols = ['', 'X', '', '']
                    else:
                        pos_cols = ['X', '', '', '']
                    row = [''] + pos_cols + ['T', title] + [''] * 6 + [start_id, end_id, str(volume), str(volume)]
                    writer.writerow(row)
                
                elif level == 2:
                    # Chapter row
                    if multi_volume:
                        pos_cols = ['', '', 'X', '']
                    else:
                        pos_cols = ['', 'X', '', '']
                    row = [''] + pos_cols + ['C', title] + [''] * 6 + [start_id, end_id, str(volume), str(volume)]
                    writer.writerow(row)


def process_ie_folder(input_folder, output_folder, ie_lname):
    """Process a single IE folder."""
    ie_input_path = Path(input_folder) / ie_lname / 'toprocess'
    if not ie_input_path.exists():
        print(f"Input path does not exist: {ie_input_path}")
        return
    
    # Find all VE folders
    ve_folders = [d for d in ie_input_path.iterdir() if d.is_dir() and d.name.startswith(f"{ie_lname}-")]
    
    if not ve_folders:
        print(f"No VE folders found in {ie_input_path}")
        return
    
    # Create output directories
    ie_output_path = Path(output_folder) / ie_lname
    sources_path = ie_output_path / 'sources'
    archive_path = ie_output_path / 'archive'
    sources_path.mkdir(parents=True, exist_ok=True)
    archive_path.mkdir(parents=True, exist_ok=True)
    
    # Collect data for CSV
    ie_csv_data = {}
    
    for ve_folder in sorted(ve_folders):
        ve_lname = ve_folder.name.split('-')[-1]
        ut_lname = f"UT{ve_lname[2:]}_0001"
        
        # Find txt files
        txt_files = list(ve_folder.glob('*.txt'))
        if not txt_files:
            print(f"No txt files found in {ve_folder}")
            continue
        
        # Process first txt file (assuming one per VE folder)
        txt_file = txt_files[0]
        file_id = txt_file.stem
        
        # Parse txt file
        metadata, text_content = parse_txt_file(txt_file)
        divisions = parse_divisions(text_content)
        
        # Calculate SHA256
        sha256_hash = calculate_sha256(txt_file)
        
        # Create XML
        xml_tree = create_xml(metadata, divisions, ve_lname, file_id, ie_lname, ut_lname, sha256_hash)
        
        # Create output directories for this VE
        ve_sources_path = sources_path / ve_lname
        ve_archive_path = archive_path / ve_lname
        ve_sources_path.mkdir(parents=True, exist_ok=True)
        ve_archive_path.mkdir(parents=True, exist_ok=True)
        
        # Copy txt file to sources
        import shutil
        shutil.copy(txt_file, ve_sources_path / f"{file_id}.txt")
        
        # Write XML to archive
        xml_output_path = ve_archive_path / f"{ut_lname}.xml"
        xml_bytes = format_xml(xml_tree)
        with open(xml_output_path, 'wb') as f:
            f.write(xml_bytes)
        
        # Collect CSV data (assume volume number based on sorted order)
        volume_number = len(ie_csv_data) + 1
        csv_rows = collect_divisions_for_csv(divisions, volume_number)
        ie_csv_data[ve_lname] = csv_rows
        
        print(f"Processed {ve_lname}: {file_id}.txt -> {ut_lname}.xml")
    
    # Generate CSV
    if ie_csv_data:
        csv_output_path = Path(output_folder) / f"{ie_lname}.csv"
        generate_csv(ie_csv_data, csv_output_path)
        print(f"Generated CSV: {csv_output_path}")


def main():
    """Main entry point."""
    if len(sys.argv) < 3:
        print("Usage: convert_ndl.py <input_folder> <output_folder>")
        print("Example: convert_ndl.py ./input ./output")
        sys.exit(1)
    
    input_folder = sys.argv[1]
    output_folder = sys.argv[2]
    
    if not os.path.exists(input_folder):
        print(f"Error: Input folder does not exist: {input_folder}")
        sys.exit(1)
    
    # Iterate through all subfolders of input_folder
    for subfolder in sorted(os.listdir(input_folder)):
        subfolder_path = os.path.join(input_folder, subfolder)
        if os.path.isdir(subfolder_path):
            ie_lname = subfolder
            print(f"Processing IE folder: {ie_lname}")
            process_ie_folder(input_folder, output_folder, ie_lname)
            print(f"Conversion complete for {ie_lname}")
    
    print("All conversions complete.")


if __name__ == '__main__':
    main()
