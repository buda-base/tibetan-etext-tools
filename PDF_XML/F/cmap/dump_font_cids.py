#!/usr/bin/env python3
"""
Dump every text glyph from a PDF: page, font (raw + normalized), CID, decoded character.

Uses pdfminer’s text renderer (same CIDs as LTChar) and font.to_unichr(cid), or "(cid:N)"
when undefined — useful for building DEFAULT_CID_TO_UNICODE_OVERRIDES in glyph_decoder.py.

Usage:
    python dump_font_cids.py path/to/file.pdf
    python dump_font_cids.py path/to/file.pdf -o cids.csv
    python dump_font_cids.py path/to/file.pdf --max-pages 5
    python dump_font_cids.py path/to/file.pdf --summary -o cid_counts.csv
    python dump_font_cids.py path/to/file.pdf --summary --only-fonts TCRCYoutso,TCRCBod \\
        --document-totals -o cid_counts.csv

Pool an existing summary: use pool_cid_summary.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Set

from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams
from pdfminer.pdfcolor import PDFColorSpace
from pdfminer.pdffont import PDFUnicodeNotDefined
from pdfminer.pdfinterp import PDFGraphicState, PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.utils import Matrix

script_dir = Path(__file__).parent.resolve()
sys.path.insert(0, str(script_dir))

from glyph_decoder import _normalize_font_key  # noqa: E402


class CIDDumpAggregator(PDFPageAggregator):
    """PDFPageAggregator that records (page, font, cid, decoded) for each render_char."""

    def __init__(
        self,
        rsrcmgr: PDFResourceManager,
        rows: List[dict],
        laparams: LAParams | None = None,
    ) -> None:
        super().__init__(rsrcmgr, pageno=1, laparams=laparams)
        self._rows = rows

    def render_char(
        self,
        matrix: Matrix,
        font,
        fontsize: float,
        scaling: float,
        rise: float,
        cid: int,
        ncs: PDFColorSpace,
        graphicstate: PDFGraphicState,
    ) -> float:
        raw_name = font.fontname or ""
        norm = _normalize_font_key(raw_name)
        try:
            decoded = font.to_unichr(cid)
            assert isinstance(decoded, str)
        except PDFUnicodeNotDefined:
            decoded = f"(cid:{cid})"
        if len(decoded) == 1:
            o = ord(decoded)
            if o < 0x20 or o == 0x7F:
                decoded = f"U+{o:04X}"

        self._rows.append(
            {
                "page": self.pageno,
                "font_raw": raw_name,
                "font_normalized": norm,
                "cid": cid,
                "decoded_char": decoded,
            }
        )
        return super().render_char(
            matrix, font, fontsize, scaling, rise, cid, ncs, graphicstate
        )


def dump_pdf_cids(
    pdf_path: Path,
    *,
    max_pages: int | None = None,
    laparams: LAParams | None = None,
) -> List[dict]:
    rows: List[dict] = []
    rsrcmgr = PDFResourceManager()
    device = CIDDumpAggregator(rsrcmgr, rows, laparams=laparams or LAParams())
    interpreter = PDFPageInterpreter(rsrcmgr, device)

    with open(pdf_path, "rb") as fp:
        for i, page in enumerate(PDFPage.get_pages(fp)):
            if max_pages is not None and i >= max_pages:
                break
            interpreter.process_page(page)
    return rows


def write_csv_full(rows: List[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["page", "font_raw", "font_normalized", "cid", "decoded_char"],
        )
        w.writeheader()
        w.writerows(rows)


def write_csv_summary(rows: List[dict], out: Path) -> None:
    ctr: Counter[tuple[int, str, str, int, str]] = Counter()
    for r in rows:
        key = (
            r["page"],
            r["font_raw"],
            r["font_normalized"],
            r["cid"],
            r["decoded_char"],
        )
        ctr[key] += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["page", "font_raw", "font_normalized", "cid", "decoded_char", "count"]
        )
        for (
            page,
            font_raw,
            font_norm,
            cid,
            decoded,
        ), count in sorted(ctr.items(), key=lambda x: (-x[1], x[0][0], x[0][2], x[0][3])):
            w.writerow([page, font_raw, font_norm, cid, decoded, count])


def _filter_rows_fonts(rows: List[dict], only: Set[str] | None) -> List[dict]:
    if not only:
        return rows
    return [r for r in rows if r["font_normalized"] in only]


def _parse_only_fonts_arg(s: str | None) -> Set[str] | None:
    if not s or not s.strip():
        return None
    return {x.strip() for x in s.split(",") if x.strip()}


def write_csv_document_totals(rows: List[dict], out: Path) -> None:
    """One row per (font_normalized, cid); sums glyphs across all pages."""
    per: dict[tuple[str, int], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        fn = r["font_normalized"]
        cid = r["cid"]
        dec = r["decoded_char"]
        per[(fn, cid)][dec] += 1

    rolled: list[tuple[str, int, str, int, int]] = []
    for (fn, cid), dec_map in per.items():
        total = sum(dec_map.values())
        best_dec = max(dec_map.items(), key=lambda x: x[1])[0]
        rolled.append((fn, cid, best_dec, total, len(dec_map)))

    rolled.sort(key=lambda x: -x[3])
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "font_normalized",
                "cid",
                "decoded_char_pdf",
                "total_count",
                "distinct_decoded_variants",
            ]
        )
        for fn, cid, dec, total, variants in rolled:
            w.writerow([fn, cid, dec, total, variants])


def main() -> None:
    p = argparse.ArgumentParser(
        description="Dump (page, font, cid, decoded_char) for every PDF text glyph."
    )
    p.add_argument("pdf", type=Path, help="Input PDF")
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output CSV (default: <stem>_cids.csv next to PDF)",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Process only the first N pages",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help="Aggregated CSV with count per (page, font, cid, decoded)",
    )
    p.add_argument(
        "--only-fonts",
        type=str,
        default=None,
        help="Comma-separated font_normalized to keep (e.g. TCRCYoutso,TCRCBod)",
    )
    p.add_argument(
        "--document-totals",
        type=Path,
        default=None,
        metavar="OUT.csv",
        help="Also write pooled (font, cid) totals across the whole PDF to this path",
    )
    args = p.parse_args()

    pdf_path = args.pdf.expanduser().resolve()
    if not pdf_path.is_file():
        print(f"Error: not a file: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    out = args.output
    if out is None:
        suffix = "_cid_summary.csv" if args.summary else "_cids.csv"
        out = pdf_path.with_name(pdf_path.stem + suffix)

    print(f"Reading {pdf_path.name} …", file=sys.stderr)
    rows = dump_pdf_cids(pdf_path, max_pages=args.max_pages)
    print(f"Captured {len(rows)} glyph row(s).", file=sys.stderr)

    only = _parse_only_fonts_arg(args.only_fonts)
    rows_f = _filter_rows_fonts(rows, only)
    if only:
        print(
            f"After --only-fonts: {len(rows_f)} glyph row(s).",
            file=sys.stderr,
        )

    if args.summary:
        write_csv_summary(rows_f, out)
    else:
        write_csv_full(rows_f, out)
    print(f"Wrote {out}", file=sys.stderr)

    if args.document_totals:
        write_csv_document_totals(rows_f, args.document_totals.resolve())
        print(f"Wrote document totals {args.document_totals}", file=sys.stderr)


if __name__ == "__main__":
    main()
