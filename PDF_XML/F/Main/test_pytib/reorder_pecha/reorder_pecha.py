#!/usr/bin/env python3
"""
reorder_pecha.py  —  Reconstruct the true reading order of a scrambled pecha PDF.

Background
----------
This PDF (e.g. LMf4a160.pdf) was scanned 3-leaves-per-sheet.  Each PDF page
holds three pecha leaves side by side (three text columns, after the page's
90° rotation).  Every leaf carries its true sequential page number printed in
the top margin.  Because the sheets were scanned front/back in batches, the
leaves are interleaved out of order:

    PDF page 2 -> printed leaves [3, 5, 7]   (recto, ascending L->R)
    PDF page 3 -> printed leaves [8, 6, 4]   (verso, descending L->R)
    PDF page 4 -> printed leaves [9, 11, 13]
    ...

A couple of leaf numbers repeat across batch boundaries (scan overlap); we
keep the first occurrence.

This script decodes each leaf's printed page number (the Latin digits in the
top margin are *not* font-scrambled — only the Tibetan body is), determines
which column each number labels, and emits a NEW PDF in which every page
contains exactly one leaf, in correct ascending reading order.  That output
drops straight into the existing convert_pdf_to_xml.py pipeline.

Usage
-----
    python reorder_pecha.py INPUT.pdf -o OUTPUT_reordered.pdf
    python reorder_pecha.py INPUT.pdf --report   # just print the order, no PDF

Requires pdf_extract.py (and pytiblegenc) importable from the same dir, but
only uses it as a fallback; page-number detection itself needs only PyMuPDF.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# Geometry constants (in rawdict / un-rotated coordinate space)
#   - The page is 1191 wide x 842 tall on disk but rotated 90°, so the text
#     coordinate system PyMuPDF reports is ~842 wide x ~1191 tall.
#   - The printed page numbers sit in the top margin: y0 < TOP_MARGIN_Y.
#   - Three leaves occupy three x-columns.
# ---------------------------------------------------------------------------
TOP_MARGIN_Y = 80.0          # printed page numbers are above this y
BODY_Y_MIN = 80.0            # body text band (used only for sanity checks)
BODY_Y_MAX = 1010.0
PAGE_NUM_RE = re.compile(r"^\d{1,4}$")


def detect_leaf_numbers(page: fitz.Page) -> list[tuple[float, int]]:
    """
    Return [(x_center, printed_number), ...] for every leaf on this page,
    sorted left-to-right by x.

    The printed page numbers in the top margin use a normal Latin font
    (TimesNewRoman / SimSun), so PyMuPDF decodes them directly — no Tibetan
    font bridging needed.
    """
    found: list[tuple[float, int]] = []
    d = page.get_text("rawdict")
    for block in d.get("blocks", []):
        if block.get("type", 1) != 0:
            continue
        for line in block.get("lines", []):
            bb = line.get("bbox", [0, 0, 0, 0])
            y0, x0, x1 = bb[1], bb[0], bb[2]
            if y0 >= TOP_MARGIN_Y:
                continue
            # Reassemble the line text from spans (digits only here)
            txt = "".join(
                ch.get("c", "")
                for span in line.get("spans", [])
                for ch in (span.get("chars") or [])
            ) or "".join(span.get("text", "") for span in line.get("spans", []))
            txt = txt.strip()
            if PAGE_NUM_RE.match(txt):
                found.append(((x0 + x1) / 2.0, int(txt)))
    found.sort(key=lambda t: t[0])
    return found


def build_order(pdf_path: Path, verbose: bool = True):
    """
    Scan every page, map printed-number -> (pdf_page_index, x_center).
    Returns:
        ordered : list of (number, pdf_page_index, x_center) sorted by number,
                  with overlap-duplicates removed (first occurrence kept).
        per_page: dict pdf_page_index -> list[(x_center, number)]  (for cropping)
        warnings: list[str]
    """
    doc = fitz.open(str(pdf_path))
    frames: list[tuple[int, int, float]] = []   # (number, page_idx, x_center)
    per_page: dict[int, list[tuple[float, int]]] = {}
    pages_without_numbers: list[int] = []

    for pno in range(doc.page_count):
        leaves = detect_leaf_numbers(doc[pno])
        per_page[pno] = leaves
        if not leaves:
            pages_without_numbers.append(pno)
            continue
        for x_center, num in leaves:
            frames.append((num, pno, x_center))

    doc.close()

    warnings: list[str] = []
    if pages_without_numbers:
        warnings.append(
            f"{len(pages_without_numbers)} page(s) had no detectable leaf number: "
            f"{pages_without_numbers[:10]}{'...' if len(pages_without_numbers) > 10 else ''}"
        )

    # Deduplicate by printed number (scan-overlap repeats); keep first occurrence
    seen: set[int] = set()
    duplicates: list[int] = []
    ordered: list[tuple[int, int, float]] = []
    for num, pno, xc in sorted(frames, key=lambda t: (t[0], t[1], t[2])):
        if num in seen:
            duplicates.append(num)
            continue
        seen.add(num)
        ordered.append((num, pno, xc))

    if duplicates:
        warnings.append(f"{len(duplicates)} overlap-duplicate leaf number(s) dropped: {sorted(set(duplicates))}")

    # Gap check
    nums = [n for n, _, _ in ordered]
    if nums:
        gaps = sorted(set(range(min(nums), max(nums) + 1)) - set(nums))
        if gaps:
            warnings.append(f"{len(gaps)} missing leaf number(s) (gaps): {gaps[:30]}{'...' if len(gaps) > 30 else ''}")

    if verbose:
        print(f"  detected {len(frames)} leaf frames across {doc.page_count if False else ''}pages")
        print(f"  reading-order leaves: {len(ordered)}  (numbers {min(nums)}..{max(nums)})" if nums else "  no leaves found")
        for w in warnings:
            print(f"  [warn] {w}")

    return ordered, per_page, warnings


def column_bounds(x_centers: list[float], page_width: float) -> list[tuple[float, float]]:
    """
    Given the x-centers of the leaves on a page, compute crop bounds
    (left, right) for each leaf: the midpoints between adjacent centers,
    clamped to page edges.
    """
    cs = sorted(x_centers)
    bounds = []
    for i, c in enumerate(cs):
        left = 0.0 if i == 0 else (cs[i - 1] + c) / 2.0
        right = page_width if i == len(cs) - 1 else (c + cs[i + 1]) / 2.0
        bounds.append((left, right))
    return bounds


def write_reordered_pdf(pdf_path: Path, out_path: Path, ordered, per_page, crop_leaves: bool = True):
    """
    Build a new PDF. For each leaf in reading order, copy its source page and
    (optionally) set the CropBox to just that leaf's column, so the output has
    exactly one leaf per page in correct sequence.

    Coordinate note (verified on this file): PyMuPDF reports rawdict text
    bboxes in the page's *unrotated* mediabox space, and ``set_cropbox`` also
    takes unrotated coordinates.  The three leaves are separated along the
    unrotated x-axis (0..mediabox.width), regardless of the 90° display
    rotation.  So we crop an x-band [left, right] over the full y-height.
    """
    src = fitz.open(str(pdf_path))
    out = fitz.open()

    for num, pno, xc in ordered:
        leaves = per_page[pno]
        centers = [c for c, _ in leaves]
        page = src[pno]
        mb = page.mediabox  # unrotated box; leaf x-centers live in [mb.x0, mb.x1]

        out.insert_pdf(src, from_page=pno, to_page=pno)
        newpage = out[-1]

        if crop_leaves and len(centers) > 1:
            bounds = column_bounds(centers, mb.x1)
            idx = (centers.index(xc) if xc in centers
                   else min(range(len(centers)), key=lambda k: abs(centers[k] - xc)))
            left_u, right_u = bounds[idx]
            # small symmetric padding so frame borders aren't clipped
            pad = 6.0
            crop = fitz.Rect(max(mb.x0, left_u - pad), mb.y0,
                             min(mb.x1, right_u + pad), mb.y1)
            crop = crop & newpage.mediabox
            try:
                newpage.set_cropbox(crop)
            except Exception:
                pass  # leave full page if crop invalid

    out.save(str(out_path), garbage=4, deflate=True)
    out.close()
    src.close()


def main():
    ap = argparse.ArgumentParser(description="Reconstruct true reading order of a scrambled 3-up pecha PDF.")
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=None)
    ap.add_argument("--report", action="store_true", help="Only print the reconstructed order; do not write a PDF.")
    args = ap.parse_args()

    if not args.input.exists():
        print(f"ERROR: not found: {args.input}", file=sys.stderr); sys.exit(1)

    print(f"Analyzing {args.input.name} ...")
    ordered, per_page, warnings = build_order(args.input)

    if args.report or args.output is None:
        print("\nReconstructed reading order (leaf_number -> source pdf_page):")
        for num, pno, xc in ordered:
            print(f"  leaf {num:>4}  <- pdf page {pno} (x~{xc:.0f})")
        if args.report:
            return

    out_path = args.output or args.input.with_name(args.input.stem + "_reordered.pdf")
    print(f"\nWriting reordered PDF -> {out_path}")
    write_reordered_pdf(args.input, out_path, ordered, per_page)
    print("Done.")


if __name__ == "__main__":
    main()
