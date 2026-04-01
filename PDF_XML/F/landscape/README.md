# Landscape Book PDF → TEI

This folder converts **landscape, two-column** Tibetan PDFs (pytiblegenc / pdfminer) into **TEI XML**. It extends the generic `SRC_CODE` idea with column-aware extraction, vertical crop bands, and TEI cleanup tuned for 2-up table-of-contents layouts.

The **instance identifier** (`IE_ID`, e.g. `IE1PD159441` in `config.py`) controls directory names under `BASE_DIR` and the `{IE_ID}-VE*` folders in `toprocess/`.

## Requirements

- Python 3.10+ (recommended)
- **pytiblegenc** (Dedris / Tibetan PDF text extraction), e.g.  
  `pip install git+https://github.com/buda-base/py-tiblegenc.git`
- **natsort** (used for stable PDF / folder ordering), e.g. `pip install natsort`
- Dependencies pulled in with pytiblegenc (e.g. **pdfminer.six**)


## Data layout (`config.py`)

Set **`BASE_DIR`** to your project root. Typical layout (names follow `IE_ID`):

| Path (conceptual) | Role |
|-------------------|------|
| `BASE_DIR / IE_ID / sources` | Input tree: PDFs live under **`sources/<VE_ID>/`** (volume ID = immediate subfolder name). |
| `BASE_DIR / IE_ID / toprocess` | Folders named **`{IE_ID}-<VE_ID>`** for optional matching **`.doc`** files (SHA256 in TEI). Also supplies VE lists when using **`--assign-flat-toprocess`**. |
| `BASE_DIR / IE_ID_output` | **`archive/<VE_ID>/UT*.xml`** TEI output; **`sources/<VE_ID>/`** receives copies of converted PDFs (and optional DOC). |


Logs and checkpoints: `LOG_DIR` / `CHECKPOINT_DIR` under `BASE_DIR`.

## Extraction settings (`config.py`)

| Setting | Role |
|--------|------|
| `PDF_TWO_COLUMN_LANDSCAPE` | If `True`, each page is read as two vertical bands (helps reversed TOC order on 2-up pages). |
| `PDF_COLUMN_ORDER` | `"lr"` = left column then right; `"rl"` if the right column should be read first. |
| `PDF_COLUMN_SPLIT` | Horizontal split between columns (0–1), usually `0.5`. |
| `PDF_BOXES_FLOW` | Optional pdfminer `LAParams.boxes_flow` (float or `None`). |
| `PDF_EXTRACT_REGION` | Optional full-page `[x, y, w, h]` in relative 0–1 (combined with crop when relative). |
| `CROP_HEADER_FRACTION` / `CROP_FOOTER_FRACTION` | Fraction of **page height** excluded from extraction at top/bottom (no PDF rewrite). With two-column mode, crop is intersected with **each column band** at `PDF_COLUMN_SPLIT`. |

## How to run

```bash
cd PDF_XML/T1/landscape

# All PDFs under sources/<VE_ID>/
python3 convert_pdf_to_xml.py

# One volume folder
python3 convert_pdf_to_xml.py --ve VE1ER1014

# Single file (path under sources/)
python3 convert_pdf_to_xml.py --single VE1ER1014/TI551-01-001.pdf

# Optional UT sequence for --single (default: next after max in archive)
python3 convert_pdf_to_xml.py --single VE1ER1014/TI551-01-001.pdf --sequence 2

# Flat PDFs at sources/*.pdf: assign across VEs using toprocess/{IE_ID}-VE* folders
python3 convert_pdf_to_xml.py --assign-flat-toprocess

# Two-column overrides (also see config)
python3 convert_pdf_to_xml.py --two-column
python3 convert_pdf_to_xml.py --no-two-column
python3 convert_pdf_to_xml.py --column-order rl --column-split 0.5
python3 convert_pdf_to_xml.py --boxes-flow 0.5

# Crop (overrides config fractions for that run)
python3 convert_pdf_to_xml.py --crop-top 0.10 --crop-bottom 0.08

# Disable font-size markup or Unicode normalization
python3 convert_pdf_to_xml.py --no-font-tags
python3 convert_pdf_to_xml.py --no-normalization
```

`--crop-top` and `--crop-bottom` must satisfy `0 ≤ value < 0.5`.

## Pipeline (short)

1. **Extract** — `pdf_extract.extract_pdf_to_text_full`: optional two-column passes, optional vertical crop merged into pytiblegenc **region** filtering (glyphs outside the region are ignored).
2. **Font markup** — `<fs:…>` simplified and classified → `<large>` / `<small>` → TEI `<hi rend="head|small">`.
3. **Page-break** — footer artifacts (page numbers, stray tshegs) trimmed before `<pb/>` where patterns match.
4. **TEI** — `tei_generator` / `convert_markup_to_tei`, then **`tibetan_text_fixes`** (spacing, TOC leaders, small-span / volume-title repair, optional stripping of duplicate standalone TOC marker lines, `<hi>` balance).


## Related files

| File | Purpose |
|------|---------|
| `convert_pdf_to_xml.py` | CLI, batch/single conversion, wiring |
| `pdf_extract.py` | Two-column extraction, crop merged into regions |
| `tei_generator.py` | TEI body / header |
| `tibetan_text_fixes.py` | Tibetan-specific TEI text fixes |
| `dedris_converter.py` | Dedris stats / helpers as used here |
| `normalization.py` | Optional Unicode normalization |
