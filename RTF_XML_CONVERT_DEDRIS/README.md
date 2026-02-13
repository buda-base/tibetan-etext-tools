# Convert RTF files to TEI XML format (DEDRIS FONT)

Converts RTF files with Dedris legacy encoding to Unicode TEI XML.

## Quick Start

```bash
# Process current directory (auto-detects IE_ID from folder name)
python convert.py

# Process specific directory (auto-detects IE_ID from folder name)
python convert.py /path/to/IE1GS58442

# Process with explicit IE_ID override
python convert.py /path/to/folder --ie-id IE1GS58442
```

The script automatically detects the IE_ID from the directory name (e.g., `IE1GS58442`, `IE00KG0540`).

## Input Structure
```
    {BASE_DIR}/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf
```
    OR
```
    {BASE_DIR}/sources/{VE_ID}/*.rtf (direct RTF files)
```

## Output structure:

**Archive (flat):** 
  ```
    {BASE_DIR}/{IE_ID}_output/archive/{VE_ID}/UT{suffix}_{index}.xml
  ```

**Sources (nested):** 
  ```
    {BASE_DIR}/{IE_ID}_output/sources/{VE_ID}/{collection_name}/rtfs/{VOL_ID}/*.rtf and *.doc
  ```

## Processing Pipeline

1. **Parse RTF** - Extract text with font information
2. **Convert Encoding** - Dedris legacy → Unicode (pytiblegenc)
   - Handles `None` returns from pytiblegenc to preserve original text
   - Processes SimSun font as suspicious font
3. **Classify Font Sizes** - Detect headers/body/footnotes
4. **Normalize Text** - Fix flying vowels, Unicode normalization
   - ASCII to Tibetan character mapping
   - Remove inverted exclamation mark (¡)
   - Preserve ellipsis characters (…)
5. **Generate TEI XML** - With proper structure and metadata

## Configuration

Edit flags in `convert.py` (near the top of the file):

```python
ENABLE_FONT_CLASSIFICATION = True   # Add <hi rend="small/head"> tags
ENABLE_NORMALIZATION = True         # Apply text normalization
```

## Directory Structure Requirements

The script expects the following structure:

```
{BASE_DIR}/
└── sources/
    └── {VE_ID}/
        ├── {collection_name}/
        │   └── rtfs/
        │       └── volume_XXX/
        │           └── *.rtf
        └── *.rtf (or direct RTF files)
```

The `{BASE_DIR}` folder name should contain the IE_ID (e.g., `IE1GS58442`).

## ASCII to Tibetan Character Mappings

The following ASCII characters are automatically converted to their Tibetan equivalents:

| ASCII | Unicode | Tibetan | Description |
|-------|---------|---------|-------------|
| `.`   | U+002E  | ད       | Letter DA (single periods only) |
| `-`   | U+002D  | ་       | Tseg (syllable separator) |
| `0`   | U+0030  | པ       | Letter PA |
| `,`   | U+002C  | ཐ       | Letter THA |
| `}`   | U+007D  | སྔ      | SA + NGA |
| `(`   | U+0028  | ༼       | Tibetan left bracket |
| `)`   | U+0029  | ༽       | Tibetan right bracket |
| `\`   | U+005C  | གླ      | GA + LA subscript |

**Note:** Ellipsis (sequences of 2 or more periods like `...` or `....................`) are preserved as-is and not converted. Only isolated single periods are converted to ད.

These mappings are applied in `tibetan_text_fixes.py` via the `fix_ascii_to_tibetan()` function.

## Dependencies

```bash
pip install natsort
pip install -U git+https://github.com/buda-base/py-tiblegenc.git
```

## Files

- `convert.py` - Main conversion script
- `basic_rtf.py` - RTF parser
- `normalization.py` - Unicode normalization
- `tibetan_text_fixes.py` - Tibetan-specific text fixes

## Example Output

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
  <fileDesc>
    <titleStmt>
      <title>01_rgyud_bla_ma_3_dkar_chag</title>
    </titleStmt>
    <publicationStmt>
      <p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p>
    </publicationStmt>
    <sourceDesc>
      <bibl>
        <idno type="src_path">VE1ER669/01_rgyud_bla_ma_3_dkar_chag.rtf</idno>
        <idno type="src_sha256">6b2f20551f35ccd9252a70e234a202fa730c8434d540b7753d975dd1a3988f1e</idno>
        <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE00KG0537</idno>
        <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE1ER669</idno>
        <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT1ER669_0001</idno>
      </bibl>
    </sourceDesc>
  </fileDesc>
  <encodingDesc>
    <p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/IE00KG0537">record in the BDRC database</ref>.</p>
  </encodingDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p><hi rend="head">༈ མཉམ་མེད་སྟོན་མཆོག་ཐུབ་པའི་དབང་པ་ོལ་ན་མ།ོ
<lb/>༄༅། །ཐེག་པ་ཆེན་པོ་རྒྱུད་བླ་མའི་བསྟན་བཅོས་ཀྱི་འགྲེལ་བཤད་དེ་ཁོ་ན་ཉིད་རབ་ཏུ་གསལ་བའི་མེ་ལོང་ཞེས་བྱ་བ་བཞུགས་ས།ོ །</hi></p>
</body>
</text>
</TEI>
```

## Changes

### Character Handling Improvements
- **Ellipsis Preservation**: Ellipsis characters (…) are now preserved in output
  - Fixed pytiblegenc `None` return handling
  - Ellipsis patterns with soft hyphens are properly converted
- **ASCII to Tibetan Mapping**: Added automatic conversion of ASCII punctuation to Tibetan characters
- **Character Cleanup**: Inverted exclamation mark (¡) is removed during processing

### Processing Enhancements
- Lines with only dashes/spaces are skipped, but ellipsis lines are preserved
- SimSun font text is processed through pytiblegenc for proper conversion
- Improved handling of font attribution errors in RTF files

## Notes

- **Generic Script**: Works with any IE collection by auto-detecting the IE_ID from the folder name
- **Flexible Structure**: Handles both direct RTF files and nested collection structures
- **Smart Cleanup**: Automatically removes lines containing only dashes and spaces (e.g., "- - - - -")
- **Character Preservation**: Preserves ellipsis characters (………………………………………………………) from table of contents
- **Current Directory**: If no path is provided, processes the current working directory

## Examples

```bash
# Navigate to the collection folder and run
cd /path/to/IE1GS58442
python /path/to/convert.py

# Or specify the path directly
python convert.py /path/to/IE00KG0540

# Override auto-detection if folder name doesn't contain IE_ID
python convert.py /path/to/my_collection --ie-id IE1GS58442
```
