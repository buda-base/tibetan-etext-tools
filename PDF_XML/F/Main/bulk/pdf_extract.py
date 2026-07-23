from __future__ import annotations

import logging
import os
import re
import tempfile
import traceback
from pathlib import Path
from typing import Optional

try:
    import pymupdf as fitz
    PYMUPDF_AVAILABLE = True
except ImportError:
    try:
        import fitz
        PYMUPDF_AVAILABLE = True
    except ImportError:
        PYMUPDF_AVAILABLE = False
        fitz = None  # type: ignore

try:
    from pytiblegenc import (
        get_glyph_db_path,
        build_font_hash_index_from_csv,
        identify_pdf_fonts_from_db,
        build_glyph_lookup_tables,
    )
    from pytiblegenc.pdfminer_text_converter import DuffedTextConverter
    from pytiblegenc.char_converter import get_base as _tibl_get_base, get_utfc_base as _tibl_get_utfc_base
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
    from pdfminer.pdfpage import PDFPage
    from io import StringIO
    PYTIBLEGENC_AVAILABLE = True
except ImportError:
    PYTIBLEGENC_AVAILABLE = False

logger = logging.getLogger(__name__)

PAGE_BREAK_STR = "ZZZZ"
_FONT_SIZE_FORMAT = "<fs:{}>"
_FS_TAG_RE = re.compile(r"<fs:\d+>")

# ─── Footnote markup tokens ─────────────────────────────────────────────────
# A footnote is emitted into the flat extraction stream as a single-line token
# so it survives normalization untouched, then converted to a TEI <note> in
# convert_markup_to_tei.  The delimiters are deliberately unusual ASCII so they
# pass through Unicode normalization (private-use chars get stripped) and never
# collide with real Tibetan text.
_NOTE_OPEN = "@@FNOTE@@"
_NOTE_CLOSE = "@@ENDFN@@"
_NOTE_TOKEN_RE = re.compile(re.escape(_NOTE_OPEN) + r"(.*?)" + re.escape(_NOTE_CLOSE))

# ─── Footnote detection thresholds ──────────────────────────────────────────
# A genuine footnote separator is a short horizontal rule on the LEFT margin
# in the bottom region of the page, with smaller-than-body text beneath it.
# These defaults are overridable from config (see _footnote_settings()).
_FN_SEP_MIN_WIDTH_PT = 40.0     # separator at least this wide
_FN_SEP_MAX_WIDTH_PT = 220.0    # …but not a full-width rule (that's a border)
_FN_SEP_MIN_Y_FRACTION = 0.62   # separator must sit below this fraction of page height
_FN_SEP_LEFT_MARGIN_TOL = 25.0  # separator x0 within this many pt of the body left margin
_FN_BODY_SIZE_RATIO = 0.92      # footnote text must be ≤ this × body font size


def get_pdf_page_content_flags(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    preserve_box: Optional[list] = None,
) -> list[bool]:
    """
    Return a per-physical-page list of booleans: ``True`` where the page has
    extractable text under the given crop/preserve settings, ``False`` for a
    blank page.

    This mirrors the page set that survives into the TEI body.  Blank pages
    produce no text, so their ``<pb/>`` is collapsed away by the body post-
    processing — which means the Nth surviving ``<pb/>`` corresponds to the
    Nth ``True`` entry here, **not** to physical page N.  :func:`inject_page_labels`
    uses this list to align ``PageLabels`` to the pages that actually appear,
    fixing the label drift caused by blank pages.

    Returns an empty list when PyMuPDF is unavailable or the PDF can't be read.
    """
    if not PYMUPDF_AVAILABLE:
        return []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        logger.warning("Could not open %s for content-flag scan: %s", pdf_path.name, exc)
        return []

    flags: list[bool] = []
    try:
        for page in doc:
            r = page.rect
            clip = None
            if preserve_box is not None and len(preserve_box) == 4:
                px0f, py0f, px1f, py1f = preserve_box
                clip = fitz.Rect(
                    r.x0 + px0f * r.width, r.y0 + py0f * r.height,
                    r.x0 + px1f * r.width, r.y0 + py1f * r.height,
                )
            elif crop_top > 0.0 or crop_bottom > 0.0:
                clip = fitz.Rect(
                    r.x0, r.y0 + r.height * crop_top,
                    r.x1, r.y1 - r.height * crop_bottom,
                )
            try:
                txt = page.get_text("text", clip=clip) if clip is not None else page.get_text("text")
            except Exception:
                txt = page.get_text("text")
            flags.append(bool(txt and txt.strip()))
    finally:
        doc.close()

    return flags


def get_pdf_page_labels(pdf_path: Path) -> dict:
    """
    Return a mapping of {page_index (0-based): label_string} for every page
    in *pdf_path* that has a PageLabel entry.

    Uses the PDF's ``PageLabels`` dictionary (the human-readable names that PDF
    viewers display in their page-number box — Roman numerals, custom prefixes,
    numeric sequences that don't start at 1, etc.).  This is distinct from the
    physical page index, which always starts at 0.

    Returns an empty dict when:
    - PyMuPDF is unavailable,
    - the PDF has no ``PageLabels`` dict, or
    - every label is just the plain sequential page number (``"1"``, ``"2"``, …),
      which is indistinguishable from having no labels.

    Example return value for a PDF with pages labelled [i, ii, iii, 1, 2, 3, …]:
        {0: 'i', 1: 'ii', 2: 'iii', 3: '1', 4: '2', 5: '3', ...}
    """
    if not PYMUPDF_AVAILABLE:
        return {}
    try:
        doc = fitz.open(str(pdf_path))
        raw_labels: list = doc.get_page_labels()  # list of rule dicts from PyMuPDF
        page_count: int = doc.page_count
        doc.close()
    except Exception as exc:
        logger.warning("Could not read PageLabels from %s: %s", pdf_path.name, exc)
        return {}

    if not raw_labels:
        return {}

    # ── helper: integer → Roman numeral ─────────────────────────────────────
    def _to_roman(n: int) -> str:
        if n <= 0:
            return str(n)
        val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
        sym = ["M", "CM", "D", "CD", "C", "XC", "L", "XL", "X", "IX", "V", "IV", "I"]
        res = ""
        for v, s in zip(val, sym):
            while n >= v:
                res += s
                n -= v
        return res

    # ── helper: 1-based integer → alphabetic (1→a, 26→z, 27→aa …) ──────────
    def _to_alpha(n: int) -> str:
        if n <= 0:
            return str(n)
        res = ""
        while n > 0:
            n, r = divmod(n - 1, 26)
            res = chr(ord("a") + r) + res
        return res

    # ── expand PageLabel rules into one label per page ───────────────────────
    # PyMuPDF returns rules sorted by startpage, but sort anyway for safety.
    rules = sorted(raw_labels, key=lambda r: r.get("startpage", 0))
    all_labels: list = [""] * page_count

    for rule_idx, rule in enumerate(rules):
        start = rule.get("startpage", 0)
        end = (
            rules[rule_idx + 1].get("startpage", page_count)
            if rule_idx + 1 < len(rules)
            else page_count
        )
        prefix = rule.get("prefix", "") or ""
        style = rule.get("style", "") or ""
        first = rule.get("firstpagenum", 1) or 1

        for i in range(start, min(end, page_count)):
            n = first + (i - start)
            if style == "D":
                num_str = str(n)
            elif style == "r":
                num_str = _to_roman(n).lower()
            elif style == "R":
                num_str = _to_roman(n).upper()
            elif style == "a":
                num_str = _to_alpha(n).lower()
            elif style == "A":
                num_str = _to_alpha(n).upper()
            else:
                # No numbering style — prefix-only label (e.g. "Cover")
                num_str = ""
            all_labels[i] = prefix + num_str

    # ── discard when every label equals plain "1", "2", "3", … ─────────────
    trivial = all(all_labels[i] == str(i + 1) for i in range(page_count))
    if trivial:
        return {}

    # Build result dict; pages whose label is the empty string get no entry
    # so the caller can use .get(idx) and emit <pb/> (no n= attr) for those.
    return {i: lbl for i, lbl in enumerate(all_labels) if lbl != ""}


# ---------------------------------------------------------------------------
# Fix 7 — Legacy font name alias map
#
# Some authoring tools (PageMaker 7, older InDesign versions) embed Tibetan
# font names with spaces stripped: "TCRCYoutso" instead of "TCRC Youtso".
# pytiblegenc's convert_string() does an exact dict lookup on the font name,
# so "TCRCYoutso" is never found → the font lands in unhandled_fonts and raw
# legacy encoding bytes pass through unchanged.
#
# Fix: build a map of {stripped_name: canonical_table_name} from pytiblegenc's
# own loaded conversion tables, then inject it into font_normalization before
# each pytiblegenc extraction so the converter sees the right key.
#
# The map is built lazily at first use (avoids import-time cost) and cached.
# ---------------------------------------------------------------------------
_FONT_NAME_ALIASES: dict[str, str] | None = None

# ---------------------------------------------------------------------------
# Fix 10 — Glyph DB structure cache
#
# build_font_hash_index_from_csv() and build_glyph_lookup_tables() parse the
# same pytiblegenc CSV on every call to extract_pdf_hybrid().  For a bulk run
# of N PDFs this repeats the parse N times unnecessarily.  Cache both
# structures after the first build so subsequent calls skip the disk read.
# ---------------------------------------------------------------------------
_GLYPH_DB_CACHE: dict | None = None


def _get_glyph_db_structures():
    """
    Return ``(glyph_db_path, glyph_index, glyph_lookup)`` built from the
    pytiblegenc glyph CSV, caching the result after the first build.

    Returns ``(None, None, None)`` when pytiblegenc is unavailable or the
    build fails — callers already handle the empty/None case gracefully.
    """
    global _GLYPH_DB_CACHE
    if _GLYPH_DB_CACHE is not None:
        return (
            _GLYPH_DB_CACHE["path"],
            _GLYPH_DB_CACHE["index"],
            _GLYPH_DB_CACHE["lookup"],
        )
    if not PYTIBLEGENC_AVAILABLE:
        return None, None, None
    try:
        glyph_db_path = get_glyph_db_path()
        glyph_index = build_font_hash_index_from_csv(str(glyph_db_path))
        glyph_lookup = build_glyph_lookup_tables(str(glyph_db_path))
        _GLYPH_DB_CACHE = {
            "path": glyph_db_path,
            "index": glyph_index,
            "lookup": glyph_lookup,
        }
        logger.info("Glyph DB structures built and cached (one-time per process).")
        return glyph_db_path, glyph_index, glyph_lookup
    except Exception as exc:
        logger.warning("Could not build/cache glyph DB structures: %s", exc)
        return None, None, None


def _reset_glyph_db_cache() -> None:
    """Drop the cached glyph-DB structures so the next call rebuilds them.

    Call this when font tables have been hot-reloaded mid-process
    (e.g. a new CSV dropped into local_font_tables/ while bulk is running).
    """
    global _GLYPH_DB_CACHE
    _GLYPH_DB_CACHE = None


# ---------------------------------------------------------------------------
# Fix 8 — TibetanChogyal missing-cid patch
# ---------------------------------------------------------------------------

# Maps cid → Tibetan Unicode string for the 8 undecoded TibetanChogyal slots.
_CHOGYAL_CID_PATCH: dict[int, str] = {
    2: "\u0F66\u0FA4\u0FB1",  # སྤྱ  sa + pa-ta subscript + ya-ta subscript
    3: "\u0F42",              # ག    ga (alternate glyph slot, same shape as cid=35)
    4: "\u0F4E",              # ཎ    retroflex na (Sanskrit ṇa; e.g. པཎ་ཆེན་ Panchen)
    5: "\u0F51\u0FAD",        # དྭ   da + wa-zur subscript
    6: "\u0F51",              # ད    da  (alternate glyph slot, same shape as cid=43)
    7: "\u0F40",              # ཀ    ka  (alternate glyph slot, same shape as cid=33)
    8: "",                    # ''   glyph index out-of-range → zero-width, emit nothing
    9: "\u0F7F",              # ཿ    visarga (alternate glyph slot, same shape as cid=239)
}

# Base font name (after stripping the random subset prefix "XXXXXX+") that
# this patch applies to.  The Skt variants have different encodings and do
# not exhibit this problem.
_CHOGYAL_BASE_NAME = "TibetanChogyal"


def _install_chogyal_cid_patch() -> None:
    """
    Monkey-patch ``pytiblegenc.pdfminer_text_converter.convert_string`` so that
    ``(cid:N)`` strings produced by pdfminer for undecoded TibetanChogyal glyphs
    are replaced with the correct Tibetan Unicode before pytiblegenc discards them.

    Background
    ----------
    When pdfminer cannot resolve a cid to a unicode character it calls
    ``handle_undefined_char(font, cid)`` which returns the string ``"(cid:N)"``.
    That string is passed to ``convert_string()``.  The very first thing
    ``convert_string`` does is::

        if s.startswith("(cid:"):
            return ""

    so the character is silently dropped — **before** ``error_chr_fun`` is ever
    called.  The only reliable interception point is ``convert_string`` itself.

    This function wraps the module-level ``convert_string`` reference that
    ``DuffedTextConverter.convert_item`` imports, so the patch is transparent to
    all other callers.  It is idempotent: calling it twice has no effect.
    """
    if not PYTIBLEGENC_AVAILABLE:
        return

    try:
        import pytiblegenc.pdfminer_text_converter as _ptc
        from pytiblegenc.char_converter import convert_string as _orig_cs

        # Idempotency guard
        if getattr(_ptc, "_chogyal_cid_patch_installed", False):
            return

        def _patched_convert_string(
            s: str,
            font_name: str,
            stats: dict,
            error_chr_fun=None,
            glyph_lookup=None,
        ) -> "str | None":
            # Intercept (cid:N) for TibetanChogyal before the original strips it.
            if s.startswith("(cid:") and s.endswith(")"):
                clean_font = (
                    font_name.split("+", 1)[-1] if "+" in font_name else font_name
                )
                if clean_font == _CHOGYAL_BASE_NAME:
                    try:
                        cid = int(s[5:-1])
                    except ValueError:
                        pass
                    else:
                        replacement = _CHOGYAL_CID_PATCH.get(cid)
                        if replacement is not None:
                            return replacement
            return _orig_cs(s, font_name, stats, error_chr_fun, glyph_lookup)

        _ptc.convert_string = _patched_convert_string
        _ptc._chogyal_cid_patch_installed = True
        logger.debug("TibetanChogyal cid patch installed into convert_string")

    except Exception as exc:
        logger.warning("Could not install TibetanChogyal cid patch: %s", exc)


# ---------------------------------------------------------------------------
# Fix 9 — Local font conversion tables
#
# pytiblegenc ships with ~70 font tables, but the BDRC corpus contains many
# more legacy Tibetan fonts (publisher-custom, regional variants, fonts whose
# upstream support is incomplete).  Each unsupported font causes its
# characters to fall through pytiblegenc's lookup and pass into the output
# unchanged — typically as Latin/Mac-Roman garbage like ``z;∫-Gh§≈``.
#
# This module loads two kinds of supplementary data from a sibling
# ``local_font_tables/`` directory:
#
#   1. **Glyph CSVs** — one CSV per font (or font family).  Each row is
#      ``font_name,decimal_codepoint,tibetan_unicode`` (same format as the
#      upstream ``tiblegenc.csv``).  Rows are merged into pytiblegenc's
#      ``get_utfc_base()`` dict at extraction start.  Drop a new CSV in the
#      directory and it's picked up automatically — no code change needed.
#
#   2. **Alias map** — ``_aliases.csv`` with two columns,
#      ``pdf_font_name,pytiblegenc_table_name``.  Use this for fonts that
#      share an existing table's byte layout but are embedded under a
#      different name (e.g. ``MyPublisher-Tibetan`` is byte-identical to
#      ``TCRC Bod-Yig`` — one row aliases the entire mapping with no per-
#      glyph work).
#
# Naming convention: any CSV in the directory whose name doesn't start with
# an underscore is treated as a glyph table.  Underscore-prefixed files are
# reserved for control data (``_aliases.csv`` today; future control files
# can use the same prefix).
#
# pytiblegenc's ``normalize_font_name()`` strips a trailing literal
# ``"Normal"`` from font names before lookup, so for every font name ending
# in ``Normal`` we also register under the stripped form.  This is the only
# normalization quirk; everything else lines up cleanly.
# ---------------------------------------------------------------------------

_LOCAL_TABLES_DIR = Path(__file__).parent / "local_font_tables"
_ALIASES_FILENAME = "_aliases.csv"

# Idempotency flag — the install runs once per process.  Subsequent calls
# return immediately so re-entering ``extract_pdf_hybrid`` doesn't repeatedly
# re-parse CSVs or log spam.
_LOCAL_TABLES_INSTALLED = False


def _install_local_font_tables(force_reload: bool = False) -> None:
    """
    Load every CSV in ``local_font_tables/`` and merge its rows into
    pytiblegenc's ``get_utfc_base()`` dict.

    Parameters
    ----------
    force_reload
        If True, ignore the idempotency flag and re-read every CSV.  Useful
        for development/REPL workflows where you edit a CSV and want the
        change picked up without restarting the process.

    File layout
    -----------
    ``local_font_tables/``
        ``<anything>.csv``       — glyph table (rows: font_name, cp, tibetan)
        ``_aliases.csv``         — alias map  (rows: pdf_name, table_name)

    The directory may not exist; that's fine, the function is a no-op then.

    Behaviour on conflicts
    ----------------------
    *Per-glyph merge*: existing entries in pytiblegenc's table always win
    (we use ``setdefault``).  Upstream pytiblegenc takes precedence so
    upgrades don't silently change behaviour.

    *Across CSVs*: if two local CSVs declare the same ``(font_name, cp)``,
    whichever is read first wins (Python's directory iteration order is
    insertion order on modern filesystems, but don't rely on it — keep one
    font per CSV).
    """
    global _LOCAL_TABLES_INSTALLED
    if _LOCAL_TABLES_INSTALLED and not force_reload:
        return
    if not PYTIBLEGENC_AVAILABLE:
        _LOCAL_TABLES_INSTALLED = True
        return
    if force_reload:
        # Font tables changing can change decode results and the glyph-DB
        # derived structures; drop the dependent caches so they rebuild
        # instead of silently serving stale decodes from before the reload.
        _reset_decode_cache()
        _reset_glyph_db_cache()

    try:
        if not _LOCAL_TABLES_DIR.is_dir():
            logger.debug(
                "No local font-tables directory at %s — skipping local "
                "font table installation.",
                _LOCAL_TABLES_DIR,
            )
            _LOCAL_TABLES_INSTALLED = True
            return

        utfc_base = _tibl_get_utfc_base()

        # --- 1. Load glyph CSVs (anything not starting with "_") -----------
        registered: set[str] = set()
        csv_count = 0
        row_count = 0

        for csv_path in sorted(_LOCAL_TABLES_DIR.glob("*.csv")):
            if csv_path.name.startswith("_"):
                continue  # reserved for control files (e.g. _aliases.csv)
            csv_count += 1
            per_font, rows = _read_glyph_csv(csv_path)
            row_count += rows
            for font_name, table in per_font.items():
                _merge_into_pytiblegenc_table(utfc_base, font_name, table)
                registered.add(font_name)
                # Register stripped form for normalize_font_name compatibility
                if font_name.endswith("Normal"):
                    stripped = font_name[: -len("Normal")].strip()
                    if stripped and stripped != font_name:
                        _merge_into_pytiblegenc_table(utfc_base, stripped, table)
                        registered.add(stripped)

        # --- 2. Load _aliases.csv (font_name → existing_table_name) --------
        alias_count = 0
        alias_path = _LOCAL_TABLES_DIR / _ALIASES_FILENAME
        if alias_path.is_file():
            for pdf_name, target_name in _read_alias_csv(alias_path):
                if target_name not in utfc_base:
                    logger.warning(
                        "Alias %r → %r skipped: target table not in "
                        "pytiblegenc (typo? upstream rename?).",
                        pdf_name, target_name,
                    )
                    continue
                target_table = utfc_base[target_name]
                # Register under both raw alias and stripped form.
                _merge_into_pytiblegenc_table(utfc_base, pdf_name, target_table)
                registered.add(pdf_name)
                if pdf_name.endswith("Normal"):
                    stripped = pdf_name[: -len("Normal")].strip()
                    if stripped and stripped != pdf_name:
                        _merge_into_pytiblegenc_table(utfc_base, stripped, target_table)
                        registered.add(stripped)
                alias_count += 1

        # --- 3. Report ----------------------------------------------------
        if csv_count or alias_count:
            logger.info(
                "Local font tables installed: %d glyph CSVs (%d rows), "
                "%d aliases. Fonts registered: %s",
                csv_count, row_count, alias_count,
                ", ".join(sorted(registered)) if registered else "(none)",
            )

        _LOCAL_TABLES_INSTALLED = True

    except Exception as exc:
        logger.warning("Could not install local font tables: %s", exc)
        # Don't set the flag so a later call has a chance to retry
        # (e.g. if the directory appears mid-run).


def _read_glyph_csv(path: Path) -> tuple[dict[str, dict[str, str]], int]:
    """Parse one glyph CSV; return ({font_name: {char: tibetan}}, row_count)."""
    import csv as _csv
    per_font: dict[str, dict[str, str]] = {}
    rows = 0
    with path.open(encoding="utf-8", newline="") as f:
        for row in _csv.reader(f):
            if not row or len(row) < 2:
                continue
            font_name = row[0].strip()
            if not font_name or font_name.startswith("#"):
                continue
            try:
                cp = int(row[1])
            except ValueError:
                continue
            tib = row[2] if len(row) > 2 else ""
            per_font.setdefault(font_name, {})[chr(cp)] = tib
            rows += 1
    return per_font, rows


def _read_alias_csv(path: Path) -> list[tuple[str, str]]:
    """Parse the alias CSV; return [(pdf_font_name, pytiblegenc_table_name)]."""
    import csv as _csv
    aliases: list[tuple[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in _csv.reader(f):
            if not row or len(row) < 2:
                continue
            pdf_name = row[0].strip()
            target = row[1].strip()
            if not pdf_name or pdf_name.startswith("#"):
                continue
            if not target:
                continue
            aliases.append((pdf_name, target))
    return aliases


def _merge_into_pytiblegenc_table(
    utfc_base: dict, font_name: str, additions: dict[str, str]
) -> None:
    """Insert *additions* into ``utfc_base[font_name]`` without overwriting
    pre-existing entries (so upstream pytiblegenc always wins if it has its
    own mapping for the same key)."""
    existing = utfc_base.get(font_name)
    if existing is None:
        utfc_base[font_name] = dict(additions)
        return
    for k, v in additions.items():
        existing.setdefault(k, v)


# Back-compat shim: keep the old install function name so any external code
# that calls ``_install_tb_youtso_tables`` still works.
def _install_tb_youtso_tables() -> None:
    """Deprecated alias kept for back-compat.  Forwards to the general loader."""
    _install_local_font_tables()


def _get_font_name_aliases() -> dict[str, str]:
    """
    Return {pdf_embedded_name: pytiblegenc_table_name} for all font names
    whose table key contains spaces (built from pytiblegenc's live tables).

    Result is cached in _FONT_NAME_ALIASES after the first call.
    """
    global _FONT_NAME_ALIASES
    if _FONT_NAME_ALIASES is not None:
        return _FONT_NAME_ALIASES
    if not PYTIBLEGENC_AVAILABLE:
        _FONT_NAME_ALIASES = {}
        return _FONT_NAME_ALIASES
    try:
        all_known: set[str] = set(_tibl_get_base().keys()) | set(_tibl_get_utfc_base().keys())
        _FONT_NAME_ALIASES = {
            name.replace(" ", ""): name
            for name in all_known
            if " " in name
        }
        logger.debug("Built font name alias map (%d entries): %s", len(_FONT_NAME_ALIASES), _FONT_NAME_ALIASES)
    except Exception as exc:
        logger.warning("Could not build font name alias map: %s", exc)
        _FONT_NAME_ALIASES = {}
    return _FONT_NAME_ALIASES


def create_cropped_pdf(
    pdf_path: Path,
    top_frac: float,
    bottom_frac: float,
    preserve_box: Optional[list] = None,
) -> Optional[Path]:
    """
    Temp PDF with margins physically redacted (text removed, white fill).

    Two mutually exclusive modes:

    **preserve_box mode** (preferred, takes priority when provided):
        ``preserve_box`` is a list of 4 normalised coordinate fractions
        ``[x0_frac, y0_frac, x1_frac, y1_frac]`` that describe the rectangle
        the user wants to *keep*.  Everything outside that rectangle is
        redacted.  The four exterior bands are:

        * top    – above y0_frac
        * bottom – below y1_frac
        * left   – left of x0_frac  (only between y0 and y1)
        * right  – right of x1_frac (only between y0 and y1)

        Example: ``preserve_box=[0.11, 0.09, 0.89, 0.82]``

    **Percentage-based fallback** (legacy):
        When ``preserve_box`` is ``None``, ``top_frac`` and ``bottom_frac``
        are used as before — they strip the top N% and bottom N% of each page.

    Uses ``add_redact_annot`` + ``apply_redactions`` on absolute ``fitz.Rect``
    coordinates derived from ``page.rect``.
    """
    # Nothing to do
    if preserve_box is None and top_frac == 0.0 and bottom_frac == 0.0:
        return None

    if not PYMUPDF_AVAILABLE:
        logger.warning(
            "Header/footer redaction requested but PyMuPDF is not installed. "
            "pip install pymupdf — continuing without redaction."
        )
        return None

    # Validate preserve_box early so we can give a clear error message.
    if preserve_box is not None:
        if len(preserve_box) != 4:
            raise ValueError(
                f"preserve_box must have exactly 4 elements [x0,y0,x1,y1], "
                f"got {len(preserve_box)}: {preserve_box}"
            )
        px0f, py0f, px1f, py1f = preserve_box
        if not (0.0 <= px0f < px1f <= 1.0 and 0.0 <= py0f < py1f <= 1.0):
            raise ValueError(
                f"preserve_box fractions must satisfy "
                f"0 ≤ x0 < x1 ≤ 1 and 0 ≤ y0 < y1 ≤ 1, got {preserve_box}"
            )

    try:
        doc = fitz.open(str(pdf_path))

        for page in doc:
            r = page.rect
            w, h = r.width, r.height

            if preserve_box is not None:
                # ── Coordinate-based mode ─────────────────────────────────
                # Convert normalised fractions → absolute points.
                abs_x0 = r.x0 + px0f * w
                abs_y0 = r.y0 + py0f * h
                abs_x1 = r.x0 + px1f * w
                abs_y1 = r.y0 + py1f * h

                # Top band  : full width, above the preserved box
                if abs_y0 > r.y0:
                    page.add_redact_annot(fitz.Rect(r.x0, r.y0, r.x1, abs_y0))

                # Bottom band : full width, below the preserved box
                if abs_y1 < r.y1:
                    page.add_redact_annot(fitz.Rect(r.x0, abs_y1, r.x1, r.y1))

                # Left band : only between y0 and y1 (top/bottom already covered)
                if abs_x0 > r.x0:
                    page.add_redact_annot(fitz.Rect(r.x0, abs_y0, abs_x0, abs_y1))

                # Right band : only between y0 and y1
                if abs_x1 < r.x1:
                    page.add_redact_annot(fitz.Rect(abs_x1, abs_y0, r.x1, abs_y1))

            else:
                # ── Percentage-based fallback (legacy) ────────────────────
                # add_redact_annot() takes coordinates in the page's raw,
                # un-rotated MediaBox frame — the same frame the content
                # stream (and get_text("rawdict")) use — never the rotated
                # *display* frame that page.rect describes. For an
                # unrotated page the two frames coincide, so the original
                # r.x0/r.y0/w/h-based rects below are correct as-is. For a
                # page carrying /Rotate 90 or 270 (landscape 2-up pecha
                # spreads use exactly this), "top_frac of what the viewer
                # sees" is NOT a horizontal band in raw coordinates — the
                # 90°/270° rotation swaps the axes, so the display top/
                # bottom band becomes a raw LEFT/RIGHT band. Using r.height
                # (the rotated dimension) here silently redacted the wrong
                # region and chopped text out of the middle of columns.
                rotation = page.rotation % 360
                if rotation in (90, 270):
                    mb = page.mediabox  # raw, un-rotated frame
                    raw_w = mb.width
                    if rotation == 90:
                        # display_y = raw_x → display "top" is the raw
                        # low-x edge, display "bottom" is the raw high-x edge.
                        if top_frac > 0.0:
                            page.add_redact_annot(
                                fitz.Rect(mb.x0, mb.y0, mb.x0 + raw_w * top_frac, mb.y1)
                            )
                        if bottom_frac > 0.0:
                            page.add_redact_annot(
                                fitz.Rect(mb.x1 - raw_w * bottom_frac, mb.y0, mb.x1, mb.y1)
                            )
                    else:  # rotation == 270 — axis mapping is mirrored vs. 90°
                        if top_frac > 0.0:
                            page.add_redact_annot(
                                fitz.Rect(mb.x1 - raw_w * top_frac, mb.y0, mb.x1, mb.y1)
                            )
                        if bottom_frac > 0.0:
                            page.add_redact_annot(
                                fitz.Rect(mb.x0, mb.y0, mb.x0 + raw_w * bottom_frac, mb.y1)
                            )
                else:
                    if top_frac > 0.0:
                        page.add_redact_annot(
                            fitz.Rect(r.x0, r.y0, r.x1, r.y0 + h * top_frac)
                        )
                    if bottom_frac > 0.0:
                        page.add_redact_annot(
                            fitz.Rect(r.x0, r.y0 + h * (1.0 - bottom_frac), r.x1, r.y1)
                        )

            page.apply_redactions(
                images=fitz.PDF_REDACT_IMAGE_NONE,
                graphics=0,
                text=fitz.PDF_REDACT_TEXT_REMOVE,
            )

        tmp = tempfile.NamedTemporaryFile(
            suffix=".pdf", delete=False, dir=tempfile.gettempdir()
        )
        tmp_path = Path(tmp.name)
        tmp.close()

        doc.save(str(tmp_path), garbage=4, deflate=True)
        doc.close()

        if preserve_box is not None:
            logger.info(
                f"    Redacted temp PDF: {tmp_path.name} "
                f"(preserve_box={preserve_box})"
            )
        else:
            logger.info(
                f"    Redacted temp PDF: {tmp_path.name} "
                f"(top={top_frac*100:.1f}%, bottom={bottom_frac*100:.1f}%)"
            )
        return tmp_path

    except Exception as e:
        logger.warning(
            f"    Failed to redact margins on {pdf_path.name}: {e} — using original PDF."
        )
        return None


def _is_wingdings_font(font_name: str) -> bool:
    if not font_name:
        return False
    base = font_name.split("+")[-1]
    compact = base.lower().replace(" ", "")
    return "wingdings" in compact



# ---------------------------------------------------------------------------
# Fix 1 & 4 — Phantom space detection
#
# Legacy Monlam/Dedris fonts encode combining marks (vowels, subscripts) as
# separate glyphs whose x-origin is shifted LEFT of the base character's
# advance position.  PyMuPDF materialises the resulting gap as a U+0020 space.
# Two sub-cases:
#
#   a) Negative advance   (subscripts): space_x < prev_x
#   b) Near-zero advance  (WinAnsi vowel spans corrected by Fix 2): the
#      corrected vowel and the space that follows share virtually the same
#      x (~0.2–0.3 pt difference — sub-pixel noise).
#
# Both are caught by: space_x < prev_x + THRESHOLD
# Real inter-word spaces always advance ≥ 4–5 pt, so they are never affected.
# ---------------------------------------------------------------------------
_PHANTOM_SPACE_ADVANCE_THRESHOLD = 1.5  # points


def _is_phantom_space(char_obj: dict, prev_char_obj: dict | None) -> bool:
    """
    Return True when *char_obj* is a phantom glyph-advance space.

    A space is phantom iff it does not advance rightward by at least
    ``_PHANTOM_SPACE_ADVANCE_THRESHOLD`` points from the preceding glyph.
    See module-level comment above for the full rationale.
    """
    if char_obj.get("c") != " ":
        return False
    if prev_char_obj is None:
        return False
    space_x = char_obj.get("origin", (0, 0))[0]
    prev_x = prev_char_obj.get("origin", (0, 0))[0]
    return space_x < prev_x + _PHANTOM_SPACE_ADVANCE_THRESHOLD


# ---------------------------------------------------------------------------
# Fix 2 — WinAnsi vowel glyph mis-mappings
#
# The WinAnsi-encoded instance of MonlamUniOuChan2 ships a broken ToUnicode
# table that maps Tibetan vowel glyph slots to Latin Extended codepoints.
# Verified by rasterising affected pages and comparing against extracted chars.
#
#   U+0140  ŀ  (l with middle dot)  →  U+0F7C  ོ  (Tibetan vowel sign O)
#   U+0132  Ĳ  (IJ digraph)         →  U+0F7A  ེ  (Tibetan vowel sign E)
#   U+0128  Ĩ  (I with tilde)       →  U+0F72  ི  (Tibetan vowel sign I)
# ---------------------------------------------------------------------------
_MONLAM_GLYPH_CORRECTIONS: dict[str, str] = {
    "\u0140": "\u0F7C",  # ŀ → ོ
    "\u0132": "\u0F7A",  # Ĳ → ེ
    "\u0128": "\u0F72",  # Ĩ → ི
}


def _correct_monlam_glyph(c: str) -> str:
    """Return the correct Tibetan character for a known Monlam WinAnsi mis-mapping."""
    return _MONLAM_GLYPH_CORRECTIONS.get(c, c)


# ---------------------------------------------------------------------------
# Fix 12 — Per-font broken-ToUnicode glyph remap
#
# Some legacy-font PDFs embed a /ToUnicode CMap that is correct for most
# glyphs but wrong for a small, bounded subset — typically because the PDF
# producer's font-conversion tool had no entry for certain conjunct/stacked
# Tibetan glyphs and fell back to emitting stray Latin punctuation
# (e.g. A-Himalaya-R: 16 of its glyph codes decode to "!\"#$%&'()*+,-./"
# instead of Tibetan). This is NOT the "font has no pytiblegenc conversion
# table at all" case (_correct_monlam_glyph's fallback already handles that
# by passing the character through unchanged) — here PyMuPDF's own
# extraction is right ~90% of the time and wrong for a few specific codes.
#
# Deliberately kept separate from _install_local_font_tables()'s pytiblegenc
# CSV merge: that mechanism registers a whole font's table with pytiblegenc,
# and an incomplete table could change behaviour for glyphs that already
# decode correctly via PyMuPDF's own ToUnicode. This remap only ever
# touches the exact (font, character) pairs listed below/in the CSV,
# leaving every other glyph from the same font untouched.
#
# Populated from local_font_tables/_broken_glyph_remap.csv (leading
# underscore keeps it out of _install_local_font_tables()'s glyph-CSV scan).
# Format: font_name,decimal_codepoint,correct_tibetan_string
# ---------------------------------------------------------------------------
_BROKEN_GLYPH_REMAP_FILENAME = "_broken_glyph_remap.csv"
_BROKEN_GLYPH_REMAP: dict[tuple[str, str], str] = {}
_BROKEN_GLYPH_REMAP_LOADED = False


def _load_broken_glyph_remap(force_reload: bool = False) -> None:
    global _BROKEN_GLYPH_REMAP_LOADED
    if _BROKEN_GLYPH_REMAP_LOADED and not force_reload:
        return
    _BROKEN_GLYPH_REMAP.clear()
    path = _LOCAL_TABLES_DIR / _BROKEN_GLYPH_REMAP_FILENAME
    if not path.is_file():
        _BROKEN_GLYPH_REMAP_LOADED = True
        return
    import csv as _csv
    loaded = 0
    skipped = 0
    with path.open(encoding="utf-8", newline="") as f:
        for row in _csv.reader(f):
            if not row or len(row) < 3:
                continue
            font_name = row[0].strip()
            if not font_name or font_name.startswith("#"):
                continue
            try:
                cp = int(row[1])
            except ValueError:
                continue
            correct = row[2]
            if not correct:
                skipped += 1  # placeholder row not yet filled in
                continue
            _BROKEN_GLYPH_REMAP[(font_name, chr(cp))] = correct
            loaded += 1
    if loaded or skipped:
        logger.info(
            "Broken-glyph remap loaded: %d entr(y/ies) from %s (%d placeholder "
            "row(s) skipped, not yet filled in).",
            loaded, path.name, skipped,
        )
    _BROKEN_GLYPH_REMAP_LOADED = True


def _correct_broken_font_glyph(c: str, font: str) -> str:
    """
    Return the correct Tibetan string for a known (font, character) broken-
    ToUnicode pair, falling back to the font-agnostic Monlam correction,
    then to the character unchanged.
    """
    remapped = _BROKEN_GLYPH_REMAP.get((font, c))
    if remapped is not None:
        return remapped
    return _correct_monlam_glyph(c)


# ---------------------------------------------------------------------------
# Fix 11 — Per-character decode cache
#
# pytiblegenc convert_string() is called for every character in every span.
# Tibetan documents use a small fixed alphabet (~80 base characters + vowels);
# the same (char, font) pair is therefore decoded thousands of times per page
# with identical results.  Memoising the lookup eliminates the redundant
# dict traversals inside pytiblegenc for all repeated characters.
#
# The cache is per-process (module-level dict).  Call _reset_decode_cache()
# after hot-reloading font tables so stale results are not reused.
# ---------------------------------------------------------------------------
_DECODE_CACHE: dict[tuple[str, str], "str | None"] = {}
_DECODE_MISSING = object()  # sentinel distinct from None (a valid decode result)


def _reset_decode_cache() -> None:
    """Clear the per-character decode memo (call after reloading font tables)."""
    _DECODE_CACHE.clear()


def _decode_char_cached(
    c: str,
    target_font: str,
    glyph_lookup,
    stats: dict,
) -> "str | None":
    """
    Memoized wrapper around ``pytiblegenc.char_converter.convert_string``
    for a single character.

    Returns the decoded Unicode string, or ``None`` when the font has no
    conversion table (caller then falls back to ``_correct_monlam_glyph``).

    Note: ``stats`` is passed through to convert_string so per-font
    unhandled/handled counters keep accumulating, but only on cache misses.
    Cache hits do not update stats — this is intentional: the first miss
    already counted the character, and subsequent hits are the same glyph.
    """
    key = (c, target_font)
    cached = _DECODE_CACHE.get(key, _DECODE_MISSING)
    if cached is not _DECODE_MISSING:
        return cached  # type: ignore[return-value]
    from pytiblegenc.char_converter import convert_string
    decoded = convert_string(
        c, target_font, stats, error_chr_fun=None, glyph_lookup=glyph_lookup
    )
    _DECODE_CACHE[key] = decoded
    return decoded


# Leading marks that belong on the previous syllable when PDF layout splits a line.
_RE_TIBETAN_ORPHAN_LEADING = re.compile(
    r"^[\u0F71\u0F72\u0F73\u0F74\u0F75\u0F76\u0F77\u0F78\u0F79"
    r"\u0F7A\u0F7B\u0F7C\u0F7D\u0F7E\u0F7F\u0F80\u0F81\u0F82\u0F83"
    r"\u0F93-\u0FBC]+"
)


def _plain_without_fs(s: str) -> str:
    return _FS_TAG_RE.sub("", s) if s else ""


def _prev_line_allows_tibetan_orphan_merge(prev_line: str) -> bool:
    """True when the previous layout line ends in Tibetan and should absorb leading marks."""
    plain = _plain_without_fs(prev_line).rstrip()
    if not plain:
        return False
    # Do not glue into Latin-only lines (e.g. English copyright block).
    return bool(re.search(r"[\u0F00-\u0FFF]$", plain))


def _split_leading_tibetan_orphan_fs_aware(line: str) -> tuple[str, str]:
    """
    If *line* begins with Tibetan combining/subjoined marks (optionally after
    leading ``<fs:N>`` tags), return (prefix_to_append_to_previous_line, remainder).
    Otherwise ("", line).
    """
    if not line:
        return "", line
    plain = _plain_without_fs(line)
    m = _RE_TIBETAN_ORPHAN_LEADING.match(plain)
    if not m:
        return "", line
    expected = m.group(0)
    taken: list[str] = []
    i = 0
    pos = 0  # index into expected
    while i < len(line) and pos < len(expected):
        mt = re.match(r"<fs:\d+>", line[i:])
        if mt:
            if pos == 0:
                taken.append(mt.group(0))
            i += len(mt.group(0))
            continue
        ch = line[i]
        if ch == expected[pos]:
            taken.append(ch)
            pos += 1
            i += 1
        else:
            return "", line
    if pos != len(expected):
        return "", line
    return "".join(taken), line[i:]


def _merge_orphan_tibetan_line_breaks(text: str) -> str:
    """
    Join lines where the PDF split a Tibetan stack across two MuPDF newlines.

    Operates on the raw extractor stream (``<fs:N>`` tags and ``\\n`` only;
    page breaks use ``PAGE_BREAK_STR``).
    """
    if not text or not text.strip():
        return text
    sep = f"\n{PAGE_BREAK_STR}\n"
    pages = text.split(sep)
    out_pages: list[str] = []

    for page in pages:
        lines = page.split("\n")
        if not lines:
            out_pages.append(page)
            continue
        merged: list[str] = [lines[0]]
        for j in range(1, len(lines)):
            curr = lines[j]
            prev = merged[-1]
            if not _prev_line_allows_tibetan_orphan_merge(prev):
                merged.append(curr)
                continue
            prefix, rest = _split_leading_tibetan_orphan_fs_aware(curr)
            if not prefix:
                merged.append(curr)
                continue
            # Join the rest of this layout line onto the same row (PDF split before the vowel).
            merged[-1] = prev + prefix + rest
        out_pages.append("\n".join(merged))

    return sep.join(out_pages)


# ---------------------------------------------------------------------------
# Fix 5 — Duplicate text-layer deduplication
#
# Some InDesign / Acrobat-generated PDFs place every visual line twice in the
# content stream at identical coordinates (same y_mid, same x0, same text).
# Without deduplication both copies land in the same merged visual row and
# their fragments are emitted twice, producing verbatim repeated text.
#
# Strategy: after collecting raw_lines, remove any entry whose (y_bucket, x0,
# text) key has already been seen.  y_bucket is y_mid rounded to the nearest
# _Y_MERGE_TOLERANCE step so sub-pixel y differences between copies don't
# defeat the check.  text_key strips font-size tags before comparison.
# ---------------------------------------------------------------------------


def _deduplicate_raw_lines(
    raw_lines: list[tuple[float, float, list[str]]],
    y_tolerance: float,
    line_spans: Optional[list[tuple[float, float]]] = None,
):
    """
    Remove duplicate raw lines produced by PDFs with overlapping text layers.

    Keeps the first occurrence of each (y_bucket, x0_rounded, text_key) triple.
    See module-level Fix 5 comment for full rationale.

    If *line_spans* (a parallel list of (x0, x1) extents, same length and order
    as *raw_lines*) is supplied, the matching spans are filtered in lockstep and
    the function returns ``(deduped_lines, deduped_spans)`` so column detection
    keeps a correctly aligned span for every surviving line.  When *line_spans*
    is ``None`` the function returns just the deduplicated list (legacy behaviour).
    """
    seen: set[tuple[float, float, str]] = set()
    deduped: list[tuple[float, float, list[str]]] = []
    deduped_spans: list[tuple[float, float]] = []

    for idx, (y_mid, x0, frags) in enumerate(raw_lines):
        y_bucket = round(y_mid / y_tolerance) * y_tolerance
        x_bucket = round(x0, 1)
        text_key = _FS_TAG_RE.sub("", "".join(frags))

        key = (y_bucket, x_bucket, text_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((y_mid, x0, frags))
        if line_spans is not None and idx < len(line_spans):
            deduped_spans.append(line_spans[idx])

    if line_spans is not None:
        return deduped, deduped_spans
    return deduped


# ---------------------------------------------------------------------------
# Footnote detection
#
# A footnote in these Tibetan prints is laid out as a short horizontal rule on
# the LEFT margin, low on the page, with smaller-than-body text beneath it.
# The body carries an inline reference marker like "[1]".  We detect the rule,
# treat everything at/below it as note content, pull it out of the normal body
# flow, and re-attach it inline right after its matching marker as a TEI <note>.
#
# Care is taken to avoid false positives — a table of contents has decorative
# rules before section titles, but those are centred/indented and sit high on
# the page, so the left-margin + bottom-region requirement rejects them.
# ---------------------------------------------------------------------------

def _footnote_settings() -> dict:
    """
    Read footnote thresholds from config when available, else use module
    defaults.  Returns a dict the detector consumes.  config is optional so
    pdf_extract stays importable standalone (e.g. in tests).
    """
    s = {
        "enabled": True,
        "sep_min_w": _FN_SEP_MIN_WIDTH_PT,
        "sep_max_w": _FN_SEP_MAX_WIDTH_PT,
        "min_y_frac": _FN_SEP_MIN_Y_FRACTION,
        "left_tol": _FN_SEP_LEFT_MARGIN_TOL,
        "body_ratio": _FN_BODY_SIZE_RATIO,
    }
    try:
        import config  # type: ignore
        s["enabled"] = bool(getattr(config, "FOOTNOTE_DETECTION", True))
        if hasattr(config, "FOOTNOTE_SEPARATOR_MIN_WIDTH_PT"):
            s["sep_min_w"] = float(config.FOOTNOTE_SEPARATOR_MIN_WIDTH_PT)
        if hasattr(config, "FOOTNOTE_SEPARATOR_MAX_WIDTH_PT"):
            s["sep_max_w"] = float(config.FOOTNOTE_SEPARATOR_MAX_WIDTH_PT)
    except Exception:
        pass
    return s


def _find_footnote_separator_y(page, body_left_x: float, settings: dict) -> Optional[float]:
    """
    Return the y-coordinate of a footnote separator rule on *page*, or None.

    A qualifying separator is a (near-)horizontal line/rectangle that:
      * is between sep_min_w and sep_max_w wide,
      * starts within left_tol of the body's left margin, and
      * sits below min_y_frac of the page height.

    When several qualify (rare), the highest one is returned so all note lines
    below it are captured.
    """
    h = page.rect.height
    min_y = page.rect.y0 + h * settings["min_y_frac"]
    candidates: list[float] = []

    try:
        drawings = page.get_drawings()
    except Exception:
        return None

    for dr in drawings:
        for item in dr.get("items", []):
            x0 = x1 = y = None
            if item[0] == "l":  # line: (op, p1, p2)
                p1, p2 = item[1], item[2]
                if abs(p1.y - p2.y) < 1.5:  # horizontal
                    x0, x1, y = min(p1.x, p2.x), max(p1.x, p2.x), (p1.y + p2.y) / 2.0
            elif item[0] == "re":  # rectangle: (op, rect)
                r = item[1]
                if r.height < 2.5:  # a thin filled rect == a rule
                    x0, x1, y = r.x0, r.x1, (r.y0 + r.y1) / 2.0
            if y is None:
                continue
            width = x1 - x0
            if not (settings["sep_min_w"] <= width <= settings["sep_max_w"]):
                continue
            if abs(x0 - body_left_x) > settings["left_tol"]:
                continue  # not on the left margin → decorative / TOC rule
            if y < min_y:
                continue  # too high → not a footnote separator
            candidates.append(y)

    if not candidates:
        return None
    return min(candidates)  # highest separator → capture everything beneath


# Inline footnote marker as it survives decoding, e.g. "[1]", "[12]".
_FN_MARKER_RE = re.compile(r"\[(\d+)\]")

# Tibetan digits U+0F20–U+0F29.
_TIB_DIGIT_RE = re.compile(r"[\u0f20-\u0f29]+")
_TIB_TO_ARABIC = {chr(0x0f20 + i): str(i) for i in range(10)}


def _tib_to_arabic(s: str) -> str:
    """Convert a run of Tibetan digits to an ASCII number string."""
    return "".join(_TIB_TO_ARABIC.get(c, c) for c in s)


def _split_footnotes_by_tibetan_numerals(block: str) -> list[tuple[str, str]]:
    """
    Split a footnote block whose individual notes are introduced by a leading
    Tibetan-digit number (e.g. ``༡ … ༢ … ༣ …``) into ``(num, text)`` pairs.

    Many Tibetan prints number footnotes with Tibetan numerals at the start of
    each note rather than with bracketed ASCII markers.  We find candidate
    numeral runs and keep only the chain that counts up 1, 2, 3, … so stray
    Tibetan digits inside note text (page refs, dates) don't cause false splits.
    Returns [] when no plausible 1-based chain is found.
    """
    candidates = list(_TIB_DIGIT_RE.finditer(block))
    if not candidates:
        return []

    # Greedily build the longest run that starts at 1 and increments by 1.
    starts: list[tuple[int, int, int]] = []  # (expected_value, start_idx, end_idx)
    expected = 1
    for m in candidates:
        val_str = _tib_to_arabic(m.group(0))
        if not val_str.isdigit():
            continue
        val = int(val_str)
        if val == expected:
            starts.append((val, m.start(), m.end()))
            expected += 1

    # Need at least the first note (#1) to anchor; a lone #1 is still valid.
    if not starts:
        return []

    notes: list[tuple[str, str]] = []
    for i, (val, s, e) in enumerate(starts):
        text_end = starts[i + 1][1] if i + 1 < len(starts) else len(block)
        text = block[e:text_end].strip(" ་\u0f0b")  # trim spaces / leading tsheg
        text = text.strip()
        if text:
            notes.append((str(val), text))
    return notes


def _build_footnote_tokens(
    footnote_lines: list[tuple[float, float, list[str]]],
    extraction_dedup: bool,
) -> list[str]:
    """
    Turn the collected below-separator lines into one note token per footnote.

    The lines are sorted top→bottom (merging same-row fragments left→right),
    joined into one text block, then split into individual footnotes.  Two
    numbering conventions are recognised, in order:

      1. Bracketed ASCII markers ``[N]`` introducing each note.
      2. Leading Tibetan-digit numbers ``༡ ༢ ༣ …`` (common in Tibetan prints).

    Each token is

        _NOTE_OPEN + "<N>|<decoded text>" + _NOTE_CLOSE

    with ``<N>`` an ASCII number so it aligns with the Arabic reference markers
    the body carries (the converter matches them positionally per page).  If no
    numbering is found the whole block becomes one unnumbered note so content is
    never dropped.  convert_markup_to_tei consumes these and emits TEI <note>.
    """
    # Sort + merge rows the same way the body flow does.
    footnote_lines.sort(key=lambda t: (t[0], t[1]))
    merged: list[list[tuple[float, float, list[str]]]] = []
    for y_mid, x0, frags in footnote_lines:
        if merged:
            avg_y = sum(e[0] for e in merged[-1]) / len(merged[-1])
            if abs(y_mid - avg_y) <= _Y_MERGE_TOLERANCE:
                merged[-1].append((y_mid, x0, frags))
                continue
        merged.append([(y_mid, x0, frags)])

    row_texts: list[str] = []
    for row in merged:
        row.sort(key=lambda t: t[1])
        if extraction_dedup:
            row = _dedup_within_row(row)
        row_texts.append("".join("".join(fr) for _y, _x, fr in row))

    block = " ".join(t for t in row_texts if t.strip())
    # Drop font-size tags inside footnotes — note text is uniformly small.
    block = _FS_TAG_RE.sub("", block).strip()
    if not block:
        return []

    # Convention 1 — bracketed ASCII markers "[N]".
    matches = list(_FN_MARKER_RE.finditer(block))
    if matches:
        tokens: list[str] = []
        for i, m in enumerate(matches):
            num = m.group(1)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
            text = block[start:end].strip()
            if text:
                tokens.append(_NOTE_OPEN + f"{num}|" + text + _NOTE_CLOSE)
        return tokens

    # Convention 2 — leading Tibetan-digit numbering "༡ ༢ ༣ …".
    tib_notes = _split_footnotes_by_tibetan_numerals(block)
    if tib_notes:
        return [
            _NOTE_OPEN + f"{num}|" + text + _NOTE_CLOSE
            for num, text in tib_notes
        ]

    # No recognisable numbering — emit the whole block as one unnumbered note.
    return [_NOTE_OPEN + "|" + block + _NOTE_CLOSE]


# Tolerance in points for treating two MuPDF lines as the same visual row.
# Tibetan glyphs with vowel marks can cause small Y shifts across spans.
_Y_MERGE_TOLERANCE = 4.0

# Maximum x-offset between two same-text entries in a merged row that are still
# considered InDesign shadow copies rather than genuine repeated words.
# InDesign drop-shadow offsets are typically 1–3 pt; genuine word repetitions
# in the same line are separated by at least one character-advance (≥ 8 pt).
_SHADOW_X_THRESHOLD = 5.0

# ---------------------------------------------------------------------------
# Vertical pecha layout detection and sorting
#
# Some Tibetan documents are traditional pecha (loose-leaf) books scanned in
# landscape orientation with text running vertically (top→bottom per column,
# columns ordered left→right).  Three problems arise:
#
#   * Detection (issue 1): MuPDF reports each text line with a ``dir``
#     direction vector.  On a horizontal page dir ≈ (1,0); on a rotated
#     pecha page dir ≈ (0,±1).  We vote by character mass so near-blank
#     pages with only marginalia don't flip the decision.
#
#   * Marginalia (issue 2): running title and folio numbers are printed
#     *horizontally* in the top/bottom margins, perpendicular to the body.
#     On a vertical page these are the only horizontal lines, so dropping
#     every horizontal line removes them cleanly without heuristic thresholds.
#
#   * Reading order (issue 3): for vertical body text reading order runs
#     along the X axis (successive vertical lines go left→right), not Y.
#     We swap to an x-primary sort when a page is detected as vertical.
# ---------------------------------------------------------------------------

# A line counts as "vertical" when |dy| dominates |dx| in its direction vector.
_VERTICAL_DIR_RATIO = 1.5
# Fraction of the short page dimension treated as the marginal edge band.
_PECHA_EDGE_BAND_FRAC = 0.18
# A page is treated as vertical-pecha when at least this fraction of its
# decoded characters live in vertical lines.
_VERTICAL_PAGE_CHAR_FRAC = 0.6
# Number of pages sampled to decide whether a whole document is a rotated pecha.
_PECHA_DOC_SAMPLE = 12
# Fraction of content-bearing sampled pages that must be vertical for the
# document to be treated as pecha.
_PECHA_DOC_FRAC = 0.6


def _line_is_vertical(direction) -> bool:
    """True when a MuPDF line ``dir`` vector points mostly up/down."""
    dx, dy = direction
    return abs(dy) > abs(dx) * _VERTICAL_DIR_RATIO


def _line_is_horizontal(direction) -> bool:
    """True when a MuPDF line ``dir`` vector points mostly left/right."""
    dx, dy = direction
    return abs(dx) > abs(dy) * _VERTICAL_DIR_RATIO


def _page_is_vertical(entries) -> bool:
    """
    Decide whether a page's body text is vertical (rotated pecha).

    *entries* is the per-line list of ``(y_mid, x0, fragments, direction, bbox)``
    5-tuples.  The decision is by decoded-character mass: if most characters
    sit in vertical lines the page is vertical.
    """
    vert = 0
    total = 0
    for _y, _x, frags, direction, _bbox in entries:
        n = len(_FS_TAG_RE.sub("", "".join(frags)).strip())
        if n == 0:
            continue
        total += n
        if _line_is_vertical(direction):
            vert += n
    if total == 0:
        return False
    return (vert / total) >= _VERTICAL_PAGE_CHAR_FRAC


def _document_is_pecha(doc, font_normalization, glyph_lookup, stats) -> bool:
    """
    Decide once per document whether it is a rotated pecha layout.

    Rationale: individual pecha pages can be near-blank (only the running
    title and folio number in the margins).  A per-page orientation test
    misclassifies those as horizontal and lets the marginalia leak into the
    body.  Deciding at the document level — by sampling pages and checking
    the dominant body orientation among content-bearing pages — keeps the
    marginalia filter and the vertical reading-order path active on
    blank-body pages too.

    A strong, cheap precondition is the page rotation flag: pecha PDFs are
    landscape pages flagged 90°/270°.  We require both that the rotation is
    non-zero on the sampled pages *and* that vertical body text dominates.
    """
    try:
        page_count = doc.page_count
    except Exception:
        return False
    if page_count == 0:
        return False

    step = max(1, page_count // _PECHA_DOC_SAMPLE)
    sample_idxs = list(range(0, page_count, step))[:_PECHA_DOC_SAMPLE]

    rotated_any = False
    vertical_pages = 0
    content_pages = 0
    for idx in sample_idxs:
        try:
            page = doc[idx]
        except Exception:
            continue
        if page.rotation % 180 != 0:
            rotated_any = True
        recs = []
        for block in page.get_text("rawdict").get("blocks", []):
            if block.get("type", 1) != 0:
                continue
            for line in block.get("lines", []):
                frags = _extract_line_text_hybrid(
                    line, font_normalization, glyph_lookup, stats
                )
                if frags:
                    recs.append((
                        0, 0, frags,
                        line.get("dir", (1.0, 0.0)),
                        line.get("bbox", [0, 0, 0, 0]),
                    ))
        total = sum(
            len(_FS_TAG_RE.sub("", "".join(f)).strip()) for _, _, f, _, _ in recs
        )
        if total < 30:
            continue  # near-blank page — ignore for the vote
        content_pages += 1
        if _page_is_vertical(recs):
            vertical_pages += 1

    if content_pages == 0:
        return rotated_any
    return rotated_any and (vertical_pages / content_pages) >= _PECHA_DOC_FRAC


def _is_pecha_marginalia(direction, bbox, page_w: float, page_h: float) -> bool:
    """
    True when a line on a vertical-pecha page is running-header / folio
    marginalia that should be dropped.

    On a vertical-pecha page genuine body text is *vertical*; running titles
    and folio numbers are *horizontal* lines in the margins.  The writing
    direction is therefore the primary, robust signal.
    """
    return _line_is_horizontal(direction)


def _is_short_edge_run(frags, bbox, page_h: float) -> bool:
    """
    Secondary guard for vertical pages: a very short text run (folio number,
    section letter) in the extreme top/bottom edge band.

    Kept separate from the direction test so it only removes tiny runs,
    never a full body column that starts near the edge.
    """
    line_text = _FS_TAG_RE.sub("", "".join(frags)).strip()
    if len(line_text) > 3:
        return False
    band = page_h * _PECHA_EDGE_BAND_FRAC
    y0, y1 = bbox[1], bbox[3]
    return (y1 <= band) or (y0 >= (page_h - band))


# ---------------------------------------------------------------------------
# Horizontal-page left-margin running-title marginalia
#
# Some horizontal (non-pecha) books print a running section title sideways
# in the left margin, repeating the section heading in two or three scripts
# -- e.g. a rotated Tibetan line, plus a CJK translation rendered as a stack
# of individually-upright single-character "lines" (MuPDF reports each of
# those with dir == (1,0) even though positionally they read top-to-bottom
# as a column). Two distinct MuPDF line shapes therefore carry this
# marginalia on an otherwise-horizontal page:
#
#   (a) genuinely rotated text -- dir far from (1,0);
#   (b) upright text stacked one (or a couple of) character(s) per row, all
#       confined to the same narrow x-band as (a).
#
# Detection must not fire on pages whose real body text legitimately starts
# near the left edge -- e.g. a table-of-contents page-number column can sit
# at a similar x0 to this margin band. So the filter only activates on a
# page that already contains at least one clearly *rotated* line inside the
# band; only then are the narrow same-band upright lines on THAT page also
# dropped. Pages without a rotated marginalia line (TOC, colophon, ...) are
# returned unchanged.
# ---------------------------------------------------------------------------
_LEFT_MARGIN_BAND_FRAC = 0.11          # x-band, as a fraction of page width
_LEFT_MARGIN_MAX_LINE_WIDTH_PT = 20.0  # width of a "single-character stack" row


def _strip_horizontal_page_left_margin_marginalia(
    line_records: list[tuple], page_width: float
) -> list[tuple]:
    """
    Drop left-margin running-title marginalia from a horizontal (non-pecha)
    page's ``(y_mid, x0, fragments, direction, bbox)`` records.

    No-op unless the page shows a genuinely rotated line inside the margin
    band -- see the module comment above for why that guard exists.
    """
    band_x = page_width * _LEFT_MARGIN_BAND_FRAC

    has_rotated_marginalia = any(
        _line_is_vertical(direction) and bbox[0] < band_x
        for (_y, _x, _f, direction, bbox) in line_records
    )
    if not has_rotated_marginalia:
        return line_records

    kept: list[tuple] = []
    for rec in line_records:
        _y, _x, _frags, direction, bbox = rec
        in_band = bbox[0] < band_x and bbox[2] < band_x
        if in_band and _line_is_vertical(direction):
            continue  # rotated marginalia (a)
        if in_band and (bbox[2] - bbox[0]) <= _LEFT_MARGIN_MAX_LINE_WIDTH_PT:
            continue  # stacked single-character marginalia (b)
        kept.append(rec)
    return kept


# ---------------------------------------------------------------------------
# Landscape 2-up pecha spreads: stacked sub-page detection
#
# PyMuPDF's raw text coordinates for a page are reported in the PDF's
# original (un-rotated) MediaBox frame — NOT the rotated frame ``page.rect``
# describes.  For a genuine rotated-pecha scan this is usually harmless:
# each "line" bbox is one vertical column running the height of a single
# source page, so a flat x-primary sort reconstructs reading order fine.
#
# But some landscape scans pack TWO book pages into one PDF page (a 2-up
# spread), each occupying the full raw-frame X range but only half the raw
# Y range (they're stacked top/bottom in the un-rotated frame, which becomes
# left/right once the page's rotation is applied for display). A flat
# x-primary sort across the whole page interleaves columns from both
# sub-pages whenever their x-ranges overlap (which they do, since each
# spans the same un-rotated width) — this is what produces alternating,
# fragment-scrambled output on such spreads.
#
# Detecting a Y-gap between the two sub-pages' column extents (mirroring
# the horizontal-page multi-column detector, transposed to the Y axis) lets
# us process each sub-page's columns independently and then order the two
# sub-pages correctly for the page's rotation.
# ---------------------------------------------------------------------------

_BAND_GAP_MIN_PT: float = 30.0
_BAND_MIN_LINES_PER_SIDE: int = 2
_BAND_MAX_CROSS_FRACTION: float = 0.10


def _detect_pecha_band_splits(
    entries: list[tuple],
) -> list[float]:
    """
    Return sorted Y split point(s) separating stacked sub-pages within a
    single vertical-pecha PDF page, or an empty list when the page is a
    single sub-page (the common case).

    *entries* is the ``kept`` list of ``(y_mid, x0, frags, direction, bbox)``
    5-tuples for a vertical-pecha page (after marginalia removal).  Each
    entry's bbox is a raw-frame ``[x0, y0, x1, y1]``; on a vertical page a
    column's y-span (y0..y1) runs the height of its own sub-page, so a real
    sub-page boundary has almost no column crossing it (mirrors the
    crossing-validation test in ``_detect_column_splits``).
    """
    if not entries:
        return []

    y_spans = [(bbox[1], bbox[3]) for (_y, _x, _f, _d, bbox) in entries]
    y0_values = sorted(set(round(y0) for y0, _y1 in y_spans))
    if len(y0_values) < 2:
        return []

    gaps: list[tuple[float, float]] = []
    for i in range(1, len(y0_values)):
        gap = y0_values[i] - y0_values[i - 1]
        if gap >= _BAND_GAP_MIN_PT:
            gaps.append((gap, y0_values[i - 1] + gap / 2.0))
    if not gaps:
        return []

    y_spread = y0_values[-1] - y0_values[0]
    threshold = max(_BAND_GAP_MIN_PT, y_spread * 0.15)
    candidates = sorted(mid for size, mid in gaps if size >= threshold)
    if not candidates:
        return []

    total = len(y_spans)
    kept_splits: list[float] = []
    for div in candidates:
        top_edges = [y1 for y0, y1 in y_spans if y0 < div]
        bottom_starts = [y0 for y0, _y1 in y_spans if y0 >= div]
        if top_edges and bottom_starts:
            gutter = (max(top_edges) + min(bottom_starts)) / 2.0
        else:
            gutter = div
        crossing = sum(1 for y0, y1 in y_spans if y0 < gutter < y1)
        if total and (crossing / total) <= _BAND_MAX_CROSS_FRACTION:
            kept_splits.append(gutter)
    candidates = sorted(kept_splits)
    if not candidates:
        return []

    boundaries = (
        [(-1e9, candidates[0])]
        + [(candidates[i], candidates[i + 1]) for i in range(len(candidates) - 1)]
        + [(candidates[-1], 1e9)]
    )
    counts = [0] * len(boundaries)
    for y0, _y1 in y_spans:
        for ci, (lo, hi) in enumerate(boundaries):
            if lo <= y0 < hi:
                counts[ci] += 1
                break
    if any(c < _BAND_MIN_LINES_PER_SIDE for c in counts):
        return []

    return candidates


# ---------------------------------------------------------------------------
# Multi-column layout detection and sorting
#
# Some Tibetan documents (e.g. tables of contents, commentary pages) use a
# two-column layout.  PyMuPDF's default coordinate sort (y ascending, then x)
# reads across both columns row-by-row, jumbling the two streams.
#
# Strategy:
#   1. Collect the x0 of every text block on the page.
#   2. Look for a clear horizontal gap in the x0 distribution that splits
#      blocks into two (or more) non-overlapping clusters.  The gap must be
#      wider than _COLUMN_GAP_MIN_PT and the page must have at least
#      _COLUMN_MIN_BLOCKS_PER_SIDE blocks on each side to count as multi-column.
#   3. When a multi-column layout is detected, assign each raw_line to a column
#      by its x0, sort each column top-to-bottom independently, then concatenate
#      columns left-to-right.  Single-column pages are unaffected.
#
# This is intentionally conservative: a gap must be *wider than half the median
# block width* to avoid splitting wide blocks that merely start at different x
# positions.  False-positive column detection would corrupt single-column pages,
# which is worse than missing a real column.
# ---------------------------------------------------------------------------

_COLUMN_GAP_MIN_PT: float = 30.0   # gap narrower than this → single column
_COLUMN_MIN_BLOCKS_PER_SIDE: int = 2  # at least N lines on each side

# A genuine column divider is crossed by almost no lines (left-column lines
# end before it; right-column lines start after it).  If more than this
# fraction of lines span a candidate divider, the page is single-column with
# varied indents — not multi-column — and the divider is rejected.  Real
# two-column scans cross at ~0 %; single-column prose crosses well above 30 %.
_COLUMN_MAX_CROSS_FRACTION: float = 0.10


def _detect_column_splits(
    raw_lines: list[tuple[float, float, list]],
    page_width: float,
    line_spans: Optional[list[tuple[float, float]]] = None,
) -> list[float]:
    """
    Return a sorted list of x-coordinates that serve as column dividers.

    Each divider x means: lines with x0 < x belong to the column to the left,
    lines with x0 >= x belong to the column to the right.

    Returns an empty list when no reliable multi-column split is found
    (i.e. treat the page as single-column).

    Parameters
    ----------
    raw_lines : list of (y_mid, x0, fragments)
    page_width : float  — used to compute a sensible gap threshold
    line_spans : optional list of (x0, x1) horizontal extents, one per entry
        in *raw_lines* and in the same order.  When supplied, a candidate
        divider is only accepted if very few lines physically *cross* it
        (their text spans the divider).  This is the decisive test that
        separates a genuine two-column layout — where left-column lines end
        before the divider and right-column lines start after it, so almost
        nothing crosses — from a single-column page whose lines merely start
        at different indents (paragraph indents, centred headings, right-
        aligned colophons).  On such single-column pages the full-width body
        lines cross any candidate divider, so the divider is rejected.

    Without *line_spans* the function falls back to the older start-position
    heuristic; callers that can supply spans always should.
    """
    if not raw_lines:
        return []

    # Build a frequency count of rounded x0 start positions.  A genuine
    # column edge is shared by many lines; an isolated heading, running
    # title, or folio number contributes a single distinct x0 value that can
    # land between two real column clusters — fragmenting the one true
    # inter-column gap into two smaller, spurious gaps, neither of which is
    # the actual divider (see the "Multi-column layout detection" module
    # comment above). Such an outlier line is usually also wide enough to
    # physically span across the true gutter (a centred heading sits above
    # *both* columns), so it must be excluded from every divider-finding
    # computation below — not just the gap scan, but also the gutter-snap
    # and crossing-count that follow — or it corrupts those the same way.
    # "Clustered" lines (x0 shared by >= _COLUMN_MIN_BLOCKS_PER_SIDE lines)
    # are used to *find* the divider; once found, it's applied to the full
    # raw_lines list by the caller, so outlier lines still get assigned to
    # whichever column they fall into — nothing is dropped from the output.
    x0_counts: dict[float, int] = {}
    for ln in raw_lines:
        key = round(ln[1])
        x0_counts[key] = x0_counts.get(key, 0) + 1

    clustered_idx = [
        i for i, ln in enumerate(raw_lines)
        if x0_counts[round(ln[1])] >= _COLUMN_MIN_BLOCKS_PER_SIDE
    ]
    # Not enough clustered signal to trust the filter — fall back to using
    # every line (old behaviour) rather than risk discarding real data.
    if len(clustered_idx) < 2 * _COLUMN_MIN_BLOCKS_PER_SIDE:
        clustered_idx = list(range(len(raw_lines)))

    clustered_lines = [raw_lines[i] for i in clustered_idx]
    clustered_spans = (
        [line_spans[i] for i in clustered_idx] if line_spans is not None else None
    )

    x0_values = sorted(set(round(ln[1]) for ln in clustered_lines))
    if len(x0_values) < 2:
        return []

    # Find gaps between consecutive x0 values
    gaps: list[tuple[float, float]] = []  # (gap_size, gap_start)
    for i in range(1, len(x0_values)):
        gap = x0_values[i] - x0_values[i - 1]
        if gap >= _COLUMN_GAP_MIN_PT:
            gaps.append((gap, x0_values[i - 1] + gap / 2.0))  # midpoint of gap

    if not gaps:
        return []

    # Keep only gaps that are at least as wide as _COLUMN_GAP_MIN_PT AND
    # larger than 50 % of the median x0 spread (avoids micro-splits).
    x0_spread = x0_values[-1] - x0_values[0]
    threshold = max(_COLUMN_GAP_MIN_PT, x0_spread * 0.15)
    candidate_splits = sorted(
        mid for size, mid in gaps if size >= threshold
    )

    if not candidate_splits:
        return []

    # ── Crossing validation (decisive test) ────────────────────────────────
    # A real column divider has almost no lines spanning across it.  Reject
    # any candidate that too many lines cross; if every candidate is rejected
    # the page is single-column.  This must run before the count check so a
    # page of full-width prose with varied indents is never treated as multi-
    # column (the bug that scrambled single-column reading order).
    if clustered_spans is not None:
        total = len(clustered_spans)
        kept: list[float] = []
        for div in candidate_splits:
            # Snap the divider into the actual whitespace gutter.  The gap was
            # computed from line *start* positions, whose midpoint can fall
            # inside the left column on a genuine two-column page (left lines
            # are wider than their indent gap).  The true divider sits between
            # the rightmost edge of the lines that start left of the candidate
            # and the leftmost start of the lines that begin right of it.
            # Uses only clustered (non-outlier) spans — see comment above on
            # why an outlier line must not influence this snap either.
            left_edges = [x1 for x0, x1 in clustered_spans if x0 < div]
            right_starts = [x0 for x0, _x1 in clustered_spans if x0 >= div]
            if left_edges and right_starts:
                gutter = (max(left_edges) + min(right_starts)) / 2.0
            else:
                gutter = div
            crossing = sum(1 for x0, x1 in clustered_spans if x0 < gutter < x1)
            if total and (crossing / total) <= _COLUMN_MAX_CROSS_FRACTION:
                kept.append(gutter)
        candidate_splits = sorted(kept)
        if not candidate_splits:
            return []

    # Validate: each resulting column must have at least
    # _COLUMN_MIN_BLOCKS_PER_SIDE lines assigned to it.
    # Build column boundaries: (-∞, split0), (split0, split1), …, (splitN-1, +∞)
    boundaries = (
        [(-1e9, candidate_splits[0])]
        + [(candidate_splits[i], candidate_splits[i + 1])
           for i in range(len(candidate_splits) - 1)]
        + [(candidate_splits[-1], 1e9)]
    )
    col_counts = [0] * len(boundaries)
    for _y, x0, _frags in raw_lines:
        for ci, (lo, hi) in enumerate(boundaries):
            if lo <= x0 < hi:
                col_counts[ci] += 1
                break

    if any(c < _COLUMN_MIN_BLOCKS_PER_SIDE for c in col_counts):
        return []

    return candidate_splits


def _sort_lines_multicolumn(
    raw_lines: list[tuple[float, float, list]],
    column_splits: list[float],
) -> list[tuple[float, float, list]]:
    """
    Re-order *raw_lines* so that lines are sorted column-by-column
    (left column top→bottom, then right column top→bottom, …).

    When *column_splits* is empty this is a no-op (returns the list unchanged).
    """
    if not column_splits:
        return raw_lines

    # Build column slot boundaries
    splits = sorted(column_splits)
    boundaries = (
        [(-1e9, splits[0])]
        + [(splits[i], splits[i + 1]) for i in range(len(splits) - 1)]
        + [(splits[-1], 1e9)]
    )

    columns: list[list[tuple[float, float, list]]] = [[] for _ in boundaries]
    for entry in raw_lines:
        _y, x0, _frags = entry
        for ci, (lo, hi) in enumerate(boundaries):
            if lo <= x0 < hi:
                columns[ci].append(entry)
                break

    # Sort each column top-to-bottom (ascending y_mid)
    result: list[tuple[float, float, list]] = []
    for col in columns:
        col.sort(key=lambda t: t[0])
        result.extend(col)

    return result

# Unicode ranges for CJK Unified Ideographs, CJK Extension A/B, and common
# CJK symbols/punctuation.  If a row contains any of these characters the
# drop-shadow heuristic must be disabled: CJK table layouts genuinely repeat
# the same character in adjacent cells (e.g. 書號 … 書名) and the threshold
# logic would incorrectly suppress those real column entries.
_CJK_RE = re.compile(
    r"[\u2E80-\u2EFF"   # CJK Radicals Supplement
    r"\u2F00-\u2FDF"    # Kangxi Radicals
    r"\u3000-\u303F"    # CJK Symbols and Punctuation
    r"\u3040-\u30FF"    # Hiragana + Katakana
    r"\u3400-\u4DBF"    # CJK Extension A
    r"\u4E00-\u9FFF"    # CJK Unified Ideographs
    r"\uF900-\uFAFF"    # CJK Compatibility Ideographs
    r"\uFE30-\uFE4F"    # CJK Compatibility Forms
    r"\U00020000-\U0002A6DF]"  # CJK Extension B
)


def _row_contains_cjk(row: list[tuple[float, float, list[str]]]) -> bool:
    """Return True if any fragment in *row* contains a CJK character."""
    for _y, _x, frags in row:
        text = _FS_TAG_RE.sub("", "".join(frags))
        if _CJK_RE.search(text):
            return True
    return False


def _dedup_within_row(
    row: list[tuple[float, float, list[str]]],
) -> list[tuple[float, float, list[str]]]:
    """
    Remove InDesign drop-shadow copies from a single merged visual row.

    After y-merge, the same text element may appear multiple times at slightly
    different x-positions (1–4 pt apart) due to InDesign shadow/glow effects
    that render each glyph or phrase several times.  ``_deduplicate_raw_lines``
    misses these because copies fall in different (y_bucket, x_bucket) bins when
    the x-spread exceeds 0.1 pt.

    Strategy (row must be pre-sorted left-to-right):
      - Track the x0 of the first occurrence of each distinct text_key.
      - Suppress any subsequent occurrence of the same text_key whose x0 is
        within ``_SHADOW_X_THRESHOLD`` of the first occurrence.
      - Genuine word repetitions (word-spaced ≥ 8–10 pt apart) are kept.

    **CJK exception**: if the row contains any CJK character the heuristic is
    disabled entirely and the row is returned unchanged.  CJK table layouts
    legitimately repeat the same character in adjacent label/value cells; the
    threshold-based suppression would incorrectly remove real content.
    """
    # Do not apply drop-shadow dedup to rows that contain CJK characters.
    if _row_contains_cjk(row):
        return row

    first_x: dict[str, float] = {}
    result: list[tuple[float, float, list[str]]] = []
    for y, x, frags in row:
        text_key = _FS_TAG_RE.sub("", "".join(frags))
        if not text_key:
            result.append((y, x, frags))
            continue
        if text_key in first_x:
            if abs(x - first_x[text_key]) <= _SHADOW_X_THRESHOLD:
                continue  # shadow copy — suppress
        else:
            first_x[text_key] = x
        result.append((y, x, frags))
    return result


# ---------------------------------------------------------------------------
# Fix 6 — pytiblegenc duplicate-line deduplication
#
# InDesign PDFs printed through PScript5.dll / Acrobat Distiller embed every
# text line twice in the content stream at exactly the same coordinates. The
# PyMuPDF rawdict path catches this via _deduplicate_raw_lines (Fix 5), but
# pytiblegenc.pdf_to_txt renders both copies and emits them as consecutive
# identical lines separated by a single newline. The page-break marker
# (PAGE_BREAK_STR) is the only guaranteed non-text separator.
#
# Strategy: split the raw output into per-page chunks, then within each chunk
# remove any line that is identical to the immediately preceding non-empty
# line. This is conservative — it only removes a line when it is *adjacent*
# and *identical*, so legitimately repeated lines separated by other content
# (e.g. a refrain that genuinely appears twice in a verse) are kept.
#
# Font-size tags (<fs:N>) are stripped before comparison so that a line whose
# only difference from its predecessor is a tag variant is still detected as
# a duplicate.
# ---------------------------------------------------------------------------
# How many preceding lines to look back when checking for duplicates.
# Must be large enough to span the interleaving gap in the 4× drop-shadow pattern
# (gap between first and last copy of a line ≈ 3×(unique_lines_per_group) ≈ 3–15 lines)
# but small enough not to suppress legitimately repeated text in verse/prose.
# 16 covers the worst observed case (4 lines × 4 copies = 16 entries) with margin.
_DEDUP_WINDOW_SIZE = 16


def _deduplicate_pytiblegenc_output(text: str, page_break_str: str) -> str:
    """
    Remove duplicate lines from pytiblegenc ``pdf_to_txt`` output using a sliding window.

    Each page is processed independently (page-break markers are never removed).
    Within a page, a line is suppressed when its content — after stripping font-size
    tags — is non-empty and has already appeared in the preceding
    ``_DEDUP_WINDOW_SIZE`` non-empty lines.

    This handles two distinct InDesign duplication patterns:

    * **2× consecutive** (PScript5/Acrobat Distiller): pdfminer emits identical
      pairs ``A A B B …`` — caught trivially by window ≥ 1.

    * **4× interleaved** (Adobe PDF Library drop-shadow): pdfminer sorts all four
      copies by y-coordinate, yielding ``A A A B A B B C B C C D …`` — the third
      copy of A is separated from the first by up to ``window-1`` other lines.
      A window of 16 safely covers all observed cases.

    The window resets between pages so it never suppresses text that legitimately
    recurs across a page boundary (running headers handled separately by
    ``strip_page_header_artifacts``).
    """
    pages = text.split(f"\n{page_break_str}\n")
    deduped_pages = []

    for page_text in pages:
        lines = page_text.split("\n")
        result_lines: list[str] = []
        # Sliding window: a deque of the last _DEDUP_WINDOW_SIZE non-empty keys.
        recent: list[str] = []

        for line in lines:
            key = _FS_TAG_RE.sub("", line).strip()
            # Never suppress lines that contain CJK characters: repeated CJK
            # characters in adjacent table cells are genuine content, not
            # InDesign shadow artefacts.
            if key and key in recent and not _CJK_RE.search(key):
                # This line appeared in the recent window — drop as duplicate.
                continue
            result_lines.append(line)
            if key:
                recent.append(key)
                if len(recent) > _DEDUP_WINDOW_SIZE:
                    recent.pop(0)

        deduped_pages.append("\n".join(result_lines))

    return f"\n{page_break_str}\n".join(deduped_pages)



def extract_pdf_to_text(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    preserve_box: Optional[list] = None,
    extraction_dedup: bool = True,
    phantom_space_drop: bool = True,
) -> str:
    """Extract text from *pdf_path* using the hybrid PyMuPDF + pytiblegenc pipeline."""
    text = extract_pdf_hybrid(
        pdf_path,
        crop_top=crop_top,
        crop_bottom=crop_bottom,
        preserve_box=preserve_box,
        extraction_dedup=extraction_dedup,
        phantom_space_drop=phantom_space_drop,
    )
    return _merge_orphan_tibetan_line_breaks(text or "")

def _extract_line_text_hybrid(
    line: dict,
    font_normalization: dict,
    glyph_lookup: dict,
    stats: dict,
    *,
    drop_phantom_spaces: bool = True
) -> list[str]:
    """
    Extracts text from a MuPDF line, but decodes legacy characters using pytiblegenc.
    """
    fragments: list[str] = []
    span_prev_char_obj: dict | None = None

    for span in line.get("spans", []):
        raw_font_name = span.get("font", "")
        if _is_wingdings_font(raw_font_name):
            continue

        fs = round(span.get("size", 12))
        fragments.append(_FONT_SIZE_FORMAT.format(fs))

        # 1. Clean the font name (remove PDF subset prefixes like 'ABCDEF+')
        clean_font = raw_font_name.split("+", 1)[-1] if "+" in raw_font_name else raw_font_name

        # 2. Resolve to canonical pytiblegenc font name using normalization map or aliases
        canonical_fonts = font_normalization.get(clean_font) or font_normalization.get(raw_font_name)
        if canonical_fonts:
            # Use the first matched canonical font from the hash DB
            target_font = list(canonical_fonts)[0] 
        else:
            # Fallback to alias map
            aliases = _get_font_name_aliases()
            target_font = aliases.get(clean_font, clean_font)

        char_objs = span.get("chars") or []
        if char_objs:
            for char_obj in char_objs:
                # Fix 1+3+4: drop phantom glyph-advance spaces
                if drop_phantom_spaces and _is_phantom_space(char_obj, span_prev_char_obj):
                    continue

                c = char_obj.get("c", "")
                
                # HYBRID DECODING: Pass PyMuPDF's char through pytiblegenc (memoized)
                decoded_c = _decode_char_cached(c, target_font, glyph_lookup, stats)

                # Fallback: If pytiblegenc returns None (unhandled font), use original char + Monlam fixes
                if decoded_c is None:
                    decoded_c = _correct_broken_font_glyph(c, target_font)

                fragments.append(decoded_c)
                span_prev_char_obj = char_obj
        else:
            # If no char-level data, process the whole text string
            text = span.get("text", "")
            decoded_text = ""
            for ch in text:
                dec = _decode_char_cached(ch, target_font, glyph_lookup, stats)
                if dec is None:
                    dec = _correct_broken_font_glyph(ch, target_font)
                decoded_text += dec
            fragments.append(decoded_text)
            span_prev_char_obj = None

    return fragments

def extract_pdf_hybrid(
    pdf_path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    preserve_box: Optional[list] = None,
    extraction_dedup: bool = True,
    phantom_space_drop: bool = True,
) -> str:
    """
    Extracts text using PyMuPDF's layout sorting, but pytiblegenc's font decoding.
    """
    logger.info(f"    Extracting (Hybrid Mode): {pdf_path.name}")

    if not PYMUPDF_AVAILABLE or not PYTIBLEGENC_AVAILABLE:
        logger.error("Both PyMuPDF and pytiblegenc are required for the hybrid extractor.")
        return ""

    tmp_pdf: Optional[Path] = None

    try:
        # 1. Handle Redaction / Cropping
        if preserve_box is not None:
            tmp_pdf = create_cropped_pdf(pdf_path, crop_top, crop_bottom, preserve_box=preserve_box)
        elif crop_top > 0.0 or crop_bottom > 0.0:
            tmp_pdf = create_cropped_pdf(pdf_path, crop_top, crop_bottom)

        target_pdf = tmp_pdf if tmp_pdf else pdf_path

        # 2. Setup pytiblegenc Font Normalization & Glyph Lookup
        # Install local font tables (Fix 9) and the TibetanChogyal cid
        # patch (Fix 8) before the first extraction call.  Both are idempotent.
        _install_local_font_tables()
        _install_chogyal_cid_patch()
        _load_broken_glyph_remap()

        font_normalization: dict = {}
        glyph_lookup = None
        try:
            # PDF-independent structures: built once per process and cached (Fix 10).
            glyph_db_path, glyph_index, glyph_lookup = _get_glyph_db_structures()
            raw_font_norm = {}
            # PDF-specific font identification: must run per document.
            if glyph_index is not None:
                with open(str(target_pdf), "rb") as _f:
                    _parser = PDFParser(_f)
                    _doc_tmp = PDFDocument(_parser)
                    raw_font_norm = identify_pdf_fonts_from_db(_doc_tmp, glyph_index) or {}

            # Clean keys: ensure both the raw PDF name and the subset-stripped name
            # are present so PyMuPDF and pdfminer name lookups both hit.
            for k, v in raw_font_norm.items():
                ck = k.split("+", 1)[-1] if "+" in k else k
                font_normalization[ck] = v
                font_normalization[k] = v

        except Exception as exc:
            logger.warning("Could not load font normalization or glyph lookup: %s", exc)

        # Inject legacy aliases (Fix 7)
        for alias, canonical in _get_font_name_aliases().items():
            if alias not in font_normalization:
                font_normalization[alias] = {canonical}

        stats: dict = {"unhandled_fonts": {}, "handled_fonts": {}, "unknown_characters": {}, "error_characters": 0, "diffs_with_utfc": {}}

        # 3. PyMuPDF Extraction Loop
        doc = fitz.open(str(target_pdf))
        parts: list[str] = []
        fn_settings = _footnote_settings()

        # Decide document orientation once so near-blank pecha pages
        # (whose only content is horizontal marginalia) are handled correctly.
        doc_is_pecha = _document_is_pecha(
            doc, font_normalization, glyph_lookup, stats
        )
        if doc_is_pecha:
            logger.info(
                "    Detected rotated pecha layout — vertical reading order,"
                " marginalia removal."
            )

        for page in doc:
            page_dict = page.get_text("rawdict")
            page_width = page.rect.width
            page_height = page.rect.height
            # Rich per-line records: (y_mid, x0, fragments, direction, bbox).
            # Populated during block traversal; direction and bbox are used
            # for pecha orientation detection and marginalia filtering.
            line_records: list[tuple] = []
            # Footnote lines pulled out of the body flow: (y, x0, fragments).
            footnote_lines: list[tuple[float, float, list[str]]] = []

            # Locate a footnote separator (left-margin rule, low on the page).
            # The body left margin is the smallest line-start x on the page.
            fn_sep_y: Optional[float] = None
            if fn_settings["enabled"]:
                left_xs = [
                    ln.get("bbox", [1e9])[0]
                    for blk in page_dict.get("blocks", [])
                    if blk.get("type", 1) == 0
                    for ln in blk.get("lines", [])
                ]
                if left_xs:
                    body_left_x = min(left_xs)
                    fn_sep_y = _find_footnote_separator_y(page, body_left_x, fn_settings)

            # Estimate the body font size (most common span size, weighted by
            # span length) so we can tell footnote text (smaller) apart from a
            # page number (body-size) that also sits below the separator.
            body_font_size = None
            if fn_sep_y is not None:
                from collections import Counter as _Counter
                _sz = _Counter()
                for blk in page_dict.get("blocks", []):
                    if blk.get("type", 1) != 0:
                        continue
                    for ln in blk.get("lines", []):
                        for sp in ln.get("spans", []):
                            _sz[round(sp.get("size", 0), 1)] += len(sp.get("text", "") or "")
                if _sz:
                    body_font_size = _sz.most_common(1)[0][0]

            for block in page_dict.get("blocks", []):
                if block.get("type", 1) != 0:
                    continue
                for line in block.get("lines", []):
                    bbox = line.get("bbox", [0, 0, 0, 0])
                    y_mid = (bbox[1] + bbox[3]) / 2.0
                    x0 = bbox[0]
                    direction = line.get("dir", (1.0, 0.0))

                    fragments = _extract_line_text_hybrid(
                        line,
                        font_normalization,
                        glyph_lookup,
                        stats,
                        drop_phantom_spaces=phantom_space_drop
                    )

                    if not fragments:
                        continue

                    # Route lines below the footnote separator into the note
                    # collection — but only those whose font is smaller than the
                    # body.  A body-size line below the separator is the printed
                    # page number, not footnote text, so it's dropped here (the
                    # existing footer-stripping handles real footers elsewhere).
                    # Pecha pages don't use Western footnotes so fn_sep_y is
                    # never set for them and this branch is never taken.
                    if fn_sep_y is not None and y_mid >= fn_sep_y:
                        line_size = max(
                            (round(sp.get("size", 0), 1) for sp in line.get("spans", [])),
                            default=0,
                        )
                        if (
                            body_font_size is None
                            or line_size <= body_font_size * fn_settings["body_ratio"]
                        ):
                            footnote_lines.append((y_mid, x0, fragments))
                        # else: body-size line below separator → page number, skip
                    else:
                        line_records.append((y_mid, x0, fragments, direction, bbox))

            # 4. Orientation branch — vertical pecha vs. horizontal standard
            page_vertical = doc_is_pecha or _page_is_vertical(line_records)

            if page_vertical:
                # ── Vertical pecha page ──────────────────────────────────────
                # Drop running-title / folio-number marginalia (horizontal
                # lines on a vertical page) and short edge-band runs.
                kept: list[tuple] = []
                dropped = 0
                for rec in line_records:
                    _y, _x, frags, direction, bbox = rec
                    if _is_pecha_marginalia(direction, bbox, page_width, page_height):
                        dropped += 1
                        continue
                    if _is_short_edge_run(frags, bbox, page_height):
                        dropped += 1
                        continue
                    kept.append(rec)
                if dropped:
                    logger.debug(
                        "  hybrid: page %d vertical pecha — dropped %d marginalia line(s)",
                        page.number + 1, dropped,
                    )

                # Landscape 2-up spreads pack two sub-pages into one PDF page,
                # stacked in the raw (un-rotated) Y frame but sharing the same
                # raw X range — a flat x-primary sort would interleave their
                # columns.  Detect a real sub-page boundary first; the common
                # single-sub-page case yields no split and behaves as before.
                band_splits = _detect_pecha_band_splits(kept)
                if band_splits:
                    boundaries = (
                        [(-1e9, band_splits[0])]
                        + [(band_splits[i], band_splits[i + 1]) for i in range(len(band_splits) - 1)]
                        + [(band_splits[-1], 1e9)]
                    )
                    bands: list[list[tuple]] = [[] for _ in boundaries]
                    for rec in kept:
                        y0 = rec[4][1]
                        for ci, (lo, hi) in enumerate(boundaries):
                            if lo <= y0 < hi:
                                bands[ci].append(rec)
                                break
                    # Sub-page reading order across the Y split: for a 90°
                    # rotation, larger raw-Y bands land further LEFT on the
                    # rotated/displayed page (read first); a 270° rotation
                    # inverts that mapping. Verified against this corpus's
                    # rotation=90 landscape scans (raw-Y-descending band
                    # order reconstructs the correct left-to-right spread).
                    if page.rotation % 360 == 270:
                        bands.sort(key=lambda b: min(r[4][1] for r in b) if b else 0)
                    else:
                        bands.sort(key=lambda b: -min(r[4][1] for r in b) if b else 0)
                    logger.debug(
                        "  hybrid: page %d pecha spread — split into %d sub-page band(s) at y=%s",
                        page.number + 1, len(bands), [f"{s:.1f}" for s in band_splits],
                    )
                else:
                    bands = [kept]

                # Reading order for vertical body text runs along X:
                # each vertical line is a full reading column; columns go
                # left→right.  Use x-midpoint as primary sort key. Each
                # sub-page band is sorted and dumped independently, in band
                # reading order.
                #
                # A single physical column is occasionally split by MuPDF
                # into two+ line records that share the same x-midpoint
                # (e.g. a font/size change mid-line) — for this rotated
                # frame, same-x entries sit on the same *display* row, and
                # the coordinate mapping (rotation_matrix: display_x =
                # page_w - raw_y, display_y = raw_x — see 90°/270° case
                # above) means left-to-right order within that row is
                # DESCENDING raw y, not ascending. Verified against this
                # corpus: two same-column fragments at raw_x=291.6 render
                # correctly only as "<higher-y text> <lower-y text>" on one
                # line, confirming the descending-y rule empirically.
                for band in bands:
                    raw_lines_v = [
                        (round((bbox[0] + bbox[2]) / 2.0, 1), bbox[1], frags)
                        for (_y, _x, frags, _d, bbox) in band
                    ]
                    if raw_lines_v and extraction_dedup:
                        raw_lines_v = _deduplicate_raw_lines(
                            raw_lines_v, _Y_MERGE_TOLERANCE
                        )
                    columns: dict[float, list[tuple[float, list]]] = {}
                    for xmid, y0, frags in raw_lines_v:
                        columns.setdefault(xmid, []).append((y0, frags))
                    for xmid in sorted(columns.keys()):
                        entries = sorted(columns[xmid], key=lambda e: -e[0])
                        for i, (_y0, frags) in enumerate(entries):
                            if i > 0:
                                parts.append(" ")
                            parts.extend(frags)
                        parts.append("\n")
                parts.append(f"\n{PAGE_BREAK_STR}\n")
                continue  # skip the horizontal path for this page

            # ── Horizontal (standard) page ───────────────────────────────────
            # Strip left-margin running-title marginalia (rotated + stacked-
            # CJK) before building raw_lines, so it never enters the reading-
            # order / column-detection pipeline. No-op on pages that lack the
            # tell-tale rotated marginalia line (e.g. a front-matter TOC page
            # whose page-number column legitimately starts near the same x —
            # see _strip_horizontal_page_left_margin_marginalia).
            line_records = _strip_horizontal_page_left_margin_marginalia(
                line_records, page_width
            )

            # Convert 5-tuples back to the 3-tuple form the rest of the
            # pipeline expects, rebuilding line_spans from the stored bboxes.
            raw_lines: list[tuple[float, float, list[str]]] = [
                (y, x, frags) for (y, x, frags, _d, _b) in line_records
            ]
            line_spans: list[tuple[float, float]] = [
                (bbox[0], bbox[2]) for (_y, _x, _frags, _d, bbox) in line_records
            ]

            # 5. Apply PyMuPDF Deduplication & Coordinate Sorting
            if raw_lines and extraction_dedup:
                raw_lines, line_spans = _deduplicate_raw_lines(
                    raw_lines, _Y_MERGE_TOLERANCE, line_spans
                )

            # Multi-column detection: if the page has a clear horizontal gap
            # between two groups of text blocks, sort each column independently
            # (top→bottom) before the normal y-sort, so reading order is correct.
            column_splits = _detect_column_splits(raw_lines, page_width, line_spans)
            if column_splits:
                logger.debug(
                    "  hybrid: page %d multi-column detected, splits at x=%s",
                    page.number + 1,
                    [f"{s:.1f}" for s in column_splits],
                )
                raw_lines = _sort_lines_multicolumn(raw_lines, column_splits)
            else:
                # Sort top-to-bottom, then left-to-right
                raw_lines.sort(key=lambda t: (t[0], t[1]))

            # Merge lines that share the same Y midpoint
            merged_rows: list[list[tuple[float, float, list[str]]]] = []
            for y_mid, x0, frags in raw_lines:
                if merged_rows:
                    avg_y = sum(e[0] for e in merged_rows[-1]) / len(merged_rows[-1])
                    if abs(y_mid - avg_y) <= _Y_MERGE_TOLERANCE:
                        merged_rows[-1].append((y_mid, x0, frags))
                        continue
                merged_rows.append([(y_mid, x0, frags)])

            # Emit text
            for row in merged_rows:
                row.sort(key=lambda t: t[1])
                if extraction_dedup:
                    row = _dedup_within_row(row)
                for _y, _x, frags in row:
                    parts.extend(frags)
                parts.append("\n")

            # Emit footnotes (if any) as single-line note tokens.  Each token
            # is reattached inline at its marker in convert_markup_to_tei.
            if footnote_lines:
                note_tokens = _build_footnote_tokens(footnote_lines, extraction_dedup)
                for tok in note_tokens:
                    parts.append(tok)
                    parts.append("\n")

            parts.append(f"\n{PAGE_BREAK_STR}\n")

        doc.close()

        # Apply sliding-window dedup to catch interleaved shadow copies
        text_output = "".join(parts)
        if extraction_dedup:
            text_output = _deduplicate_pytiblegenc_output(text_output, PAGE_BREAK_STR)

        # Log unhandled fonts to help debug missed legacy fonts
        if stats["unhandled_fonts"]:
            logger.warning("Hybrid Mode - Unhandled fonts (no conversion table): %s", stats["unhandled_fonts"])

        return text_output

    except Exception as e:
        logger.error(f"    ERROR extracting {pdf_path.name}: {e}")
        traceback.print_exc()
        return ""
    finally:
        if tmp_pdf is not None and tmp_pdf.exists():
            try:
                os.unlink(tmp_pdf)
            except OSError:
                pass