"""
pdf2line.cli — Command-line interface.

    pdf2line -i ./pdfs -o ./out
    pdf2line -i book.pdf -o ./out --backend pymupdf
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .convert import convert_pdf, convert_folder


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pdf2line",
        description="Convert PDFs to plain text. Visual line breaks within a "
                    "pecha page are preserved (one line per pecha line) and "
                    "pecha pages are separated by a blank line.",
    )
    p.add_argument("-i", "--input", required=True,
                   help="A PDF file, or a folder containing PDFs.")
    p.add_argument("-o", "--output", required=True,
                   help="Flat output folder for .txt files.")
    p.add_argument("--backend", choices=["hybrid", "pymupdf", "pytiblegenc"],
                   default="pymupdf",
                   help="Extraction backend (default: pymupdf). 'hybrid' falls "
                        "back to pytiblegenc for legacy fonts.")
    p.add_argument("--crop-top", type=float, default=0.0,
                   help="Crop fraction of page height from top.")
    p.add_argument("--crop-bottom", type=float, default=0.0,
                   help="Crop fraction of page height from bottom.")
    p.add_argument("--keep-page-numbers", action="store_true",
                   help="Keep the page-number line at the start of each page "
                        "instead of dropping it.")
    p.add_argument("--drop-boilerplate", action="store_true",
                   help="Drop non-Tibetan lines (URLs, English notes) instead "
                        "of collecting them at the top.")
    p.add_argument("--normalize", action="store_true",
                   help="Apply NFC/Tibetan normalization (default: off, raw).")
    p.add_argument("-j", "--jobs", type=int, default=1,
                   help="Parallel workers across PDFs (folder mode).")
    p.add_argument("-r", "--recursive", action="store_true",
                   help="Recurse into sub-folders (output stays flat).")
    p.add_argument("--overwrite", action="store_true",
                   help="Overwrite existing .txt files (default: skip).")
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    args = build_parser().parse_args(argv)

    in_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.output).expanduser().resolve()

    common = dict(
        backend=args.backend,
        crop_top=args.crop_top,
        crop_bottom=args.crop_bottom,
        keep_page_numbers=args.keep_page_numbers,
        keep_boilerplate=not args.drop_boilerplate,
        normalize=args.normalize,
        overwrite=args.overwrite,
    )

    if in_path.is_file():
        r = convert_pdf(in_path, out_dir, **common)
        if r.error.startswith("skipped"):
            logging.info("  - %s (%s)", r.pdf, r.error)
        elif r.ok:
            logging.info("  OK %s -> %s (%d pages, %.2fs)", r.pdf, r.txt, r.pages, r.seconds)
        else:
            logging.info("  XX %s FAILED: %s", r.pdf, r.error)
        return 0 if r.ok else 1

    if in_path.is_dir():
        results = convert_folder(
            in_path, out_dir, recursive=args.recursive, jobs=args.jobs, **common
        )
        return 0 if all(r.ok for r in results) else 1

    logging.error("Input not found: %s", in_path)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())