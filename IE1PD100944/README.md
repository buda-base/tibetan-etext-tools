# IE1PD100944 - KAMA Collection RTF to TEI XML Converter

This module converts RTF files from the KAMA Collection (IE1PD100944) containing Tibetan text in **Dedris legacy encoding** to Unicode TEI XML format.

## Overview

The KAMA Collection consists of RTF files created with Dedris fonts, a legacy encoding system for Tibetan text. This converter:

1. Parses RTF files extracting text with font metadata
2. Converts Dedris-encoded characters to Unicode Tibetan
3. Normalizes Unicode (Tibetan-specific reordering, deprecated character replacement)
4. Classifies font sizes (regular body text, headings, annotations/yig chung)
5. Generates TEI XML with proper structure and `<hi>` tags for formatting

## Architecture

```
RTF File (Dedris encoding)
         │
         ▼
┌─────────────────────────────┐
│  Stage 1: RTF Parsing       │
│  (basic_rtf.py)             │
│  - Extract text streams     │
│  - Capture font info        │
│  - Handle escaped chars     │
│  - Detect paragraph breaks  │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Stage 2: Encoding Conv.    │
│  (pytiblegenc)              │
│  - Dedris → Unicode         │
│  - Per-font mappings        │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Stage 3: Normalization     │
│  (normalization.py)         │
│  (tibetan_text_fixes.py)    │
│  - Fix flying vowels        │
│  - Unicode reordering       │
│  - Space normalization      │
└─────────────────────────────┘
         │
         ▼
┌─────────────────────────────┐
│  Stage 4: TEI Generation    │
│  (convert.py)               │
│  - Font size classification │
│  - <hi> tag markup          │
│  - <lb/> line breaks        │
│  - TEI header generation    │
└─────────────────────────────┘
         │
         ▼
   TEI XML Output
```

## Dependencies

```bash
# Required
pip install natsort                    # Natural sorting of file names
pip install git+https://github.com/buda-base/py-tiblegenc.git  # Dedris conversion

# For testing (Windows only)
pip install pywin32                    # MS Word automation for validation
```

## Files

### Core Scripts

| File | Description |
|------|-------------|
| `basic_rtf.py` | RTF parser that extracts text streams with font information. Handles both 'simple' and 'complex' RTF formats, escaped characters (`\{`, `\}`, `\\`), and table structures. |
| `convert.py` | Main conversion pipeline. Orchestrates RTF parsing, Dedris conversion, normalization, font classification, and TEI XML generation. |
| `normalization.py` | Unicode normalization functions. Includes Tibetan-specific character reordering, deprecated character replacement, and space normalization. |
| `tibetan_text_fixes.py` | Fixes common issues in converted text: flying vowels, flying subscripts, flying tseg, and spacing around XML tags. |

### Test Scripts

| File | Description |
|------|-------------|
| `test_basic_rtf.py` | Unit tests for the RTF parser. Verifies font parsing, stream extraction, escaped character handling, and concatenated output. |
| `test_word_comparison.py` | Validates parser output against Microsoft Word's rendering. Uses COM automation to compare text extraction. |
| `test_integration.py` | End-to-end integration tests covering the full conversion pipeline. |
| `test_tibetan_text_fixes.py` | Tests for Tibetan text normalization functions. |

### Test Data

| File | Description |
|------|-------------|
| `KAMA-001.rtf` | Sample RTF file for unit testing (~30KB) |
| `test.rtf`, `test1.rtf`, `test2.rtf` | Large test files for validation (~18-20MB each) |
| `*-word-output.txt` | Reference output from Microsoft Word |
| `*-parser-output.txt` | Output from BasicRTF parser for comparison |

## Usage

### Convert a Single File

```bash
python convert.py --single KAMA-001.rtf
```

### Convert All Volume Files

```bash
python convert.py --all
```

The script expects:
- RTF files in `IE1PD100944_rtf/` folder
- VE ID folders in `IE1PD100944/toprocess/` for mapping
- DOC source files in `IE1PD100944/sources/` for SHA256 hashes

### Output Structure

```
IE1PD100944_output/
├── archive/
│   ├── VE3KG466/
│   │   └── UT3KG466_0001.xml    # TEI XML output
│   ├── VE3KG467/
│   │   └── UT3KG467_0001.xml
│   └── ...
├── sources/
│   ├── VE3KG466/
│   │   ├── KAMA-001.doc         # Original DOC file
│   │   └── KAMA-001.rtf         # RTF conversion
│   └── ...
└── conversion_stats.txt          # Conversion statistics
```

## Running Tests

### Unit Tests

```bash
# Run all RTF parser tests
python -m pytest test_basic_rtf.py -v

# Run integration tests
python -m pytest test_integration.py -v

# Run all tests
python -m pytest . -v
```

### Word Comparison Test (Windows only)

Requires Microsoft Word installed:

```bash
# Test with default file (test.rtf)
python test_word_comparison.py

# Test with specific file
python test_word_comparison.py KAMA-001.rtf
```

## Key Algorithms

### Font Size Classification

The converter classifies font sizes to identify:
- **Regular**: Most frequently occurring size (body text)
- **Large** (`<hi rend="head">`): Sizes larger than regular (headings)
- **Small** (`<hi rend="small">`): Sizes smaller than regular (annotations/yig chung)

```python
# Classification is based on character frequency
most_common_size = max(size_counts.items(), key=lambda x: x[1])[0]
# Sizes > most_common → large
# Sizes < most_common → small
```

### Flying Vowel Fixes

Tibetan vowels (U+0F71-U+0F84) are combining marks that attach to consonants. RTF line wrapping can cause them to appear at the start of a line ("flying"):

```
Before: དང་པ
        ོ་ནི།     (vowel ོ is "flying")

After:  དང་པོ་ནི། (vowel attached correctly)
```

The `fix_flying_vowels_and_linebreaks()` function joins:
- Flying vowels to previous consonant
- Flying subscripts (U+0F90-U+0FBC) to previous consonant
- Flying tseg (་) to previous syllable

### RTF Escaped Character Handling

The parser handles escaped RTF control characters:
- `\{` → literal `{` (Dedris: སྐ)
- `\}` → literal `}` (Dedris: སྔ)
- `\\` → literal `\`

This is critical because Dedris fonts map ASCII braces to Tibetan character clusters.

## Dedris Font Mappings

The Dedris font family encodes Tibetan text using ASCII characters:

| ASCII | Dedris-a Output | Unicode |
|-------|-----------------|---------|
| `o` | རྒྱ | U+0F62 U+0F92 U+0FB3 |
| `-` | ་ (tseg) | U+0F0B |
| `.` | ད | U+0F51 |
| `{` | སྐ | U+0F66 U+0F90 |
| `}` | སྔ | U+0F66 U+0F94 |

Different Dedris variants (a, b, c, d, e, vowa, etc.) have different mappings for the same ASCII characters.

## TEI XML Output Format

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
  <fileDesc>
    <titleStmt><title>KAMA-001</title></titleStmt>
    <sourceDesc>
      <bibl>
        <idno type="src_path">sources/VE3KG466/KAMA-001.doc</idno>
        <idno type="src_sha256">abc123...</idno>
        <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE1PD100944</idno>
        <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE3KG466</idno>
        <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT3KG466_0001</idno>
      </bibl>
    </sourceDesc>
  </fileDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p>སྐྱབས་འགྲོ་ཡན་ལག་དྲུག་པ།
<lb/>ཞེས་བྱ་བ་བཞགས་སོ༔
<lb/><hi rend="small">ཡིག་ཆུང་དཔེར་མཚོན།</hi></p>
</body>
</text>
</TEI>
```

## Troubleshooting

### "pytiblegenc not found"

Install the latest version:
```bash
pip install -U git+https://github.com/buda-base/py-tiblegenc.git
```

### Unicode characters appearing incorrectly

Ensure your terminal/editor supports UTF-8 and has a Tibetan font installed (e.g., Microsoft Himalaya, Jomolhari).

### Parser output doesn't match Word

Run the comparison test to identify differences:
```bash
python test_word_comparison.py your_file.rtf
```

Check the generated `*-word-output.txt` and `*-parser-output.txt` files for detailed comparison.

## License

See the LICENSE file in the parent `tibetan-etext-tools` directory.

## Contributing

When making changes:
1. Run the test suite: `python -m pytest . -v`
2. Test against Word output: `python test_word_comparison.py`
3. Verify TEI XML is well-formed: `xmllint --noout output.xml`

