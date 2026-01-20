#!/usr/bin/env python3
"""
Script to clean unwanted characters from XML files.
Removes patterns like «£¨38£©, «£¨3»9£©, etc., keeping only «
Also removes sequences of dots.
"""

import re
import os
from pathlib import Path
from typing import List

# Default input directory containing all IE collections
INPUT_DIR = Path(__file__).parent.parent / "rtf"


def clean_xml_content(content: str) -> str:
    """
    Clean unwanted characters from XML content.
    
    Removes:
    - Sequences of dots (..............)
    - Patterns like «£¨38£©, «£¨3»9£©, etc., replacing them with just «
    """
    # Remove sequences of dots (2 or more consecutive dots)
    content = re.sub(r'\.{2,}', '', content)
    
    # First, handle patterns that have a trailing « after £©
    # This handles: «£¨38£©«, «£¨51£©«, etc. -> «
    content = re.sub(r'«£¨[^«]*?£©«', '«', content)
    
    # Handle patterns with trailing » after £©
    # This handles: «£¨93£©», etc. -> «
    content = re.sub(r'«£¨[^«]*?£©»', '«', content)
    
    # Replace patterns like «£¨...£© with just «
    # This handles: «£¨38£©, «£¨51£©, etc.
    # The pattern matches «£¨ followed by any characters (non-greedy) until £©
    content = re.sub(r'«£¨[^«]*?£©', '«', content)
    
    # Replace patterns like «£¨...»...£© with just «
    # This handles: «£¨3»9£©, etc.
    content = re.sub(r'«£¨[^«]*?»[^«]*?£©', '«', content)
    
    # Handle edge cases where there might be «£¨...« (without closing £©)
    # This handles: «£¨65« -> « (replace the whole pattern including the trailing « with just one «)
    content = re.sub(r'«£¨[^«]*?«', '«', content)
    
    # Clean up any remaining standalone £ characters that are part of these patterns
    # Remove any remaining £¨ or £© that might be left over
    content = re.sub(r'£¨', '', content)
    content = re.sub(r'£©', '', content)
    
    # Clean up «» patterns (where » immediately follows «) - these are leftovers from cleaning
    # Replace «» with just «
    content = re.sub(r'«»', '«', content)
    
    # Clean up any double «« that might have been created
    # Replace multiple consecutive « with just one «
    content = re.sub(r'«+', '«', content)
    
    return content


def process_xml_file(file_path: Path, dry_run: bool = False) -> bool:
    """
    Process a single XML file.
    
    Args:
        file_path: Path to the XML file
        dry_run: If True, only show what would be changed without modifying files
    
    Returns:
        True if changes were made (or would be made in dry_run mode)
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            original_content = f.read()
        
        cleaned_content = clean_xml_content(original_content)
        
        if original_content != cleaned_content:
            if not dry_run:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(cleaned_content)
                print(f"✓ Cleaned: {file_path}")
            else:
                print(f"Would clean: {file_path}")
            return True
        else:
            print(f"  No changes needed: {file_path}")
            return False
    except Exception as e:
        print(f"✗ Error processing {file_path}: {e}")
        return False


def find_file_in_directory(directory: Path, filename: str, recursive: bool = True) -> Path:
    """
    Find a file by name within a directory.
    
    Args:
        directory: Directory to search in
        filename: Name of the file to find
        recursive: If True, search subdirectories recursively
    
    Returns:
        Path to the found file, or None if not found
    """
    if recursive:
        matches = list(directory.rglob(filename))
    else:
        matches = list(directory.glob(filename))
    
    if not matches:
        return None
    if len(matches) > 1:
        print(f"Warning: Multiple files named '{filename}' found:")
        for match in matches:
            print(f"  - {match}")
        print(f"Using: {matches[0]}")
    return matches[0]


def process_directory(directory: Path, dry_run: bool = False, recursive: bool = True):
    """
    Process all XML files in a directory.
    
    Args:
        directory: Directory to process
        dry_run: If True, only show what would be changed
        recursive: If True, process subdirectories recursively
    """
    if not directory.exists():
        print(f"Error: Directory {directory} does not exist")
        return
    
    xml_files = list(directory.rglob('*.xml')) if recursive else list(directory.glob('*.xml'))
    
    if not xml_files:
        print(f"No XML files found in {directory}")
        return
    
    print(f"Found {len(xml_files)} XML file(s)")
    print(f"Mode: {'DRY RUN (no changes will be made)' if dry_run else 'LIVE (files will be modified)'}")
    print("-" * 60)
    
    changed_count = 0
    for xml_file in xml_files:
        if process_xml_file(xml_file, dry_run=dry_run):
            changed_count += 1
    
    print("-" * 60)
    print(f"Summary: {changed_count} file(s) {'would be' if dry_run else ''} modified out of {len(xml_files)} total")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Clean unwanted characters from XML files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Clean all XML files for a specific IE collection (dry run)
  python clean_xml.py --ie-id IE1KG1802 --dry-run
  
  # Clean all XML files for a specific IE collection
  python clean_xml.py --ie-id IE1KG1802
  
  # Clean a specific file by name within an IE collection
  python clean_xml.py --ie-id IE1KG1802 --file UT1KG1802_001_0005.xml
  
  # Clean a specific file using full path
  python clean_xml.py --file rtf/IE1KG1802/IE1KG1802_output/archive/VE1KG1802_001/UT1KG1802_001_0005.xml
  
  # Clean all files in a custom directory
  python clean_xml.py --directory rtf/IE1KG1802/IE1KG1802_output/archive
        """
    )
    
    parser.add_argument(
        '--ie-id',
        type=str,
        default=None,
        help='Process all XML files for this specific IE collection'
    )
    
    parser.add_argument(
        '--directory', '-d',
        type=str,
        help='Directory containing XML files to process'
    )
    
    parser.add_argument(
        '--file', '-f',
        type=str,
        help='Single XML file to process'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without modifying files'
    )
    
    parser.add_argument(
        '--no-recursive',
        action='store_true',
        help='Do not process subdirectories recursively'
    )
    
    args = parser.parse_args()
    
    # Handle file processing
    if args.file:
        file_path = Path(args.file)
        
        # If --ie-id is also specified, search for the file within that IE collection
        if args.ie_id:
            archive_dir = INPUT_DIR / args.ie_id / f"{args.ie_id}_output" / "archive"
            if not archive_dir.exists():
                print(f"Error: Archive directory {archive_dir} does not exist")
                exit(1)
            
            # Search for the file by name in the archive directory
            found_file = find_file_in_directory(archive_dir, file_path.name, recursive=True)
            if found_file:
                file_path = found_file
                print(f"Found file: {file_path}")
            else:
                print(f"Error: File '{file_path.name}' not found in {archive_dir}")
                exit(1)
        else:
            # Use the provided path as-is
            if not file_path.exists():
                print(f"Error: File {file_path} does not exist")
                exit(1)
        
        process_xml_file(file_path, dry_run=args.dry_run)
    
    # Handle directory processing
    elif args.ie_id:
        # Construct path from ie-id: rtf/{IE_ID}/{IE_ID}_output/archive
        archive_dir = INPUT_DIR / args.ie_id / f"{args.ie_id}_output" / "archive"
        if not archive_dir.exists():
            print(f"Error: Archive directory {archive_dir} does not exist")
            exit(1)
        process_directory(archive_dir, dry_run=args.dry_run, recursive=not args.no_recursive)
    
    elif args.directory:
        directory = Path(args.directory)
        process_directory(directory, dry_run=args.dry_run, recursive=not args.no_recursive)
    
    else:
        parser.print_help()
        print("\nError: You must specify either --ie-id, --directory, or --file")
        exit(1)

