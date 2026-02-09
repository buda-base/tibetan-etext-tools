#  RTF to TEI XML conversion for IE1PD45495

## Overview

This collection contains Tibetan texts in RTF format with Dedris legacy encoding.

## Directory Structure

```
IE1PD45495/
├── organizer.py          # Step 1: Organize source RTF/DOC files
├── convert.py            # Step 2: Convert RTF to TEI XML
├── basic_rtf.py          # RTF parser
├── normalization.py      # Unicode normalization
└── tibetan_text_fixes.py # Tibetan-specific text fixes
```

## Workflow

### Step 1: Organize Source Files

First, run `organizer.py` to organize your source RTF files into the proper structure:

This script:
- Reads RTF and DOC files from `/Users/tenzinmonlam/Documents/dharmaduta/file_convert_1/taranatha-gsung-qbum/sources`
- Organizes them by volume into the structure expected by `convert.py`
- Creates folders: `VE1PD45495_001`, `VE1PD45495_002`, etc.
- Each volume folder contains: `taranatha-gsung-qbum/volume_NNN/` (with both .rtf and .doc files)

**Configuration:**
Edit the `source_base` path in `organizer.py` if your source files are in a different location.

### Step 2: Convert to TEI XML

After organizing the files, run the conversion:

```bash
# Convert all volumes (uses multiprocessing)
python3 convert.py --all

# Convert all volumes with custom worker count
python3 convert.py --all --workers 4

# Convert a single volume (for testing)
python3 convert.py --single VE1PD45495_001

# Specify custom output directory
python3 convert.py --all --output /path/to/output
```

**Output Structure:**
```
IE1PD45495_output/
├── archive/                          # Flat structure with filenames matching RTF
│   ├── VE1PD45495_001/
│   │   ├── UT1PD45495_001_001.xml   # Matches volume_001_001.rtf
│   │   ├── UT1PD45495_001_002.xml   # Matches volume_001_002.rtf
│   │   └── ...
│   ├── VE1PD45495_029/
│   │   ├── UT1PD45495_029_266.xml   # Matches volume_029_266.rtf
│   │   └── ...
│   └── ...
├── sources/                          # Nested structure preserving original
│   ├── VE1PD45495_001/
│   │   └── taranatha-gsung-qbum/
│   │       └── volume_001/
│   │           ├── file1.rtf
│   │           ├── file1.doc
│   │           ├── file2.rtf
│   │           ├── file2.doc
│   │           └── ...
│   └── ...
└── conversion_stats.txt
```

## Updated changes

1. **Dedris to Unicode** (`pytiblegenc`)
   - Converts legacy Dedris encoding to Unicode
   - Handles multiple Dedris font variants
   - Tracks conversion statistics

2. **Watermark Removal** (Automatic)
   - Detects and removes watermark/copyright protection patterns
   - Identifies long text streams (>500 chars) with low unique character ratios (<10%)
   - Removes repetitive character sequences before XML processing
   - Logs removed watermark streams for verification

3. **Text Fixes** (`tibetan_text_fixes.py`)
   - Fixes flying vowels and subscripts
   - Corrects spacing around XML tags
   - Preserves paragraph boundaries
   - Merges consecutive identical `<hi>` tags
   - Removes duplicate `<lb/>` tags

## Configuration Options

Edit `convert.py` to adjust conversion behavior:

```python
# Enable/disable font size classification
ENABLE_FONT_CLASSIFICATION = True

# Enable/disable text normalization
ENABLE_NORMALIZATION = True

# Debug mode - test single volume
DEBUG_MODE = False
DEBUG_VOLUME = "VE1PD45495_001"
```

## Dependencies

```bash
pip install natsort
pip install -U git+https://github.com/buda-base/py-tiblegenc.git
```
