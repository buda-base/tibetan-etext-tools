# TestOCR: PDF → TEI → diff → group → apply

## 1. Configure `config.py`

Edit `config.py`:

- **`IE_ID`** — Edition ID (must match `IE3KG694-VE*` style folders under `toprocess`).
- **Paths** — `BASE_DIR`, `SOURCES_DIR`, `TOPROCESS_DIR`, `OUTPUT_DIR`, `ARCHIVE_DIR`, `SOURCES_OUTPUT_DIR`, `LOG_DIR`, `CHECKPOINT_DIR` (and log/checkpoint file paths) for your machine and corpus layout.
- **`PDF_EXTRACT_REGION`** — Crop `[x, y, width, height]`; values in `(0, 1)` are page-relative. Use `None` or `[]` for full page.

### `PDF_EXTRACT_BACKEND` (three modes)

| Value | Behavior |
|-------|----------|
| `"pytiblegenc"` | Legacy: Dedris + pdfminer layout. |
| `"pymupdf"` | PyMuPDF layout + pytiblegenc per span. |
| `"tesseract"` | Rasterize (same region) + Tesseract; tune `PDF_EXTRACT_TESS_DPI`, `PDF_EXTRACT_TESS_LANG`, `PDF_EXTRACT_TESS_CONFIG` if needed. |

---

## 2. Run `convert_pdf_to_xml.py`

Update `PDF_EXTRACT_BACKEND` (and region/Tesseract settings) in `config.py`, then run as usual:

```bash
python TestOCR/convert_pdf_to_xml.py
```

Optional: `--ve`, `--single`, `--sequence`, `--assign-flat-toprocess`, `--no-font-tags`, `--no-normalization` (see script `--help`).

---

## 3. Diff pipeline (run in this order)

Paths are edited **inside each script** (constants at the top), unless noted.

### (1) `compare_tei_lb.py`

Set:

- `PATH_XML_LEFT`, `PATH_XML_RIGHT` — two TEI XML files to compare.
- `OUTPUT_CSV` — base path for diff output.

With defaults, this also writes `OUTPUT_CSV` with stem `*_correction_dataset.csv` next to it (see `OUTPUT_CORRECTION_CSV` in the file). The **grouping step** expects the correction dataset CSV (`*_correction_dataset.csv`), not the legacy-only file.

```bash
python compare_tei_lb.py
```

### (2) `group_tibetan_csv_diffs.py`

Groups `*_correction_dataset.csv` by `(left_token, right_token)` and writes beside the input:

- `<stem>_grouped.csv`
- `<stem>_grouped.json` (used by `replace_diff.py`)

Set `INPUT_CSV` in the script to your `*_correction_dataset.csv`, then:

```bash
python group_tibetan_csv_diffs.py
```

### (3) `replace_diff.py`

Set in the script:

- `INPUT_XML` — TEI file to patch (usually the “left” XML from the comparison).
- `DIFF_JSON` — the `*_grouped.json` from step (2).
- `ONE_BASED` — if `True`, treat `page_index` / `line_index` in the JSON as 1-based.
- `BODY_ONLY` — if `False`, split `<pb/>` over the whole file, not only `<body>`.

```bash
python replace_diff.py
```

Output: `<INPUT_XML_stem>_modified.xml` next to the input.
Compare the modified xml to the original xml to verify if replacement was done properly.

---

## Dependencies

Install Python packages:

```bash
pip install lxml
pip install pillow
pip install pytesseract
```

You still need whatever your PDF stack uses (e.g. pytiblegenc, PyMuPDF) and a working **Tesseract** binary on `PATH` for OCR mode; `pytesseract` is the Python wrapper to that binary.
