# RTF to TEI XML Converter

Python script to convert Tibetan RTF documents into TEI XML format.

## Directory Structure
### Input Path: 
```
{IE_ID}/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf
```
### Output Path:
For nested: 
```
{IE_ID}_output/archive/{VE_ID}/{collection_name}/xml/volume_{VOL_ID}/{filename}.xml
```
For direct: 
```
{IE_ID}_output/archive/{VE_ID}/{filename}.xml
```

**Note:** Output XML files now preserve the original RTF filename (e.g., `document.rtf` → `document.xml`)

### Supported Input Structures

#### Nested Structure (New):

```
IE2DB4577/
└── sources/
    └── VE2DB4576/
        └── collection_name/
            └── rtfs/
                └── volume_001/
                    ├── 01.rtf
                    └── 02.rtf
```

#### Direct Structure:
```
IE2DB4577/
└── sources/
    └── VE2DB4577/
        ├── 01.rtf
        └── 02.rtf
```
#### Legacy Structure:
```
IE2DB4577/
└── toprocess/
    └── IE2DB4577-VE2DB4577/
        ├── 01.rtf
        └── ...
```

### Output Structure
```
IE2DB4577_output/
├── archive/
│   └── VE2DB4577/
│       └── [collection_name]/
│           └── xml/
│               └── volume_001/
│                   ├── 01.xml
│                   └── 02.xml
└── sources/
    └── VE2DB4577/
        └── [collection_name]/
            └── rtfs/
                └── volume_001/
                    ├── 01.rtf
                    └── 02.rtf
```

## Features

### Text Cleaning (`text_cleaning.py`)

The converter includes comprehensive text cleaning functionality that removes:

1. **PAGE MERGEFORMAT strings** - RTF metadata noise
2. **PAGE number patterns** - Patterns like `-PAGE 522-`, `PAGE 521`, etc.
3. **Non-Tibetan characters**:
   - Guillemets: `«` `»`
   - Angle brackets: `<` `>`
   - Periods: `.`
   - Inverted exclamation: `¡`
   - Middle dot: `·`
   - Pilcrow: `¶`
   - Currency sign: `¤`
   - Diaeresis: `¨`
   - Dash: `-`
   

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
python convert.py --ie-id IE2DB4577
```

## Technical Details

### ID Generation

- VE ID: Extracted from the source folder name.

### Output File Naming

Output XML files preserve the original RTF filename:

- Input: `text_001.rtf` → Output: `text_001.xml`

## Modules

- `convert.py` - Main conversion script with multiprocessing support
- `basic_rtf.py` - RTF parser
- `normalization.py` - Unicode normalization for Tibetan text
- `text_cleaning.py` - Text cleaning and noise removal functions

   


