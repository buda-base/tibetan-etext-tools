# IE2KG234648 — PDF to TEI XML

Convert Tibetan PDFs into TEI XML using **pytiblegenc** (pdfminer), **TCRC-oriented CID overrides** (`glyph_decoder` + pytiblegenc `utfc.csv`), an optional **Tibetan decode quality gate** with **TrueType cmap–first** fallback (`pdf_cmap_extract`), then normalization, text fixes, and TEI generation.

## Requirements

- Python 3.9+
- **Core:** `pytiblegenc`, `pdfminer.six`, `fonttools`, `natsort`
- **Optional:** `pymupdf` — only for `--crop-top` / `--crop-bottom`

```bash
pip install pytiblegenc pdfminer.six fonttools natsort pymupdf
```

## Main entry point (production)

From this directory, after editing `config.py`:

```bash
python3 convert_pdf_to_xml.py
```

The module docstring in `convert_pdf_to_xml.py` still shows example `IE3KG664` text in places; treat **`config.py`** as the source of truth for `IE_ID` and paths.

See `--help` for `--ve`, `--single`, `--sequence`, `--crop-top`, `--no-decode-quality-gate`, `--assign-flat-toprocess`, etc.

## Configuration (`config.py`)

| Setting | Role |
|--------|------|
| `IE_ID` | Entity id (e.g. `IE2KG234648`) |
| `BASE_DIR` | Root for your machine (absolute path) |
| `SOURCES_DIR` | PDFs under `…/sources` |
| `TOPROCESS_DIR` | `IE2KG234648-VE*` folders (batch hints, optional `.doc` for SHA256) |
| `OUTPUT_DIR` | Conversion output root |
| `ARCHIVE_DIR` | `…/archive/<VE_ID>/UT*.xml` |
| `LOG_DIR` / `CHECKPOINT_DIR` | `pdf_to_xml.log`, resume checkpoint |
| `CROP_HEADER_FRACTION` / `CROP_FOOTER_FRACTION` | Default crop (0 = off); CLI overrides |
| `ENABLE_TIBETAN_DECODE_QUALITY_GATE` | If extraction looks non-Tibetan, retry with TT-cmap-first (`pdf_cmap_extract`) |

`ensure_directories()` runs when the converter starts.

### Example commands

```bash
python3 convert_pdf_to_xml.py
python3 convert_pdf_to_xml.py --ve VE1ER1021
python3 convert_pdf_to_xml.py --single VE1ER1021/TI594-01-001.pdf --ve VE1ER1021
python3 convert_pdf_to_xml.py --single path/under/sources.pdf --ve VE1ER1021 --sequence 3
```

## Files required for normal conversion

These modules are **imported** by `convert_pdf_to_xml.py` and are needed for the standard PDF → TEI run.

| Role | Path |
|------|------|
| CLI / batch orchestration | `convert_pdf_to_xml.py` |
| Paths, IDs, feature flags | `config.py` |
| CID overrides + pytiblegenc patch | `glyph_decoder.py` |
| TT cmap–first fallback extract | `pdf_cmap_extract.py` |
| Decode-quality gate | `tibetan_decode_quality.py` |
| Unicode normalization | `normalization.py` |
| Post-extract string / markup fixes | `tibetan_text_fixes.py` |
| Conversion stats (logging) | `dedris_converter.py` |
| TEI XML build | `tei_generator.py` |

**Data:** `glyph_decoder.py` loads **pytiblegenc**’s bundled **`font-tables/utfc.csv`** at runtime (via the package install path). Manual CID rows live in **`_MANUAL_CID_TO_UNICODE_OVERRIDES`** inside `glyph_decoder.py`. No separate `qomolangma_cid_map.json` in this IE.

**CLI flags (summary):** Unicode normalization and font-size → `<hi rend="…">` are always on. `--no-decode-quality-gate` skips the Tibetan decode check and TT-cmap-first fallback. Crop flags need PyMuPDF.

---

**Other repo files:** `steps.md` is human notes, not executed. CSVs such as `cid_counts.csv` / `book_cid_counts.csv` (if present) are **outputs** from analysis runs, not runtime inputs for the converter.

---

## Pipeline (summary)

1. Optional **crop** → temporary PDF (PyMuPDF).
2. **Extract** with pytiblegenc; **`glyph_decoder.patch_pytiblegenc_cid_decoder`** resolves `(cid:N)` using embedded font maps + **`DEFAULT_CID_TO_UNICODE_OVERRIDES`** (utfc-derived + manual).
3. If **`ENABLE_TIBETAN_DECODE_QUALITY_GATE`**: **`tibetan_decode_quality`** may replace text using **`pdf_cmap_extract.extract_text_tt_cmap_first`** (embedded TT cmap, not PDF ToUnicode only).
4. **Font-size simplification** → **normalization** → Dedris-oriented cleanup where applied.
5. **`tibetan_text_fixes`**: TOC leader dots, Latin mojibake, strip standalone page numbers after `<pb/>`, dedupe consecutive duplicate lines, etc.
6. Markup → TEI via **`dedris_converter`** / **`tei_generator`** (`post_process_body`, **`generate_tei_xml`**).

## Decoding caveats

- Overrides apply when the stream contains **`(cid:N)`**. If the PDF’s **ToUnicode** maps straight to Latin (e.g. `Ç`), CID tables are bypassed until the **quality-gate fallback** runs or you fix the PDF/font path.
- **`fix_pdf_latin_mojibake`** in `tibetan_text_fixes.py` can correct known wrong Latin bytes after extract.
- Extend **`_UTFC_FONT_ALIASES`** / **`_MANUAL_CID_TO_UNICODE_OVERRIDES`** in `glyph_decoder.py` when fonts or CIDs do not match `utfc.csv`.
