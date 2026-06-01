# pdf2line

Convert PDFs to plain text, **preserving pecha line structure**.

Each pecha page is identified by a **page-number line** (a line that is just
digits, e.g. `3`, `014`, a dotted index like `1.2`, a Jonang-style folio
marker like `p1`, `P7`, `P 904`, `p1036`, or a `PageN` marker with optional
colon and optional parenthetical sub-index (`Page981(157):`). Blank/missing page notes (`354 空白`, `Page306:空白`) are dropped.
Asterisk-only artifact lines (`* **`), volunteer placeholder lines (`xxxx`,
`Image As Per Original Document`), and Ladakh-style markers (`Page:402:`,
`Page79:xxxx`, `764空白缺頁`, `530此為空白頁`) are skipped. The marker itself is
dropped; the short header that follows it (e.g. `ཏཾ` or text after `Page1:`)
is kept as the first line of the page.

Output structure:

- **Within a pecha page** — every visual line break from the PDF is preserved
  as a single newline (one pecha line per output line).
- **Between pecha pages** — a blank line (double newline) acts as the page
  separator.

Lines with no Tibetan script (URLs, English notes) are collected,
de-duplicated, and placed at the top of the file as one block with single
newlines between lines (not blank-line spacing).

## Install

Requires **Python 3.9+** (3.10+ recommended).

```bash
python3 --version   # should be 3.9 or newer
pip install -e .            # core (PyMuPDF)
pip install -e ".[legacy]"  # + pytiblegenc for legacy-encoded fonts
```

## Usage
```bash
pdf2line -i ./pdfs -o ./out                 # folder -> one .txt each
pdf2line -i book.pdf -o ./out               # single file
pdf2line -i ./pdfs -o ./out --backend hybrid -j 4
```

## Verified behaviour
Tested against `Dolpopa-'Dzam-Thang-1-p1-579_test.pdf` and its expected
`test_output.txt`: line boundaries, page-number dropping, header retention,
tight joining, space-collapsing, and boilerplate placement all reproduced.

Note on encoding: this package extracts **canonical Unicode** Tibetan (combining
vowels in correct order). Some reference files contain raw, mis-ordered vowels
straight from the PDF (e.g. `ག་ྱི` instead of `གྱི`); pdf2line produces the
correct order, so it will differ from such references at those code points while
the content is identical.

## Key options
| Flag | Effect |
|---|---|
| `--backend pymupdf\|hybrid\|pytiblegenc` | Extraction backend (default pymupdf). |
| `--keep-page-numbers` | Keep the number line at the start of each page. |
| `--drop-boilerplate` | Drop URLs/English notes instead of collecting at top. |
| `--normalize` | Apply NFC/Tibetan normalization (default: off, raw). |
| `-j N` / `-r` / `--overwrite` | Parallel / recurse / overwrite. |

## Layout
```
pdf2line/
  extract.py    # hybrid PyMuPDF + pytiblegenc extraction (per page)
  assemble.py   # split on page-number lines, tight join, boilerplate handling
  normalize.py  # optional NFC + Tibetan space rules
  convert.py    # orchestration, flat output, parallel
  cli.py        # `pdf2line` command
```