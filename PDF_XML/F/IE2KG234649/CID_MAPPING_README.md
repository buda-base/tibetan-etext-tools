# CID Mapping for Monlam Fonts

## Problem

The PDFs in the IE2KG234649 collection use CID-keyed fonts (MonlamUniOuChan1, MonlamUniOuChan2, TTB444o00) that have incomplete ToUnicode CMaps. This means many Tibetan characters appear as `(cid:N)` tokens instead of proper Unicode text.

Example:
- **Input PDF**: མངོན་􏰁མ་􏰂ི་མཚན་ཉིད་བ􏰃ག་པ།
- **Without mapping**: མངོན་(cid:505)མ་(cid:369)ི་མཚན་ཉིད་བ(cid:411)ག་པ།
- **With mapping**: མངོན་སུམ་གྱི་མཚན་ཉིད་བསྟན་པ།

## Solution

The `glyph_decoder.py` module intercepts these CID tokens and maps them to proper Unicode text using the `DEFAULT_CID_TO_UNICODE_OVERRIDES` dictionary.

## Current Status

**Partial mapping implemented**. The following CIDs are currently mapped:
- CID 299, 306, 320, 345, 369, 399, 411, 428, 453, 505 for MonlamUniOuChan1/2

However, **150+ additional CIDs** need to be mapped to achieve complete coverage.

## How to Add More Mappings

### Step 1: Find Unmapped CIDs

Run the extraction script on your PDF:

```bash
cd /Users/tenzinmonlam/Documents/dharmaduta/tibetan-etext-tools/PDF_XML/T1/IE2KG234649
python extract_unmapped_cids.py path/to/your.pdf
```

This will output a list of unmapped CIDs with their occurrence counts.

### Step 2: Identify the Unicode Text

For each unmapped CID:

1. Open the PDF in a viewer
2. Find text containing that CID (search for the surrounding context)
3. Visually identify what Tibetan character(s) the CID represents
4. Note the correct Unicode representation

### Step 3: Add to glyph_decoder.py

Edit `glyph_decoder.py` and add the mapping to `DEFAULT_CID_TO_UNICODE_OVERRIDES`:

```python
DEFAULT_CID_TO_UNICODE_OVERRIDES: Dict[Tuple[str, int], str] = {
    # ... existing mappings ...
    
    # Add your new mappings here
    ("MonlamUniOuChan1", 299): "སུ",
    ("MonlamUniOuChan1", 306): "གྱི",
    # etc.
}
```

### Step 4: Test

Re-run the conversion and verify the output is correct.

## Common CID Patterns

Based on analysis of the IE2KG234649 PDFs:

- **CIDs 299-526** (MonlamUniOuChan1/2): Tibetan stacked consonants and special forms
- **CIDs 1-85** (TTB444o00): Decorative characters and special symbols

## Alternative Approach: Reference Font

If you have access to a reference version of the MonlamUniOuChan font with proper Unicode mappings, you can extract all CID-to-Unicode mappings programmatically using `fontTools`:

```python
from fontTools.ttLib import TTFont

tt = TTFont("MonlamUniOuChan.ttf")
cmap = tt.getBestCmap()
for cid, unicode_char in cmap.items():
    print(f"CID {cid}: {chr(unicode_char)}")
```

## Technical Details

### How It Works

1. `glyph_decoder.py` monkey-patches `pytiblegenc.pdfminer_text_converter.convert_string`
2. When a `(cid:N)` token is encountered, it looks up the mapping in:
   - `DEFAULT_CID_TO_UNICODE_OVERRIDES` (explicit mappings)
   - Embedded font's ToUnicode CMap (parsed from PDF)
   - Embedded font's cmap table (for non-CID fonts)
3. If found, returns the Unicode text; otherwise returns empty string

### Why ToUnicode CMap is Incomplete

The MonlamUniOuChan fonts in these PDFs have minimal ToUnicode CMaps that only cover CIDs 103-263. All other CIDs (including the commonly used stacked consonants) are not mapped, which is why manual mapping is necessary.

## Files

- `glyph_decoder.py`: Main module with CID decoding logic
- `extract_unmapped_cids.py`: Helper script to find unmapped CIDs
- `convert_pdf_to_xml.py`: Uses glyph_decoder via `patch_pytiblegenc_cid_decoder()`

## Future Work

- Build complete CID mapping for all MonlamUniOuChan CIDs
- Investigate if there's a public reference font with proper mappings
- Consider using OCR or visual glyph matching as fallback
