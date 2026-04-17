#!/usr/bin/env python3
"""
Tibetan PDF Folder Router
==========================
Single-pass scan of a root directory that inspects every PDF once and routes
each IE_ID folder to exactly the right extractor,
eliminating the need to run the same multiple folders through multiple tools and
sort results manually.

Usage
─────
  python route_folders.py /path/to/folders/
  python route_folders.py /path/to/folders/ --out ./results/
  python route_folders.py /path/to/folders/ --all-pages --verbose
  python route_folders.py /path/to/folders/ --workers 8   # parallel scan
  python route_folders.py /Users/tenzinmonlam/Downloads/F/unzip --out ./all_results/ --workers 8


Requirements
────────────
  pip install pymupdf pdfminer.six 
  pip install git+https://github.com/buda-base/py-tiblegenc.git 
"""

import argparse
import csv
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ── PyMuPDF ────────────────────────────────────────────────────────────────────
try:
    import fitz
    FITZ_OK = True
except ImportError:
    print("ERROR: PyMuPDF not installed.\n  pip install pymupdf --break-system-packages")
    sys.exit(1)

# ── py-tiblegenc (optional but recommended) ────────────────────────────────────
_PTL_OK = False
_PTL_GLYPH_DB_FONTS: Set[str] = set()   # all PostScript names in glyph_db.csv
_PTL_GLYPH_INDEX: Optional[Dict] = None  # {font_name: set_of_hashes}
_PTL_GLYPH_DB_PATH: Optional[Path] = None

try:
    import csv as _csv_mod
    from pytiblegenc import (
        get_glyph_db_path,
        build_font_hash_index_from_csv,
        identify_pdf_fonts_from_db,
    )
    from pdfminer.pdfdocument import PDFDocument
    from pdfminer.pdfparser import PDFParser

    _PTL_GLYPH_DB_PATH  = Path(get_glyph_db_path())
    _PTL_GLYPH_INDEX    = build_font_hash_index_from_csv(str(_PTL_GLYPH_DB_PATH))

    with open(str(_PTL_GLYPH_DB_PATH), newline="", encoding="utf-8") as _f:
        _r = _csv_mod.reader(_f)
        next(_r)
        for _row in _r:
            if len(_row) >= 2:
                _PTL_GLYPH_DB_FONTS.add(_row[1])

    _PTL_OK = True
    print(f"[py-tiblegenc] glyph_db loaded — {len(_PTL_GLYPH_DB_FONTS)} known fonts")

except Exception as _ptl_err:
    print(f"[py-tiblegenc] not available ({_ptl_err})")
    print("  Install: pip install git+https://github.com/buda-base/py-tiblegenc.git")
    print("  'in_pytiblegenc' and pytiblegenc routing will be skipped.\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════════

# Extractor route labels (written into CSV)
ROUTE_PYMUPDF       = "USE_PYMUPDF"       # direct text extraction via fitz
ROUTE_PYTIBLEGENC   = "USE_PYTIBLEGENC"   # legacy glyph mapping, font known
ROUTE_NEEDS_REVIEW  = "NEEDS_REVIEW"      # legacy font, NOT in glyph_db
ROUTE_NOT_CONVERT   = "NOT_CONVERTIBLE"   # scanned/image only
ROUTE_MIXED         = "MIXED"             # folder contains multiple route types
ROUTE_EMPTY         = "EMPTY"             # no PDFs or all blank

ROUTE_DESCRIPTION = {
    ROUTE_PYMUPDF:      "Run with PyMuPDF (fitz.page.get_text()) — Unicode Tibetan directly extractable",
    ROUTE_PYTIBLEGENC:  "Run with py-tiblegenc — legacy font recognised in glyph_db, glyph mapping available",
    ROUTE_NEEDS_REVIEW: "Legacy font NOT in py-tiblegenc glyph_db — needs manual glyph mapping before conversion",
    ROUTE_NOT_CONVERT:  "Scanned raster images — no text layer; needs OCR not text extraction",
    ROUTE_MIXED:        "Multiple extractor types needed — see file_detail.csv for per-file breakdown",
    ROUTE_EMPTY:        "No usable content found",
}

# Font encoding classes
FC_UNICODE_TIBETAN = "UNICODE_TIBETAN"  # clean Unicode, direct extract
FC_LEGACY_TIBETAN  = "LEGACY_TIBETAN"   # pre-Unicode encoding
FC_NON_UNICODE     = "NON_UNICODE"      # CID font, no ToUnicode
FC_LATIN_OTHER     = "LATIN_OTHER"
FC_SCANNED         = "SCANNED_IMAGE"
FC_UNKNOWN         = "UNKNOWN"

# Page types
P_UNICODE     = "UNICODE"
P_LEGACY      = "LEGACY"
P_NON_UNICODE = "NON_UNICODE"
P_DEBRIS      = "DEBRIS"
P_EMPTY       = "EMPTY"

# Tibetan Unicode block
TIBETAN_LO, TIBETAN_HI = 0x0F00, 0x0FFF


# ═══════════════════════════════════════════════════════════════════════════════
# Font pattern tables
# ═══════════════════════════════════════════════════════════════════════════════

# Pre-Unicode Tibetan font names — these need py-tiblegenc glyph matching
LEGACY_PATTERNS: List[str] = [
    r"TCRC",                              # Tibetan Computer Resource Centre
    r"Youtso",
    r"^TT[0-9A-F]{4}",                   # embedded CFF Type1 from old pdflatex
    r"Tibetan\s*Machine(?!.*Uni)",        # TibetanMachine (not Uni)
    r"TibtnMachine",
    r"TibMachUni",                        # older TibMachUni builds
    r"Sambhota",
    r"Pedurma",
    r"Druk\d*",
    r"Jamyang",
    r"CDAC", r"Gist", r"ISM.*Druk",
    r"Pem.*Tshewang", r"Gelong",
    r"DBu.can",
    # py-tiblegenc glyph_db font families (these ARE known)
    r"^(Dedris|Ededris|Khamdris|Drutsa|Narthang|Ume|Sama[bcw]?|Esam[abc])",
    r"^(DzongkhaCalligraphic|TibetanCalligraphic|TibetanChogyal|TibetanClassic)",
    r"^(LTibetan|LMantra|Mantra\s*Regular|L\s*Regular|LTibetanExtension)",
    r"TibetanMachineWeb",
    r"TibetanMachineNormalA",
    r"TibtnMachine",
]

# Unicode Tibetan fonts — fitz can extract directly
UNICODE_PATTERNS: List[str] = [
    r"Monlam",
    r"Jomolhari",
    r"Noto.*Tibetan",
    r"DDC.*Uchen",
    r"Kailasa",
    r"Kokonor",
    r"Microsoft.*Himalaya",
    r"Tibetan.*Machine.*Uni",
    r"Qomolangma",
    r"TibetanMachineUni",
]

LATIN_PATTERNS: List[str] = [
    r"Times", r"Helvetica", r"Arial", r"Tahoma", r"Courier",
    r"Symbol", r"ZapfDingbats", r"Verdana", r"Georgia",
    r"Calibri", r"Cambria", r"Myriad", r"Garamond",
]


def _strip_prefix(name: str) -> str:
    """'NCLDNC+TCRCYoutso' → 'TCRCYoutso'"""
    return re.sub(r"^[A-Z]{6}\+", "", name)


def _matches(name: str, patterns: List[str]) -> bool:
    return any(re.search(p, name, re.IGNORECASE) for p in patterns)


def _classify_font(base: str, font_type: str,
                   encoding: str, has_to_unicode: bool) -> str:
    if _matches(base, LEGACY_PATTERNS):
        return FC_LEGACY_TIBETAN
    if _matches(base, UNICODE_PATTERNS):
        return FC_UNICODE_TIBETAN
    if _matches(base, LATIN_PATTERNS):
        return FC_LATIN_OTHER
    is_cid = "CID" in font_type.upper() or encoding in ("Identity-H", "Identity-V")
    if is_cid:
        return FC_UNICODE_TIBETAN if has_to_unicode else FC_NON_UNICODE
    if encoding in ("WinAnsi", "WinAnsiEncoding", "Custom"):
        return FC_LEGACY_TIBETAN
    return FC_UNKNOWN


def _pytiblegenc_check(base: str, raw: str,
                        glyph_matches: Dict) -> Tuple[str, str]:
    """
    Return (in_glyph_db, matched_name).
    Two-step: fast name lookup first, then glyph-hash result from identify_pdf_fonts_from_db.
    """
    if not _PTL_OK:
        return "N/A", ""
    if base in _PTL_GLYPH_DB_FONTS:
        return "YES", base
    # Check if glyph-hash matching found it
    candidates = glyph_matches.get(raw, set()) | glyph_matches.get(base, set())
    if candidates:
        return "YES", ", ".join(sorted(candidates))
    return "NO", ""


def _pytiblegenc_identify(pdf_path: str) -> Dict:
    if not _PTL_OK:
        return {}
    try:
        with open(pdf_path, "rb") as f:
            doc = PDFDocument(PDFParser(f))
            return identify_pdf_fonts_from_db(doc, _PTL_GLYPH_INDEX)
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class FontInfo:
    base_name: str
    font_class: str           # FC_* constant
    font_type: str
    encoding: str
    has_to_unicode: bool
    in_glyph_db: str = "N/A"  # YES / NO / N/A
    glyph_db_match: str = ""


@dataclass
class FileResult:
    path: str
    route: str                # ROUTE_* constant
    page_count: int = 0
    unicode_pages: int = 0
    legacy_pages: int = 0
    non_unicode_pages: int = 0
    debris_pages: int = 0
    fonts: List[FontInfo] = field(default_factory=list)
    error: str = ""

    @property
    def filename(self) -> str:
        return Path(self.path).name

    @property
    def folder_name(self) -> str:
        return Path(self.path).parent.name


@dataclass
class IEIDSummary:
    ie_id: str
    route: str
    total_files: int = 0
    pymupdf_files: int = 0
    pytiblegenc_files: int = 0
    needs_review_files: int = 0
    not_convert_files: int = 0
    font_classes: str = ""          # e.g. "UNICODE_TIBETAN, LEGACY_TIBETAN"
    tibetan_font_names: str = ""    # unique Tibetan font names found
    unknown_legacy_fonts: str = ""  # legacy fonts not in glyph_db
    files: List[FileResult] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# Core: extract fonts from a PDF via PyMuPDF (fitz)
# ═══════════════════════════════════════════════════════════════════════════════

def extract_fonts(pdf_path: str, run_glyph_hash: bool = False) -> List[FontInfo]:
    """
    Extract all unique fonts from a PDF using fitz (PyMuPDF).

    Fitz reads directly from the PDF object model — no CLI text parsing,
    no column-width assumptions. Works for any PDF fitz can open.

    For fonts classified as LEGACY_TIBETAN, optionally runs the py-tiblegenc
    glyph-hash identifier (identify_pdf_fonts_from_db) as a second check.
    This is slower but catches cases where the font name alone is ambiguous.
    """
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        return []

    seen: Set[str] = set()
    raw_fonts: List[Dict] = []

    try:
        for page in doc:
            for f in page.get_fonts(full=True):
                # (xref, ext, type, basefont, name, encoding, referencer)
                raw_name  = f[3] if len(f) > 3 else ""
                font_type = f[2] if len(f) > 2 else ""
                encoding  = f[5] if len(f) > 5 else ""
                xref      = f[0]

                base = _strip_prefix(raw_name)
                if not base or base in seen:
                    continue
                seen.add(base)

                # ToUnicode: check the raw PDF object for /ToUnicode key
                has_tou = False
                try:
                    has_tou = "/ToUnicode" in doc.xref_object(xref)
                except Exception:
                    pass

                raw_fonts.append({
                    "raw": raw_name, "base": base,
                    "type": font_type, "enc": encoding, "tou": has_tou,
                })
    finally:
        doc.close()

    # Glyph-hash identification for legacy fonts (optional, slower)
    glyph_matches: Dict = {}
    if run_glyph_hash and _PTL_OK:
        has_legacy = any(
            _classify_font(r["base"], r["type"], r["enc"], r["tou"]) == FC_LEGACY_TIBETAN
            for r in raw_fonts
        )
        if has_legacy:
            glyph_matches = _pytiblegenc_identify(pdf_path)

    result: List[FontInfo] = []
    for r in raw_fonts:
        fc = _classify_font(r["base"], r["type"], r["enc"], r["tou"])
        if fc == FC_LEGACY_TIBETAN:
            in_db, db_match = _pytiblegenc_check(r["base"], r["raw"], glyph_matches)
        else:
            in_db, db_match = "N/A", ""
        result.append(FontInfo(
            base_name=r["base"], font_class=fc,
            font_type=r["type"], encoding=r["enc"],
            has_to_unicode=r["tou"],
            in_glyph_db=in_db, glyph_db_match=db_match,
        ))
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# Core: classify pages and determine file-level route
# ═══════════════════════════════════════════════════════════════════════════════

def _page_type(page: fitz.Page,
               has_legacy: bool, has_unicode: bool) -> str:
    """Classify a single page based on its content."""
    text   = page.get_text()
    total  = len(text.strip())
    images = page.get_images(full=False)

    if total == 0:
        return P_DEBRIS if images else P_EMPTY

    tibetan = sum(1 for c in text if TIBETAN_LO <= ord(c) <= TIBETAN_HI)
    if tibetan > 5:
        return P_UNICODE
    if has_legacy:
        return P_LEGACY
    if has_unicode:
        return P_NON_UNICODE

    # Fallback: check this specific page's fonts
    for f in page.get_fonts(full=True):
        base = _strip_prefix(f[3])
        if _matches(base, LEGACY_PATTERNS):
            return P_LEGACY
        if _matches(base, UNICODE_PATTERNS):
            return P_NON_UNICODE
    return P_LEGACY


def _decide_route(
    counts: Dict[str, int],
    content_pages: int,
    fonts: List[FontInfo],
) -> str:
    """
    Map page-type counts + font details to a single ROUTE_* value.

    Priority order:
      1. If any Unicode pages exist and no legacy → PYMUPDF
      2. If legacy pages exist:
           a. All legacy fonts in glyph_db → PYTIBLEGENC
           b. Some/all legacy fonts NOT in glyph_db → NEEDS_REVIEW
      3. NON_UNICODE pages (CID font, no ToUnicode) → NEEDS_REVIEW
         (needs CMap/fontTools work, similar effort to unknown legacy)
      4. All debris → NOT_CONVERTIBLE
      5. Multiple route types in same folder → MIXED (set at IE_ID level)
    """
    if content_pages == 0:
        return ROUTE_EMPTY

    u  = counts.get(P_UNICODE,     0)
    l  = counts.get(P_LEGACY,      0)
    nu = counts.get(P_NON_UNICODE, 0)
    d  = counts.get(P_DEBRIS,      0)

    # Scanned only
    if d / content_pages > 0.9 and u == 0 and l == 0 and nu == 0:
        return ROUTE_NOT_CONVERT

    # Unicode present and no legacy → pymupdf
    if u > 0 and l == 0 and nu == 0:
        return ROUTE_PYMUPDF

    # Legacy present — check if glyph_db covers all legacy fonts
    if l > 0:
        legacy_fonts = [f for f in fonts if f.font_class == FC_LEGACY_TIBETAN]
        all_in_db    = all(f.in_glyph_db == "YES" for f in legacy_fonts)
        any_in_db    = any(f.in_glyph_db == "YES" for f in legacy_fonts)

        if all_in_db and _PTL_OK:
            return ROUTE_PYTIBLEGENC
        else:
            return ROUTE_NEEDS_REVIEW   # unknown legacy fonts

    # NON_UNICODE (CID font, no ToUnicode map) → needs CMap work
    if nu > 0:
        return ROUTE_NEEDS_REVIEW

    # Mixed unicode+legacy → caller sets MIXED at folder level
    if u > 0 and l > 0:
        return ROUTE_NEEDS_REVIEW  # conservative: legacy takes priority

    return ROUTE_NEEDS_REVIEW


def classify_file(pdf_path: str, sample_pages: int = 20) -> FileResult:
    """
    Open a PDF once, extract fonts, sample pages, and return a FileResult
    with a recommended extractor route.
    """
    result = FileResult(path=str(pdf_path), route=ROUTE_EMPTY)

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        result.route = ROUTE_NEEDS_REVIEW
        result.error = f"fitz open error: {str(e)[:100]}"
        return result

    result.page_count = len(doc)
    if result.page_count == 0:
        doc.close()
        return result

    # ── Font extraction ────────────────────────────────────────────────────────
    fonts = extract_fonts(pdf_path, run_glyph_hash=True)
    result.fonts = fonts

    has_legacy  = any(f.font_class == FC_LEGACY_TIBETAN  for f in fonts)
    has_unicode = any(f.font_class == FC_UNICODE_TIBETAN  for f in fonts)

    # ── Page sampling ──────────────────────────────────────────────────────────
    total   = result.page_count
    step    = max(1, total // sample_pages) if sample_pages and total > sample_pages else 1
    indices = list(range(0, total, step))[:sample_pages] if step > 1 else list(range(total))

    counts: Dict[str, int] = {P_UNICODE: 0, P_LEGACY: 0,
                               P_NON_UNICODE: 0, P_DEBRIS: 0, P_EMPTY: 0}
    for i in indices:
        counts[_page_type(doc[i], has_legacy, has_unicode)] += 1
    doc.close()

    result.unicode_pages     = counts[P_UNICODE]
    result.legacy_pages      = counts[P_LEGACY]
    result.non_unicode_pages = counts[P_NON_UNICODE]
    result.debris_pages      = counts[P_DEBRIS]

    content = len(indices) - counts[P_EMPTY]
    result.route = _decide_route(counts, content, fonts)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# IE_ID aggregation
# ═══════════════════════════════════════════════════════════════════════════════

def _get_ie_id(pdf_path: str, root: str) -> str:
    """Return the top-level folder directly under root."""
    parts = Path(pdf_path).resolve().relative_to(Path(root).resolve()).parts
    return parts[0] if len(parts) > 1 else "."


def _ie_id_route(files: List[FileResult]) -> str:
    """
    Determine the IE_ID-level route from its constituent file routes.

    Rules:
    - All files same route → that route
    - Any mix of PYMUPDF + (PYTIBLEGENC or NEEDS_REVIEW) → MIXED
    - Any NEEDS_REVIEW in the mix → promote to NEEDS_REVIEW
      (except pure PYMUPDF+PYTIBLEGENC → MIXED)
    """
    routes = {f.route for f in files
              if f.route not in (ROUTE_EMPTY,)}
    if not routes:
        return ROUTE_EMPTY
    if len(routes) == 1:
        return routes.pop()

    # Multiple routes
    has_pymupdf     = ROUTE_PYMUPDF      in routes
    has_pytiblegenc = ROUTE_PYTIBLEGENC  in routes
    has_review      = ROUTE_NEEDS_REVIEW in routes
    has_notconv     = ROUTE_NOT_CONVERT  in routes

    # If all content-bearing files agree on ONE route, ignore debris
    content_routes = routes - {ROUTE_NOT_CONVERT}
    if len(content_routes) == 1:
        return content_routes.pop()

    return ROUTE_MIXED


def aggregate(file_results: List[FileResult], root: str) -> List[IEIDSummary]:
    """Group FileResults by IE_ID and compute folder-level summaries."""
    groups: Dict[str, List[FileResult]] = defaultdict(list)
    for fr in file_results:
        groups[_get_ie_id(fr.path, root)].append(fr)

    summaries: List[IEIDSummary] = []

    for ie_id, files in sorted(groups.items()):
        route = _ie_id_route(files)

        s = IEIDSummary(ie_id=ie_id, route=route, total_files=len(files), files=files)
        s.pymupdf_files      = sum(1 for f in files if f.route == ROUTE_PYMUPDF)
        s.pytiblegenc_files  = sum(1 for f in files if f.route == ROUTE_PYTIBLEGENC)
        s.needs_review_files = sum(1 for f in files if f.route == ROUTE_NEEDS_REVIEW)
        s.not_convert_files  = sum(1 for f in files if f.route == ROUTE_NOT_CONVERT)

        # Collect unique Tibetan font names across all files
        all_fonts: List[FontInfo] = [f for fr in files for f in fr.fonts]
        tibetan_classes = sorted(set(
            f.font_class for f in all_fonts
            if f.font_class not in (FC_LATIN_OTHER, FC_UNKNOWN)
        ))
        s.font_classes = ", ".join(tibetan_classes)

        tibetan_names = sorted(set(
            f.base_name for f in all_fonts
            if f.font_class in (FC_UNICODE_TIBETAN, FC_LEGACY_TIBETAN, FC_NON_UNICODE)
        ))
        s.tibetan_font_names = " | ".join(tibetan_names[:15])
        if len(tibetan_names) > 15:
            s.tibetan_font_names += f" (+{len(tibetan_names)-15} more)"

        unknown_legacy = sorted(set(
            f.base_name for f in all_fonts
            if f.font_class == FC_LEGACY_TIBETAN and f.in_glyph_db == "NO"
        ))
        s.unknown_legacy_fonts = " | ".join(unknown_legacy[:10])

        summaries.append(s)

    return summaries


# ═══════════════════════════════════════════════════════════════════════════════
# CSV writers
# ═══════════════════════════════════════════════════════════════════════════════

_ROUTE_CSV_FIELDS = [
    "ie_id", "route", "route_description",
    "total_files", "font_classes", "tibetan_font_names", "unknown_legacy_fonts",
    "pymupdf_files", "pytiblegenc_files", "needs_review_files", "not_convertible_files",
]

def _summary_row(s: IEIDSummary) -> Dict:
    return {
        "ie_id":                  s.ie_id,
        "route":                  s.route,
        "route_description":      ROUTE_DESCRIPTION.get(s.route, ""),
        "total_files":            s.total_files,
        "font_classes":           s.font_classes,
        "tibetan_font_names":     s.tibetan_font_names,
        "unknown_legacy_fonts":   s.unknown_legacy_fonts,
        "pymupdf_files":          s.pymupdf_files,
        "pytiblegenc_files":      s.pytiblegenc_files,
        "needs_review_files":     s.needs_review_files,
        "not_convertible_files":  s.not_convert_files,
    }


def write_route_csv(summaries: List[IEIDSummary],
                    output_path: str,
                    routes: List[str]) -> int:
    rows = [s for s in summaries if s.route in routes]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_ROUTE_CSV_FIELDS)
        w.writeheader()
        for s in rows:
            w.writerow(_summary_row(s))
    return len(rows)


def write_all_csv(summaries: List[IEIDSummary], output_path: str) -> None:
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=_ROUTE_CSV_FIELDS)
        w.writeheader()
        for s in summaries:
            w.writerow(_summary_row(s))


def write_file_detail_csv(file_results: List[FileResult],
                           output_path: str, root: str) -> None:
    """Per-file CSV for auditing — shows exact fonts per PDF."""
    fields = [
        "ie_id", "file_path", "filename", "route",
        "page_count", "unicode_pages", "legacy_pages",
        "non_unicode_pages", "debris_pages",
        "tibetan_fonts", "unknown_legacy_fonts", "error",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in file_results:
            ie_id = _get_ie_id(r.path, root)
            tibetan = " | ".join(
                f"{f.base_name}[{f.font_class}]"
                + (f"(glyph_db:{f.in_glyph_db})" if f.font_class == FC_LEGACY_TIBETAN else "")
                for f in r.fonts
                if f.font_class not in (FC_LATIN_OTHER,)
            )
            unknown_leg = " | ".join(
                f.base_name for f in r.fonts
                if f.font_class == FC_LEGACY_TIBETAN and f.in_glyph_db == "NO"
            )
            w.writerow({
                "ie_id":               ie_id,
                "file_path":           r.path,
                "filename":            r.filename,
                "route":               r.route,
                "page_count":          r.page_count,
                "unicode_pages":       r.unicode_pages,
                "legacy_pages":        r.legacy_pages,
                "non_unicode_pages":   r.non_unicode_pages,
                "debris_pages":        r.debris_pages,
                "tibetan_fonts":       tibetan,
                "unknown_legacy_fonts": unknown_leg,
                "error":               r.error,
            })


# ═══════════════════════════════════════════════════════════════════════════════
# Scanner (with optional parallelism)
# ═══════════════════════════════════════════════════════════════════════════════

def scan(root: str, sample_pages: int = 20,
         workers: int = 1, verbose: bool = False) -> List[FileResult]:
    """
    Walk root recursively, classify every PDF.
    Use workers > 1 for parallel scanning of large collections.
    """
    pdf_files = sorted(Path(root).rglob("*.pdf"))
    total = len(pdf_files)
    if total == 0:
        print("No PDF files found.")
        return []

    print(f"Scanning {total} PDF(s) under {root}\n")
    results: List[FileResult] = []
    w_pad = len(str(total))

    def _process(i_path):
        i, pdf_path = i_path
        r = classify_file(str(pdf_path), sample_pages=sample_pages)
        return i, pdf_path, r

    items = list(enumerate(pdf_files, 1))

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(_process, item): item for item in items}
            done = 0
            for fut in as_completed(futures):
                try:
                    i, pdf_path, r = fut.result()
                except Exception as e:
                    i, pdf_path = futures[fut]
                    r = FileResult(path=str(pdf_path), route=ROUTE_NEEDS_REVIEW,
                                   error=str(e)[:80])
                rel = Path(pdf_path).relative_to(root)
                done += 1
                print(f"  [{done:>{w_pad}}/{total}] {rel} → {r.route}")
                results.append(r)
    else:
        for i, pdf_path in items:
            rel = pdf_path.relative_to(root)
            print(f"  [{i:>{w_pad}}/{total}] {rel} ...", end="", flush=True)
            r = classify_file(str(pdf_path), sample_pages=sample_pages)
            results.append(r)
            print(f" → {r.route}")
            if verbose and r.fonts:
                for f in r.fonts:
                    if f.font_class not in (FC_LATIN_OTHER,):
                        ptl = f" (glyph_db:{f.in_glyph_db})" if f.font_class == FC_LEGACY_TIBETAN else ""
                        print(f"       [{f.font_class}] {f.base_name}{ptl}")

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Route Tibetan PDF folders to the right extractor in one pass.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output files
────────────
  use_pymupdf.csv       folders to process with PyMuPDF (fitz.get_text)
  use_pytiblegenc.csv   folders to process with py-tiblegenc (legacy glyph mapping)
  needs_review.csv      legacy fonts not in py-tiblegenc glyph_db — manual work needed
  not_convertible.csv   scanned/image-only folders — OCR required
  all_folders.csv       every IE_ID with full detail
  file_detail.csv       per-file breakdown for auditing

CSV columns
────────────
  ie_id                 top-level folder name (e.g. W1234)
  route                 USE_PYMUPDF / USE_PYTIBLEGENC / NEEDS_REVIEW /
                        NOT_CONVERTIBLE / MIXED
  route_description     human-readable explanation
  total_files           number of PDFs in this IE_ID
  font_classes          font encoding types found (UNICODE_TIBETAN, LEGACY_TIBETAN…)
  tibetan_font_names    actual font names found in the PDFs
  unknown_legacy_fonts  legacy fonts not recognised by py-tiblegenc glyph_db

Examples
────────
  python route_folders.py /data/bdrc_etext_sync/
  python route_folders.py /data/bdrc_etext_sync/ --out ./results/
  python route_folders.py /data/bdrc_etext_sync/ --workers 8 --verbose
  python route_folders.py /data/bdrc_etext_sync/ --all-pages --out ./results/
""",
    )
    ap.add_argument("root",          help="Root directory to scan")
    ap.add_argument("--out",         default=".", metavar="DIR",
                    help="Output directory for CSV files (default: .)")
    ap.add_argument("--sample",      type=int, default=20,
                    help="Pages to sample per PDF for page-type detection (default 20; 0=all)")
    ap.add_argument("--all-pages",   action="store_true",
                    help="Analyse every page (slower but more accurate)")
    ap.add_argument("--workers",     type=int, default=1,
                    help="Parallel workers for scanning (default 1; try 4-8 for large sets)")
    ap.add_argument("--verbose",     action="store_true",
                    help="Print font details for each file during scan")
    args = ap.parse_args()

    root = str(Path(args.root).resolve())
    if not Path(root).is_dir():
        print(f"ERROR: not a directory: {root}")
        sys.exit(1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    sample = 0 if args.all_pages else args.sample

    # ── Scan ─────────────────────────────────────────────────────────────────
    file_results = scan(root, sample_pages=sample,
                        workers=args.workers, verbose=args.verbose)
    if not file_results:
        sys.exit(0)

    # ── Aggregate to IE_ID level ─────────────────────────────────────────────
    summaries = aggregate(file_results, root)

    # ── Terminal summary ──────────────────────────────────────────────────────
    counts: Dict[str, int] = defaultdict(int)
    for s in summaries:
        counts[s.route] += 1

    print("\n" + "═" * 66)
    print("ROUTING SUMMARY")
    print("═" * 66)
    icons = {
        ROUTE_PYMUPDF:      "🟢",
        ROUTE_PYTIBLEGENC:  "🔵",
        ROUTE_NEEDS_REVIEW: "🟡",
        ROUTE_NOT_CONVERT:  "🔴",
        ROUTE_MIXED:        "🟠",
        ROUTE_EMPTY:        "⚪",
    }
    for route in [ROUTE_PYMUPDF, ROUTE_PYTIBLEGENC,
                  ROUTE_NEEDS_REVIEW, ROUTE_NOT_CONVERT,
                  ROUTE_MIXED, ROUTE_EMPTY]:
        n = counts.get(route, 0)
        if n:
            icon = icons.get(route, " ")
            print(f"  {icon}  {route:<22}  {n:>5} IE_ID(s)")

    print(f"\n  Total IE_IDs : {len(summaries)}")
    print(f"  Total PDFs   : {len(file_results)}")
    if not _PTL_OK:
        print("\n  ⚠  py-tiblegenc not installed — all legacy folders routed to NEEDS_REVIEW")
    print("═" * 66)

    # ── Write CSVs ────────────────────────────────────────────────────────────
    n1 = write_route_csv(summaries, str(out_dir/"use_pymupdf.csv"),
                         [ROUTE_PYMUPDF])
    n2 = write_route_csv(summaries, str(out_dir/"use_pytiblegenc.csv"),
                         [ROUTE_PYTIBLEGENC])
    n3 = write_route_csv(summaries, str(out_dir/"needs_review.csv"),
                         [ROUTE_NEEDS_REVIEW, ROUTE_MIXED])
    n4 = write_route_csv(summaries, str(out_dir/"not_convertible.csv"),
                         [ROUTE_NOT_CONVERT])
    write_all_csv(summaries, str(out_dir/"all_folders.csv"))
    write_file_detail_csv(file_results, str(out_dir/"file_detail.csv"), root)

    print(f"\nResults → {out_dir}/")
    print(f"use_pymupdf.csv       {n1:>5} IE_ID(s)  — run with fitz.get_text()")
    print(f"use_pytiblegenc.csv   {n2:>5} IE_ID(s)  — run with py-tiblegenc")
    print(f"needs_review.csv      {n3:>5} IE_ID(s)  — unknown fonts, manual review")
    print(f"not_convertible.csv   {n4:>5} IE_ID(s)  — scanned, needs OCR")
    print(f"all_folders.csv       {len(summaries):>5} IE_ID(s)  — full summary")
    print(f"file_detail.csv       {len(file_results):>5} file(s)   — per-file audit")


if __name__ == "__main__":
    main()
