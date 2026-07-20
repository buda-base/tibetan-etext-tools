#!/usr/bin/env python3
"""
batch_pdf_to_xml.py — batch-convert a folder tree of loose PDFs into TEI XML.

Unlike pdf_to_xml.py (which is tailored to a single BUDA workset with VE/UT
IDs and a sources/ layout), this script walks an arbitrary folder tree, finds
every *.pdf (including *.patched.pdf), and converts each one INDEPENDENTLY into
its own TEI XML file, mirroring the input folder structure under the output
root.

It reuses the proven conversion core from pdf_to_xml.py:
    extract -> clean artifacts -> simplify font sizes -> normalize unicode
    -> classify font sizes -> font markup -> TEI body -> TEI document

Usage:
    python batch_pdf_to_xml.py <input_root> [output_root]

    # default output_root is <input_root>/_XML_OUTPUT
    python batch_pdf_to_xml.py /path/to/downloads_fixed

Resume:
    Re-running skips any PDF already attempted (tracked in
    <output_root>/_processed.txt) or already written. Set env var
    BATCH_MAX_SECONDS to stop cleanly after N seconds (then re-run to continue).
"""

from __future__ import annotations

import os
import sys
import csv
import re
import time
from pathlib import Path

# Reuse the conversion core from the sibling module.
sys.path.insert(0, str(Path(__file__).parent))
import pdf_to_xml as P  # noqa: E402

OUTPUT_DIRNAME = "_XML_OUTPUT"
_TIB_RE = re.compile(r"[ༀ-࿿]")


def find_pdfs(input_root: Path, output_root: Path) -> list[Path]:
    """Recursively collect every PDF under input_root, skipping the output dir."""
    pdfs = []
    for p in input_root.rglob("*.pdf"):
        try:
            p.relative_to(output_root)
            continue
        except ValueError:
            pass
        if p.is_file():
            pdfs.append(p)
    return sorted(pdfs, key=lambda x: str(x).lower())


def make_header(pdf_file: Path, title: str = "XXX") -> str:
    """A generic TEI header (no BDRC VE/UT idnos — these are loose PDFs)."""
    sha256 = P.calculate_sha256(pdf_file)
    return (
        "<teiHeader>\n"
        "<fileDesc>\n"
        "<titleStmt>\n"
        f"<title>{P.escape_xml(title)}</title>\n"
        "</titleStmt>\n"
        "<publicationStmt>\n"
        "<p>TEI generated from a PDF by batch_pdf_to_xml.py.</p>\n"
        "</publicationStmt>\n"
        "<sourceDesc>\n"
        "<bibl>\n"
        f"<idno type=\"src_path\">{P.escape_xml(pdf_file.name)}</idno>\n"
        f"<idno type=\"src_sha256\">{sha256}</idno>\n"
        "</bibl>\n"
        "</sourceDesc>\n"
        "</fileDesc>\n"
        "</teiHeader>"
    )


def pdf_to_tei(pdf_file: Path) -> tuple[str, int]:
    """Run the full pipeline on one PDF. Returns (tei_document, tib_char_count)."""
    raw_text = P.extract_pdf_to_text(pdf_file)
    if not raw_text:
        return "", 0

    raw_text = P.remove_standalone_yigmgo(raw_text)
    raw_text = P.remove_artifact_line(raw_text)
    text = P.remove_indesign_artifacts(raw_text)
    text = P.remove_headers_footers(text)

    simplified = P.simplify_font_sizes(text)
    normalized = P.normalize_text(simplified)

    classifications = P.classify_font_sizes(normalized)
    marked = P.apply_font_markup(normalized, classifications)

    tei_body = P.convert_markup_to_tei(marked)
    header = make_header(pdf_file)
    document = P.generate_tei_document(tei_body, header)

    tib_chars = len(_TIB_RE.findall(normalized))
    return document, tib_chars


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <input_root> [output_root]")
        return 1

    input_root = Path(sys.argv[1]).resolve()
    if not input_root.is_dir():
        print(f"ERROR: input_root is not a directory: {input_root}")
        return 1

    if len(sys.argv) >= 3:
        output_root = Path(sys.argv[2]).resolve()
    else:
        output_root = input_root / OUTPUT_DIRNAME
    output_root.mkdir(parents=True, exist_ok=True)

    pdfs = find_pdfs(input_root, output_root)
    print(f"Found {len(pdfs)} PDF(s) under {input_root}")
    print(f"Output root: {output_root}\n", flush=True)

    processed_log = output_root / "_processed.txt"
    processed = set()
    if processed_log.exists():
        processed = set(processed_log.read_text(encoding="utf-8").splitlines())
    plog = open(processed_log, "a", encoding="utf-8")

    report_rows = []
    ok = empty = failed = 0

    budget = float(os.environ.get("BATCH_MAX_SECONDS", "0"))
    start = time.time()

    for i, pdf in enumerate(pdfs, 1):
        if budget and (time.time() - start) > budget:
            print(f"-- time budget {budget}s reached; stopping (resume to continue) --", flush=True)
            break

        rel = pdf.relative_to(input_root)
        out_path = (output_root / rel).with_suffix(".xml")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if str(rel) in processed or (out_path.exists() and out_path.stat().st_size > 0):
            continue

        print(f"[{i}/{len(pdfs)}] {rel}", flush=True)

        status = "ok"
        tib_chars = 0
        try:
            document, tib_chars = pdf_to_tei(pdf)
            if not document or tib_chars == 0:
                status = "empty_or_no_tibetan"
                empty += 1
            else:
                ok += 1
            if document and tib_chars > 0:
                out_path.write_text(document, encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            status = f"error: {e}"
            failed += 1
            print(f"    ERROR: {e}", flush=True)

        report_rows.append({
            "input_pdf": str(rel),
            "output_xml": str(out_path.relative_to(output_root)) if out_path.exists() else "",
            "tibetan_chars": tib_chars,
            "status": status,
        })
        plog.write(str(rel) + "\n")
        plog.flush()

    plog.close()

    # Append this run's rows to a persistent CSV report.
    report_path = output_root / "_conversion_report.csv"
    write_header = not report_path.exists()
    with open(report_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["input_pdf", "output_xml", "tibetan_chars", "status"]
        )
        if write_header:
            writer.writeheader()
        writer.writerows(report_rows)

    print(f"\n{'=' * 60}")
    print(f"This run: {ok} ok, {empty} empty/no-tibetan, {failed} failed")
    print(f"Report: {report_path}")
    print(f"{'=' * 60}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
