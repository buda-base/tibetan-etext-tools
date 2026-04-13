# Tibetan PDF Folder Router

**`route_folders.py`** — Single-pass classifier that inspects every PDF in a folder tree once and routes each top-level work folder (IE_ID) to the correct extraction tool, eliminating the need to run all folders through multiple tools and sort results manually.

---

## The Problem This Solves

Previously, processing N folders required:

1. Run all N folders through PyMuPDF → get output A
2. Run all N folders through py-tiblegenc → get output B
3. Manually compare A and B to decide which tool works per folder
4. Handle failures from both tools separately

This is **O(2N) compute + manual sorting**. For 1000 folders with subfolders, this wastes hours.

**This script scans each PDF exactly once** and assigns every IE_ID folder to the right tool in the same pass — **O(N), no manual work**.

---

## Quick Start

```bash
# Install dependencies
pip install pymupdf pdfminer.six --break-system-packages
pip install git+https://github.com/buda-base/py-tiblegenc.git --break-system-packages

# Run
python route_folders.py /path/to/bdrc_etext_sync/ --out ./results/

# For large collections (parallel)
python route_folders.py /path/to/bdrc_etext_sync/ --out ./results/ --workers 8

# See every font detected per file
python route_folders.py /path/to/bdrc_etext_sync/ --verbose
```

---

## Output Files

Running the script produces **6 CSV files** in the `--out` directory:

```
results/
├── use_pymupdf.csv        🟢  Run these with PyMuPDF
├── use_pytiblegenc.csv    🔵  Run these with py-tiblegenc
├── needs_review.csv       🟡  Require manual investigation
├── not_convertible.csv    🔴  Scanned images — OCR only
├── all_folders.csv            Every IE_ID (combined summary)
└── file_detail.csv            Per-file breakdown for auditing
```

---

## Output File Details

### `use_pymupdf.csv` 🟢

**Route: `USE_PYMUPDF`**

Folders where `fitz.page.get_text()` extracts Tibetan Unicode text directly.

**How a folder gets here:**
- Fonts are CID/Identity-H type with a `/ToUnicode` map embedded
- Page content contains Tibetan Unicode characters (U+0F00–0FFF) confirmed by sampling
- Font names match known Unicode Tibetan fonts: Monlam, Jomolhari, Noto Tibetan, DDC Uchen, Kailasa, Qomolangma, etc.
- No legacy-encoded pages detected

**What to do:** Feed IE_IDs from this list directly into your PyMuPDF extraction pipeline.

```python
import fitz
doc = fitz.open("file.pdf")
for page in doc:
    text = page.get_text()   # returns clean Tibetan Unicode
```

---

### `use_pytiblegenc.csv` 🔵

**Route: `USE_PYTIBLEGENC`**

Folders using pre-Unicode legacy Tibetan fonts **that py-tiblegenc already knows** via its `glyph_db.csv`.

**How a folder gets here:**
- Fonts are WinAnsi or Custom encoded (pre-Unicode encoding)
- Font name OR glyph hash matches an entry in py-tiblegenc's glyph database
- Known font families: Dedris, Ededris, Khamdris, Drutsa, Narthang, Ume, Sama, TibetanMachine, TibetanMachineWeb, DzongkhaCalligraphic, TibetanChogyal, LTibetan, LMantra, etc.

**What to do:** Feed IE_IDs from this list into py-tiblegenc's `DuffedTextConverter`.

```python
from pytiblegenc import DuffedTextConverter, build_font_hash_index_from_csv
# Use converted_txt_from_pdf() from demo.py
txt = converted_txt_from_pdf("file.pdf")
```

---

### `needs_review.csv` 🟡

**Route: `NEEDS_REVIEW` or `MIXED`**

Folders that cannot be processed automatically without additional work. Two sub-cases:

#### Sub-case A: `NEEDS_REVIEW` — Unknown legacy font
- Font encoding is WinAnsi/Custom (confirmed legacy Tibetan)
- Font name is **not** in py-tiblegenc's `glyph_db.csv`
- Common examples: `TCRCYoutso`, `TT9E1Ao00`, `TTD4Co00–TTD5Do00`
- py-tiblegenc cannot convert these until the font's glyph shapes are mapped

**What to do:**
1. Check the `unknown_legacy_fonts` column to see which fonts are unrecognised
2. Extract the font from the PDF using fontTools and add glyphs to the glyph database
3. Or contact `help@bdrc.io` — BDRC may already have mappings in progress
4. Once glyphs are mapped, re-run to verify route changes to `USE_PYTIBLEGENC`

#### Sub-case B: `MIXED` — IE_ID contains multiple encoding types
- Some PDFs inside the IE_ID are Unicode → `USE_PYMUPDF`
- Other PDFs inside the same IE_ID are legacy → `USE_PYTIBLEGENC` or `NEEDS_REVIEW`
- Different subfolders need different extractors

**What to do:**
1. Open `file_detail.csv` and filter by the `ie_id`
2. Each file row shows its own `route` — process files individually

---

### `not_convertible.csv` 🔴

**Route: `NOT_CONVERTIBLE`**

Folders where all PDFs are scanned raster images with no text layer at all.

**How a folder gets here:**
- Every page sampled returns 0 characters from `fitz.get_text()`
- Every page has 1+ embedded raster images (CCITTFax, JPEG, etc.)
- No fonts are present in the PDF — the "text" is pixels in an image

**What to do:**
- These cannot be converted by text extraction tools (PyMuPDF or py-tiblegenc)
- OCR is required: Tesseract with the Tibetan language pack, or a specialist service
- Keep these in a separate `cannot_convert/` folder as noted in the spec

---

### `all_folders.csv`

Every IE_ID from the scan regardless of route. Use this as the master reference.

Useful for:
- Getting a total count of all work folders
- Filtering/pivoting on `route` in Excel or pandas
- Tracking progress: add a `status` column and update as you process each IE_ID

---

### `file_detail.csv`

One row per PDF file (not per IE_ID). Used for auditing and debugging.

Key columns:
| Column | Description |
|--------|-------------|
| `ie_id` | Top-level folder this file belongs to |
| `route` | This specific file's recommended extractor |
| `tibetan_fonts` | All Tibetan font names found, with class and glyph_db status |
| `unknown_legacy_fonts` | Legacy fonts not in py-tiblegenc — the blocker |
| `unicode_pages` | Pages with confirmed Tibetan Unicode text |
| `legacy_pages` | Pages with legacy-encoded font glyphs |
| `debris_pages` | Pages that are raster images (no text) |

---

## CSV Column Reference

All route CSVs share the same columns:

| Column | Values | Description |
|--------|--------|-------------|
| `ie_id` | e.g. `W1234` | Top-level folder name directly under the scanned root |
| `route` | see below | Recommended extractor |
| `route_description` | text | Human-readable explanation of why this route was assigned |
| `total_files` | integer | Number of PDFs inside this IE_ID (including subfolders) |
| `font_classes` | e.g. `UNICODE_TIBETAN` | Encoding type(s) found: `UNICODE_TIBETAN`, `LEGACY_TIBETAN`, `NON_UNICODE` |
| `tibetan_font_names` | pipe-separated | Actual font names found, e.g. `MonlamUniOuChan2 \| TCRCYoutso` |
| `unknown_legacy_fonts` | pipe-separated | Legacy fonts not in glyph_db — only present when `route=NEEDS_REVIEW` |
| `pymupdf_files` | integer | Files in this IE_ID routed to PyMuPDF |
| `pytiblegenc_files` | integer | Files routed to py-tiblegenc |
| `needs_review_files` | integer | Files needing manual investigation |
| `not_convertible_files` | integer | Files that are scanned images |

### Route Values

| Route | Meaning |
|-------|---------|
| `USE_PYMUPDF` | Direct extraction with `fitz.get_text()` |
| `USE_PYTIBLEGENC` | Legacy glyph mapping with py-tiblegenc |
| `NEEDS_REVIEW` | Unknown legacy font — manual glyph mapping required |
| `NOT_CONVERTIBLE` | Scanned image — OCR required |
| `MIXED` | Multiple extractors needed within the same IE_ID |
| `EMPTY` | No PDFs found or all pages blank |

---

## Font Classification Logic

The script identifies each font using this priority chain:

```
font name matches LEGACY_PATTERNS?   → LEGACY_TIBETAN
font name matches UNICODE_PATTERNS?  → UNICODE_TIBETAN
font name matches LATIN_PATTERNS?    → LATIN_OTHER
CID/Identity-H encoding?
  → has /ToUnicode?  YES → UNICODE_TIBETAN
                     NO  → NON_UNICODE
WinAnsi or Custom encoding?          → LEGACY_TIBETAN
else                                 → UNKNOWN
```

**Known legacy font families** (classified as `LEGACY_TIBETAN`):
TCRCYoutso, Youtso, TibetanMachine, TibetanMachineWeb, TibtnMachine, TibMachUni, Sambhota, Pedurma, Druk, Jamyang, CDAC, Gist, Dedris, Ededris, Khamdris, Drutsa, Narthang, Ume, Sama/Samb/Samc, TibetanCalligraphic, TibetanChogyal, TibetanClassic, DzongkhaCalligraphic, LTibetan, LMantra, `TT[0-9A-F]{4}` (embedded CFF Type1 fonts from old pdflatex Tibetan)

**Known Unicode Tibetan font families** (classified as `UNICODE_TIBETAN`):
Monlam (MonlamUniOuChan*), Jomolhari, Noto Tibetan, DDC Uchen, Kailasa, Kokonor, Microsoft Himalaya, Tibetan Machine Uni, Qomolangma

---

## py-tiblegenc Glyph DB Check

For every `LEGACY_TIBETAN` font, the script checks if py-tiblegenc can convert it using two methods:

**Step 1 — Name lookup (fast):** Is the base font name directly in `glyph_db.csv`? The database contains 221 PostScript font names across families like Dedris, Ume, TibetanMachine, etc.

**Step 2 — Glyph hash (slower):** If the name is not found, `identify_pdf_fonts_from_db()` is called. This extracts the actual font program from the PDF, computes glyph shape hashes, and compares against the database. Catches cases where the font is renamed but uses the same glyphs.

Result is recorded in `file_detail.csv` as `glyph_db:YES` or `glyph_db:NO` per font.

---

## Folder Structure Assumption

```
root/                        ← what you pass as the argument
├── IE2KG238120/             ← IE_ID (one row in output CSVs)
│   ├── vol001/
│   │   ├── TI0001.pdf
│   │   └── TI0002.pdf
│   └── vol002/
│       └── TI0003.pdf
├── IE3CN10192/              ← IE_ID
│   └── TI0004.pdf
└── ...
```

The script groups all PDFs under `IE2KG238120/` (regardless of subfolder depth) into a single IE_ID entry.

---

## CLI Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `root` | required | Root directory to scan |
| `--out DIR` | `.` | Output directory for CSVs |
| `--sample N` | `20` | Pages to sample per PDF (0 = all pages) |
| `--all-pages` | off | Sample every page (slower, more accurate) |
| `--workers N` | `1` | Parallel threads (try 4–8 for large sets) |
| `--verbose` | off | Print font details per file while scanning |

---

## Troubleshooting

**All folders showing `(no fonts detected)`**
→ Was a previous bug caused by `pdffonts` CLI column-width parsing. Now fixed — the script uses PyMuPDF (`fitz`) directly to read the PDF object model.

**Legacy folders all showing `NEEDS_REVIEW` instead of `USE_PYTIBLEGENC`**
→ py-tiblegenc is not installed, or `glyph_db.csv` could not be loaded. Check startup output for `[py-tiblegenc] not available`.

**A known-convertible folder shows `NEEDS_REVIEW`**
→ The font may be in py-tiblegenc's database but under a different PostScript name. Add the font name to `LEGACY_PATTERNS` in the script, or submit a glyph mapping to the BDRC team.

**`MIXED` folders**
→ Open `file_detail.csv`, filter by `ie_id`, and look at individual file routes. Process PyMuPDF-routed files first, then handle legacy files separately.
