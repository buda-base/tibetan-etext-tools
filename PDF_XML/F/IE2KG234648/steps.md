# Step-by-step: running IE2KG234648 scripts

This guide describes **when** to use each script and **how** to run them. All command examples assume your shell’s current directory is:

`PDF_XML/F/IE2KG234648`

Use `cd` there first:

```bash
cd /path/to/tibetan-etext-tools/PDF_XML/F/IE2KG234648
```

---

## Part A — One-time setup

### Step 1: Install Python dependencies

```bash
pip install pytiblegenc pdfminer.six fonttools natsort pymupdf
```

- **PyMuPDF** (`pymupdf`) is optional unless you use `--crop-top` / `--crop-bottom`.

### Step 2: Edit `config.py`

1. Set `**BASE_DIR`** to the parent folder that contains your `IE2KG234648` input/output tree (absolute path on your machine).
2. Confirm `**IE_ID**` is `IE2KG234648`.
3. Adjust `**CROP_HEADER_FRACTION**` / `**CROP_FOOTER_FRACTION**` if you want default cropping (or leave `0.00` and use CLI).
4. `**ENABLE_TIBETAN_DECODE_QUALITY_GATE**`: leave `True` unless you intentionally want to skip the TT-cmap fallback (see Part D).

### Step 3: Lay out PDFs

- Put PDFs under `**SOURCES_DIR**` (see `config.py`), typically in volume folders, e.g.  
`…/IE2KG234648/sources/VE1ER1021/TI594-01-001.pdf`.

---

## Part B — Normal conversion (production)

**When to use:** You have PDFs in `sources/` and want TEI XML under `**ARCHIVE_DIR`** (e.g. `…/archive/VE1ER1021/UT*.xml`).

### Step 1: Convert everything assigned to your layout

```bash
python3 convert_pdf_to_xml.py
```

- Uses checkpoints and logs (paths in `config.py`).
- Writes stats to `OUTPUT_DIR` / `pdf_conversion_stats.txt` (see script).

### Step 2: Convert one volume only

```bash
python3 convert_pdf_to_xml.py --ve VE1ER1021
```

Replace `VE1ER1021` with your `VE…` folder name under `sources/`.

### Step 3: Convert a single PDF

```bash
python3 convert_pdf_to_xml.py --single VE1ER1021/TI594-01-001.pdf --ve VE1ER1021
```

- `**--single**`: path relative to `sources/` (or include the `VE/…` prefix).
- `**--ve**`: disambiguates when the same filename exists in multiple VEs.
- `**--sequence N**`: optional; forces UT number `N` instead of “next free” in archive.

### Step 4: Optional — crop headers/footers

**When to use:** Running heads/footers or page numbers pollute body text.

```bash
python3 convert_pdf_to_xml.py --ve VE1ER1021 --crop-top 0.08 --crop-bottom 0.07
```

- Values are **fractions of page height** (e.g. `0.08` ≈ top 8%).
- Requires **PyMuPDF**.

### Step 5: Optional — flat PDFs in `sources/*.pdf`

**When to use:** Some PDFs sit directly in `sources/` (not under `sources/VE…/`) and you want them assigned via `toprocess/IE2KG234648-VE`* rules.

```bash
python3 convert_pdf_to_xml.py --assign-flat-toprocess
```

---

## Part C — Testing / development (`test.py`)

**When to use:**

- You are **debugging** extraction or TEI output without running the full batch.
- You want `**test.py`-specific behavior** (e.g. its crop CLI defaults differ from `convert_pdf_to_xml.py` — run `python3 test.py --help`).

**How:**

```bash
python3 test.py --ve VE1ER1021
python3 test.py --single VE1ER1021/TI594-01-001.pdf --ve VE1ER1021
```

Same general flags as the main converter where implemented (`--help` for the exact list).

---

## Part D — When to change decode behavior

### Disable Tibetan decode-quality gate

**When to use:** You trust the primary extraction, or the fallback causes problems and you need to compare behavior.

```bash
python3 convert_pdf_to_xml.py --no-decode-quality-gate
```

---

## Part E — Diagnostic workflow (fonts & CIDs)

Use this when XML shows `**(cid:123)**`, wrong Latin letters instead of Tibetan, or you are **building overrides** in `glyph_decoder.py`.

### When to use which tool


| Goal                                                 | Script                                                              | Typical order                      |
| ---------------------------------------------------- | ------------------------------------------------------------------- | ---------------------------------- |
| See every glyph: page, font, CID, decoded char       | `dump_font_cids.py`                                                 | 1                                  |
| Summarize counts per `(font, CID)` for the whole PDF | `dump_font_cids.py --summary` then optionally `pool_cid_summary.py` | 2                                  |
| List `(cid:N)` still missing from override tables    | `extract_unmapped_cids.py`                                          | After editing overrides, to verify |


### Step 1: Full or sampled CID dump

```bash
python3 dump_font_cids.py "/full/path/to/file.pdf" -o cids.csv
```

Optional:

- `**--max-pages 5**`: first pages only.
- `**--summary -o cid_counts.csv**`: aggregated counts per page/font/cid (better for large PDFs).

### Step 2 (optional): Pool summary across the document

**When to use:** You have a **summary** CSV and want one row per `(font_normalized, cid)` sorted by frequency (e.g. for TCRC fonts only).

```bash
python3 dump_font_cids.py "/full/path/to/file.pdf" --summary -o book_cid_counts.csv
python3 pool_cid_summary.py book_cid_counts.csv -o book_pooled.csv --only-fonts TCRCYoutso,TCRCBod
```

Use `**--only-fonts ""**` or adjust the flag if you want all fonts (see `pool_cid_summary.py --help`).

### Step 3: Edit `glyph_decoder.py`

**When to use:** Dump shows wrong decode or `(cid:N)` for fonts not fully covered by `utfc.csv`.

- Add or adjust `**_MANUAL_CID_TO_UNICODE_OVERRIDES`** or `**_UTFC_FONT_ALIASES**` as documented in `README.md`.

### Step 4: Check for remaining unmapped CIDs

**When to use:** After updating overrides, confirm nothing is still unmapped for `(cid:…)` extraction.

```bash
python3 extract_unmapped_cids.py "/full/path/to/file.pdf"
```

- Prints suggested `("", …)` lines for `**glyph_decoder.py**`.
- If it prints **“All CIDs are mapped”**, `(cid:N)` overrides cover every CID seen in that run.

### Step 5: Re-run conversion

```bash
python3 convert_pdf_to_xml.py --single VE1ER1021/TI594-01-001.pdf --ve VE1ER1021
```

---

## Part F — Quick reference: script roles


| Script                      | Role                                         |
| --------------------------- | -------------------------------------------- |
| `**convert_pdf_to_xml.py**` | Main batch/single PDF → TEI (production).    |
| `**test.py**`               | Same pipeline for local testing / debugging. |


