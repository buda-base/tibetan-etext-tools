# IE3JT13367 - Batch RTF to TEI XML Converter

Convert Tibetan RTF documents into TEI XML format.

## Overview

This collection-specific converter processes RTF files from the IE3JT13367 collection, converting them to TEI XML format.

## Directory Structure

### Input Structure
```
{INPUT_DIR}/{IE_ID}/
├── toprocess/{IE_ID}-{VE_ID}/*.rtf
└── sources/*.doc (optional - original DOC files)
```

**Example:**
```
file_convert_2/
    └── IE3JT13367/
        ├── toprocess/
        │   └── IE3JT13367-VE3JT13367_001/
        │       ├── volume_001_001.rtf
        │       ├── volume_001_002.rtf
        │       └── volume_001_003.rtf
        └── sources/
            ├── volume_001_001.doc
            ├── volume_001_002.doc
            └── volume_001_003.doc
```

### Output Structure
```
{INPUT_DIR}/{IE_ID}/{IE_ID}_output/
├── archive/{VE_ID}/UT{suffix}_{index}.xml
└── sources/{VE_ID}/
    ├── *.rtf (converted RTF files)
    └── *.doc (original DOC files, if present in input)
```
## Text Cleaning

The converter includes comprehensive text cleaning functionality:

#### RTF Fallback Character Removal
- Removes ASCII fallback characters that RTF parsers insert before Tibetan Unicode
- Handles patterns like `a་`, `?་`, etc. where ASCII characters precede Tibetan text
- Cleans both line-initial and mid-text fallback characters

#### Page Marker Removal
Automatically removes page markers in various formats:
- Simple markers: `- PAGE 10 -`, `PAGE 11`, etc.
- Complex patterns with Tibetan/Devanagari characters
- Specific unwanted patterns:
  - `གྲཨཀྱཎགླཁ`
  - `དྷཱི།ཁདྷཱི།`
  - `དྷཱི།`
  - `页：` (Chinese page marker)
  - `PAGE«¿¿»`
- Case-insensitive matching
- Prevents consecutive `<lb/>` tags after removal

#### Unicode Normalization
- All Tibetan text is normalized using the `normalization.py` module
- Ensures consistent Unicode representation across all output files
- Applies NFC normalization
- Handles Tibetan-specific Unicode reordering
- Normalizes spaces and line breaks
- Removes zero-width characters and BOMs

## Font Size Classification

The converter automatically classifies font sizes based on Tibetan character frequency:
- **Regular**: Most common font size (no markup) - determined by counting Tibetan characters
- **Large**: Larger than regular (wrapped in `<hi rend="head">`)
- **Small**: Smaller than regular (wrapped in `<hi rend="small">`)

The classification is dynamic and adapts to each file's font usage.

## Usage

### Basic Usage

Process all collections in the default input directory:
```bash
python convert.py
```

### Process Specific Collection

Process only the IE3JT13367 collection:
```bash
python convert.py --ie-id IE3JT13367
```

### Custom Input Directory

Specify a different input directory:
```bash
python convert.py --input-dir /path/to/collections
```

### Adjust Worker Count

Control the number of parallel workers:
```bash
python convert.py --workers 4
```

### Command-Line Options

- `--input-dir PATH` - Input directory containing IE collections (default: `/Users/tenzinmonlam/Documents/dharmaduta/file_convert_2`)
- `--ie-id IE_ID` - Process only this specific IE collection
- `--workers N` - Number of parallel workers (default: CPU count - 1)

### UT ID Generation

UT IDs are generated from VE IDs and file indices:
- `VE3JT13367_001`, index 0 → `UT3JT13367_001_0001`
- `VE3JT13367_001`, index 1 → `UT3JT13367_001_0002`
- Format: `UT{ve_suffix}_{index:04d}`

## Requirements

- Python 3.6+
- `natsort` package (optional, falls back to basic sorting if not available)

Install dependencies:
```bash
pip install natsort
```