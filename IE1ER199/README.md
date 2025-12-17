# IE1ER199 Derge Kangyur to TEI XML Converter

This script converts Tibetan text files from the Digital Derge Kangyur (IE1ER199) format into TEI XML format and generates CSV outlines of the document structure.

## Overview

The `convert_derge.py` script processes text files with page/line markers (`[1a]`, `[1b.1]`), Derge catalog markers (`{D1}`, `{D1-1}`), and various annotation types, converting them into:
1. TEI XML files with proper structure and metadata
2. CSV files outlining the document structure with text markers

## Input Structure

The script expects input files in the following directory structure:

```
{input_folder}/
  sources/
    text/
      001_འདུལ་བ།_ཀ.txt
      002_འདུལ་བ།_ཁ.txt
      ...
  toprocess/
    IE1ER199-VE1ER148/
    IE1ER199-VE1ER149/
    ...
```

Where:
- `sources/text/`: Contains the source text files (one per volume)
- `toprocess/`: Contains empty VE folders from BDRC that provide volume identifiers

## Input File Format

Text files use page and line markers with inline annotations:

```
[1a]
[1a.1]
[1b]
[1b.1]{D1}{D1-1}༄༅༅། །རྒྱ་གར་སྐད་དུ། བི་ན་ཡ་བསྟུ། བོད་སྐད་དུ། འདུལ་བ་གཞི། བམ་པོ་དང་པོ།
[1b.2]རྣམས་ཡང་དག་རབ་བཅད་ཅིང་། །མུ་སྟེགས་ཚོགས་རྣམས་ཐམས་ཅད་རབ་བཅོམ་སྟེ།
[2a]
[2a.1]རྩོད་པ་དང་། །དགེ་འདུན་དབྱེན་རྣམས་བསྡུས་པ་ཡིན།
```

### Annotation Types

| Source Format | Description | TEI Output |
|---------------|-------------|------------|
| `[1a]`, `[1b]` | Page markers | `<pb n="1a"/>`, `<pb n="1b"/>` |
| `[1a.1]`, `[2b.3]` | Page + line markers | `<pb/>` + `<lb/>` |
| `[93xa]`, `[355xb]` | Duplicate page markers | `<pb n="93xa"/>` |
| `(X,Y)` | Error + correction | `<choice><orig>X</orig><corr>Y</corr></choice>` |
| `{X,Y}` | Variant/archaic spelling | `<choice><orig>X</orig><reg>Y</reg></choice>` |
| `{D###}`, `{D###-#}` | Derge catalog markers | `<milestone xml:id="D###" unit="section"/>` |
| `[Tibetan text]` | Error candidates | `<unclear reason="illegible">...</unclear>` |

## Output Structure

The script generates the following output structure:

```
{output_folder}/
  sources/
    VE1ER148/
      001_འདུལ་བ།_ཀ.txt    # Copy of original text file
    VE1ER149/
      002_འདུལ་བ།_ཁ.txt
    ...
  archive/
    VE1ER148/
      UT1ER148_0001.xml    # TEI XML file
    VE1ER149/
      UT1ER149_0001.xml
    ...
  IE1ER199.csv              # Structure outline CSV
```

## TEI XML Output

The XML output follows the TEI (Text Encoding Initiative) standard with:
- TEI header containing title, publication info, and source metadata
- BDRC resource identifiers (IE, VE, UT)
- SHA256 hash of the source file
- Page breaks (`<pb n="..."/>`) and line breaks (`<lb/>`)
- Milestone markers for Derge catalog numbers
- Editorial annotations using `<choice>`, `<orig>`, `<corr>`, `<reg>`
- Unclear text marked with `<unclear reason="illegible">`
- Language attribute set to Tibetan (`xml:lang="bo"`)
- `xml:space="preserve"` for exact whitespace handling

### Sample XML Output

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>001_འདུལ་བ།_ཀ</title>
      </titleStmt>
      <publicationStmt>
        <p>File from the archive of the Buddhist Digital Resource Center (BDRC)...</p>
      </publicationStmt>
      <sourceDesc>
        <bibl>
          <idno type="src_path">VE1ER148/001_འདུལ་བ།_ཀ.txt</idno>
          <idno type="src_sha256">d674db022f71315d7e9779b9d19fc24b...</idno>
          <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE1ER199</idno>
          <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE1ER148</idno>
          <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT1ER148_0001</idno>
        </bibl>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <body xml:lang="bo">
      <p xml:space="preserve">
<pb n="1a"/>
<pb n="1b"/>
<lb/><milestone xml:id="D1" unit="section"/>༄༅༅། །རྒྱ་གར་སྐད་དུ།...
<lb/>རྣམས་ཡང་དག་རབ་བཅད་ཅིང་།...
</p>
    </body>
  </text>
</TEI>
```

## CSV Output

The CSV file provides a structural outline with the following columns:
- RID, Position (×4), part type, label, titles, work, notes, colophon, authorshipStatement, identifiers, etext start, etext end, img grp start, img grp end

Part types:
- `V`: Volume
- `T`: Text (Derge catalog entry)

## Usage

```bash
python convert_derge.py <input_folder> <output_folder>
```

### Example

```bash
cd /home/gangagyatso/Desktop/work/tibetan-etext-tools/IE1ER199
python3 convert_derge.py ../input/IE1ER199 ../output
```

This will process all volumes from `../input/IE1ER199/` and generate output in `../output/`.

## Features

- Automatic parsing of page/line markers (`[1a]`, `[1b.1]`, `[93xa]`)
- Derge catalog milestone extraction (`{D1}`, `{D1-1}`, `{T841-1}`)
- Error annotation conversion: `(X,Y)` → `<choice><orig>X</orig><corr>Y</corr></choice>`
- Variant spelling conversion: `{X,Y}` → `<choice><orig>X</orig><reg>Y</reg></choice>`
- Error candidate conversion: `[Tibetan]` → `<unclear reason="illegible">...</unclear>`
- TEI XML generation with proper namespace and structure
- SHA256 hash calculation for source file verification
- Multi-volume support using VE identifiers from toprocess folder
- CSV outline generation for navigation and indexing
- Unicode normalization (NFC + Tibetan-specific)
- Handles duplicate page numbers (`[93xa]`, `[355xb]`)

## Requirements

- Python 3.6+
- `normalization.py` module (in parent directory)

## Notes

- VE identifiers are extracted from the `toprocess/IE1ER199-VE*` folder names
- Source files are processed in alphabetical order (001, 002, 003...)
- Empty lines in source (lines with no content after markers) are skipped
- The script follows BDRC TEI Paginated Shape specification
- XML uses `xml:space="preserve"` to maintain exact whitespace

## Source Format Reference

This converter is designed for the Digital Derge Kangyur dataset. See `sources/README.md` for detailed documentation of the source format including:
- Page/folio marker conventions
- Error annotation syntax
- Unicode encoding specifications
- Punctuation normalization rules
- Page numbering exceptions

## Validation

After conversion, validate the output using the BDRC validation tool:

```bash
cd /path/to/ao_etexts
python bdrc_etext_sync/validation.py /path/to/output
```

