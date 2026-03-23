#!/usr/bin/env python3
"""
Copy original .doc files to output sources folders.

This script copies .doc files from the original sources directory (sources/27_GRAM/)
to the corresponding IE11249_OUTPUT/sources/VE*/ folders, matching by filename
prefix (e.g., GRAM001) with the RTF files already there.

This handles cases where filenames differ due to Windows truncation/encoding issues.

Usage:
    python copy_doc_sources.py
"""

from pathlib import Path
import shutil

BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE11249")
ORIGINAL_SOURCES_DIR = BASE_DIR / "sources" / "27_GRAM"
OUTPUT_SOURCES_DIR = BASE_DIR / "IE11249_OUTPUT" / "sources"


def copy_doc_files():
    """Copy .doc files to output sources folders matching RTF files."""
    copied = 0
    not_found = 0
    
    print(f"Original sources: {ORIGINAL_SOURCES_DIR}")
    print(f"Output sources: {OUTPUT_SOURCES_DIR}")
    print()
    
    # Iterate through all VE* folders in output sources
    for ve_folder in sorted(OUTPUT_SOURCES_DIR.iterdir()):
        if not ve_folder.is_dir():
            continue
        
        ve_copied = 0
        ve_not_found = 0
        
        # For each RTF file, find and copy matching .doc by prefix
        for rtf_file in sorted(ve_folder.glob("*.rtf")):
            # Extract prefix (e.g., "GRAM001" from "GRAM001_དཀར་ཆགས།.rtf")
            prefix = rtf_file.stem.split('_')[0]
            
            # Find .doc file matching the prefix
            matching_docs = list(ORIGINAL_SOURCES_DIR.glob(f"{prefix}_*.doc"))
            
            if matching_docs:
                doc_file = matching_docs[0]  # Take the first match
                dest = ve_folder / doc_file.name
                shutil.copy2(doc_file, dest)
                ve_copied += 1
            else:
                print(f"  Not found: {prefix}_*.doc (for {rtf_file.name})")
                ve_not_found += 1
        
        if ve_copied > 0 or ve_not_found > 0:
            print(f"{ve_folder.name}: copied {ve_copied}, not found {ve_not_found}")
        
        copied += ve_copied
        not_found += ve_not_found
    
    print()
    print(f"Total copied: {copied}")
    print(f"Total not found: {not_found}")


if __name__ == "__main__":
    copy_doc_files()

