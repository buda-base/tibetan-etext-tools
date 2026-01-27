# RTF to TEI XML Converter

Python script to convert Tibetan RTF documents into TEI XML format.

## Directory Structure
### Input Path: 
```
{IE_ID}/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf
```
### Output Structure:

**Archive (flat structure with UT IDs):**
```
{IE_ID}_output/archive/{VE_ID}/UT{suffix}_{index}.xml
```

**Sources (preserves nested structure):**
```
{IE_ID}_output/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf
```

**Note:** 
- Archive uses sequential UT IDs (e.g., `UT1KG1795_001_0001.xml`, `UT1KG1795_001_0002.xml`)
- Sources preserves the original directory structure and RTF files

### Supported Input Structures

#### Nested Structure (New):

```
IE1PD105893/
└── sources/
    └── VE1PD105893/
        └── collection_name/
            └── rtfs/
                └── volume_001/
                    ├── 01.rtf
                    └── 02.rtf
```

#### Direct Structure:
```
IE1PD105893/
└── sources/
    └── VE1PD105893/
        ├── 01.rtf
        └── 02.rtf
```
#### Legacy Structure:
```
IE1PD105893/
└── toprocess/
    └── IE1PD105893-VE1PD105893/
        ├── 01.rtf
        └── ...
```

### Output Structure
```
IE1PD105893_output/
├── archive/
│   └── VE1PD105893/
│       ├── UT1PD105893_0001.xml
│       ├── UT1PD105893_0002.xml
│       └── UT1PD105893_0003.xml
└── sources/
    └── VE1PD105893/
        └── [collection_name]/
            └── rtfs/
                └── volume_001/
                    ├── volume_001_001.rtf
                    ├── volume_001_002.rtf
                    └── volume_001_003.rtf
```

## Features

### Text Cleaning (`text_cleaning.py`)

The converter includes text cleaning functionality that removes:

1. **PAGE MERGEFORMAT strings** - RTF metadata noise
2. **PAGE number patterns** - Patterns like `-PAGE 522-`, `PAGE 521`, etc.
3. **Dash-number-dash patterns** - Patterns like `-1-`, `-2-`, `-123-`


The cleaning process also:
- Filters out text streams that become empty after cleaning
- Prevents empty markup tags in the output
- Maintains proper text flow without introducing extra whitespace
   

### Font Size Classification

The converter automatically classifies font sizes based on Tibetan character frequency:
- **Regular**: Most common font size (no markup)
- **Large**: Larger than regular (wrapped in `<hi rend="head">`)
- **Small**: Smaller than regular (wrapped in `<hi rend="small">`)

### Unicode Normalization

All Tibetan text is normalized using the `normalization.py` module to ensure consistent Unicode representation.

## Usage

### Process All Collections:
```bash
python convert.py
```

### Process a Specific Collection:
```bash
python convert.py --ie-id IE1PD105893
```

## Technical Details

### ID Generation

**UT ID Format:** `UT{VE_suffix}_{sequential_index}`

Examples:
- `VE1KG1795_001` → `UT1KG1795_001_0001`, `UT1KG1795_001_0002`, etc.
- `VE3KG253` → `UT3KG253_0001`, `UT3KG253_0002`, etc.

**Sequential Numbering:**
- Index starts at 0001 for each VE collection
- Continues sequentially across all volumes
- Ensures unique identifiers for each text unit

## Modules

- `convert.py` - Main conversion script with multiprocessing support
- `basic_rtf.py` - RTF parser
- `normalization.py` - Unicode normalization for Tibetan text
- `text_cleaning.py` - Text cleaning and noise removal functions

   


