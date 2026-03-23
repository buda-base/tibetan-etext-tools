# IE1KG14 (Terdzo Collection) PDF to TEI Converter

This script converts PDF files from IE1KG14 (Terdzo Collection) to TEI XML format.

## Overview

The converter implements a 4-step pipeline:

1. **PDF Extraction** - Extract text from PDFs using py-tiblegenc with font size tracking
2. **Normalization** - Simplify font size markup and apply Unicode normalization
3. **Font Classification** - Auto-classify font sizes as regular/small/large (yigchung)
4. **TEI Generation** - Generate TEI XML with proper structure

## Input Structure

The IE1KG14 collection has a nested folder structure where each volume is in a separate subfolder:

```
IE1KG14/
  sources/
    1-KA PDF/
      Terdzo-ka KARCHAK P.pdf
      Terdzo-ka P1.pdf
      Terdzo-ka P2.pdf
      ...
    2-KHA-PDF/
      ...
    3-GA PDF/
      ...
    ...
    71-YAA PDF/
      ...
  toprocess/
    IE1KG14-VE1ER489/
    IE1KG14-VE1ER490/
    ...
    IE1KG14-VE1KG14_001/
    ...
    IE1KG14-VE1KG14_054/
```

- **sources/**: Contains 71 subfolders (one per volume), each with multiple PDF files
- **toprocess/**: Contains 71 empty VE ID folders that define the volume-to-VE mapping

### Folder Naming

Source subfolders are named with a numeric prefix followed by Tibetan volume names:
- `1-KA PDF` (Volume 1, KA)
- `2-KHA-PDF` (Volume 2, KHA)
- `10-THA PDF` (Volume 10, THA)
- `61-DHOJO BUMSANG-(OM)PDF`
- etc.

## Output Structure

```
IE1KG14_OUTPUT/
  archive/
    VE1ER489/
      UT1ER489_0001.xml  # From Terdzo-ka KARCHAK P.pdf
      UT1ER489_0002.xml  # From Terdzo-ka P1.pdf
      UT1ER489_0003.xml  # From Terdzo-ka P2.pdf
      ...
    VE1ER490/
      UT1ER490_0001.xml
      ...
  sources/
    VE1ER489/
      Terdzo-ka KARCHAK P.pdf
      Terdzo-ka P1.pdf
      ...
```

- **archive/**: TEI XML files organized by VE ID, with multiple XML files per volume
- **sources/**: Copies of the source PDF files organized by VE ID

## Usage

### Default Paths

```bash
python convert_pdf.py
```

Uses the default paths defined in the script.

### Custom Paths

```bash
python convert_pdf.py <input_folder> <output_folder>
```

Where `<input_folder>` contains `sources/` and `toprocess/` subfolders.

## Requirements

- Python 3.8+
- py-tiblegenc (for PDF extraction)
- natsort (for natural sorting)

### Installation

```bash
pip install git+https://github.com/buda-base/py-tiblegenc.git
pip install natsort
```

## Volume Mapping

The script maps source subfolders to VE IDs by:

1. **Natural sort source subfolders** by their numeric prefix (1, 2, 3, ..., 71)
2. **Natural sort toprocess folders** by VE ID
3. **Match by index position**

| Index | Source Folder | VE ID |
|-------|---------------|-------|
| 1 | 1-KA PDF | VE1KG14_001 |
| 2 | 2-KHA-PDF | VE1KG14_002 |
| 3 | 3-GA PDF | VE1KG14_003 |
| ... | ... | ... |
| 54 | 54-YI PDF | VE1KG14_054 |
| 55 | 55-RI PDF | VE1ER489 |
| ... | ... | ... |
| 71 | 71-YAA PDF | VE1ER505 |

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
  <fileDesc>
    <titleStmt>
      <title>Terdzo-ka P1</title>
    </titleStmt>
    <publicationStmt>...</publicationStmt>
    <sourceDesc>
      <bibl>
        <idno type="src_path">sources/VE1ER489/Terdzo-ka P1.pdf</idno>
        <idno type="src_sha256">...</idno>
        <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE1KG14</idno>
        <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE1ER489</idno>
        <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT1ER489_0002</idno>
      </bibl>
    </sourceDesc>
  </fileDesc>
  <encodingDesc>...</encodingDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p xml:space="preserve">
<pb/>
<lb/>༄༅། །text content...
<pb/>
<lb/>...more content...
</p>
</body>
</text>
</TEI>
```

### Key Features

- `xml:space="preserve"` for exact whitespace preservation
- `<pb/>` for page breaks
- `<lb/>` for line breaks
- `<hi rend="small">` for yigchung text
- `<hi rend="head">` for title text

## Notes

- Unicode normalization follows BDRC standards (NFC + Tibetan-specific rules)
- Font sizes are simplified to remove layout noise before classification
- Natural sorting ensures "1-KA PDF" comes before "10-THA PDF"
- Each PDF in a volume gets a separate XML file with sequential UT ID
- Thumbs.db files are automatically ignored

