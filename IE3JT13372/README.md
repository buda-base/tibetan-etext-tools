# IE3JT13372 - Batch RTF to TEI XML Converter

Convert Tibetan RTF documents into TEI XML format.

## Overview

This collection-specific converter processes RTF files from the IE3JT13372 collection, converting them to TEI XML format.

## Directory Structure

### Input Structure
```
{INPUT_DIR}/{IE_ID}/{IE_ID}/toprocess/{IE_ID}-{VE_ID}/*.rtf
```

**Example:**
```
file_convert_2/
    └── IE3JT13372/
        └── toprocess/
            └── IE3JT13372-VE3JT13372_001/
                ├── volume_001.rtf
                ├── volume_002.rtf
                └── ...
```

### Output Structure
```
{INPUT_DIR}/{IE_ID}/{IE_ID}_output/
├── archive/{VE_ID}/UT{suffix}_{index}.xml
└── sources/{VE_ID}/*.rtf
```

**Example:**
```
file_convert_2/
└── IE3JT13372/
    └── IE3JT13372_output/
        ├── archive/
        │   └── VE3JT13372_001/
        │       ├── UT3JT13372_001_0001.xml
        │       ├── UT3JT13372_001_0002.xml
        │       └── ...
        └── sources/
            └── VE3JT13372_001/
                ├── volume_001.rtf
                ├── volume_002.rtf
                └── ...
```

## Features

### 1. Multiprocessing Support

- Processes multiple volumes in parallel for faster conversion
- Configurable worker count (default: CPU count - 1)
- Progress tracking with detailed logging
- Each volume is processed independently by a separate worker

### 2. Text Cleaning

The converter includes comprehensive text cleaning functionality:

#### RTF Fallback Character Removal
- Removes ASCII fallback characters that RTF parsers insert before Tibetan Unicode
- Handles patterns like `a་`, `?་`, etc. where ASCII characters precede Tibetan text
- Cleans both line-initial and mid-text fallback characters

#### Page Marker Removal
Automatically removes page markers in various formats:
- `- PAGE 10 -`
- `-- PAGE 11 --`
- `-PAGE 123-`
- `PAGE 11` (without dashes)
- Case-insensitive matching

#### Unicode Normalization
- All Tibetan text is normalized using the `normalization.py` module
- Ensures consistent Unicode representation across all output files
- Applies NFC normalization
- Handles Tibetan-specific Unicode reordering
- Normalizes spaces and line breaks
- Removes zero-width characters and BOMs

### 3. Font Size Classification

The converter automatically classifies font sizes based on Tibetan character frequency:
- **Regular**: Most common font size (no markup) - determined by counting Tibetan characters
- **Large**: Larger than regular (wrapped in `<hi rend="head">`)
- **Small**: Smaller than regular (wrapped in `<hi rend="small">`)

The classification is dynamic and adapts to each file's font usage.

### 4. TEI XML Structure

Each output file includes:
- Complete TEI header with metadata
- Source file SHA256 hash for verification
- BDRC resource identifiers (IE, VE, UT)
- Proper XML escaping and line breaks (`<lb/>` tags)
- Language declaration (`xml:lang="bo"` for Tibetan)

## Usage

### Basic Usage

Process all collections in the default input directory:
```bash
python convert.py
```

### Process Specific Collection

Process only the IE3JT13372 collection:
```bash
python convert.py --ie-id IE3JT13372
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
- `VE3JT13372_001`, index 0 → `UT3JT13372_001_0001`
- `VE3JT13372_001`, index 1 → `UT3JT13372_001_0002`
- Format: `UT{ve_suffix}_{index:04d}`

## Requirements

- Python 3.6+
- `natsort` package (optional, falls back to basic sorting if not available)

Install dependencies:
```bash
pip install natsort
```
