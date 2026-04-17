# Convert RTF files from IE00EGS1017177 to TEI XML format.
This script converts RTF files with Dedris legacy encoding to Unicode TEI XML.

## Quick Start

```bash
# Convert with default settings
python convert.py

# Convert with custom base directory
python convert.py --base-dir /path/to/IE00EGS1017177
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

Edit flags in `convert.py` (lines 83-84):

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
      <title>01_kun_byed_rgyal_po_dkar_chag_v01</title>
    </titleStmt>
    <sourceDesc>
      <bibl>
        <idno type="bdrc_ie">http://purl.bdrc.io/resource/IE00EGS1017177</idno>
        <idno type="bdrc_ve">http://purl.bdrc.io/resource/VE1ER664</idno>
        <idno type="bdrc_ut">http://purl.bdrc.io/resource/UT1ER664_0001</idno>
      </bibl>
    </sourceDesc>
  </fileDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p>དཀར་ཆག
<lb/>༄༅། །ཆོས་ཐམས་ཅད་རྫོགས་པ་ཆེན་པོ་བྱང་ཆུབ་ཀྱི་སེམས་ཀུན་བྱེད་རྒྱལ་པོའི་འགྲེལ་བ་ཀུན་བཟང་དགོངས་རྒྱན་ཞེས་བྱ་བ་བཞུགས་ས།ོ །
<lb/>དེ་ལས་འདིར་ལེའུ་བརྒྱད་ཅུ་རྩ་བཞི་ཡོད་པའི་ནང་ནས་ཐོག་མ་ཡིན་པས་ན་དང་པོའི་འགྲེལ་བ།། །།
</p>
</body>
</text>
</TEI>
```

## Notes

- Default base directory: `/Users/tenzinmonlam/Documents/dharmaduta/file_convert_3/IE00EGS1017177`
- No toprocess folder required (VE IDs discovered automatically)
- Handles both direct RTF files and nested collection structures
- Page breaks (`\page`) not currently supported
