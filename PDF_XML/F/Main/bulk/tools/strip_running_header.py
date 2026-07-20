#!/usr/bin/env python3
"""
strip_running_header — auto-detect and remove a repeated running-header line
from a converted TEI-XML file.

Why this exists
----------------
Some source PDFs print a running header (book/section title) on every page,
sitting in a Y-band immediately above the body text -- but with no reliable
physical crop-top fraction that removes it everywhere without also clipping
real content: front-matter pages (title page, editorial note, table of
contents) often have no header/footer at all and their text can run right up
into the same Y-band the header occupies on body pages. Physically cropping
that band is therefore unsafe for the whole document.

This script sidesteps the geometry problem entirely by working on already-
extracted text: it looks at the first <lb/> line after every <pb/>, finds
the line that repeats near-identically across a large majority of pages
(the running header, by definition), and removes just that line -- wherever
it occurs, regardless of page geometry. Bare page-number footers are already
handled by convert_pdf_to_xml.py's strip_page_number_artifacts(); this
script complements that for non-numeric running headers/titles.

It correctly preserves <hi rend="..."> font-size spans that open on the
page *before* the header line and close *after* it (or vice versa) --
a header line is frequently marked small-font along with adjacent TOC/body
text, so naively deleting the line's own tags can leave an unbalanced span.

Some books alternate two different running headers on facing pages (a
verso/recto layout -- e.g. the book title on even pages, the publisher or
chapter name on odd pages). Each then repeats on only ~50% of pages, not
a clear majority on its own. This script accounts for that: instead of
only taking the single most frequent first-line, it strips *every* line
whose repetition frequency clears --min-frac, so both alternating headers
are removed in one pass.

Usage
-----
    python tools/strip_running_header.py IN.xml OUT.xml
    python tools/strip_running_header.py IN.xml OUT.xml --min-frac 0.4
    python tools/strip_running_header.py IN.xml OUT.xml --header "exact text"
    python tools/strip_running_header.py IN.xml OUT.xml --header "text one" --header "text two"
    python tools/strip_running_header.py IN.xml --in-place

Exit code: 0 if at least one header was found and stripped (or none needed
removing with --header), 1 if no line met the repetition threshold.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# First <lb/> line right after each <pb/>, optionally wrapped in <hi rend=...>.
_FIRST_LINE_RE = re.compile(r'<pb/>\s*\n<lb/>(?:<hi rend="[^"]*">)?([^\n<]+)')


def detect_running_headers(text: str, min_frac: float) -> list[tuple[str, int, int]]:
    """
    Return [(header_text, occurrences, total_pb), ...] for every first-line
    whose repetition frequency clears min_frac, most frequent first.

    Handles single running headers (one line dominant on nearly every page)
    as well as alternating verso/recto headers (two lines each covering
    roughly half the pages) -- both are legitimate boilerplate to strip.
    """
    matches = _FIRST_LINE_RE.findall(text)
    if not matches:
        return []
    total = len(matches)
    counts = Counter(matches)
    return [
        (line, freq, total)
        for line, freq in counts.most_common()
        if freq / total >= min_frac
    ]


def strip_header(text: str, header_text: str) -> tuple[str, int]:
    """
    Remove every occurrence of *header_text* as the first line after <pb/>,
    handling four tag configurations so <hi> spans stay balanced:

      A. <pb/>\\n<lb/><hi rend="x">HEADER</hi>\\n   -- self-contained, drop all
      B. <pb/>\\n<lb/>HEADER</hi>\\n                 -- opening tag was on the
                                                        previous page; keep the
                                                        close, drop the line
      C. <pb/>\\n<lb/>HEADER\\n                       -- no <hi> involved
      D. <pb/>\\n<lb/><hi rend="x">HEADER\\n          -- span continues past the
                                                        header; keep the open,
                                                        drop the line
    """
    esc = re.escape(header_text)
    total = 0

    text, n = re.subn(r'<pb/>\s*\n<lb/><hi rend="[^"]*">' + esc + r'</hi>\n', "<pb/>\n", text)
    total += n
    text, n = re.subn(r'<pb/>\s*\n<lb/>' + esc + r'</hi>\n', "<pb/>\n</hi>\n", text)
    total += n
    text, n = re.subn(r'(<pb/>\s*\n<lb/><hi rend="[^"]*">)' + esc + r'\n', r"\1", text)
    total += n
    text, n = re.subn(r'<pb/>\s*\n<lb/>' + esc + r'\n', "<pb/>\n", text)
    total += n

    return text, total


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path, nargs="?", help="Defaults to overwriting input with --in-place")
    p.add_argument("--in-place", action="store_true")
    p.add_argument(
        "--min-frac", type=float, default=0.4,
        help="Minimum fraction of pages a line must repeat on to count as a "
             "running header (default 0.4, low enough to catch alternating "
             "verso/recto headers that each cover ~50%% of pages without "
             "also catching one-off repeated body lines)",
    )
    p.add_argument(
        "--header", action="append", default=None,
        help="Skip auto-detection; strip this exact line instead. Repeatable "
             "for documents with more than one alternating running header.",
    )
    args = p.parse_args()

    if not args.in_place and not args.output:
        print("error: pass an OUTPUT path or --in-place", file=sys.stderr)
        return 2

    text = args.input.read_text(encoding="utf-8")

    if args.header:
        matches = _FIRST_LINE_RE.findall(text)
        headers = []
        for header_text in args.header:
            freq = sum(1 for m in matches if m == header_text)
            print(f"Using given header: {header_text!r} ({freq}/{len(matches)} pages)")
            headers.append(header_text)
    else:
        detected = detect_running_headers(text, args.min_frac)
        if not detected:
            print("No line repeats often enough to be a running header; nothing stripped.", file=sys.stderr)
            return 1
        headers = []
        for header_text, freq, total in detected:
            print(f"Auto-detected running header: {header_text!r} on {freq}/{total} pages ({freq/total:.1%})")
            headers.append(header_text)

    new_text = text
    total_stripped = 0
    for header_text in headers:
        new_text, n = strip_header(new_text, header_text)
        print(f"  stripped {n} occurrence(s) of {header_text!r}")
        total_stripped += n
    print(f"Stripped {total_stripped} occurrence(s) total across {len(headers)} header line(s).")

    try:
        ET.fromstring(new_text)
        print("Output is well-formed XML.")
    except ET.ParseError as e:
        print(f"WARNING: output is not well-formed XML: {e}", file=sys.stderr)

    out_path = args.input if args.in_place else args.output
    out_path.write_text(new_text, encoding="utf-8")
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
