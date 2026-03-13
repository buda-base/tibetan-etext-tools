# Footnote Implementation for DOCX to TEI XML Conversion

## Overview

The DOCX to TEI XML conversion script has been updated to support footnotes according to the BDRC TEI "Paginated Shape" guidelines. Footnotes are now extracted from Word documents and inserted inline at the exact location where they appear in the original document.

## Implementation Details

### 1. Footnote Extraction (`basic_docx.py`)

The `BasicDOCX` class now:
- Parses `word/footnotes.xml` from the DOCX file
- Extracts footnote text for each footnote ID
- Skips special footnote types (separator, continuationSeparator)
- Cleans footnote text by:
  - Stripping leading/trailing whitespace
  - Removing leading footnote numbers (e.g., "1 Text" → "Text")
  - Joining multiple paragraphs with spaces
  - Converting line breaks within footnotes to spaces

### 2. Footnote Reference Detection

During document parsing, the script:
- Detects `<w:footnoteReference>` elements in runs
- Inserts a special marker at the exact position where the footnote appears
- Preserves the footnote ID for later replacement

### 3. Inline Footnote Insertion (`tei_generator.py`)

The `build_tei_body` function:
- Receives the footnotes dictionary from the parser
- Replaces footnote markers with properly formatted `<note>` tags
- Formats footnotes as: `<note n="{footnote_number}" place="foot">{footnote_text}</note>`
- Ensures NO extra whitespace is added around the tags

### 4. XML Formatting

The generated TEI XML:
- Uses `<p xml:space="preserve">` to maintain exact spacing
- Places `<note>` tags inline with surrounding text
- Escapes XML special characters in footnote text
- Maintains strict whitespace control (no extra spaces, tabs, or newlines)

## Example Output

### Input (Word Document)
```
Main text with a footnote reference¹ continues here.

Footnote:
¹ This is the footnote text.
```

### Output (TEI XML)
```xml
<p xml:space="preserve">Main text with a footnote reference<note n="1" place="foot">This is the footnote text.</note> continues here.</p>
```

## Files Modified

1. **basic_docx.py**
   - Added `_footnotes` dictionary to store footnote ID → text mapping
   - Added `_parse_footnotes()` method to extract footnotes from `word/footnotes.xml`
   - Updated `_parse_document()` to detect `<w:footnoteReference>` elements
   - Added `get_footnotes()` method to retrieve footnotes
   - Added `FOOTNOTE_MARKER` constant for temporary placeholder

2. **convert.py**
   - Updated `convert_docx_to_tei()` to retrieve footnotes from parser
   - Modified stream processing to preserve footnote marker information
   - Passed footnotes dictionary to `build_tei_body()`

3. **tei_generator.py**
   - Updated `build_tei_body()` to accept `footnotes` parameter
   - Added logic to replace footnote markers with `<note>` tags
   - Updated `post_process_body()` to remove any spaces around `<note>` tags
   - Added `xml:space="preserve"` attribute to `<p>` tag in `generate_tei_xml()`

## Usage

The conversion script works exactly as before:

```bash
# Convert all DOCX files
python convert.py

# Convert a single file
python convert.py --single IE2122-VE3KG1/file.docx
```

Footnotes are automatically detected and converted. No additional configuration is required.

## Technical Notes

### Whitespace Handling

The implementation strictly controls whitespace around `<note>` tags:
- No spaces before the opening `<note>` tag
- No spaces after the closing `</note>` tag
- The tag sits flush with surrounding text
- The `xml:space="preserve"` attribute ensures exact spacing is maintained

### Footnote Number Extraction

The footnote number (`n` attribute) is taken directly from the footnote ID in the DOCX file. This is typically a sequential number (1, 2, 3, etc.) assigned by Word.

### Multiple Paragraphs in Footnotes

If a footnote contains multiple paragraphs, they are joined with spaces to create a single inline note. This follows the BDRC TEI guidelines for inline footnote placement.

### Error Handling

- If `word/footnotes.xml` is not present, the script continues without errors
- If a footnote reference points to a non-existent footnote ID, it's silently skipped
- XML parsing errors in footnotes are logged as warnings but don't stop conversion

## Testing

To test the footnote functionality:
1. Create a Word document with footnotes
2. Place the document in the appropriate `toprocess` folder
3. Run the conversion script
4. Verify that the output XML contains `<note>` tags inline with the text
5. Check that no extra whitespace appears around the tags
