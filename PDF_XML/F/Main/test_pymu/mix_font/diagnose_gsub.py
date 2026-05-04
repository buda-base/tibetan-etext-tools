#!/usr/bin/env python3
"""
Diagnostic script for gsub_resolver integration.
Run this from the same directory as your conversion scripts:

    python diagnose_gsub.py /path/to/your/PDF.pdf

It prints a step-by-step trace of every decision made during CMap patching.
"""

import sys, io, re
from pathlib import Path

# ── make sure local modules are importable ──────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

# ── check dependencies ──────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1: Dependency check")
print("=" * 60)

try:
    import pymupdf as fitz
    print(f"  ✓ pymupdf  (version: {fitz.version[0]})")
except ImportError:
    try:
        import fitz
        print(f"  ✓ fitz  (version: {fitz.version[0]})")
    except ImportError:
        print("  ✗ PyMuPDF not installed"); sys.exit(1)

try:
    from fontTools import ttLib
    print("  ✓ fontTools")
except ImportError:
    print("  ✗ fontTools not installed — run: pip install fonttools"); sys.exit(1)

try:
    from gsub_resolver import build_glyph_unicode_map
    print("  ✓ gsub_resolver")
except ImportError as e:
    print(f"  ✗ gsub_resolver not found: {e}")
    print("    Make sure gsub_resolver.py is in the same directory"); sys.exit(1)

# ── check config ─────────────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 2: config.py — FONT_DIR setting")
print("=" * 60)

try:
    from config import FONT_DIR
    if FONT_DIR is None:
        print("  ✗ FONT_DIR = None  →  GSUB correction is disabled")
        print("    Set FONT_DIR in config.py to your .ttf file or fonts directory")
        sys.exit(1)
    p = Path(FONT_DIR)
    print(f"  FONT_DIR = {FONT_DIR!r}")
    print(f"  Path type: {'directory' if p.is_dir() else 'file' if p.is_file() else 'DOES NOT EXIST'}")
    if not p.exists():
        print(f"  ✗ Path does not exist on disk!")
        sys.exit(1)
    print("  ✓ Path exists")
except ImportError:
    print("  ✗ config.py not found or FONT_DIR not defined"); sys.exit(1)

# ── check _get_font_paths ────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 3: Font file discovery")
print("=" * 60)

try:
    from pdf_extract import _get_font_paths, _find_font_file
    font_paths = _get_font_paths()
    print(f"  _get_font_paths() returned {len(font_paths)} file(s):")
    for fp in font_paths:
        print(f"    {fp}")
    if not font_paths:
        print("  ✗ No font files found — check FONT_DIR path")
        sys.exit(1)
except Exception as e:
    print(f"  ✗ Error calling _get_font_paths(): {e}")
    sys.exit(1)

# Test name matching against known Monlam basefont names
print()
print("  Name-match test (basefont vs filename):")
for basefont in ["MonlamUniOuChan2", "MonlamUniOuChan5",
                 "FPDEGJ+MonlamUniOuChan2", "EKPMCM+MonlamUniOuChan2"]:
    found = _find_font_file(basefont)
    status = f"✓ → {found.name}" if found else "✗ not matched"
    print(f"    {basefont!r:40s} {status}")

# ── test loading each font ────────────────────────────────────────────────────
print()
print("=" * 60)
print("STEP 4: Font loading & GSUB check")
print("=" * 60)

for fp in font_paths:
    print(f"\n  Font: {fp.name}")
    try:
        tt = ttLib.TTFont(str(fp))
        tables = list(tt.keys())
        has_cmap = "cmap" in tt
        has_gsub = "GSUB" in tt
        has_glyf = "glyf" in tt
        print(f"    Tables: {tables}")
        print(f"    Has cmap:  {'✓' if has_cmap else '✗ (needed for GSUB inversion)'}")
        print(f"    Has GSUB:  {'✓' if has_gsub else '✗ (needed for GSUB inversion)'}")
        print(f"    Has glyf:  {'✓' if has_glyf else '✗'}")
        if not has_cmap or not has_gsub:
            print("    ⚠ This looks like a SUBSET font (cmap/GSUB stripped during PDF subsetting)")
            print("    ⚠ You need the FULL (unsubsetted) font file")
        else:
            cmap = tt["cmap"].getBestCmap() or {}
            tib = {cp: g for cp, g in cmap.items() if 0x0F00 <= cp <= 0x0FFF}
            print(f"    cmap entries: {len(cmap)} total, {len(tib)} Tibetan")
            gsub = tt["GSUB"].table
            n_lookups = len(gsub.LookupList.Lookup) if gsub.LookupList else 0
            print(f"    GSUB lookups: {n_lookups}")
            # Try inverting
            from gsub_resolver import invert_gsub
            inv = invert_gsub(tt)
            tib_inv = {k: v for k, v in inv.items()
                       if any(all(0x0F00 <= ord(c) <= 0x0FFF for c in "".join(chr(x) for x in seq))
                              for seq in v)}
            print(f"    GSUB inverse map: {len(inv)} entries total, {len(tib_inv)} Tibetan")
            if tib_inv:
                print(f"    ✓ GSUB inversion working — ALL {len(tib_inv)} Tibetan entries:")
                for gname, seqs in tib_inv.items():
                    best = min(seqs, key=len)
                    uni = "".join(chr(c) for c in best)
                    npts = ""
                    try:
                        if "glyf" in tt:
                            g = tt["glyf"][gname]
                            coords,_,_ = g.getCoordinates(tt["glyf"])
                            npts = f" [{len(coords)}pts]"
                    except: pass
                    print(f"      {gname!r} → {uni!r}  (U+{'+'.join(f'{ord(c):04X}' for c in uni)}){npts}")
                
                # Build hash table and show counts
                from hashlib import sha256 as _sha256
                def _fh(tt, gname, res=6):
                    try:
                        if "glyf" not in tt: return None
                        glyf=tt["glyf"]; g=glyf[gname]
                        c,e,f=g.getCoordinates(glyf)
                    except: return None
                    upem=tt["head"].unitsPerEm
                    if not c: return None
                    n=[(x/upem,y/upem) for x,y in c]
                    mx=min(p[0] for p in n); my=min(p[1] for p in n)
                    n=[(x-mx,y-my) for x,y in n]; ce=set(e); pts=[]
                    for i,(x,y) in enumerate(n):
                        rx=round(x*res)/res; ry=round(y*res)/res
                        pts.append(f"{rx:.4f},{ry:.4f},{f[i]&1}")
                        if i in ce: pts.append("|")
                    return _sha256(";".join(pts).encode()).hexdigest()
                htable = {}
                for gname, seqs in tib_inv.items():
                    best = min(seqs, key=len)
                    uni = "".join(chr(c) for c in best)
                    h = _fh(tt, gname)
                    if h: htable[h] = uni
                print(f"    Hash table: {len(htable)} entries (glyph outlines hashed)")
                
                # Check specific bad GIDs from the PDF if provided
                if len(sys.argv) > 1:
                    import fitz as _fitz
                    _doc = _fitz.open(sys.argv[1])
                    for _pn in range(len(_doc)):
                        for _f in _doc[_pn].get_fonts(full=True):
                            if _f[5]!="Identity-H": continue
                            _fn=_f[3]; _bare=_fn.split("+")[-1] if "+" in _fn else _fn
                            def _norm(s): return s.lower().replace("_","").replace("-","").replace(" ","")
                            if _norm(_bare) != _norm(fp.stem): continue
                            _obj=_doc.xref_object(_f[0],compressed=False)
                            _dm=re.search(r'/DescendantFonts\s*\[\s*(\d+)',_obj)
                            if not _dm: continue
                            _do=_doc.xref_object(int(_dm.group(1)),compressed=False)
                            _fm=re.search(r'/FontDescriptor\s+(\d+)',_do)
                            if not _fm: continue
                            _fo=_doc.xref_object(int(_fm.group(1)),compressed=False)
                            _ff=re.search(r'/FontFile2\s+(\d+)',_fo)
                            if not _ff: continue
                            try:
                                _sb=_doc.xref_stream(int(_ff.group(1)))
                                _tt_sub=ttLib.TTFont(__import__("io").BytesIO(_sb))
                                _so=_tt_sub.getGlyphOrder()
                                print(f"    Matching subset GIDs:")
                                for _gid in [0x0128,0x0132,0x0140]:
                                    if _gid>=len(_so): continue
                                    _gn=_so[_gid]; _h=_fh(_tt_sub,_gn)
                                    _match=htable.get(_h) if _h else None
                                    print(f"      GID 0x{_gid:04X} ({_gn}): hash_match={_match!r}")
                            except: pass
                            break
                    _doc.close()
    except Exception as e:
        print(f"    ✗ Failed to load: {e}")

# ── test on actual PDF ────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print()
    print("=" * 60)
    print("STEP 5: PDF test")
    print("=" * 60)
    print("  (skip — pass a PDF path as argument to test on a real file)")
    print("  Usage: python diagnose_gsub.py /path/to/file.pdf")
    sys.exit(0)

pdf_path = Path(sys.argv[1])
print()
print("=" * 60)
print(f"STEP 5: PDF test — {pdf_path.name}")
print("=" * 60)

if not pdf_path.exists():
    print(f"  ✗ PDF not found: {pdf_path}"); sys.exit(1)

# Show which fonts the PDF needs and whether each is covered
doc_check = fitz.open(str(pdf_path))
seen_bases = set()
print("  Fonts needed by this PDF:")
for pn in range(len(doc_check)):
    for f in doc_check[pn].get_fonts(full=True):
        if f[5] != "Identity-H": continue
        base = f[3].split("+")[-1] if "+" in f[3] else f[3]
        if base in seen_bases: continue
        seen_bases.add(base)
        found = _find_font_file(f[3])
        status = f"✓ → {found.name}" if found else "✗ NOT FOUND in FONT_DIR"
        print(f"    {base:35s} {status}")
doc_check.close()
if any(_find_font_file(b) is None for b in seen_bases):
    print()
    print("  ⚠ Some fonts are missing — add their .ttf files to FONT_DIR")
    print("  ⚠ Correction will be skipped for those fonts")
print()

doc = fitz.open(str(pdf_path))
bad_before = {0x0128: 0, 0x0132: 0, 0x0140: 0}
for page in doc:
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0: continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span.get("chars", []):
                    cp = ord(ch.get("c", "X"))
                    if cp in bad_before:
                        bad_before[cp] += 1
doc.close()

names = {0x0128: "Ĩ (→ི)", 0x0132: "Ĳ (→ེ)", 0x0140: "ŀ (→ོ)"}
total_bad = sum(bad_before.values())
print(f"  Bad chars in raw PDF (before any correction):")
for cp, count in bad_before.items():
    print(f"    U+{cp:04X} {names[cp]}: {count} occurrences")
if total_bad == 0:
    print("  ✓ No bad chars in this PDF — nothing to fix")
    sys.exit(0)

print()
print("  Running _patch_font_cmaps()...")
import logging
logging.basicConfig(level=logging.DEBUG, format="  [%(levelname)s] %(message)s")

doc2 = fitz.open(str(pdf_path))
from pdf_extract import _patch_font_cmaps
_patch_font_cmaps(doc2)

bad_after = {0x0128: 0, 0x0132: 0, 0x0140: 0}
for page in doc2:
    raw = page.get_text("rawdict")
    for block in raw.get("blocks", []):
        if block.get("type") != 0: continue
        for line in block["lines"]:
            for span in line["spans"]:
                for ch in span.get("chars", []):
                    cp = ord(ch.get("c", "X"))
                    if cp in bad_after:
                        bad_after[cp] += 1
doc2.close()

print()
print("  Results after _patch_font_cmaps():")
for cp, before in bad_before.items():
    after = bad_after[cp]
    fixed = before - after
    status = "✓ fixed" if after == 0 else f"✗ {after} remaining"
    print(f"    U+{cp:04X} {names[cp]}: {before} → {after}  {status}")

total_after = sum(bad_after.values())
print()
if total_after == 0:
    print("  ✓ ALL bad chars corrected")
else:
    print(f"  ✗ {total_after} bad chars still remain after patching")
    print("    This means gsub_resolver could not resolve them.")
    print("    Possible causes:")
    print("    - The font file is a subset (no cmap/GSUB tables)")
    print("    - The font file doesn't match the one used in this PDF")