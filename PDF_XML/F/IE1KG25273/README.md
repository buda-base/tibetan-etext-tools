# IE1KG25273 PDF → TEI XML

Converts Tibetan PDFs for **IE1KG25273** into TEI P5 XML via **`convert_pdf_to_xml.py`**.

## Extractors

| Backend | Flag | Line breaks | Notes |
|---------|------|-------------|--------|
| **PyMuPDF** `rawdict` | `--extractor pymupdf` (default) | One `\n` per MuPDF **line** (block → line → span) | Skips **Wingdings** spans. Best for **MonlamUniOuChan** (and similar) PDFs that are already Unicode; ToUnicode/CMap handling avoids many pdfminer-style CID glitches (e.g. stray Latin `m`). |
| **pytiblegenc** | `--extractor pytiblegenc` | From **`pdf_to_txt`** layout (same options as IE3KG664 / Desktop SRC_CODE) | Install: `pip install git+https://github.com/buda-base/py-tiblegenc.git` |


## Requirements

- Python 3.10+
- **PyMuPDF** — `pip install pymupdf`  
  Required for **`pymupdf`** extraction. Also used to build the **redacted temp PDF** when header/footer **crop** is enabled (for **both** extractors).
- **natsort** — `pip install natsort`
- **pytiblegenc** (optional) — only if you use **`--extractor pytiblegenc`**

## Data layout (`config.py`)

Set **`BASE_DIR`** to your deployment root. The checked-in example points at a local tree; change **`BASE_DIR`** for your machine.

| Path | Role |
|------|------|
| `BASE_DIR / IE1KG25273 / sources` | Input PDFs under `sources/<VE_ID>/` (volume ID = immediate subfolder name). |
| `BASE_DIR / IE1KG25273 / toprocess` | Folders **`IE1KG25273-<VE_ID>`** for optional **`.doc`** files (SHA256 in TEI header when a matching DOC exists). |
| `BASE_DIR / IE1KG25273_output` | **`archive/<VE_ID>/UT*.xml`** TEI output; **`sources/<VE_ID>/`** receives copies of PDFs (and matching DOC when found). |

Logs: **`LOG_DIR / pdf_to_xml.log`**. Batch checkpoint: **`CHECKPOINT_DIR / pdf_to_xml_checkpoint.txt`**.

### Header / footer redaction

**`CROP_HEADER_FRACTION`** and **`CROP_FOOTER_FRACTION`** in **`config.py`** are fractions of page height (`0.0` = off; typical **0.07–0.12**). When non-zero, **`pdf_extract.create_cropped_pdf`** writes a **temporary PDF** with those bands **physically redacted** (`add_redact_annot` + `apply_redactions`, text removed—not CropBox-only hiding). Extraction runs on that temp file, then the temp file is deleted.

**CLI:** **`--crop-top`** and **`--crop-bottom`** (each **0.0–0.49**) override config for that run. Building the temp PDF requires **PyMuPDF** even when using **`pytiblegenc`** extraction.

## How to run

```bash
cd PDF_XML/F/IE1KG25273

# Default: all PDFs under sources/<VE_ID>/ (PyMuPDF rawdict)
python3 convert_pdf_to_xml.py

# One volume
python3 convert_pdf_to_xml.py --ve VE1ER999

# Single file (path relative to sources/)
python3 convert_pdf_to_xml.py --single VE1ER999/TI596-01-001.pdf

# pytiblegenc line breaks (IE3KG664-style)
python3 convert_pdf_to_xml.py --extractor pytiblegenc

# Flat PDFs at sources/*.pdf: split across VEs using toprocess IE1KG25273-VE* folders
python3 convert_pdf_to_xml.py --assign-flat-toprocess

# Redact top/bottom bands before extraction
python3 convert_pdf_to_xml.py --crop-top 0.09 --crop-bottom 0.08

# Disable font-size → TEI <hi> markup, or full Unicode normalization
python3 convert_pdf_to_xml.py --no-font-tags
python3 convert_pdf_to_xml.py --no-normalization
```

With **`--no-normalization`**, full NFC/Tibetan normalization is skipped, but **Wingdings PUA** stripping (`U+F020–U+F0FF`) still runs via **`remove_wingdings_private_use`**.

## Pipeline

1. **Extract** — **`pdf_extract.extract_pdf_to_text`**: optional crop temp PDF → string with **`\n`** per layout line, **`ZZZZ`** page markers, per-span **`<fs:N>`** (when the extractor emits font tags).
2. **Simplify font sizes** — **`simplify_font_sizes`** merges adjacent size segments where configured.
3. **Normalize** — **`normalize_unicode`** (unless **`--no-normalization`**): NFC, spaces, stray Latin **`m`**, Wingdings PUA, Tibetan Unicode rules.
4. **Font markup** — Classify sizes → **`<large>`** / **`<small>`** via **`apply_font_markup`**, or strip **`<fs:>`** if **`--no-font-tags`**.
5. **TEI body** — **`convert_markup_to_tei`**: **`<pb/>`** / **`<lb/>`**, strip page-number and header/footer artefacts, map to **`<hi rend="head|small">`**, then **`tei_generator.post_process_body`** and empty-line cleanup.
6. **Document** — **`generate_tei_xml`** wraps the body in **`<p>`** with BDRC-oriented **`teiHeader`**.

Optional **`tibetan_text_fixes`** hooks (e.g. TOC leaders, **`<hi>`** spacing) can be enabled in **`convert_pdf_to_tei`** if you add that module and uncomment the import/calls.

### `<lb/>` and printed lines

Each **newline** from extraction becomes a **`<lb/>`** boundary in TEI. With **`pymupdf`**, that follows MuPDF **`line`** objects; with **`pytiblegenc`**, it follows **`pdf_to_txt`**. Neither encodes Tibetan syntax—only layout—so line breaks may fall in the middle of a phrase.

## Files in this folder

| File | Purpose |
|------|---------|
| `convert_pdf_to_xml.py` | CLI, checkpointing, **`PDF_EXTRACTOR`** / crop globals, font pipeline, **`convert_markup_to_tei`**, orchestration |
| `pdf_extract.py` | **`PAGE_BREAK_STR`**, **`create_cropped_pdf`**, **`extract_pdf_pymupdf`** / **`extract_pdf_pytiblegenc`**, **`extract_pdf_to_text`**, availability flags |
| `config.py` | **`IE_ID`**, **`BASE_DIR`**, directory paths, **`CROP_HEADER_FRACTION`** / **`CROP_FOOTER_FRACTION`**, UT/archive helpers |
| `normalization.py` | **`normalize_unicode`**, **`remove_wingdings_private_use`**, Tibetan/space rules |
| `tei_generator.py` | **`post_process_body`**, **`generate_tei_xml`**, **`calculate_sha256`**, optional stream helpers |
