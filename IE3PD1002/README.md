# IE3PD1002 PDF to TEI Converter

This script converts PDF files from IE3PD1002 to TEI XML format.

## Overview

The converter implements a 4-step pipeline:

1. **PDF Extraction** - Extract text from PDFs using py-tiblegenc with font size tracking
2. **Normalization** - Simplify font size markup and apply Unicode normalization
3. **Font Classification** - Auto-classify font sizes as regular/small/large (yigchung)
4. **TEI Generation** - Generate TEI XML with proper structure

## Input Structure

```
IE3PD1002_INPUT/
  sources/
    Copy of v1.pdf
    Copy of v2.pdf
    ...
    Copy of v25.pdf
  toprocess/
    IE3PD1002-VE1ER464/
    IE3PD1002-VE1ER465/
    ...
    IE3PD1002-VE1ER488/
```

- **sources/**: Contains the source PDF files (25 volumes)
- **toprocess/**: Contains empty VE ID folders that define the volume-to-VE mapping

## Output Structure

```
IE3PD1002/
  archive/
    VE1ER464/
      UT1ER464_0001.xml
    VE1ER465/
      UT1ER465_0001.xml
    ...
  sources/
    Copy of v1.pdf
    Copy of v2.pdf
    ...
  IE3PD1002.csv
```

- **archive/**: TEI XML files organized by VE ID
- **sources/**: Copies of the source PDF files
- **IE3PD1002.csv**: Outline CSV with volume metadata

## Usage

```bash
python convert_pdf.py <input_folder> <output_folder>
```

### Example

```bash
python convert_pdf.py /path/to/IE3PD1002_INPUT /path/to/IE3PD1002_OUTPUT
```

## Requirements

- Python 3.8+
- py-tiblegenc (for PDF extraction)
- natsort (for natural sorting)

### Installation

```bash
pip install git+https://github.com/buda-base/py-tiblegenc.git
pip install natsort
```

## Font Size Classification

The converter automatically classifies font sizes based on frequency analysis:

| Classification | Description | TEI Markup |
|---------------|-------------|------------|
| regular | Main body text (most common size) | (none) |
| small | Yigchung, footnotes, annotations | `<hi rend="small">` |
| large | Titles, headings | `<hi rend="head">` |

## TEI Output Format

The generated XML follows the TEI "Paginated Shape" minimal spec:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
  ...
</teiHeader>
<text>
<body xml:lang="bo">
<p xml:space="preserve">
<pb n="1"/>
<lb/>༄༅། །text content...
<pb n="2"/>
<lb/>...more content...
</p>
</body>
</text>
</TEI>
```

### Key Features

- `xml:space="preserve"` for exact whitespace preservation
- `<pb n="X"/>` for page breaks
- `<lb/>` for line breaks
- `<hi rend="small">` for yigchung text
- `<hi rend="head">` for title text

## Volume Mapping

The VE IDs are extracted from the `toprocess/` folder structure and matched to PDF files via natural sorting:

| Volume | PDF File | VE ID |
|--------|----------|-------|
| 1 | Copy of v1.pdf | VE1ER464 |
| 2 | Copy of v2.pdf | VE1ER465 |
| ... | ... | ... |
| 25 | Copy of v25.pdf | VE1ER488 |

## Notes

- Unicode normalization follows BDRC standards (NFC + Tibetan-specific rules)
- Font sizes are simplified to remove layout noise before classification
- Natural sorting ensures "Copy of v2.pdf" comes before "Copy of v10.pdf"


