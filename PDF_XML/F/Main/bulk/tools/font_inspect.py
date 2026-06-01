#!/usr/bin/env python3
"""
font_inspect — diagnose unsupported Tibetan fonts in a PDF.

Run this on any PDF that produces garbled output to learn:

  1. Which fonts pytiblegenc doesn't have a table for, ranked by character
     volume (so you fix the biggest offenders first).
  2. The PDF's Encoding object for each unsupported font — base encoding
     plus any /Differences overrides.  This tells you what byte-to-character
     mapping the PDF reader will apply, which is half the puzzle.
  3. The embedded font file extracted to a .cff/.ttf/.otf on disk, so you
     can hand it to font_bridge or a font editor.
  4. A contact-sheet PNG showing what glyph sits at each codepoint, so you
     can visually identify Tibetan letters and conjuncts.

Usage
-----
    python tools/font_inspect.py path/to/document.pdf
    python tools/font_inspect.py path/to/document.pdf --out work/

What it doesn't do
------------------
* It doesn't decide whether the font matches an existing pytiblegenc table.
  That's font_bridge's job — run it on the .cff/.ttf produced here.
* It doesn't write any pytiblegenc table rows.  Once you've picked a
  strategy (alias or fresh CSV), use the templates in
  ``local_font_tables/`` to write the rows by hand or with a small script.

Exit code
---------
0 if at least one unsupported font was found, 1 if everything was already
covered (i.e. nothing to inspect).  Useful for shell scripting.
"""
from __future__ import annotations

import argparse
import logging
import sys
from io import BytesIO
from pathlib import Path

# Allow running as `python tools/font_inspect.py` from project root.
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # type: ignore

from fontTools.agl import toUnicode
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("font_inspect")


# ---------------------------------------------------------------------------
# Step 1: which fonts is pytiblegenc unable to handle?
# ---------------------------------------------------------------------------

def detect_unsupported_fonts(pdf_path: Path) -> dict[str, int]:
    """
    Run the project's hybrid extractor on *pdf_path* and return its
    ``unhandled_fonts`` stats — a dict ``{font_name: char_count}``.

    We import ``pdf_extract`` rather than re-implementing the detection, so
    the result is exactly what the real pipeline would see (same font-name
    normalization, same alias maps, same local-table installation).
    """
    from pdf_extract import extract_pdf_hybrid, _install_local_font_tables

    # Make sure local tables are loaded before we extract, so fonts already
    # covered by a local CSV don't show up as "unsupported".
    _install_local_font_tables()

    stats: dict = {}
    # extract_pdf_hybrid writes to its own stats dict internally and logs the
    # unhandled fonts; the easiest way to capture them is to monkey-patch the
    # logger or re-implement the loop.  Cleaner: peek at the function's
    # innards.  We just run a normal extraction and parse the warning line.
    captured: list[dict] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            msg = record.getMessage()
            if "Unhandled fonts" in msg and "{" in msg:
                # message format: "Hybrid Mode - Unhandled fonts (no conversion table): {...}"
                start = msg.index("{")
                try:
                    captured.append(eval(msg[start:]))  # safe: pdf_extract emits a dict-repr
                except Exception:
                    pass

    handler = _Capture()
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    old_level = root_logger.level
    if old_level > logging.WARNING:
        root_logger.setLevel(logging.WARNING)
    try:
        extract_pdf_hybrid(pdf_path)
    finally:
        root_logger.removeHandler(handler)
        root_logger.setLevel(old_level)

    if captured:
        return captured[-1]
    return {}


# ---------------------------------------------------------------------------
# Step 2: extract the embedded font binary
# ---------------------------------------------------------------------------

def extract_embedded_font(
    doc: fitz.Document, font_name: str, out_dir: Path
) -> Path | None:
    """
    Extract the embedded font binary for *font_name* (with or without subset
    prefix) and write it to *out_dir*.  Returns the written path, or None
    if the font couldn't be found / wasn't embedded.

    If the PDF has multiple subset copies of the same font, returns the
    largest one (most glyphs embedded = best for inspection).
    """
    candidates: list[tuple[int, str, str, bytes]] = []  # (size, basename, ext, data)
    for xref in range(1, doc.xref_length()):
        try:
            info = doc.extract_font(xref)
        except Exception:
            continue
        if not info:
            continue
        name, ext, ftype, buf = info
        if not name or not buf:
            continue
        # Match against base name (after subset prefix), case-sensitive,
        # also allow matching the stripped form ("TB-Youtso-" matches both
        # "TB-Youtso-Normal" and "TB-Youtso-Bold" — pick the first by size).
        base = name.split("+", 1)[-1] if "+" in name else name
        if base == font_name or name == font_name or (
            font_name.endswith("-") and base.startswith(font_name)
        ):
            candidates.append((len(buf), name, ext, buf))

    if not candidates:
        return None

    candidates.sort(reverse=True)  # largest first
    _, name, ext, data = candidates[0]
    safe = name.replace("/", "_").replace("\\", "_")
    out_path = out_dir / f"{safe}.{ext}"
    out_path.write_bytes(data)
    return out_path


# ---------------------------------------------------------------------------
# Step 3: dump the PDF Encoding object (BaseEncoding + Differences)
# ---------------------------------------------------------------------------

def dump_pdf_encoding(doc: fitz.Document, font_name: str) -> str:
    """
    Return a human-readable description of the PDF Encoding object(s)
    referenced by Font objects matching *font_name*.

    There may be more than one match (subsets) — we return all of them
    concatenated.  Each block lists BaseEncoding and Differences.
    """
    import re

    blocks: list[str] = []
    for xref in range(1, doc.xref_length()):
        obj = doc.xref_object(xref)
        if "/Type /Font" not in obj and "/Subtype /" not in obj:
            continue
        if "FontDescriptor" in obj.split(font_name, 1)[0] if font_name in obj else True:
            # Skip FontDescriptor objects; we want the Font dict itself.
            if "/Type /FontDescriptor" in obj:
                continue
        if font_name not in obj:
            continue

        block = [f"=== Font object xref {xref} ==="]
        block.append(obj.strip())
        # Find /Encoding reference and resolve it
        m = re.search(r"/Encoding\s+(\d+)\s+\d+\s+R", obj)
        if m:
            enc_xref = int(m.group(1))
            try:
                enc_obj = doc.xref_object(enc_xref)
                block.append(f"\n--- /Encoding object xref {enc_xref} ---")
                block.append(enc_obj.strip())
            except Exception as e:
                block.append(f"  (could not read encoding obj: {e})")
        elif "/Encoding /" in obj:
            block.append("--- Standard encoding (no Differences) ---")
        blocks.append("\n".join(block))

    return "\n\n".join(blocks) if blocks else f"(no Font object found for {font_name!r})"


# ---------------------------------------------------------------------------
# Step 4: rasterize a contact sheet of the font's glyphs
# ---------------------------------------------------------------------------

def rasterize_contact_sheet(
    font_path: Path,
    out_path: Path,
    *,
    encoding: str = "mac_roman",
    cell_w: int = 80,
    cell_h: int = 90,
    cols: int = 16,
    dpi: int = 120,
) -> None:
    """
    Render every byte 0x20..0xFF of *font_path* into a single PNG grid.
    Each cell is labelled with the codepoint (red) and outlined.

    Combining/zero-width glyphs (vowels, subscripts) won't show their shape
    in isolation — they need a base glyph to combine with.  Their cells
    will look empty.  That's diagnostic: cells with width-3 glyphs but no
    visible shape are top-marks (above baseline) or bottom-marks (below).
    """
    nrows = 16  # 256 cells / 16 cols
    page_w = cols * cell_w
    page_h = nrows * cell_h

    doc = fitz.open()
    page = doc.new_page(width=page_w, height=page_h)
    try:
        page.insert_font(fontfile=str(font_path), fontname="legacy")
    except Exception as e:
        logger.warning("Could not load font %s for rasterization: %s", font_path, e)
        doc.close()
        return

    for cp in range(0x20, 0x100):
        idx = cp - 0x20
        col = idx % cols
        row = idx // cols
        x = col * cell_w
        y = row * cell_h
        try:
            ch = bytes([cp]).decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            page.insert_text((x + 10, y + cell_h - 25), ch, fontname="legacy", fontsize=36)
        except Exception:
            pass

    tmp = font_path.parent / f"_{font_path.stem}_grid.pdf"
    doc.save(str(tmp))
    doc.close()

    rast = fitz.open(str(tmp))
    pix = rast[0].get_pixmap(dpi=dpi)
    img = Image.open(BytesIO(pix.tobytes("png")))
    rast.close()
    tmp.unlink(missing_ok=True)

    # Overlay codepoint labels and cell outlines
    draw = ImageDraw.Draw(img)
    try:
        label_font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12
        )
    except Exception:
        label_font = ImageFont.load_default()
    scale = dpi / 72
    for cp in range(0x20, 0x100):
        idx = cp - 0x20
        col = idx % cols
        row = idx // cols
        x = int(col * cell_w * scale)
        y = int(row * cell_h * scale)
        draw.text((x + 3, y + 3), f"{cp}", fill="red", font=label_font)
        draw.rectangle(
            [x, y, x + int(cell_w * scale) - 1, y + int(cell_h * scale) - 1],
            outline="lightgray", width=1,
        )

    img.save(out_path)


# ---------------------------------------------------------------------------
# Step 5: dump the font's own glyph-name encoding (for the bridge tool)
# ---------------------------------------------------------------------------

def dump_font_glyph_names(font_path: Path) -> str:
    """
    Return a human-readable listing of byte → glyph_name → AGL-unicode
    for the embedded font.  Useful for understanding what character each
    byte resolves to during PDF text extraction.

    Supports CFF, OTF, and TTF.  For TrueType, uses the best cmap.
    """
    suffix = font_path.suffix.lower()
    lines: list[str] = []

    if suffix in {".cff"}:
        cff = CFFFontSet()
        cff.decompile(BytesIO(font_path.read_bytes()), None, isCFF2=False)
        top = cff[cff.fontNames[0]]
        enc = top.Encoding
        lines.append(f"Font: {cff.fontNames[0]}")
        lines.append(f"Type: CFF, {len(top.charset)} glyphs")
        lines.append(f"{'byte':>4} {'glyph_name':<18} {'AGL-unicode':<20}")
        lines.append("-" * 60)
        for b in range(0x20, 0x100):
            if b >= len(enc):
                break
            g = enc[b]
            if not g or g == ".notdef":
                continue
            u = toUnicode(g)
            u_repr = (
                f"{u!r} (U+{ord(u):04X})" if u and len(u) == 1
                else (repr(u) if u else "(no AGL match)")
            )
            lines.append(f"{b:4d} {g:<18} {u_repr}")
    else:
        try:
            font = TTFont(str(font_path))
            cmap = font.getBestCmap()
            lines.append(f"Font: {Path(font_path).stem}")
            lines.append(f"Type: {suffix.lstrip('.').upper()}, {len(cmap)} cmap entries")
            lines.append(f"{'unicode':>8}  glyph_name")
            lines.append("-" * 40)
            for cp, gname in sorted(cmap.items())[:200]:
                lines.append(f"U+{cp:04X}  {gname}")
            if len(cmap) > 200:
                lines.append(f"... ({len(cmap) - 200} more)")
        except Exception as e:
            lines.append(f"Could not parse font: {e}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI driver
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Diagnose unsupported Tibetan fonts in a PDF.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("pdf", type=Path, help="Path to the PDF to inspect.")
    parser.add_argument(
        "--out", type=Path, default=None,
        help="Output directory (default: <pdf-stem>_fontinspect/ next to the PDF).",
    )
    parser.add_argument(
        "--min-chars", type=int, default=10,
        help="Only inspect fonts with at least this many unhandled characters "
             "(default: 10). Use 0 to inspect everything.",
    )
    parser.add_argument(
        "--encoding", default="mac_roman", choices=["mac_roman", "latin-1", "cp1252"],
        help="Byte-decoding to use when rasterizing the contact sheet "
             "(default: mac_roman). Try latin-1 if mac_roman shows empty cells.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    pdf_path: Path = args.pdf
    if not pdf_path.is_file():
        print(f"error: PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    out_dir: Path = args.out or pdf_path.parent / f"{pdf_path.stem}_fontinspect"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'=' * 70}")
    print(f"Inspecting: {pdf_path}")
    print(f"Output dir: {out_dir}")
    print(f"{'=' * 70}\n")

    # --- 1. Detect unsupported fonts ----------------------------------
    print("Step 1: running pipeline to detect unhandled fonts...")
    unhandled = detect_unsupported_fonts(pdf_path)

    # Filter out Latin/system fonts that aren't Tibetan-relevant
    LATIN_FONTS = {
        "Times-Roman", "Times-Bold", "Times-Italic", "Times-BoldItalic",
        "TimesNewRomanPSMT", "TimesNewRomanPS-BoldMT", "TimesNewRomanPS-ItalicMT",
        "Helvetica", "Helvetica-Bold", "Helvetica-Oblique",
        "Arial", "Arial-Bold", "Arial-Italic",
        "Courier", "Courier-Bold", "Courier-Oblique",
        "Calibri", "Calibri-Bold", "Calibri-Italic",
        "Symbol", "ZapfDingbats",
    }
    tibetan_candidates = {
        f: n for f, n in unhandled.items()
        if f not in LATIN_FONTS and n >= args.min_chars
    }

    if not unhandled:
        print("  No unhandled fonts. Pipeline output is fully covered.")
        return 1

    print(f"  Total unhandled fonts: {len(unhandled)}")
    print(f"  After Latin-font filter and --min-chars: {len(tibetan_candidates)}")

    if not tibetan_candidates:
        print("\n  Only Latin/system fonts left after filtering — nothing to inspect.")
        print(f"  Full unhandled-fonts list: {unhandled}")
        return 1

    print()
    print("Candidate Tibetan fonts (sorted by character volume):")
    print(f"  {'count':>10}  font_name")
    for fn, n in sorted(tibetan_candidates.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>10}  {fn}")
    print()

    # --- 2-5. For each candidate: extract, dump, rasterize -----------
    doc = fitz.open(str(pdf_path))
    for fn in sorted(tibetan_candidates):
        # Sanitize font name for filesystem
        safe = fn.replace("/", "_").replace("+", "_").replace(" ", "_")
        per_font_dir = out_dir / safe
        per_font_dir.mkdir(exist_ok=True)

        print(f"--- {fn} (chars: {tibetan_candidates[fn]}) ---")

        # Step 2: extract embedded binary
        font_bin = extract_embedded_font(doc, fn, per_font_dir)
        if font_bin:
            print(f"  embedded font:    {font_bin.name}")
        else:
            print(f"  embedded font:    (not found / not embedded)")

        # Step 3: PDF Encoding object
        enc_txt = dump_pdf_encoding(doc, fn)
        enc_path = per_font_dir / "pdf_encoding.txt"
        enc_path.write_text(enc_txt, encoding="utf-8")
        print(f"  PDF encoding:     {enc_path.name}")

        # Step 5: font glyph-name encoding (helpful for the bridge)
        if font_bin:
            try:
                gname_txt = dump_font_glyph_names(font_bin)
                gname_path = per_font_dir / "font_glyph_names.txt"
                gname_path.write_text(gname_txt, encoding="utf-8")
                print(f"  glyph names:      {gname_path.name}")
            except Exception as e:
                print(f"  glyph names:      (failed: {e})")

        # Step 4: contact sheet
        if font_bin:
            try:
                sheet_path = per_font_dir / f"contact_sheet_{args.encoding}.png"
                rasterize_contact_sheet(font_bin, sheet_path, encoding=args.encoding)
                print(f"  contact sheet:    {sheet_path.name}")
            except Exception as e:
                print(f"  contact sheet:    (failed: {e})")
        print()

    doc.close()

    print(f"{'=' * 70}")
    print("Next steps:")
    print(f"  1. For each font above, run font_bridge to test if its byte layout")
    print(f"     matches an existing pytiblegenc table:")
    print(f"       python tools/font_bridge.py {out_dir}/<font>/<font>.cff")
    print(f"  2. If bridge match rate is >90%, add an alias to")
    print(f"     local_font_tables/_aliases.csv.")
    print(f"  3. Otherwise, eyeball the contact sheet and build a fresh CSV.")
    print(f"{'=' * 70}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
