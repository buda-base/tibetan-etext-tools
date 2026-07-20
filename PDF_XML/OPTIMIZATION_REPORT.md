# PDF_XML Main Script Optimization Report

**Target**: `F/Main/bulk/convert_pdf_to_xml.py`, `F/Main/bulk/pdf_extract.py`, `F/Main/bulk/normalization.py`  
**Source analysis**: All variant files across `F/Main/test_pymu/`, `F/Main/test_pytib/`, `F/IE2KG209991/`

---

## Summary

After a full cross-file analysis, **7 groups of improvements** were identified — ranging from critical correctness fixes to significant performance gains. Ordered by priority.

---

## 1. PERFORMANCE — Glyph DB caching (pdf_extract.py)

**Problem**: `extract_pdf_hybrid()` rebuilds `glyph_index` and `glyph_lookup` from disk **on every single PDF call**. For a batch of 200 PDFs this parses the glyph CSV 200 times.

**Fix**: Port `_get_glyph_db_structures()` + `_GLYPH_DB_CACHE` from `test_pytib/pdf_extract.py`. Add after the global flags section:

```python
_GLYPH_DB_CACHE: dict | None = None

def _get_glyph_db_structures():
    """Return (glyph_db_path, glyph_index, glyph_lookup), cached after first build."""
    global _GLYPH_DB_CACHE
    if _GLYPH_DB_CACHE is not None:
        return _GLYPH_DB_CACHE["path"], _GLYPH_DB_CACHE["index"], _GLYPH_DB_CACHE["lookup"]
    if not PYTIBLEGENC_AVAILABLE:
        return None, None, None
    try:
        glyph_db_path = get_glyph_db_path()
        glyph_index = build_font_hash_index_from_csv(str(glyph_db_path))
        glyph_lookup = build_glyph_lookup_tables(str(glyph_db_path))
        _GLYPH_DB_CACHE = {"path": glyph_db_path, "index": glyph_index, "lookup": glyph_lookup}
        logger.info("Glyph DB structures built and cached (one-time).")
        return glyph_db_path, glyph_index, glyph_lookup
    except Exception as exc:
        logger.warning("Could not build/cache glyph DB structures: %s", exc)
        return None, None, None

def _reset_glyph_db_cache() -> None:
    global _GLYPH_DB_CACHE
    _GLYPH_DB_CACHE = None
```

In `extract_pdf_hybrid()`, replace the build block:
```python
# AFTER:
glyph_db_path, glyph_index, glyph_lookup = _get_glyph_db_structures()
raw_font_norm = {}
if glyph_index is not None:
    with open(str(target_pdf), "rb") as _f:
        _parser = PDFParser(_f)
        _doc_tmp = PDFDocument(_parser)
        raw_font_norm = identify_pdf_fonts_from_db(_doc_tmp, glyph_index) or {}
```

---

## 2. PERFORMANCE — Per-character decode caching (pdf_extract.py)

**Problem**: `_extract_line_text_hybrid()` calls `convert_string()` for every character in every span. Tibetan documents use ~80 base characters — the same `(char, font)` pairs repeat thousands of times per page with zero memoization.

**Fix**: Port `_decode_char_cached()` from `test_pytib/pdf_extract.py`. Add after `_correct_monlam_glyph()`:

```python
_DECODE_CACHE: dict[tuple[str, str], "str | None"] = {}
_MISSING = object()

def _reset_decode_cache() -> None:
    _DECODE_CACHE.clear()

def _decode_char_cached(c: str, target_font: str, glyph_lookup, stats: dict) -> "str | None":
    key = (c, target_font)
    cached = _DECODE_CACHE.get(key, _MISSING)
    if cached is not _MISSING:
        return cached
    from pytiblegenc.char_converter import convert_string
    decoded = convert_string(c, target_font, stats, error_chr_fun=None, glyph_lookup=glyph_lookup)
    _DECODE_CACHE[key] = decoded
    return decoded
```

In `_extract_line_text_hybrid()`, replace all `convert_string()` calls:
```python
# BEFORE:
decoded_c = convert_string(c, target_font, stats, error_chr_fun=None, glyph_lookup=glyph_lookup)

# AFTER:
decoded_c = _decode_char_cached(c, target_font, glyph_lookup, stats)
```

Apply in both the per-char path and the no-chars-data fallback path.

---

## 3. CORRECTNESS — Pecha vertical-text handling (pdf_extract.py)

**Problem**: `bulk/pdf_extract.py` has no handling for rotated pecha PDFs (landscape pages with vertical Tibetan text running in columns left→right). Such PDFs produce scrambled output because `extract_pdf_hybrid()` applies y-sort then x-sort, interleaving columns. Horizontal running-title and folio lines in the margins also bleed into body text.

`test_pytib/pdf_extract.py` solves this with five functions:
- `_line_is_vertical(direction)` / `_line_is_horizontal(direction)` — checks MuPDF `dir` vector
- `_page_is_vertical(entries)` — votes by decoded character mass
- `_document_is_pecha(doc, ...)` — document-level decision (robust to near-blank pages)
- `_is_pecha_marginalia(direction, bbox, ...)` — drops horizontal lines on vertical pages
- `_is_short_edge_run(frags, bbox, ...)` — secondary guard for edge-band folio numbers

**Fix**: Port all five functions verbatim from `test_pytib/pdf_extract.py` (lines 1019–1158). Then update `extract_pdf_hybrid()`:

1. After opening the doc: `doc_is_pecha = _document_is_pecha(doc, font_normalization, glyph_lookup, stats)`.
2. Collect per-line records as 5-tuples: `(y_mid, x0, fragments, direction, bbox)` by adding `line.get("dir", (1.0, 0.0))` and `bbox` to each entry.
3. Per page: `page_vertical = doc_is_pecha or _page_is_vertical(line_records)`.
4. **If vertical**: filter via `_is_pecha_marginalia()` + `_is_short_edge_run()`, then sort by x-midpoint (column) → y0 (within column). No y-merge — each vertical line is its own row.
5. **If horizontal**: strip direction/bbox and continue with the existing sort + merge path unchanged.

The complete vertical-page block from `test_pytib/pdf_extract.py` (lines 1617–1700) transplants directly; the only adaptation is preserving bulk's `line_spans` tracking for the superior column crossing-validation.

---

## 4. CORRECTNESS — InDesign shadow text deduplication (normalization.py)

**Problem**: `bulk/normalization.py` is missing three functions from `test_pymu/normalization.py` that handle InDesign shadow/glow layers producing duplicate text in the extraction stream.

### 4a. `collapse_duplicate_consonant_clusters()`
Removes bare-consonant shadow copies before their vowelled version:
- **Pattern A**: གྱགྱི → གྱི (bare consonant stack + vowelled copy)
- **Pattern B**: ཆུཆུབ → ཆུབ (identical token when it carries a vowel or length > 1)

Uses a token-based approach with `_UNIT_RE` regex to avoid splitting valid ligatures.

### 4b. `collapse_duplicate_tibetan_marks()`
```python
_COLLAPSE_DUP_TIB_MARKS_RE = re.compile(r"([ཱ-྇ྍ-ྼ༹༵༷])\1+")

def collapse_duplicate_tibetan_marks(text: str) -> str:
    return _COLLAPSE_DUP_TIB_MARKS_RE.sub(r"\1", text)
```

### 4c. `remove_indesign_section_markers()`
Removes UTF-16-BE hex section headers (e.g. `<FEFF0053006500630031003A>` = "Sec1:") and `<fs:N>IVXLCDM\n` Roman numeral lines:
```python
_INDESIGN_HEX_SECTION_RE = re.compile(r"<[0-9A-Fa-f]{4}(?:[0-9A-Fa-f]{4})*>")
_INDESIGN_FS_ROMAN_RE = re.compile(r"<fs:\d+>[IVXLCDM]+\n")

def remove_indesign_section_markers(text: str) -> str:
    text = _INDESIGN_HEX_SECTION_RE.sub("", text)
    text = _INDESIGN_FS_ROMAN_RE.sub("", text)
    return text
```

**Call site** — in `bulk/convert_pdf_to_xml.py`, `convert_pdf_to_tei()`, after `normalize_unicode()`:
```python
normalized_text = collapse_duplicate_consonant_clusters(normalized_text)
normalized_text = collapse_duplicate_tibetan_marks(normalized_text)
normalized_text = remove_indesign_section_markers(normalized_text)
```

---

## 5. CORRECTNESS — Missing character fixes (normalization.py)

**Problem**: `fix_pdf_glyph_to_unicode_artifacts()` is missing three substitutions present in `test_pymu/normalization.py`:

| Char | Codepoint | Source | Replacement |
|------|-----------|--------|-------------|
| Ľ | U+013D | MuPDF GID-as-Unicode fallback for Tibetan Naro+Anusvara ligature (MonlamUniOuChan2) | ོཾ (U+0F7C + U+0F7E) |
| † | U+2020 | WinAnsi byte 0x86 — Monlam dot-leader glyph | `.` |
| ‡ | U+2021 | WinAnsi byte 0x87 — Monlam dot-leader glyph | `.` |

**Fix** — add to `fix_pdf_glyph_to_unicode_artifacts()`:
```python
# Ľ (U+013D): only substitute in Tibetan context (Naro+Anusvara context).
text = re.sub(r"([ༀ-࿿])Ľ", r"\1ོཾ", text)

# † ‡ (U+2020, U+2021): Monlam dot-leaders → ASCII dot.
text = text.replace("†", ".").replace("‡", ".")
```

---

## 6. CORRECTNESS — Space handling refinements (normalization.py)

**Problem**: `bulk/normalize_spaces()` is more aggressive than `test_pymu`'s in two ways:

### 6a. Tsheg → consonant spaces
Bulk strips ALL spaces after tsheg (U+0F0B) before any consonant. `test_pymu` only collapses tsheg→tsheg/shad sequences, preserving tsheg→consonant spaces (legitimate word boundaries in some contexts).

### 6b. Shad → consonant spaces
Bulk strips spaces after shad (U+0F0D–U+0F11) before consonants. In Tibetan typography this gap is a sentence/paragraph separator and should be normalized to exactly one space.

**Fix**:
```python
# Shad → consonant: normalize to one space instead of stripping:
# BEFORE: text = re.sub(r"([།-༑]) +(?=[ཀ-ྼ])", r"\1", text)
# AFTER:
text = re.sub(r"([།-༑]) +(?=[ཀ-ྼ])", r"\1 ", text)
```

**Caution**: Test on a representative sample before enabling — may interact with existing header/footer stripping.

---

## 7. NOTE — Column split crossing validation (bulk already superior)

`bulk/pdf_extract.py`'s `_detect_column_splits()` is **more robust** than `test_pytib`'s. Bulk added `line_spans` + crossing-validation that rejects false column splits on single-column pages with varied indents. `test_pytib` lacks this and can scramble single-column reading order. No action for bulk; back-port to `test_pytib` when next updated.

---

## Implementation Order

| # | Change | File(s) | Impact |
|---|--------|---------|--------|
| 1 | Glyph DB caching | `pdf_extract.py` | **High** — batch performance |
| 2 | Char decode caching | `pdf_extract.py` | **High** — per-PDF performance |
| 3 | Pecha vertical handling | `pdf_extract.py` | **High** — pecha corpus correctness |
| 4 | InDesign shadow dedup (3 functions) | `normalization.py` + `convert_pdf_to_xml.py` | **Medium** — InDesign PDFs |
| 5 | Missing char fixes (Ľ, †, ‡) | `normalization.py` | **Medium** — MonlamUniOuChan2 PDFs |
| 6 | Space handling refinements | `normalization.py` | **Low-medium** — test first |
| 7 | (bulk already better) | — | — |

Items 1 and 2 are safe, self-contained, high-value — implement first. Items 3–5 have no regression risk on existing Unicode-font PDFs. Item 6 requires sampling before enabling.
