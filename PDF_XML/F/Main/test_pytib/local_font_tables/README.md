# Onboarding a new Tibetan font into the pipeline

This directory contains the tools and data files you need when the pipeline
encounters an unsupported Tibetan font.  The system is designed so that
adding a new font is a **30-minute task without code changes**: you drop a
new CSV (or one line in `_aliases.csv`) into `local_font_tables/` and the
pipeline picks it up automatically on the next run.

## Layout

```
scripts/
├── pdf_extract.py                  # Extraction pipeline. Loads everything below.
├── local_font_tables/              # Drop new font tables here.
│   ├── _aliases.csv                # font_name → existing_pytiblegenc_table
│   ├── tb_youtso.csv               # Example: TB-Youtso family (570 rows)
│   └── <your-new-font>.csv         # Future fonts.
└── tools/
    ├── font_inspect.py             # Diagnose which fonts a PDF needs.
    └── font_bridge.py              # Test if a font matches an existing table.
```

The CSV format is the same as upstream `pytiblegenc/tiblegenc.csv`:

```
font_name,decimal_codepoint,tibetan_unicode_string
```

One row per glyph, one CSV per font family.

## The three-step workflow

### Step 1 — diagnose

Run `font_inspect` on the problem PDF:

```bash
python tools/font_inspect.py path/to/document.pdf
```

This:

1. Runs the full extraction pipeline and captures pytiblegenc's
   `unhandled_fonts` list.
2. For each unsupported Tibetan font, extracts the embedded font binary
   (`.cff`/`.ttf`).
3. Dumps the PDF's `/Encoding` object (BaseEncoding plus any `/Differences`
   array — this tells you what byte-to-character mapping the PDF reader
   applies).
4. Writes a contact-sheet PNG showing the glyph at every byte position
   0x20-0xFF so you can visually identify what each byte represents.

Output goes to `<pdf-stem>_fontinspect/<font-name>/`.

### Step 2 — bridge

For each unsupported font, run `font_bridge` on the extracted binary:

```bash
python tools/font_bridge.py <pdf-stem>_fontinspect/<font>/<font>.cff
```

The tool tries three character-translation strategies (`direct`,
`mac_to_latin1`, `latin1_to_mac`) against every pytiblegenc table and
reports match rates.  **The raw rate is misleading on its own** — many
tables happen to score >90% because they have entries at the right byte
slots even when those entries are wrong.

The definitive disambiguator is `--ground-truth`.  Find one phrase in the
PDF whose Tibetan you can read (a title, an author name, a chapter
heading), get the raw extracted text for it from
`<pdf-stem>_raw.txt`, and run:

```bash
python tools/font_bridge.py <font>.cff \
    --ground-truth "<raw extracted text>" "<expected Tibetan>"
```

The tool decodes the raw text against each candidate and reports which
table+strategy combination produces the exact expected Tibetan.

### Step 3 — install

Depending on what the bridge found, take one of three paths:

#### Path A: alias (strategy `direct`, ground-truth matched)

The new font is a name-only reskin of an existing pytiblegenc table.  Add
one line to `local_font_tables/_aliases.csv`:

```
NewFontName,ExistingTableName
```

That's it.  Rerun extraction — pipeline will resolve the new name through
the existing table.

#### Path B: byte-bridge CSV (strategy `mac_to_latin1`, ground-truth matched)

The byte layout is identical to an existing table, but the surface
character encoding differs (this is the TB-Youtso case).  You need a
*translated* CSV.  Use `local_font_tables/tb_youtso.csv` as a template;
the build script that generated it (see commit history) shows the pattern:

* Walk every byte 32-255.
* Compute the extracted-character codepoint under the PDF's actual
  encoding (typically MacRoman + Differences).
* Look up the Tibetan glyph by feeding the byte through the bridge
  strategy into the matching pytiblegenc table.
* Emit a CSV row `font_name,extracted_codepoint,tibetan`.

Plus any byte-specific overrides where the bridge gives a wrong answer
(rare — 4 bytes in the TB-Youtso case).

#### Path C: fresh CSV (no ground-truth match, no strategy works)

The font's byte layout is genuinely new.  No way around it: open the
contact-sheet PNG, identify each glyph visually, and write the CSV by
hand.  For ~140 used bytes this takes about an hour.

## How the pipeline picks up changes

`pdf_extract._install_local_font_tables()` is called once at the start of
every `extract_pdf_hybrid()` invocation.  It:

1. Scans `local_font_tables/` for `*.csv` files (excluding underscore-
   prefixed ones like `_aliases.csv`).
2. Merges each CSV's rows into `pytiblegenc.char_converter`'s in-memory
   `get_utfc_base()` dict.  Existing pytiblegenc entries always win (we
   use `setdefault`), so upgrades don't silently change behaviour.
3. Reads `_aliases.csv` and registers each alias under both the as-given
   name and the post-`normalize_font_name()` form (which strips trailing
   `Normal` from font names).

The install is **idempotent** — subsequent calls in the same process are
no-ops.

If you edit a CSV during a long-running process and want the change
picked up, call `_install_local_font_tables(force_reload=True)`.

## When to upstream

Once a local CSV has been verified across several PDFs, consider sending
it upstream to `buda-base/py-tiblegenc/font-tables/tiblegenc.csv`.  The
format is identical — just concatenate the rows.

Until the PR is merged and released to PyPI, keep the local CSV as a
fallback so you don't regress on `pip install --upgrade pytiblegenc`.

## Limits

* The tools assume the embedded font is **Type 1 / CFF** or **TrueType**.
  CID-keyed fonts (less common in legacy Tibetan publishing but seen in
  some title fonts like `TT49Exxx`) need a different approach — see the
  `_install_chogyal_cid_patch` in `pdf_extract.py` for a model.
* `font_bridge.py` only tries three byte-encoding strategies.  Genuinely
  custom encodings (rare) need manual analysis.
* The Latin-font filter list in `font_inspect.py` is a small allowlist —
  if you see fonts named `MinionPro-Bold` etc. in the candidate list,
  they're not Tibetan and can be safely ignored.
