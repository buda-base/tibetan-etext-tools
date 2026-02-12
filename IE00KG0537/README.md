# Convert RTF files from IE00KG0537 to TEI XML format.
This script converts RTF files with Dedris legacy encoding to Unicode TEI XML.

## Quick Start

```bash
# Convert with default settings
python convert.py

# Convert with custom base directory
python convert.py --base-dir /path/to/IE00KG0537
```

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
3. **Classify Font Sizes** - Detect headers/body/footnotes
4. **Normalize Text** - Fix flying vowels, Unicode normalization
5. **Generate TEI XML** - With proper structure and metadata

## Configuration

Edit flags in `convert.py` (lines 66-67):

```python
ENABLE_FONT_CLASSIFICATION = True   # Add <hi rend="small/head"> tags
ENABLE_NORMALIZATION = True         # Apply text normalization
```

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
- `convert_old.py` - Backup of original script

## Documentation

- `IMPLEMENTATION_SUMMARY.md` - Complete implementation details
- `STAGED_PROCESSING.md` - Processing stages documentation
- `CONVERSION_UPDATE.md` - Update history

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

## Notes

- Default base directory: `/Users/tenzinmonlam/Documents/dharmaduta/file_convert_3/IE00KG0537`
- No toprocess folder required (VE IDs discovered automatically)
- Handles both direct RTF files and nested collection structures
- Automatically removes lines containing only dashes and spaces (e.g., "- - - - -")
