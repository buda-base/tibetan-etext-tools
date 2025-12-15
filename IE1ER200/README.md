# IE1ER200 Derge Tengyur to TEI XML Converter

This script converts Tibetan text files from the Digital Derge Tengyur (IE1ER200) format into TEI XML format and generates CSV outlines of the document structure.

## Overview

The `convert_tengyur.py` script processes text files with page/line markers (`[1a]`, `[1b.1]`), Derge catalog markers (`{D1}`, `{D1-1}`), and various annotation types, converting them into:
1. TEI XML files with proper structure and metadata
2. CSV files outlining the document structure with text markers

## Input Structure

The script expects input files in the following directory structure:

```
{input_folder}/
  sources/
    001_བསྟོད་ཚོགས།_ཀ.txt
    002_རྒྱུད་འགྲེལ།_ཀ.txt
    ...
    README.md (ignored)
  toprocess/
    IE1ER200-VE1ER251/
    IE1ER200-VE1ER252/
    ...
```

Where:
- `sources/`: Contains the source text files (one per volume)
- `toprocess/`: Contains empty VE folders from BDRC that provide volume identifiers

## Input File Format

Text files use page and line markers with inline annotations:

```
[1a]
[1a.1]
[1b]
[1b.1]{D3786}༄༅༅། །རྒྱ་གར་སྐད་དུ། ...
[1b.2]བོད་སྐད་དུ། བཅོམ་ལྡན་འདས་མ་ཤེས་རབ་ཀྱི་ཕ་རོལ་ཏུ་ཕྱིན་པའི་སྙིང་པོ།
[2a]
[2a.1]དཀོན་མཆོག་གསུམ་ལ་ཕྱག་འཚལ་ལོ།
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
    VE1ER251/
      001_བསྟོད་ཚོགས།_ཀ.txt    # Copy of original text file
    VE1ER252/
      002_རྒྱུད་འགྲེལ།_ཀ.txt
    ...
  archive/
    VE1ER251/
      UT1ER251_0001.xml    # TEI XML file
    VE1ER252/
      UT1ER252_0001.xml
    ...
  IE1ER200.csv              # Structure outline CSV
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
        <title>001_བསྟོད་ཚོགས།_ཀ</title>
      </titleStmt>
      <publicationStmt>
        <p>File from the archive of the Buddhist Digital Resource Center (BDRC)...</p>
      </publicationStmt>
      <sourceDesc>
        <bibl>
          <idno type="src_path">VE1ER251/001_བསྟོད་ཚོགས།_ཀ.txt</idno>
          <idno type="src_sha256">d674db022f71315d7e9779b9d19fc24b...</idno>
          <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE1ER200</idno>
          <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE1ER251</idno>
          <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT1ER251_0001</idno>
        </bibl>
      </sourceDesc>
    </fileDesc>
  </teiHeader>
  <text>
    <body xml:lang="bo">
      <p xml:space="preserve">
<pb n="1a"/>
<pb n="1b"/>
<lb/><milestone xml:id="D3786" unit="section"/>༄༅༅། །རྒྱ་གར་སྐད་དུ།...
<lb/>བོད་སྐད་དུ། བཅོམ་ལྡན་འདས་མ་ཤེས་རབ་ཀྱི་ཕ་རོལ་ཏུ་ཕྱིན་པའི་སྙིང་པོ།...
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
python convert_tengyur.py <input_folder> <output_folder>
```

### Example

```bash
cd /home/gangagyatso/Desktop/work/tibetan-etext-tools/IE1ER200
python3 convert_tengyur.py ../IE1ER200_input/IE1ER200 ../IE1ER200_output
```

This will process all volumes from `../IE1ER200_input/IE1ER200/` and generate output in `../IE1ER200_output/`.

## Features

- Automatic parsing of page/line markers (`[1a]`, `[1b.1]`, `[93xa]`)
- Derge catalog milestone extraction (`{D3786}`, `{D3786-1}`, etc.)
- Error annotation conversion: `(X,Y)` → `<choice><orig>X</orig><corr>Y</corr></choice>`
- Variant spelling conversion: `{X,Y}` → `<choice><orig>X</orig><reg>Y</reg></choice>`
- Error candidate conversion: `[Tibetan]` → `<unclear reason="illegible">...</unclear>`
- TEI XML generation with proper namespace and structure
- SHA256 hash calculation for source file verification
- Multi-volume support using VE identifiers from toprocess folder (213 volumes)
- CSV outline generation for navigation and indexing
- Unicode normalization (NFC + Tibetan-specific)
- Handles duplicate page numbers (`[93xa]`, `[355xb]`)

## Requirements

- Python 3.6+
- `normalization.py` module (included in this directory)

## Notes

- VE identifiers are extracted from the `toprocess/IE1ER200-VE*` folder names
- Source files are processed in alphabetical order (001, 002, 003...)
- Empty lines in source (lines with no content after markers) are skipped
- The script follows BDRC TEI Paginated Shape specification
- XML uses `xml:space="preserve"` to maintain exact whitespace
- README.md in sources folder is automatically excluded from processing

## Source Format Reference

This converter is designed for the Digital Derge Tengyur dataset. The source format includes:
- Page/folio marker conventions (`[1a]`, `[1b]`, `[2a]`...)
- Error annotation syntax (`(X,Y)` for errors, `{X,Y}` for variants)
- Unicode encoding specifications (UTF-8, NFD)
- Punctuation normalization rules
- Page numbering exceptions

### Tengyur Sections (213 volumes)

The IE1ER200 dataset includes:
- བསྟོད་ཚོགས། (Hymns) - Volume 1
- རྒྱུད་འགྲེལ། (Tantra commentaries) - Volumes 2-79
- ཤེར་ཕྱིན། (Prajñāpāramitā) - Volumes 80-95
- དབུ་མ། (Madhyamaka) - Volumes 96-112
- མདོ་སྡེ། (Sūtra commentaries) - Volumes 113-122
- སེམས་ཙམ། (Cittamātra) - Volumes 123-138
- མངོན་པ། (Abhidharma) - Volumes 139-149
- འདུལ་བ། (Vinaya) - Volumes 150-167
- སྐྱེས་རབས། (Jātaka) - Volumes 168-169, 172
- འཁྲི་ཤིང། - Volumes 170-171
- སྤྲིང་ཡིག (Letters) - Volume 173
- ཚད་མ། (Pramāṇa) - Volumes 174-193
- སྒྲ་མདོ། (Grammar) - Volumes 194-197, 208
- གསོ་རིག (Medicine) - Volumes 198-202
- སྣ་ཚོགས། (Miscellaneous) - Volumes 203-212
- དཀར་ཆག (Catalog) - Volume 213

## Validation

After conversion, validate the output using the BDRC validation tool:

```bash
cd /path/to/ao_etexts
python bdrc_etext_sync/validation.py /path/to/output
```


