# IE2KG209991 — Tibetan PDF → TEI XML

This folder converts Tibetan PDFs with **PyMuPDF** (`rawdict`), **Qomolangma-oriented CID remapping** (Private Use Area / glyph ID → Unicode), deduplication of overlaid glyphs, optional header/footer cropping, **normalization**, and **TEI** output via **pytiblegenc**-style layout.

## Main entry point

From this directory (after editing `config.py` paths and `IE_ID` for your machine):

```bash
python convert_main.py
```

See the module docstring in `convert_main.py` for flags (`--ve`, `--single`, `--crop-top`, `--no-normalization`, etc.).

**Configure `config.py`** before running: set `IE_ID`, `BASE_DIR`, and related paths to your local layout (`sources/`, `toprocess/`, output dirs). Values in the repo may point at another machine or IE.

## Files required for normal conversion

| Role | Path |
|------|------|
| CLI / orchestration | `convert_main.py` |
| Paths, IDs, dirs | `config.py` |
| CID → Unicode map loader + remap | `cid_remap.py` |
| Unicode normalization | `normalization.py` |
| Post-layout text fixes | `tibetan_text_fixes.py` |
| Dedris conversion helpers / stats | `dedris_converter.py` |
| TEI XML generation | `tei_generator.py` |
| Primary CID map (runtime) | `qomolangma_cid_map.json` |

**Python dependencies** (typical): PyMuPDF (`pymupdf` / `fitz`), `natsort`, and **pytiblegenc** (see `convert_main.py` import error message).

**Note:** `convert_main.py` loads **only** `qomolangma_cid_map.json` into the global `CIDRemapper`. The files `kailasa_cid_map.json` and `monlamuniouchan2_cid_map.json` are **not** read by the main converter; they are auxiliary artifacts from cmap / font work and can be ignored unless you extend the code to load them per font.

### `cmap/` — build / inspect CMap data

Used when (re)building **`qomolangma_cid_map.json`** or related maps from PDF font CMaps — **not** part of day-to-day PDF→TEI runs.

| Script | Purpose |
|--------|---------|
| `cmap/extract_cmap.py` | Extract CMap text from a PDF (PyMuPDF); sample paths in file. |
| `cmap/extract_cmap2.py` | Font-focused CMap / CID stats → JSON (Monlam / Kailasa oriented). |
| `cmap/extract_pdf_struct.py` | Dump PDF structure / fonts to XML for inspection. |
| `cmap/build_cmap_json.py` | Merge `qomolangma_cmap_*.txt` → `qomolangma_cid_map.json`. |
| `cmap/merge.py` | Merge multiple cmap JSON sources into one map file. |
| `cmap/json_struct.py` | Inspect rawdict / build per-font maps (hardcoded paths). |

