# Crop variant: PDF → TEI XML

This folder holds a **pytiblegenc** (pdfminer-based) pipeline for converting Tibetan PDFs to TEI XML, with **optional header/footer removal** before text extraction. 

## Two entry points

| Script | Cropping | TEI post-fixes |
|--------|----------|----------------|
| **`test.py`** | **Physical redaction** — PyMuPDF `add_redact_annot` + `apply_redactions` blanks top/bottom bands so extractors never see that text (unlike cropbox-only, which can still leave glyphs in the stream). | `fix_hi_tag_syllable_splits`, `fix_tei_flying_vowels` (after `fix_hi_tag_spacing`). |
| **`convert_pdf_to_xml.py`** | **Cropbox** — temporary PDF with `set_cropbox` (visual crop; lighter weight). | Standard: `fix_hi_tag_spacing`, `fix_toc_leader_dots` only (no syllable / flying-vowel TEI pass). |

Use **`test.py`** when running headers/footers must disappear from the extracted string (e.g. repeated page titles in body text). Use **`convert_pdf_to_xml.py`** when cropbox is enough or you want the simpler pipeline.

## Requirements

- Python 3.10+ (recommended)
- **pytiblegenc** — `pip install git+https://github.com/buda-base/py-tiblegenc.git`
- **PyMuPDF** (`pymupdf`) — required for any non-zero crop in both scripts
- **natsort** — `pip install natsort`

## Data layout (`config.py`)

Set **`BASE_DIR`** to your project root. Adjust **`IE_ID`** for each corpus.

| Path | Role |
|------|------|
| `BASE_DIR / IE_ID / sources` | Input PDFs under `sources/<VE_ID>/` (volume ID = immediate subfolder name). |
| `BASE_DIR / IE_ID / toprocess` | Folders `{IE_ID}-<VE_ID>` for optional matching `.doc` (SHA256 in TEI). Also drives `--assign-flat-toprocess`. |
| `BASE_DIR / IE_ID_output` | `archive/<VE_ID>/UT*.xml`; `sources/<VE_ID>/` receives copies of PDFs (and DOC when present). |

Logs: `LOG_DIR / pdf_to_xml.log`. Checkpoints: `CHECKPOINT_DIR / pdf_to_xml_checkpoint.txt`.

Default crop fractions: `CROP_HEADER_FRACTION` / `CROP_FOOTER_FRACTION` in `config.py` (often `0.0`). Override per run with CLI flags on **`test.py`** (`--crop-top` / `--crop-bottom`).

## How to run

```bash
cd PDF_XML/F/crop

# Recommended when headers/footers must be removed from text (physical redaction)
python3 test.py
python3 test.py --ve VE1ER1001
python3 test.py --single VE1ER1001/TI1188-01-001.pdf
python3 test.py --crop-top 0.09 --crop-bottom 0.08

# Alternative: cropbox-only pipeline
python3 convert_pdf_to_xml.py --ve VE1ER1001

# Flat PDFs at sources/*.pdf → split across toprocess VEs
python3 test.py --assign-flat-toprocess

# Disable font-size TEI markup or Unicode normalization
python3 test.py --no-font-tags
python3 test.py --no-normalization
```

`--crop-top` and `--crop-bottom` must satisfy `0 ≤ value < 0.5` (on **`test.py`**; see **`convert_pdf_to_xml.py`** help for its crop flags if they differ).

## Pipeline (short)

1. **Optional crop** — Both scripts pass the temporary cropped/redacted PDF to `pdf_to_txt` when crop fractions are non-zero.
2. **Font sizes** — `<fs:…>` simplified → classified → `<large>` / `<small>` → TEI `<hi rend="head|small">`.
3. **Normalization** — `normalization.normalize_unicode` when enabled.
4. **TEI body** — `convert_markup_to_tei` (`<pb/>`, `<lb/>`), page-number artefact stripping, then **`test.py`-only** syllable / flying-vowel repairs, `post_process_body`, `generate_tei_xml`.

## Related files

| File | Purpose |
|------|---------|
| `test.py` | CLI with redaction cropping + extended TEI fixes |
| `convert_pdf_to_xml.py` | CLI with cropbox cropping |
| `config.py` | `IE_ID`, paths, default crop fractions |
| `tibetan_text_fixes.py` | Flying vowels (raw text), `<hi>` spacing, TOC leaders; TEI helpers `fix_tei_flying_vowels`, `fix_hi_tag_syllable_splits` |
| `tei_generator.py` | TEI header/body |
| `normalization.py` | Unicode / Tibetan normalization |
| `dedris_converter.py` | Conversion stats |
