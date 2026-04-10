# Tibetan PDF → TEI XML Conversion Pipeline

A Python pipeline for extracting Tibetan text from Monlam-font PDFs and converting it to TEI P5 XML for the Buddhist Digital Resource Center (BDRC).

---

## Project Structure

```
├── convert_pdf_to_xml.py   # Main entry point — orchestrates the full pipeline
├── config.py               # Paths, IDs, and directory configuration
├── pdf_extract.py          # PDF text extraction (PyMuPDF or pytiblegenc)
├── normalization.py        # Unicode and Tibetan-specific text normalization
└── tei_generator.py        # TEI P5 XML body builder and document emitter
```

---

## Requirements

```
Python 3.10+
pymupdf          >= 1.23     pip install pymupdf
pytiblegenc                  pip install git+https://github.com/buda-base/py-tiblegenc.git
```

`pytiblegenc` is only required when using `--extractor pytiblegenc`. The default `pymupdf` extractor works without it.

---

## Configuration (`config.py`)

Edit `config.py` before running:

```python
IE_ID = "IE3KG647"           # BDRC Internet Archive entity ID

BASE_DIR = Path("/path/to/working/directory")

# Input: PDFs live under BASE_DIR / IE_ID / sources / <VE_ID> /
SOURCES_DIR  = BASE_DIR / IE_ID / "sources"
TOPROCESS_DIR = BASE_DIR / IE_ID / "toprocess"

# Output
OUTPUT_DIR        = BASE_DIR / f"{IE_ID}_output"
ARCHIVE_DIR       = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# Optional header/footer cropping (fractions of page height, 0.0 = off)
CROP_HEADER_FRACTION: float = 0.00   # e.g. 0.08 strips top 8%
CROP_FOOTER_FRACTION: float = 0.00   # e.g. 0.07 strips bottom 7%
```

Running `ensure_directories()` (called automatically by the main script) creates all output directories.

---

## Usage

```bash
# Process all PDFs found under SOURCES_DIR
python convert_pdf_to_xml.py

# Process a single VE folder
python convert_pdf_to_xml.py --ve VE1ER999

# Process a single PDF by path
python convert_pdf_to_xml.py --single TI596-01-001.pdf
python convert_pdf_to_xml.py --single VE1ER999/TI596-01-001.pdf

# Choose extractor
python convert_pdf_to_xml.py --extractor pymupdf       # default
python convert_pdf_to_xml.py --extractor pytiblegenc

# Header/footer crop (overrides config values)
python convert_pdf_to_xml.py --crop-top 0.08 --crop-bottom 0.07

# Skip font-size tagging or Unicode normalization
python convert_pdf_to_xml.py --no-font-tags
python convert_pdf_to_xml.py --no-normalization

# Organize flat PDFs into VE sub-folders under toprocess/
python convert_pdf_to_xml.py --assign-flat-toprocess
```

---

## Pipeline Overview

```
PDF file
   │
   ▼
pdf_extract.py          Extract raw text with font-size tags
   │                    One \n per visual line; ZZZZ marks page breaks
   ▼
normalization.py        Unicode NFC, Tibetan-specific space rules,
   │                    Wingdings/PUA removal, reorder combining marks
   ▼
tei_generator.py        Classify font sizes → <hi rend="head/small">
   │                    Map \n → <lb/>,  page breaks → <pb/>
   ▼
TEI P5 XML              Output written to OUTPUT_DIR/archive/<VE_ID>/UT*.xml
```

---

## `pdf_extract.py` — Detailed Reference

This module handles all PDF-to-text extraction. It supports two backends and contains five bug-fix layers specific to Monlam/Dedris font PDFs.

### Extractors

#### `pymupdf` (default)

Uses `page.get_text("rawdict")` from [PyMuPDF](https://pymupdf.readthedocs.io/). Operates at the individual character level, reading each glyph's Unicode codepoint and `(x, y)` origin from the PDF content stream.

- Lines within the same visual row (Y midpoints within `3.0 pt`) are merged and sorted left-to-right.
- Font size per span is embedded as `<fs:N>` tags so downstream code can distinguish headings from body text.
- Suited to **MonlamUniOuChan** Unicode PDFs (the majority of modern BDRC source files).

#### `pytiblegenc`

Uses `pytiblegenc.pdf_to_txt()` — a library tuned for legacy Tibetan PDFs. Line-break semantics follow that library's layout engine. Header/footer cropping is applied via the same redacted temp PDF mechanism as the `pymupdf` path.

### Output Format

```
<fs:19>༄༅། །བར་དོ་ཐོས་གྲོལ།
<fs:15>རྒྱལ་བའི་གསུང་རབ་ལས་བཏུས་པ།
ZZZZ
<fs:15>ལེའུ་དང་པོ།
...
```

- `<fs:N>` — font size tag (points, rounded to nearest integer)
- `ZZZZ` — page break marker (`PAGE_BREAK_STR`)
- One `\n` per visual line

### Public API

```python
from pdf_extract import extract_pdf_to_text
from pathlib import Path

text = extract_pdf_to_text(
    pdf_path  = Path("TI1049-01-001.pdf"),
    extractor = "pymupdf",        # or "pytiblegenc"
    crop_top  = 0.0,              # fraction of page height to redact at top
    crop_bottom = 0.0,            # fraction of page height to redact at bottom
)
```

---

## Bug Fixes in `pdf_extract.py`

The following five issues were diagnosed by character-level inspection of `rawdict` output and rasterised page comparisons, and are corrected in the `pymupdf` extraction path.

---

### Fix 1 — Phantom space detection rule

**Symptom:** Spurious spaces inside Tibetan syllables, e.g. `སུ མ་ཅུ ་པ` instead of `སུམ་ཅུ་པ`.

**Root cause:** Legacy Monlam/Dedris fonts encode combining marks (vowel signs, subscript consonants) as separate glyphs whose `x`-origin is shifted *left* of the base character's advance position. PyMuPDF materialises this layout gap as a `U+0020` space character. These phantom spaces carry no linguistic meaning.

**Fix:** A space is discarded when `space_x < prev_char_x + 1.5 pt`. Real inter-word spaces always advance at least 4–5 pt rightward, so they are never affected.

```
Phantom:  ས(x=110)  ུ(x=122)  SPACE(x=116)  མ(x=122)   ← space_x(116) < prev_x(122) ✓ drop
Real:     །(x=129)  SPACE(x=134)  རྭ(x=139)              ← space_x(134) > prev_x(129) ✓ keep
```

---

### Fix 2 — WinAnsi vowel glyph mis-mappings

**Symptom:** Latin Extended characters appearing inside Tibetan text, e.g. `ཚŀགས་` instead of `ཚོགས་`, and `ཚĲས་` instead of `ཚེས་`.

**Root cause:** Each page in these PDFs contains two instances of `MonlamUniOuChan2`: one CID/Identity-H encoded (correct) and one WinAnsi-encoded. The WinAnsi instance has a broken `ToUnicode` table that maps Tibetan vowel glyph slots to Latin Extended codepoints.

**Fix:** A correction table is applied per character before it is appended to the output:

| Extracted (wrong) | Codepoint | Correct | Codepoint | Tibetan name |
|---|---|---|---|---|
| `ŀ` | U+0140 | `ོ` | U+0F7C | Vowel sign O |
| `Ĳ` | U+0132 | `ེ` | U+0F7A | Vowel sign E |
| `Ĩ` | U+0128 | `ི` | U+0F72 | Vowel sign I |

---

### Fix 3 — Cross-span phantom spaces

**Symptom:** Some phantom spaces were not removed even after Fix 1, e.g. `འགྲེམས་` extracted as `འགྲ ེམས་`.

**Root cause:** The previous-character pointer (`prev_char_obj`) was reset to `None` at the start of each font span. A phantom space at position 0 of span N — whose true preceding glyph is the last character of span N-1 — had no previous character to compare against and was therefore passed through unchecked.

**Fix:** `span_prev_char_obj` is now threaded continuously across all spans within a single visual line, so cross-span boundaries are handled identically to within-span boundaries.

---

### Fix 4 — Near-zero-advance phantom spaces

**Symptom:** Residual spaces after Fix 1, e.g. `མི ང་` instead of `མིང་`, on lines where the vowel glyph was corrected by Fix 2.

**Root cause:** The corrected vowel character (e.g. `ི` restored from `Ĩ`) sits at virtually the same `x` position as the phantom space that follows its WinAnsi span — the advance is only ~0.2–0.3 pt (sub-pixel rounding noise), making `space_x` slightly *greater* than `prev_x`. The original strict `space_x < prev_x` rule did not catch this.

**Fix:** The threshold `space_x < prev_x + 1.5 pt` (introduced as the combined Fix 1+4 rule) covers both negative-advance and near-zero-advance phantoms. The 1.5 pt value sits in the wide gap between phantom advances (≤ 0.3 pt) and real word-space advances (≥ 4.9 pt).

---

### Fix 5 — Duplicate text layer deduplication

**Symptom:** Every line of text appeared twice in the XML output, e.g.:

```xml
མཛོད་འགྲེལ་མངོན་པའི་རྒྱན། མཛོད་འགྲེལ་མངོན་པའི་རྒྱན།
```

**Root cause:** PDFs exported from Adobe InDesign via Acrobat Distiller can embed every visual line twice in the content stream at identical `(x, y)` coordinates — a side effect of InDesign's overprint simulation or duplicate layer export. PyMuPDF faithfully reports both copies, and after the Y-merge step both land in the same visual row, causing their fragments to be emitted twice.

**Fix:** After collecting `raw_lines` for each page, `_deduplicate_raw_lines()` removes any entry whose `(y_bucket, x0_rounded, text_key)` triple has already been seen. `y_bucket` is `y_mid` rounded to the nearest `_Y_MERGE_TOLERANCE` step to handle sub-pixel coordinate noise between the two copies.

---

## Normalization (`normalization.py`)

Applied after extraction, before TEI generation:

- **Unicode NFC** normalization
- **Line break normalisation** — all `\r\n`, `\u0085`, `\u2028`, `\u2029` → `\n`
- **Zero-width character removal** — ZWS, BOM, Word Joiner, etc.
- **Unicode space mapping** — all non-ASCII spaces (NBSP, em-space, thin-space, tab, etc.) → ASCII space
- **Control character stripping**
- **Tibetan space rules** — removes spaces adjacent to tshegs (U+0F0B) and shads (U+0F0D) per Tibetan typography conventions
- **Wingdings/PUA removal** — strips U+F020–U+F0FF private-use symbols
- **Tibetan Unicode NFD** — decomposes stacked vowel forms (U+0F73, U+0F75, etc.) to canonical sequences; reorders combining marks

---

## TEI Output (`tei_generator.py`)

Each PDF produces one TEI P5 XML file at:

```
OUTPUT_DIR/archive/<VE_ID>/UT<suffix>_<seq:04d>.xml
```

The TEI header contains BDRC-specific identifiers:

```xml
<idno type="bdrc_ie">http://purl.bdrc.io/resource/IE3KG647</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/VE1ER999</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/UT1ER999_0001</idno>
<idno type="src_sha256">...</idno>
```

Font-size classification maps extracted `<fs:N>` tags to TEI inline elements:

| Font size relative to modal body size | TEI markup |
|---|---|
| Larger than body | `<hi rend="head">…</hi>` |
| Body (most common) | *(plain text)* |
| Smaller than body | `<hi rend="small">…</hi>` |

Line breaks become `<lb/>` and page breaks become `<pb/>`.

---

## Checkpoint and Logging

Progress is saved to `CHECKPOINT_DIR/pdf_to_xml_checkpoint.txt` so interrupted runs resume without reprocessing completed files. Logs are written to `LOG_DIR/pdf_to_xml.log`.

---

## Known Limitations

- The `pymupdf` extractor currently handles **MonlamUniOuChan1/2** fonts. Other legacy Tibetan fonts (Dedris, TibetanMachine) may require additional glyph correction entries in `_MONLAM_GLYPH_CORRECTIONS`.
- Multi-column layout is not supported. Pages are treated as a single reading stream sorted top-to-bottom, left-to-right.
- Scanned (image-only) PDFs produce no text output. OCR is not included in this pipeline.
