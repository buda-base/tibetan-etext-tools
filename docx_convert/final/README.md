# DOCX to TEI XML Converter

A Python script for converting DOCX files to TEI XML format following BDRC TEI "Paginated Shape" guidelines.

## Features

- **Unicode Text Extraction**: Extracts text from DOCX files with proper Unicode handling
- **Font Size Classification**: Automatically classifies text as headers, body, or footnotes based on font size
- **Footnote Support**: Extracts Word footnotes and inserts them inline as `<note>` tags
- **Tibetan Text Normalization**: Applies Tibetan-specific Unicode normalization
- **Batch Processing**: Converts multiple files with checkpoint support for resumable operations
- **Header/Footer Handling**: Includes header and footer content (useful for TOC)

## Installation

Required Python packages:
```bash
pip install python-docx natsort
```

## Configuration

Edit `config.py` to set:
- `IE_ID`: Image Entity ID for your collection
- `BASE_DIR`: Base directory for input/output
- `TOPROCESS_DIR`: Directory containing DOCX files to convert
- `OUTPUT_DIR`: Directory for output XML files

## Usage

### Convert All Files
```bash
python convert.py
```

### Convert Single File
```bash
python convert.py --single IE2122-VE3KG1/file.docx
```

### Options
- `--no-font-tags`: Disable font size classification
- `--no-normalization`: Disable Unicode normalization

## Footnote Support

The script now fully supports Word footnotes according to BDRC TEI guidelines:

### How It Works

1. **Extraction**: Footnotes are extracted from `word/footnotes.xml` in the DOCX file
2. **Inline Placement**: Footnotes are inserted at the exact location where the reference appears
3. **XML Format**: Footnotes are wrapped in `<note n="{number}" place="foot">{text}</note>`
4. **Text Cleaning**: Leading footnote numbers and extra whitespace are removed
5. **Normalization**: Footnote text undergoes the same Unicode normalization as main text

### Example

**Input (Word Document):**
```
Main text with a footnote¹ continues here.

Footnote:
¹ This is the footnote text.
```

**Output (TEI XML):**
```xml
<p xml:space="preserve">Main text with a footnote<note n="1" place="foot">This is the footnote text.</note> continues here.</p>
```

### Testing Footnotes

Use the test script to verify footnote extraction:
```bash
python test_footnotes.py path/to/file.docx
```

This will display:
- All footnotes found in the document
- Where footnote markers appear in the text
- Context around each footnote reference

## Output Structure

```
{OUTPUT_DIR}/
├── archive/
│   └── {VE_ID}/
│       ├── {UT_ID}_0001.xml
│       ├── {UT_ID}_0002.xml
│       └── ...
└── sources/
    └── {IE_ID-VE_ID}/
        ├── file1.docx
        ├── file2.docx
        └── ...
```

## TEI XML Structure

The generated TEI XML follows BDRC guidelines:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title>Document Title</title>
      </titleStmt>
      <publicationStmt>...</publicationStmt>
      <sourceDesc>
        <bibl>
          <idno type="src_path">IE2122-VE3KG1/file.docx</idno>
          <idno type="src_sha256">...</idno>
          <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE2122</idno>
          <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE3KG1</idno>
          <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT3KG1_0001</idno>
        </bibl>
      </sourceDesc>
    </fileDesc>
    <encodingDesc>...</encodingDesc>
  </teiHeader>
  <text>
    <body xml:lang="bo">
      <p xml:space="preserve">
        <hi rend="head">Header Text</hi><lb/>
        Body text with footnote<note n="1" place="foot">Footnote text.</note> continues.<lb/>
        <hi rend="small">Small text</hi>
      </p>
    </body>
  </text>
</TEI>
```

## Text Processing Pipeline

1. **Parse DOCX**: Extract text runs with font information and footnotes
2. **Normalize Unicode**: Apply NFC normalization and Tibetan-specific rules
3. **Classify Fonts**: Identify headers, body text, and small text by font size
4. **Build TEI Body**: Generate TEI XML with `<hi>` tags and inline `<note>` tags
5. **Post-Process**: Add `<lb/>` tags, clean whitespace, normalize tag placement
6. **Generate TEI**: Create complete TEI XML document with metadata

## Modules

- `convert.py`: Main conversion script and orchestration
- `basic_docx.py`: DOCX parser that extracts text runs and footnotes
- `normalization.py`: Unicode and Tibetan text normalization
- `tibetan_text_fixes.py`: Tibetan-specific text fixes
- `tei_generator.py`: TEI XML generation and formatting
- `config.py`: Configuration and path settings

## Logging

Logs are written to `{BASE_DIR}/logs/docx_to_xml.log` with detailed information about:
- Files processed
- Footnotes found
- Conversion stages
- Errors and warnings

## Checkpoint System

The script maintains a checkpoint file to track converted files. If conversion is interrupted, it will resume from where it left off when run again.

Checkpoint file: `{BASE_DIR}/checkpoints/docx_to_xml_checkpoint.txt`

## Troubleshooting

### No Footnotes Found

If footnotes aren't being extracted:
1. Verify the DOCX file contains actual Word footnotes (not endnotes)
2. Check that `word/footnotes.xml` exists in the DOCX file (unzip to verify)
3. Run `test_footnotes.py` to see detailed extraction information

### Extra Whitespace Around Notes

The script is designed to prevent extra whitespace around `<note>` tags. If you see extra spaces:
1. Check that `xml:space="preserve"` is present in the `<p>` tag
2. Verify that `post_process_body()` is running correctly
3. Check for any custom text processing that might add spaces

### Footnote Text Issues

If footnote text appears incorrect:
1. Verify the footnote text in the original Word document
2. Check that Unicode normalization is enabled
3. Look for special characters or formatting in the footnote

## References

- [BDRC TEI Guidelines](https://github.com/buda-base/tei-guidelines)
- [TEI P5 Guidelines](https://tei-c.org/release/doc/tei-p5-doc/en/html/)
- [python-docx Documentation](https://python-docx.readthedocs.io/)
