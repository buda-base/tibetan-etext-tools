"""Find all missing XML outputs by comparing source PDFs with archive outputs."""
from pathlib import Path
from natsort import natsorted
import re

BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1KG14")
SOURCES_DIR = BASE_DIR / "IE1KG14" / "sources"
ARCHIVE_DIR = BASE_DIR / "IE1KG14_OUTPUT" / "archive"
TOPROCESS_DIR = BASE_DIR / "IE1KG14" / "toprocess"

# Get VE IDs in correct order (same as convert_pdf.py)
ve_kg14 = []
ve_er = []
for folder in TOPROCESS_DIR.iterdir():
    if folder.is_dir() and folder.name.startswith('IE1KG14-'):
        ve_id = folder.name.replace('IE1KG14-', '')
        if ve_id.startswith('VE1KG14_'):
            ve_kg14.append(ve_id)
        elif ve_id.startswith('VE1ER'):
            ve_er.append(ve_id)
ve_ids = natsorted(ve_kg14) + natsorted(ve_er)

# Get source folders in numeric order
source_folders = []
for folder in SOURCES_DIR.iterdir():
    if folder.is_dir():
        match = re.match(r'^(\d+)', folder.name)
        if match:
            source_folders.append((int(match.group(1)), folder))
source_folders = sorted(source_folders, key=lambda x: x[0])

# Check each volume for missing files
print("Checking for missing XML output files...\n")
total_source = 0
total_output = 0
missing = []

for (idx, source_folder), ve_id in zip(source_folders, ve_ids):
    pdfs = natsorted([f for f in source_folder.glob('*.pdf')], key=lambda p: p.name)
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    
    archive_ve_dir = ARCHIVE_DIR / ve_id
    
    for file_idx, pdf in enumerate(pdfs):
        total_source += 1
        ut_id = f"UT{ve_suffix}_{file_idx + 1:04d}"
        xml_path = archive_ve_dir / f"{ut_id}.xml"
        
        if xml_path.exists():
            total_output += 1
        else:
            missing.append({
                'volume': ve_id,
                'volume_num': idx,
                'pdf': pdf.name,
                'ut_id': ut_id,
                'source_folder': source_folder.name
            })

# Also check for any PDFs in root sources folder (not processed)
root_pdfs = list(SOURCES_DIR.glob('*.pdf'))
if root_pdfs:
    print("PDFs in root sources folder (NOT PROCESSED - wrong location):")
    for pdf in root_pdfs:
        print(f"  - {pdf.name}")
    print()

# Print missing files
print(f"Source PDFs in numbered folders: {total_source}")
print(f"Output XML files: {total_output}")
print(f"Missing: {len(missing)}")
print()

if missing:
    print("FAILED CONVERSIONS (no XML output):")
    print("-" * 80)
    for m in missing:
        print(f"Vol {m['volume_num']:2d} ({m['volume']}) | {m['source_folder']}")
        print(f"       PDF: {m['pdf']}")
        print(f"       Expected: {m['ut_id']}.xml")
        print()







