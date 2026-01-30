#!/usr/bin/env python3
"""
Count pages in TEI XML files across all IE folders in the rtf directory.

Rules:
- If XML has <pb> tags, count the number of <pb> tags as pages
- If no <pb> tags, count double newlines in body as page separators
- If no <pb> tags AND no double newlines, count as 1 page
- Ignores hidden files (starting with .)
- Sums pages for each IE folder

The script automatically finds the rtf directory relative to the script location.

Usage:
    python count_page.py [--rtf-dir RTF_DIR]
    
Example:
    python count_page.py
    python count_page.py --rtf-dir /path/to/rtf
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional, Tuple


def count_pb_tags(xml_path: Path) -> int:
    """
    Count page breaks in an XML file.
    
    Logic:
    1. If XML has <pb tags, count the number of <pb tags
    2. If no <pb tags, count double newlines in body as page separators
       (pages = number of double newlines + 1)
    3. If no <pb tags AND no double newlines, count as 1 page
    
    Returns:
        Number of pages found
    """
    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Count all <pb tags (with or without attributes)
        # Matches: <pb/>, <pb />, <pb n="1a"/>, etc.
        pb_count = len(re.findall(r'<pb\s*[^>]*/?\s*>', content))
        
        if pb_count > 0:
            return pb_count
        
        # No <pb tags found - try counting double newlines in body
        # Extract body content between <body> and </body>
        body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL)
        if body_match:
            body_content = body_match.group(1)
            # Count double newlines (page separators)
            double_newline_count = len(re.findall(r'\n\n', body_content))
            if double_newline_count > 0:
                # Pages = separators + 1
                return double_newline_count + 1
        
        # No <pb tags and no double newlines - count as 1 page
        return 1
    
    except Exception as e:
        print(f"  Warning: Error reading {xml_path}: {e}")
        return 0


def find_archive_folder(ie_folder: Path) -> Optional[Path]:
    """
    Find the archive folder within an IE folder.
    
    Structure can be:
    - IE_FOLDER/IE_FOLDER/archive/
    - IE_FOLDER/IE_FOLDER_output/archive/
    - IE_FOLDER/archive/
    """
    # Try nested structure first (IE_FOLDER/IE_FOLDER/archive/)
    nested_archive = ie_folder / ie_folder.name / 'archive'
    if nested_archive.exists():
        return nested_archive
    
    # Try nested output structure (IE_FOLDER/IE_FOLDER_output/archive/)
    nested_output_archive = ie_folder / f"{ie_folder.name}_output" / 'archive'
    if nested_output_archive.exists():
        return nested_output_archive
    
    # Try direct structure (IE_FOLDER/archive/)
    direct_archive = ie_folder / 'archive'
    if direct_archive.exists():
        return direct_archive
    
    return None


def count_pages_in_folder(archive_folder: Path) -> Tuple[int, int]:
    """
    Count total pages in all XML files in the archive folder.
    
    Returns:
        (total_pages, file_count)
    """
    total_pages = 0
    file_count = 0
    
    # Walk through all subdirectories
    for xml_file in archive_folder.rglob('*.xml'):
        # Skip hidden files
        if xml_file.name.startswith('.'):
            continue
        
        pages = count_pb_tags(xml_file)
        total_pages += pages
        file_count += 1
    
    return total_pages, file_count


def main():
    parser = argparse.ArgumentParser(
        description="Count pages in TEI XML files across all IE folders in the rtf directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python count_page.py
  python count_page.py --rtf-dir /path/to/rtf
        """
    )
    
    parser.add_argument(
        '--rtf-dir',
        type=Path,
        default=None,
        help='Path to the rtf directory (default: parent directory of this script)'
    )
    
    args = parser.parse_args()
    
    # Determine rtf directory
    if args.rtf_dir:
        rtf_dir = args.rtf_dir
    else:
        # Default: parent directory of this script
        script_dir = Path(__file__).parent
        rtf_dir = script_dir / "rtf"
    
    if not rtf_dir.exists():
        print(f"Error: RTF directory not found: {rtf_dir}", file=sys.stderr)
        sys.exit(1)
    
    print(f"Scanning: {rtf_dir}")
    print("=" * 70)
    
    results = []
    grand_total_pages = 0
    grand_total_files = 0
    
    # Find all IE folders (directories that start with 'IE')
    ie_folders = sorted([
        d for d in rtf_dir.iterdir()
        if d.is_dir() and d.name.startswith('IE') and not d.name.endswith('.zip')
    ])
    
    if not ie_folders:
        print(f"No IE folders found in {rtf_dir}")
        sys.exit(1)
    
    for ie_folder in ie_folders:
        archive_folder = find_archive_folder(ie_folder)
        
        if archive_folder is None:
            print(f"{ie_folder.name}: No archive folder found")
            continue
        
        pages, files = count_pages_in_folder(archive_folder)
        results.append((ie_folder.name, pages, files))
        grand_total_pages += pages
        grand_total_files += files
        
        print(f"{ie_folder.name}: {pages:,} pages ({files} XML files)")
    
    print("=" * 70)
    print(f"TOTAL: {grand_total_pages:,} pages across {grand_total_files:,} XML files in {len(results)} folders")


if __name__ == "__main__":
    main()

