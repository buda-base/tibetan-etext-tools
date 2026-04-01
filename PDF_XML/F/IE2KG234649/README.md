# IE2KG234649 — PDF to TEI XML

Convert Tibetan PDFs to TEI XML with **pytiblegenc** (pdfminer), optional **page cropping** (PyMuPDF), **Monlam-oriented manual CID overrides** in `glyph_decoder.py`, **normalization**, **tibetan_text_fixes**, and **tei_generator**.

CID-keyed fonts (e.g. MonlamUniOuChan1/2) often emit `(cid:N)` where ToUnicode is incomplete; see **`CID_MAPPING_README.md`** for the problem, current partial map, and how to extend **`DEFAULT_CID_TO_UNICODE_OVERRIDES`** in `glyph_decoder.py`.

## Requirements

- **Core:** `pytiblegenc`, `pdfminer.six`, `fonttools`, `natsort`
- **Optional:** `pymupdf` (or legacy `fitz`) — only if you use `--crop-top` / `--crop-bottom`

```bash
pip install pytiblegenc pdfminer.six fonttools natsort pymupdf
```

## Main entry point

From this directory, after editing **`config.py`** (`IE_ID`, `BASE_DIR`, `SOURCES_DIR`, `TOPROCESS_DIR`, output paths):

```bash
python3 convert_pdf_to_xml.py / test.py
```

The docstrings in `convert_pdf_to_xml.py` / `config.py` may still mention other IE ids from a copied template; treat **`config.py`** as the source of truth for your machine.

Common flags (see `--help`): `--ve`, `--single`, `--assign-flat-toprocess`, `--no-font-tags`, `--no-normalization`, `--crop-top`, `--crop-bottom`.

## Files required for normal conversion

These are **imported** by `convert_pdf_to_xml.py` for a normal batch or single-file run.

| Role | Path |
|------|------|
| CLI / orchestration | `convert_pdf_to_xml.py` |
| Paths and IDs | `config.py` |
| PUA + Monlam CID overrides + pytiblegenc patch | `glyph_decoder.py` |
| Unicode normalization | `normalization.py` |
| Post-extract fixes (e.g. `<hi>`, TOC dots) | `tibetan_text_fixes.py` |
| Conversion stats | `dedris_converter.py` |
| TEI output | `tei_generator.py` |

**Data:** CID/PUA tables live **inside** `glyph_decoder.py` (`DEFAULT_PUA_TO_UNICODE_OVERRIDES`, `DEFAULT_CID_TO_UNICODE_OVERRIDES`). There is no separate JSON map file in this IE.

