# Tibetan PDF → TEI conversion pipeline

Converts BUDA-style worksets (one IE folder per work, with one or more VE
volume folders containing PDFs) into TEI P5 XML, handling both modern
Unicode PDFs (MonlamUniOuChan, Noto, Microsoft Himalaya) and legacy
byte-encoded fonts (TB-Youtso, TCRC Bod-Yig, Esukhia, Chogyal CID, etc.).

This README covers the full end-to-end workflow. For the legacy font
onboarding deep-dive (when you encounter a font the pipeline has never
seen before), jump to **[Adding a new legacy font](#adding-a-new-legacy-font)**.

---

## Table of contents

- [What this pipeline does](#what-this-pipeline-does)
- [Package contents](#package-contents)
- [Quick start](#quick-start)
- [Folder layout](#folder-layout)
- [The two extraction pipelines](#the-two-extraction-pipelines)
- [Bulk conversion](#bulk-conversion)
  - [Discovery & auto-detection](#discovery--auto-detection)
  - [Resume](#resume)
  - [Progress & summary](#progress--summary)
  - [Manifest of per-IE overrides](#manifest-of-per-ie-overrides)
  - [Forwarding extra flags](#forwarding-extra-flags)
- [Single-IE conversion](#single-ie-conversion)
- [Per-PDF debugging](#per-pdf-debugging)
- [Adding a new legacy font](#adding-a-new-legacy-font)
- [Configuration reference](#configuration-reference)
- [Troubleshooting](#troubleshooting)

---

## What this pipeline does

For each input PDF the pipeline:

1. **Optionally redacts headers/footers** (running titles, page numbers)
   either by a top/bottom crop fraction or a `preserve-box` keep-region.
2. **Extracts text** via the hybrid PyMuPDF + pytiblegenc decoder:
   PyMuPDF gives the layout-correct line/span structure, pytiblegenc
   decodes each character against the right font table (Unicode CMap,
   GSUB inversion, or local byte-table CSV).
3. **Normalizes Unicode** (NFC, Tibetan reordering, glyph-artifact
   repair, space cleanup, Wingdings PUA stripping).
4. **Classifies font sizes** into `regular` / `small` / `head` to drive
   `<hi rend="…">` markup.
5. **Emits TEI P5 XML** with one `<pb/>` per page (with `n=` from
   PageLabels when present), `<lb/>` per source line, BDRC-format
   `<idno>` headers, and a SHA-256 of the source DOC (or PDF, if no
   DOC sibling).

The result is one `UT*.xml` per input PDF under `archive/<VE_ID>/`,
plus the original PDFs (and any matching DOC files) copied into
`sources/<VE_ID>/`.

---

## Package contents

```
tibetan-pdf-to-tei/
├── README.md                       ← this file
├── requirements.txt                ← Python deps
├── manifest.example.yaml           ← annotated bulk-driver manifest
│
├── bulk_convert.py                 ← NEW: batch driver over many IEs
├── convert_pdf_to_xml.py           ← single-IE / single-PDF converter
├── config.py                       ← paths, crops, FONT_DIR, footnotes
│
├── pdf_extract.py                  ← PyMuPDF + pytiblegenc hybrid extractor
├── normalization.py                ← Unicode/Tibetan text normalization
├── tei_generator.py                ← TEI P5 body + header emitter
├── gsub_resolver.py                ← GSUB inversion for Monlam subsets
│
├── local_font_tables/              ← drop new legacy-font CSVs here
│   ├── _aliases.csv                ←   name → existing-table map
│   └── tb_youtso.csv               ←   example: TB-Youtso (570 rows)
│
└── tools/                          ← font-onboarding utilities
    ├── font_inspect.py             ←   diagnose unsupported fonts
    └── font_bridge.py              ←   test font ↔ existing-table match
```

`bulk_convert.py` replaces the older `bulk_multi_ie.py`. Its CLI is
mostly compatible (still uses `-r/--root`, `-j/--jobs`, `--ie`, and
`--dry-run`), and it adds `--manifest`, `--force`/`--force-ie`,
incremental resume, a progress bar, and `_bulk_summary.{txt,json}`
reports. See [Bulk conversion](#bulk-conversion).

---

## Quick start

```bash
# 1. Install dependencies (see requirements.txt for pins)
pip install -r requirements.txt

# 2. Lay out your input tree
ROOT/
  IE1KG25273/sources/VE1KG1/foo.pdf       # Unicode PDFs
  IE2KG209991/to_convert/VE2KG1/bar.pdf   # legacy-font PDFs

# 3. Dry-run to see what would happen
python bulk_convert.py -r /path/to/ROOT --dry-run

# 4. Run for real (uses all CPUs up to 8)
python bulk_convert.py -r /path/to/ROOT
```

You'll see a progress bar, then a summary table, then file paths to a
JSON/text summary report. Re-running picks up where it left off.

---

## Folder layout

The pipeline accepts **either** of two conventional input subfolders per
IE, and auto-detects which one a given IE uses:

```
ROOT/                                  ← pass this as --root
├── IE1KG25273/
│   └── sources/                       ← Unicode-pipeline convention
│       └── VE1KG1/
│           └── foo.pdf
├── IE2KG209991/
│   ├── to_convert/                    ← legacy-pipeline convention
│   │   └── VE2KG1/
│   │       └── bar.pdf
│   └── toprocess/                     ← optional, for source DOC sibling lookup
│       └── IE2KG209991-VE2KG1/
│           └── bar.doc                ← SHA-256 source if present
├── IE1KG25273_output/                 ← auto-created by the converter
│   ├── archive/VE1KG1/UT1KG1_0001.xml
│   └── sources/VE1KG1/foo.pdf         (+ foo.doc if found)
├── IE2KG209991_output/
├── logs/
│   ├── IE1KG25273/pdf_to_xml.log      ← per-IE log under bulk mode
│   ├── IE2KG209991/pdf_to_xml.log
│   ├── _bulk_summary.txt              ← bulk-driver report (text)
│   └── _bulk_summary.json             ← same, machine-readable
└── checkpoints/
    ├── IE1KG25273/pdf_to_xml_checkpoint.txt   ← per-PDF resume (within IE)
    ├── IE2KG209991/pdf_to_xml_checkpoint.txt
    └── _bulk_state.json               ← bulk-driver resume (across IEs)
```

A folder is treated as an IE workset if:

- its name matches `IE[A-Z0-9]+` (case-insensitive), **and**
- it contains a `sources/` **or** `to_convert/` subdirectory, **and**
- that subdirectory has at least one `.pdf` somewhere inside.

Non-matching siblings are silently skipped (intentional — handy for
mixing input folders with other working data under the same root).

---

## The two extraction pipelines

Both pipelines share the same converter (`convert_pdf_to_xml.py`) and
extractor (`pdf_extract.py`). The difference is which character-decode
mechanism handles a given font.

### Unicode pipeline

For PDFs whose embedded fonts (Monlam, Noto, Microsoft Himalaya, Tibetan
Machine Uni…) declare a `ToUnicode` CMap, the extractor reads each
glyph's Unicode value directly. When the CMap is missing or mis-encoded
(common in MonlamUniOuChan subsets — vowel signs land in U+0140 etc.),
`gsub_resolver.py` inverts the font's GSUB table to recover the correct
Tibetan codepoint. Provide the full (unsubsetted) font files via
`FONT_DIR` for this to engage.

### Legacy-font pipeline

For PDFs using byte-encoded fonts (TB-Youtso, TCRC Bod-Yig, Esukhia,
Chogyal CID, etc.) where each byte in the encoded stream maps to a
Tibetan glyph through a font-specific table, the extractor delegates
each character to `pytiblegenc.char_converter.convert_string()`.
pytiblegenc ships built-in tables for most published Tibetan fonts;
when you hit one it doesn't know, see
[Adding a new legacy font](#adding-a-new-legacy-font).

### Auto-detection

`bulk_convert.py` peeks at the first PDF in each IE folder, lists its
embedded font names, and picks `legacy` when it sees any of:

```
TB-Youtso, TCRC, TibetanMachine, Bod-Yig, Chogyal, Esukhia,
Sambhota, Qomolangma, DDC-, Jomolhari
```

…else `unicode`. The pipeline *itself* is the same code regardless —
the only effect of the detection is the label in the summary report
and in `_bulk_state.json`. **You don't need to override it manually**
unless you've extended the font lists in unusual ways.

---

## Bulk conversion

```bash
python bulk_convert.py -r ROOT [options] [-- forward-args-to-converter]
```

### Common options

| Flag | Purpose |
|------|---------|
| `-r`, `--root` PATH | Parent directory containing IE*/ worksets (required) |
| `-j`, `--jobs` N | Parallel workers (default: min(CPUs, 8)) |
| `--ie IE_ID` | Process only this IE (repeatable) |
| `--manifest PATH` | YAML/JSON of per-IE overrides |
| `--dry-run` | Report what would run; convert nothing |
| `--force` | Re-run every IE, ignoring resume state |
| `--force-ie IE_ID` | Re-run only this IE (repeatable) |
| `--no-progress` | Suppress the live progress bar |
| `--quiet-children` | Don't echo each child's tail mid-run |

### Discovery & auto-detection

`--dry-run` is the safe first step on any new root. It prints:

```
IE_ID                 PIPE      SUBDIR        PDFs  STATUS      NOTES
--------------------------------------------------------------------------------
IE1KG25273            unicode   sources          7  run         manifest override
IE2KG209991           legacy    to_convert      14  skip
IE3KG88               unicode   sources          3  run         forced
```

Columns:
- **PIPE** — auto-detected pipeline (`unicode` / `legacy`)
- **SUBDIR** — which input folder name was found
- **PDFs** — count of `.pdf` files under that subfolder (recursive)
- **STATUS** — `run` or `skip` based on resume state
- **NOTES** — `manifest override` / `forced` markers

### Resume

State is kept in `<ROOT>/checkpoints/_bulk_state.json`. An IE is skipped
on subsequent runs when it has `status: "ok"` in the state **and** its
`<IE>_output/archive/` directory still contains XML files (so deleting
the output dir forces a clean redo without needing `--force`).

Failed IEs (any non-zero exit from `convert_pdf_to_xml.py`) are
automatically retried on the next run — no flag needed. Use `--force`
or `--force-ie IE_ID` to redo successes.

The state file is written incrementally **as each IE completes**, so a
Ctrl-C halfway through still saves progress for whatever finished.

### Progress & summary

While running, a single-line progress bar on stderr shows completed /
total worksets, percentage, ETA based on the rolling mean of completed
durations, and the last-finished IE. Pass `--no-progress` for CI logs.

At the end (or after Ctrl-C), `<ROOT>/logs/` contains:

- `_bulk_summary.txt` — human-readable per-IE table + failure tails
- `_bulk_summary.json` — same data, machine-readable

The bulk driver exits **0** when every workset succeeded, **1** when one
or more failed, **2** on usage errors (missing root, bad manifest, etc.).

### Manifest of per-IE overrides

Crop fractions, preserve-box coordinates, the `FONT_DIR` for GSUB
resolution, and any other per-IE tuning lives in an optional manifest
file. YAML and JSON are both accepted.

```yaml
# manifest.yaml
defaults:                     # applied to every IE (then overridden per-IE)
  crop_top: 0.05
  crop_bottom: 0.05

IE1KG25273:
  crop_top: 0.10              # overrides default
  preserve_box: [0.11, 0.09, 0.89, 0.82]

IE3KG648:
  preserve_box: [0.12, 0.06, 0.87, 0.86]

IE3KG719:                     # tight footer; opt out of font tags
  preserve_box: [0.11, 0.06, 0.89, 0.80]
  no_font_tags: true

IE2KG999:                     # Unicode pipeline needs full Monlam fonts
  font_dir: /Users/me/fonts/tibetan
  extra_args: ["--no-phantom-space"]
```

Supported keys (hyphens and underscores both accepted):

| Key | CLI equivalent |
|-----|----------------|
| `crop_top` | `--crop-top FRAC` |
| `crop_bottom` | `--crop-bottom FRAC` |
| `preserve_box` | `--preserve-box X0 Y0 X1 Y1` |
| `font_dir` | sets `PDF_BULK_FONT_DIR` env var |
| `no_font_tags` | `--no-font-tags` |
| `no_normalization` | `--no-normalization` |
| `no_extraction_dedup` | `--no-extraction-dedup` |
| `no_phantom_space` | `--no-phantom-space` |
| `extra_args` | list of extra flag tokens (escape hatch) |

To clear a default for one IE, pass the empty value:

```yaml
defaults:
  crop_top: 0.08
IE5KG_FullPage:
  crop_top: 0.0
```

### Forwarding extra flags

Anything after `--` is appended to every converter invocation. Useful
for one-off debugging across the whole batch:

```bash
python bulk_convert.py -r ROOT -- --no-phantom-space --no-extraction-dedup
```

The manifest's per-IE overrides come **before** the forwarded args, so
forwarded flags act as "global on top of manifest" and override
conflicting per-IE values that happen to be identical CLI flags.

---

## Single-IE conversion

For ad-hoc work, hand-debugging, or one-off pipelines, use
`convert_pdf_to_xml.py` directly. Edit `IE_ID` and `BASE_DIR` at the
top of `config.py`, then:

```bash
# Batch all PDFs under <IE>/<sub>/<VE>/*.pdf
python convert_pdf_to_xml.py

# Just one volume
python convert_pdf_to_xml.py --ve VE1KG1

# Just one file
python convert_pdf_to_xml.py --single VE1KG1/foo.pdf

# With crops
python convert_pdf_to_xml.py --crop-top 0.09 --crop-bottom 0.08

# With a tight preserve-box
python convert_pdf_to_xml.py --preserve-box 0.11 0.09 0.89 0.82
```

Full flag list: `python convert_pdf_to_xml.py --help`.

---

## Per-PDF debugging

When extraction looks wrong on a specific PDF, use `--dump-extraction`
to write intermediate text files at each pipeline stage:

```bash
python convert_pdf_to_xml.py \
  --single VE1KG1/foo.pdf \
  --dump-extraction ./debug_out
```

Produces four files in `./debug_out/`:

| File | Content |
|------|---------|
| `foo_01_raw_extract.txt` | Output of `extract_pdf_to_text` (before normalization) |
| `foo_02_after_normalize.txt` | After Unicode normalization |
| `foo_03_pre_tei_markup.txt` | After font-size markup, before TEI conversion |
| `foo_04_tei_body_postprocess.txt` | After TEI body post-processing |

Comparing `01` ↔ `02` exposes normalization bugs; `02` ↔ `03` exposes
font-classification glitches; `03` ↔ `04` exposes TEI-tag placement
issues. To rule out suspected extractor over-correction:

```bash
# Keep narrow spaces PyMuPDF normally drops as font-advance phantoms
python convert_pdf_to_xml.py --single foo.pdf --no-phantom-space

# Keep duplicate text lines (InDesign drop-shadow layers etc.)
python convert_pdf_to_xml.py --single foo.pdf --no-extraction-dedup

# Skip Unicode normalization entirely (keeps Wingdings strip)
python convert_pdf_to_xml.py --single foo.pdf --no-normalization

# Skip font-size <hi rend="…"> markup
python convert_pdf_to_xml.py --single foo.pdf --no-font-tags
```

---

## Adding a new legacy font

When the legacy pipeline hits a font that pytiblegenc doesn't know,
the extracted text will contain literal Latin-PUA characters (`ŀ`, `Ĳ`,
random box characters) where Tibetan should be. The pipeline is designed
to make adding a new font a **30-minute task without code changes**:
drop a CSV (or one line in `_aliases.csv`) into `local_font_tables/`
and the next run picks it up.

### Layout

```
scripts/
├── convert_pdf_to_xml.py
├── pdf_extract.py
├── bulk_convert.py
├── local_font_tables/              ← drop new font tables here
│   ├── _aliases.csv                ← font_name → existing_pytiblegenc_table
│   ├── tb_youtso.csv               ← example: TB-Youtso family (570 rows)
│   └── <your-new-font>.csv         ← future fonts
└── tools/
    ├── font_inspect.py             ← diagnose: which fonts does this PDF need?
    └── font_bridge.py              ← test: does font match an existing table?
```

CSV format (same as upstream `pytiblegenc/tiblegenc.csv`):

```
font_name,decimal_codepoint,tibetan_unicode_string
```

One row per glyph, one CSV per font family. Empty third column = drop
this byte.

### The three-step workflow

#### Step 1 — diagnose

```bash
python tools/font_inspect.py path/to/document.pdf
```

This runs the full extraction pipeline and captures pytiblegenc's
`unhandled_fonts` list, then for each unsupported Tibetan font:

1. Extracts the embedded font binary (`.cff` / `.ttf`).
2. Dumps the PDF's `/Encoding` object (BaseEncoding + `/Differences`).
3. Writes a contact-sheet PNG of byte positions 0x20–0xFF so you can
   visually identify each glyph.

Output lands in `<pdf-stem>_fontinspect/<font-name>/`.

#### Step 2 — bridge

For each unsupported font:

```bash
python tools/font_bridge.py <pdf-stem>_fontinspect/<font>/<font>.cff
```

The tool tries three character-translation strategies (`direct`,
`mac_to_latin1`, `latin1_to_mac`) against every pytiblegenc table and
reports match rates. **Raw rates are misleading** — many tables happen
to score >90% because they have entries at the right byte slots even
when those entries are wrong.

The definitive disambiguator is `--ground-truth`. Find one phrase in
the PDF whose Tibetan you can read (a title, an author name), get the
raw extracted text from `<pdf-stem>_raw.txt`, and run:

```bash
python tools/font_bridge.py <font>.cff \
    --ground-truth "<raw extracted text>" "<expected Tibetan>"
```

The tool decodes the raw text against each candidate and reports which
table + strategy produces the exact expected Tibetan.

#### Step 3 — install

Depending on what the bridge found, take one of three paths:

**Path A: alias** — strategy `direct`, ground-truth matched. The new
font is a name-only reskin of an existing table. Add one line to
`local_font_tables/_aliases.csv`:

```
NewFontName,ExistingTableName
```

Done. Rerun extraction; the pipeline resolves the new name through the
existing table.

**Path B: byte-bridge CSV** — strategy `mac_to_latin1`, ground-truth
matched. The byte layout is identical to an existing table, but the
surface character encoding differs (this is the TB-Youtso case). Use
`local_font_tables/tb_youtso.csv` as a template: walk every byte
32–255, compute the extracted-character codepoint under the PDF's
actual encoding (typically MacRoman + Differences), look up the
Tibetan glyph through the bridge strategy, emit a CSV row
`font_name,extracted_codepoint,tibetan`. Add byte-specific overrides
for any wrong bridge outputs (rare — 4 bytes in the TB-Youtso case).

**Path C: fresh CSV** — no ground-truth match, no strategy works.
The font's byte layout is genuinely new. Open the contact-sheet PNG,
identify each glyph visually, and write the CSV by hand. For ~140
used bytes this takes about an hour.

### How the pipeline picks up changes

`pdf_extract._install_local_font_tables()` runs once at the start of
every `extract_pdf_hybrid()` invocation. It:

1. Scans `local_font_tables/` for `*.csv` files (excluding underscore-
   prefixed ones like `_aliases.csv`).
2. Merges each CSV's rows into `pytiblegenc.char_converter`'s in-memory
   `get_utfc_base()` dict. **Existing pytiblegenc entries always win**
   (we use `setdefault`), so upgrades don't silently change behaviour.
3. Reads `_aliases.csv` and registers each alias under both the raw
   name and the post-`normalize_font_name()` form (which strips
   trailing `Normal`).

The install is **idempotent** — subsequent calls in the same process
are no-ops. To force a re-read mid-process (REPL workflows), call
`_install_local_font_tables(force_reload=True)`.

### When to upstream

Once a local CSV is verified across several PDFs, consider sending it
upstream to `buda-base/py-tiblegenc/font-tables/tiblegenc.csv`. The
format is identical — just concatenate the rows. Until the PR merges
and a new pytiblegenc is released, keep the local CSV as a fallback so
you don't regress on `pip install --upgrade pytiblegenc`.

### Limits

- The tools assume the embedded font is **Type 1 / CFF** or **TrueType**.
  CID-keyed fonts (`TT49Exxx` etc.) need a different approach — see
  `_install_chogyal_cid_patch` in `pdf_extract.py` as a template.
- `font_bridge.py` only tries three byte-encoding strategies. Genuinely
  custom encodings (rare) need manual analysis.
- The Latin-font filter list in `font_inspect.py` is a small allowlist;
  fonts like `MinionPro-Bold` in the candidate list are not Tibetan and
  can be safely ignored.

---

## Configuration reference

### `config.py`

Hand-edit for single-IE workflows. The bulk driver overrides these
through environment variables (`PDF_BULK_BASE_DIR`, `PDF_BULK_IE_ID`,
`PDF_BULK_INPUT_SUBDIR`, `PDF_BULK_FONT_DIR`).

| Setting | Purpose |
|---------|---------|
| `IE_ID` | The image-group ID being processed |
| `BASE_DIR` | Parent of `<IE_ID>/` |
| `SOURCES_DIR` | Derived: `<BASE_DIR>/<IE_ID>/<input_subdir>` |
| `OUTPUT_DIR` | Derived: `<BASE_DIR>/<IE_ID>_output` |
| `LOG_DIR` | Flat in single-IE mode; nested under `<IE_ID>/` in bulk mode |
| `CHECKPOINT_DIR` | Same nesting rule as `LOG_DIR` |
| `CROP_HEADER_FRACTION` | Default top-redact fraction (0.0–0.49) |
| `CROP_FOOTER_FRACTION` | Default bottom-redact fraction (0.0–0.49) |
| `FONT_DIR` | Directory of full (unsubsetted) Tibetan fonts for GSUB resolution; `None` to disable |
| `FOOTNOTE_DETECTION` | Whether to emit `<note>` elements for separator-line footnotes |
| `FOOTNOTE_*` | Tuning constants for footnote detection geometry |

### Environment variables (bulk mode)

| Variable | Set by | Purpose |
|----------|--------|---------|
| `PDF_BULK_BASE_DIR` | `bulk_convert.py` | Parent of all IE folders |
| `PDF_BULK_IE_ID` | `bulk_convert.py` | Which IE this subprocess handles |
| `PDF_BULK_INPUT_SUBDIR` | `bulk_convert.py` | `sources` or `to_convert` (auto-detected) |
| `PDF_BULK_FONT_DIR` | manifest `font_dir` | Override for `FONT_DIR`; empty string clears |

---

## Troubleshooting

**"No IE worksets under …"** — root has no children matching `IE…` with
a `sources/` or `to_convert/` subfolder containing at least one PDF.
Run with `--dry-run` first and check folder names.

**"Missing converter script"** — `bulk_convert.py` expects
`convert_pdf_to_xml.py` in the same directory.

**Wrong pipeline auto-detected** — open the affected `_bulk_summary.txt`,
note the `PIPE` column. If `legacy` was picked for a Unicode PDF (or
vice-versa), it's almost always cosmetic — the same extractor handles
both, the pytiblegenc lookup just no-ops for fonts it doesn't know.
If extraction is actually wrong, look at the embedded font names with
`python tools/font_inspect.py <pdf>` and consider extending
`_LEGACY_FONT_HINTS` / `_UNICODE_FONT_HINTS` in `bulk_convert.py`.

**An IE keeps getting "skipped" after I deleted its output** — the
state file still says `status: "ok"`. Either delete just that entry
from `<ROOT>/checkpoints/_bulk_state.json` or run with
`--force-ie IE_ID`.

**Resume seems wrong after a crash** — `_bulk_state.json` is updated
*after* each IE finishes. An IE that was mid-run when the bulk driver
crashed is *not* in the state, so it'll re-run cleanly. The per-PDF
checkpoint inside that IE (`<IE>/checkpoints/pdf_to_xml_checkpoint.txt`)
preserves per-file progress within the IE.

**Latin PUA characters in output (`ŀ`, `Ĳ`, …)** — either you're on
the legacy pipeline without the right pytiblegenc table, or on the
Unicode pipeline without `FONT_DIR` pointing at the full Monlam fonts.
For the legacy case, follow [Adding a new legacy font](#adding-a-new-legacy-font).
For the Unicode case, set `FONT_DIR` (or the per-IE `font_dir` in the
manifest) and re-run.

**PyMuPDF not installed** — `pip install pymupdf`. The pipeline
requires it; pytiblegenc-only extraction is no longer supported.

**Different PyYAML import errors** — manifests in YAML need
`pip install pyyaml`. JSON manifests work with no extra deps.
