#!/usr/bin/env python3
"""
Copy original .doc files to output sources folders.

This script copies .doc files from the original sources directory (sources/2_SALO/)
to the corresponding IE1KG4325_OUTPUT/sources/VE*/ folders, matching by filename
prefix (e.g., SALO001) with the RTF files already there.

Usage:
    python copy_doc_sources.py
"""

from pathlib import Path
import shutil

BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1KG4325")
ORIGINAL_SOURCES_DIR = BASE_DIR / "sources" / "2_SALO"
OUTPUT_SOURCES_DIR = BASE_DIR / "IE1KG4325_OUTPUT" / "sources"


def copy_doc_files():
    """Copy .doc files to output sources folders matching RTF files."""
    copied = 0
    not_found = 0
    
    print(f"Original sources: {ORIGINAL_SOURCES_DIR}")
    print(f"Output sources: {OUTPUT_SOURCES_DIR}")
    print()
    
    if not OUTPUT_SOURCES_DIR.exists():
        print(f"ERROR: Output sources directory does not exist: {OUTPUT_SOURCES_DIR}")
        print("Please run convert.py first to create the output structure.")
        return
    
    for ve_folder in sorted(OUTPUT_SOURCES_DIR.iterdir()):
        if not ve_folder.is_dir():
            continue
        
        ve_copied = 0
        ve_not_found = 0
        
        for rtf_file in sorted(ve_folder.glob("*.rtf")):
            prefix = rtf_file.stem.split('_')[0]
            matching_docs = list(ORIGINAL_SOURCES_DIR.glob(f"{prefix}_*.doc"))
            
            if matching_docs:
                doc_file = matching_docs[0]
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






