# IE1KG25273 PDF → TEI XML

Converts Tibetan PDFs for **IE1KG25273** into TEI XML using **`convert_pdf_to_xml.py`** and **PyMuPDF** `page.get_text("rawdict")`.

The PDFs are expected to use **MonlamUniOuChan** (or similar) fonts that are already Unicode-encoded. PyMuPDF resolves ToUnicode/CMap more reliably than pdfminer-style paths, which can mis-map CIDs to stray Latin **`m`**.

## Requirements

- Python 3.10+
- **PyMuPDF** — `pip install pymupdf` (required for extraction and for physical crop/redaction when cropping is enabled)
- **natsort** — `pip install natsort`

## Data layout (`config.py`)

Set **`BASE_DIR`** to your deployment root. The checked-in example points at a local `pdf_convert_5/1-11` tree; change **`BASE_DIR`** for your machine.

| Path | Role |
|------|------|
| `BASE_DIR / IE1KG25273 / sources` | Input PDFs under `sources/<VE_ID>/` (volume ID = subfolder name). |
| `BASE_DIR / IE1KG25273 / toprocess` | Folders **`IE1KG25273-<VE_ID>`** for optional `.doc` files (SHA256 in TEI header when present). |
| `BASE_DIR / IE1KG25273_output` | `archive/<VE_ID>/UT*.xml` TEI output; `sources/<VE_ID>/` receives copies of PDFs (and matching DOC when found). |

Logs: **`LOG_DIR / pdf_to_xml.log`**. Conversion checkpoint: **`CHECKPOINT_DIR / pdf_to_xml_checkpoint.txt`**.

### Header / footer redaction

`CROP_HEADER_FRACTION` and `CROP_FOOTER_FRACTION` in **`config.py`** are fractions of **`page.rect` height** (0.0 = off; typical 0.07–0.12). When non-zero, **`create_cropped_pdf`** builds a **temporary PDF** with those bands **physically redacted** (`add_redact_annot` + `apply_redactions`, text removed—not CropBox-only hiding), then extraction runs on that temp file.

**CLI overrides:** `--crop-top` and `--crop-bottom` (each 0.0–0.49) set the same globals for that run. If omitted, **config** values apply.

## How to run

```bash
cd PDF_XML/F/IE1KG25273

# All PDFs under sources/<VE_ID>/
python3 convert_pdf_to_xml.py

# One volume
python3 convert_pdf_to_xml.py --ve VE1ER999

# Single file (path relative to sources/)
python3 convert_pdf_to_xml.py --single VE1ER999/TI596-01-001.pdf

# Flat PDFs at sources/*.pdf: assign across VEs using toprocess folders
python3 convert_pdf_to_xml.py --assign-flat-toprocess

# Redact top/bottom bands before extraction (overrides config for this run)
python3 convert_pdf_to_xml.py --crop-top 0.09 --crop-bottom 0.08

# Disable font-size → TEI <hi> markup, or full Unicode normalization
python3 convert_pdf_to_xml.py --no-font-tags
python3 convert_pdf_to_xml.py --no-normalization
```

With **`--no-normalization`**, full NFC/Tibetan normalization is skipped, but **Wingdings PUA** stripping (`U+F020–U+F0FF`) still runs as a safety net.

## Pipeline

1. **Extract** — `extract_pdf_to_text`: `rawdict`, per-span **`<fs:N>`**, Wingdings spans skipped (`_is_wingdings_font`), optional redaction when crop fractions are non-zero.
2. **Simplify font sizes** — `simplify_font_sizes` merges adjacent size segments where configured.
3. **Normalize** — `normalize_unicode`: NFC, spaces, stray Latin **`m`** cleanup (`remove_stray_latin_m`), **Wingdings PUA** removal, Tibetan Unicode normalization (unless `--no-normalization`).
4. **Text fixes** — `fix_mixed_dedris_patterns` (`tei_generator`): leftover Dedris-like ASCII next to Tibetan (dots, braces, commas, etc.). **ASCII `(` / `)` are not mapped to Tibetan** here, so gloss parentheses from Unicode PDFs stay literal. **`fix_toc_leader_dots`**, **`fix_paren_ya_before_de_yang`** (narrow fallback, e.g. legacy `ཡདེ་ཡང་` → `(དེ་ཡང་`).
5. **Font markup** — Classify sizes → `<large>` / `<small>` (or strip `<fs:>` if `--no-font-tags`).
6. **TEI body** — `convert_markup_to_tei` inserts **`<pb/>`** / **`<lb/>`**, strips page-number/header artefacts, maps to **`<hi rend="head|small">`**, then **`post_process_body`** and empty-line cleanup.

### `<lb/>` and printed lines

Each **newline** from extraction (one PyMuPDF **line** in `rawdict`) becomes a **`<lb/>`** in TEI. That follows **layout in the PDF**, not Tibetan sentence boundaries. MuPDF may emit two `line` objects where the printed page still reads as one phrase. Merging those would need an extra heuristic, not the current default.

## Files in this folder

| File | Purpose |
|------|---------|
| `convert_pdf_to_xml.py` | CLI: PyMuPDF `rawdict` extraction, redaction, normalization, TEI assembly |
| `config.py` | `IE_ID`, `BASE_DIR`, paths, `CROP_HEADER_FRACTION` / `CROP_FOOTER_FRACTION` |
| `normalization.py` | Unicode + Tibetan normalization, stray `m`, Wingdings PUA strip |
| `tibetan_text_fixes.py` | `<hi>` spacing, TOC leaders, `fix_paren_ya_before_de_yang` |
| `tei_generator.py` | `fix_mixed_dedris_patterns`, `post_process_body`, `generate_tei_xml`, SHA256 helper |
| `dedris_converter.py` | Dedris conversion helpers and conversion stats (logging/stats in this pipeline) |
