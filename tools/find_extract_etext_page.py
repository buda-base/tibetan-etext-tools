#!/usr/bin/env python3
"""
Recursively scan a folder tree of BDRC-style archival etexts and find the
specific etext-unit XML page(s) matching given file details, then report
and optionally extract them.

Folder/file naming convention (see ../README.md and the BDRC archival
format docs referenced from REDME.md):

    <IE-id>/.../archive/VE<id>/UT<id>_<NNNN>.xml

  - IE  = etext instance   (e.g. IE3KG218)
  - VE  = etext volume     (e.g. VE1ER123)
  - UT  = etext unit/page  (e.g. UT1ALS00415M_0001)  <- one XML file per page

Each page XML has a TEI teiHeader with <idno> elements identifying it:
    <idno type="src_path">...</idno>          original source file path/name
    <idno type="src_sha256">...</idno>        sha256 of the original source file
    <idno type="bdrc_ie">.../IE.../</idno>
    <idno type="bdrc_ve">.../VE.../</idno>
    <idno type="bdrc_ut">.../UT.../</idno>

This script lets you locate the page XML(s) that correspond to a particular
source file (by name, path substring, or sha256), a particular BDRC
identifier (IE/VE/UT), a particular page number, or any free-text/regex
match -- any combination of filters may be combined (AND).

Examples
--------
# Which archive page(s) came from this original source file?
python find_extract_etext_page.py /path/to/archive --src-path-contains "KAMA-001.rtf"

# Find by exact sha256 of a source file
python find_extract_etext_page.py /path/to/archive --sha256 1f2e3a...

# Find a specific page of a specific etext unit
python find_extract_etext_page.py /path/to/archive --ut UT1KG12980 --page 1

# Find all pages of a volume and copy them out
python find_extract_etext_page.py /path/to/archive --ve VE1KG12980 --extract-dir ./out

# Generic regex search across filenames + header content
python find_extract_etext_page.py /path/to/archive --regex "KAMA-00[12]"

# Write a CSV report of all matches
python find_extract_etext_page.py /path/to/archive --ie IE3KG218 --csv matches.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Matches files like UT1ALS00415M_0001.xml -> ut_id="UT1ALS00415M", page=1
UT_FILENAME_RE = re.compile(r"^(?P<ut_id>UT[^_]+(?:_[^_]+)*?)_(?P<page>\d+)$", re.IGNORECASE)
# Fallback for filenames without a UT prefix but ending in _NNNN
PAGE_SUFFIX_RE = re.compile(r"_(?P<page>\d+)$")
IDNO_RE = re.compile(r'<idno\s+type="([^"]+)"\s*>([^<]*)</idno>', re.IGNORECASE)
TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)


@dataclass
class PageRecord:
    xml_path: Path
    ut_id: str | None = None
    ve_id: str | None = None
    page_num: int | None = None
    title: str = ""
    idno: dict = field(default_factory=dict)
    raw_text: str = ""

    @property
    def ie_idno(self) -> str:
        return self._strip_url(self.idno.get("bdrc_ie", ""))

    @property
    def ve_idno(self) -> str:
        return self._strip_url(self.idno.get("bdrc_ve", ""))

    @property
    def ut_idno(self) -> str:
        return self._strip_url(self.idno.get("bdrc_ut", ""))

    @staticmethod
    def _strip_url(value: str) -> str:
        return value.rsplit("/", 1)[-1] if value else value

    def haystack(self) -> str:
        """Everything searchable by a generic --regex match."""
        parts = [str(self.xml_path), self.title, *self.idno.values()]
        return "\n".join(parts)


def parse_page_xml(path: Path) -> PageRecord:
    """Lightweight parse: pull header fields with regex (robust to slightly
    malformed XML, which is common in OCR-derived intermediate files)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"Warning: could not read {path}: {exc}", file=sys.stderr)
        text = ""

    rec = PageRecord(xml_path=path, raw_text=text)

    for m in IDNO_RE.finditer(text):
        rec.idno[m.group(1).strip()] = m.group(2).strip()

    tmatch = TITLE_RE.search(text)
    if tmatch:
        rec.title = tmatch.group(1).strip()

    # Derive UT id / page number from the filename, per the archive
    # naming convention (UT<id>_<NNNN>.xml). Fall back to the bdrc_ut idno.
    stem = path.stem
    fmatch = UT_FILENAME_RE.match(stem)
    if fmatch:
        rec.ut_id = fmatch.group("ut_id").upper()
        rec.page_num = int(fmatch.group("page"))
    else:
        rec.ut_id = rec.ut_idno or None
        pmatch = PAGE_SUFFIX_RE.search(stem)
        if pmatch:
            rec.page_num = int(pmatch.group("page"))

    # Derive VE id from an ancestor folder named VE<id>, per convention.
    for part in path.parts:
        if re.match(r"^VE[\w-]+$", part, re.IGNORECASE):
            rec.ve_id = part
            break

    return rec


def iter_xml_files(root: Path):
    for path in sorted(root.rglob("*.xml")):
        if path.is_file():
            yield path


def page_in_ranges(page: int | None, ranges: list[tuple[int, int]]) -> bool:
    if page is None:
        return False
    return any(lo <= page <= hi for lo, hi in ranges)


def parse_page_arg(values: list[str]) -> list[tuple[int, int]]:
    ranges = []
    for v in values:
        if "-" in v:
            lo_s, hi_s = v.split("-", 1)
            ranges.append((int(lo_s), int(hi_s)))
        else:
            n = int(v)
            ranges.append((n, n))
    return ranges


def record_matches(rec: PageRecord, args) -> bool:
    if args.ut and (rec.ut_id or "").upper() not in {u.upper() for u in args.ut}:
        return False
    if args.ve and (rec.ve_id or "").upper() not in {v.upper() for v in args.ve}:
        return False
    if args.ie and rec.ie_idno.upper() not in {i.upper() for i in args.ie}:
        return False
    if args.page_ranges and not page_in_ranges(rec.page_num, args.page_ranges):
        return False
    if args.src_path_contains and args.src_path_contains.lower() not in rec.idno.get("src_path", "").lower():
        return False
    if args.sha256 and rec.idno.get("src_sha256", "").lower() != args.sha256.lower():
        return False
    if args.filename_regex and not re.search(args.filename_regex, rec.xml_path.name, re.IGNORECASE):
        return False
    if args.regex and not re.search(args.regex, rec.haystack(), re.IGNORECASE):
        return False
    return True


def extract_page(rec: PageRecord, extract_dir: Path) -> Path:
    """Copy the matched page XML into extract_dir, named per the archive
    convention so the output stays self-describing."""
    extract_dir.mkdir(parents=True, exist_ok=True)
    if rec.ut_id and rec.page_num is not None:
        out_name = f"{rec.ut_id}_{rec.page_num:04d}.xml"
    else:
        out_name = rec.xml_path.name
    out_path = extract_dir / out_name
    shutil.copy2(rec.xml_path, out_path)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find BDRC archival etext page XML(s) by file details and optionally extract them.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("root", type=Path, help="Root folder to scan recursively")

    parser.add_argument("--ut", action="append", default=[], metavar="UT_ID",
                         help="Match this UT (etext unit) id (repeatable)")
    parser.add_argument("--ve", action="append", default=[], metavar="VE_ID",
                         help="Match this VE (etext volume) id / folder name (repeatable)")
    parser.add_argument("--ie", action="append", default=[], metavar="IE_ID",
                         help="Match this IE (etext instance) bdrc_ie idno (repeatable)")
    parser.add_argument("--page", action="append", default=[], metavar="N|N-M",
                         help="Match this page number or range, e.g. 3 or 1-10 (repeatable)")
    parser.add_argument("--src-path-contains", metavar="TEXT",
                         help="Substring match against the <idno type=\"src_path\"> value")
    parser.add_argument("--sha256", metavar="HEX",
                         help="Exact match against the <idno type=\"src_sha256\"> value")
    parser.add_argument("--filename-regex", metavar="PATTERN",
                         help="Regex match against the XML filename only")
    parser.add_argument("--regex", metavar="PATTERN",
                         help="Regex match against path + title + all idno values")

    parser.add_argument("--csv", type=Path, metavar="PATH",
                         help="Write a CSV report of all matches")
    parser.add_argument("--extract-dir", type=Path, metavar="PATH",
                         help="Copy each matched page XML into this folder")
    parser.add_argument("-q", "--quiet", action="store_true",
                         help="Suppress per-match stdout lines (still writes --csv/--extract-dir)")

    args = parser.parse_args()
    args.page_ranges = parse_page_arg(args.page) if args.page else []

    if not args.root.is_dir():
        raise SystemExit(f"Not a directory: {args.root}")

    if not any([args.ut, args.ve, args.ie, args.page_ranges, args.src_path_contains,
                args.sha256, args.filename_regex, args.regex]):
        raise SystemExit("No search criteria given. Provide at least one of: "
                          "--ut/--ve/--ie/--page/--src-path-contains/--sha256/"
                          "--filename-regex/--regex")

    matches: list[PageRecord] = []
    for xml_path in iter_xml_files(args.root):
        rec = parse_page_xml(xml_path)
        if record_matches(rec, args):
            matches.append(rec)
            if not args.quiet:
                print(f"{rec.xml_path}  [ut={rec.ut_id or '-'} ve={rec.ve_id or '-'} "
                      f"page={rec.page_num if rec.page_num is not None else '-'}]")

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["xml_path", "ut_id", "ve_id", "page_num", "title",
                              "src_path", "src_sha256", "bdrc_ie", "bdrc_ve", "bdrc_ut"])
            for rec in matches:
                writer.writerow([
                    str(rec.xml_path), rec.ut_id or "", rec.ve_id or "",
                    rec.page_num if rec.page_num is not None else "",
                    rec.title, rec.idno.get("src_path", ""), rec.idno.get("src_sha256", ""),
                    rec.idno.get("bdrc_ie", ""), rec.idno.get("bdrc_ve", ""), rec.idno.get("bdrc_ut", ""),
                ])
        print(f"CSV report written: {args.csv} ({len(matches)} rows)")

    if args.extract_dir:
        for rec in matches:
            out_path = extract_page(rec, args.extract_dir)
            if not args.quiet:
                print(f"  -> extracted: {out_path}")

    print(f"Total matches: {len(matches)}")


if __name__ == "__main__":
    main()
