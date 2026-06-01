#!/usr/bin/env python3
"""
batch_reorder_pecha.py — Recursively reorder every pecha PDF under a root and
replace each one in place.

You pass a root directory. It may contain many IE_ID folders; the script
recurses through all subfolders and processes every PDF it finds, e.g.:

    <root>/IE.../to_convert/VE.../*.pdf
    <root>/IE.../to_convert/VE.../*.pdf
    ...

For each PDF it runs the leaf-reordering logic from ``reorder_pecha.py`` and
replaces the original.  By default originals are OVERWRITTEN with no backup.

Safety
------
* Reordering is written to a temp file first; the original is only touched
  after the new file is successfully produced and sanity-checked.
* A PDF that does not look like the 3-up scrambled layout (no leaf numbers
  detected, or the reconstructed sequence has large gaps) is SKIPPED and the
  original is left untouched.  Every decision is recorded in a report CSV.
* --dry-run performs all analysis and writes the report, but changes nothing.
* A live run with the default (no backup) asks for confirmation once; use
  --yes to skip the prompt for scripted runs.

Usage
-----
    # dry run first — review the report, changes nothing
    python batch_reorder_pecha.py /path/to/root --dry-run

    # real run: overwrite in place, no backup (default); prompts once
    python batch_reorder_pecha.py /path/to/root

    # scripted real run, no prompt
    python batch_reorder_pecha.py /path/to/root --yes

    # keep copies instead of overwriting
    python batch_reorder_pecha.py /path/to/root --backup-mode folder

Requires reorder_pecha.py (and PyMuPDF) importable from the same directory.
"""
from __future__ import annotations

import argparse
import csv
import shutil
import sys
import tempfile
import time
from pathlib import Path

import fitz  # PyMuPDF

import reorder_pecha as rp


# ─── Conformance thresholds ────────────────────────────────────────────────
# A PDF is treated as a valid 3-up scrambled pecha only if it clears these.
MIN_LEAVES = 2                 # need at least this many numbered leaves
MAX_GAP_FRACTION = 0.05        # >5% missing numbers in 1..max ⇒ suspicious
# ────────────────────────────────────────────────────────────────────────────


def assess_pdf(pdf_path: Path):
    """
    Analyze one PDF. Returns a dict describing whether it conforms and what the
    reconstructed order is.
    """
    info = {
        "path": str(pdf_path),
        "conforms": False,
        "reason": "",
        "n_leaves": 0,
        "min_num": None,
        "max_num": None,
        "n_gaps": 0,
        "n_dupes": 0,
        "n_pages_src": 0,
        "ordered": None,
        "per_page": None,
    }
    try:
        with fitz.open(str(pdf_path)) as d:
            info["n_pages_src"] = d.page_count
    except Exception as e:
        info["reason"] = f"cannot open: {e}"
        return info

    try:
        ordered, per_page, warnings = rp.build_order(pdf_path, verbose=False)
    except Exception as e:
        info["reason"] = f"analysis error: {e}"
        return info

    nums = [n for n, _, _ in ordered]
    info["n_leaves"] = len(ordered)
    info["ordered"] = ordered
    info["per_page"] = per_page
    info["n_dupes"] = sum(1 for w in warnings if "overlap-duplicate" in w)

    if not nums:
        info["reason"] = "no leaf numbers detected"
        return info

    info["min_num"], info["max_num"] = min(nums), max(nums)
    span = info["max_num"] - info["min_num"] + 1
    gaps = span - len(set(nums))
    info["n_gaps"] = gaps

    if len(ordered) < MIN_LEAVES:
        info["reason"] = f"too few leaves ({len(ordered)})"
        return info
    if span > 0 and gaps / span > MAX_GAP_FRACTION:
        info["reason"] = f"{gaps}/{span} numbers missing (>{MAX_GAP_FRACTION:.0%})"
        return info

    info["conforms"] = True
    info["reason"] = "ok"
    return info


def backup_original(pdf_path: Path, root: Path, mode: str) -> Path | None:
    """Preserve the original according to mode. Returns the backup path (or None)."""
    if mode == "none":
        return None
    if mode == "sibling":
        bak = pdf_path.with_suffix(pdf_path.suffix + ".bak")
        # don't clobber an existing backup
        if bak.exists():
            bak = pdf_path.with_suffix(pdf_path.suffix + f".{int(time.time())}.bak")
        shutil.copy2(pdf_path, bak)
        return bak
    if mode == "folder":
        # mirror the tree under <root>/../_pre_reorder_backup/
        backup_root = root.parent / f"{root.name}_pre_reorder_backup"
        rel = pdf_path.relative_to(root)
        dest = backup_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_suffix(dest.suffix + f".{int(time.time())}.bak")
        shutil.copy2(pdf_path, dest)
        return dest
    raise ValueError(f"unknown backup mode: {mode}")


def reorder_in_place(pdf_path: Path, info: dict, root: Path, backup_mode: str) -> tuple[bool, str]:
    """
    Write the reordered PDF to a temp file, sanity-check it, back up the
    original, then atomically replace. Returns (ok, message).
    """
    ordered = info["ordered"]
    per_page = info["per_page"]
    expected_pages = len(ordered)

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".pdf", dir=str(pdf_path.parent))
    tmp_path = Path(tmp_name)
    import os
    os.close(tmp_fd)
    try:
        rp.write_reordered_pdf(pdf_path, tmp_path, ordered, per_page)

        # sanity-check the output
        with fitz.open(str(tmp_path)) as chk:
            if chk.page_count != expected_pages:
                return False, f"page count mismatch (got {chk.page_count}, expected {expected_pages})"
            if chk.page_count == 0:
                return False, "produced empty PDF"

        bak = backup_original(pdf_path, root, backup_mode)
        os.replace(tmp_path, pdf_path)  # atomic on same filesystem
        msg = "replaced"
        if bak is not None:
            msg += f" (backup: {bak})"
        return True, msg
    except Exception as e:
        return False, f"reorder failed: {e}"
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser(description="Recursively reorder pecha PDFs and replace in place.")
    ap.add_argument("root", type=Path,
                    help="Root folder to walk. May contain many IE_ID folders; the script "
                         "recurses into every subfolder (e.g. IE_ID/to_convert/VE_ID/*.pdf).")
    ap.add_argument("--backup-mode", choices=["none", "folder", "sibling"], default="none",
                    help="How to preserve originals (default: none = overwrite in place, no backup). "
                         "Use 'folder' to mirror the tree into a backup dir, or 'sibling' for .bak files.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Analyze and report only; do not write or replace anything.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the confirmation prompt for a live no-backup run (for scripted use).")
    ap.add_argument("--report", type=Path, default=None,
                    help="Path for the CSV report (default: <root>/reorder_report.csv).")
    ap.add_argument("--glob", default="*.pdf",
                    help="Filename pattern to match (default: *.pdf).")
    args = ap.parse_args()

    root = args.root.resolve()
    if not root.exists():
        print(f"ERROR: root does not exist: {root}", file=sys.stderr)
        sys.exit(1)
    if not root.is_dir():
        print(f"ERROR: root is not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    pdfs = sorted(p for p in root.rglob(args.glob) if p.is_file()
                  and not p.name.endswith(".bak"))
    if not pdfs:
        print(f"No PDFs matching {args.glob!r} found under {root}")
        sys.exit(0)

    report_path = args.report or (root / "reorder_report.csv")
    print(f"Root:        {root}")
    print(f"PDFs found:  {len(pdfs)}")
    print(f"Backup mode: {args.backup_mode}")
    print(f"Mode:        {'DRY RUN (no changes)' if args.dry_run else 'LIVE (will replace in place)'}")
    print(f"Report:      {report_path}\n")

    # Destructive-run guard: live + no backup means originals are gone for good.
    if not args.dry_run and args.backup_mode == "none" and not args.yes:
        print("WARNING: backup-mode is 'none' — originals will be OVERWRITTEN with no backup.")
        print("         Run with --dry-run first to review reorder_report.csv, or pass")
        print("         --backup-mode folder to keep copies. To proceed now, type 'yes'.")
        try:
            resp = input("Proceed with in-place overwrite? [yes/N] ").strip().lower()
        except EOFError:
            resp = ""
        if resp != "yes":
            print("Aborted. Nothing was changed.")
            sys.exit(0)
        print()

    rows = []
    n_ok = n_skip = n_fail = 0
    for i, pdf in enumerate(pdfs, 1):
        rel = pdf.relative_to(root)
        info = assess_pdf(pdf)
        status = ""
        detail = info["reason"]

        if not info["conforms"]:
            status = "SKIP"
            n_skip += 1
        elif args.dry_run:
            status = "WOULD_REORDER"
            n_ok += 1
        else:
            ok, msg = reorder_in_place(pdf, info, root, args.backup_mode)
            if ok:
                status = "REORDERED"
                detail = msg
                n_ok += 1
            else:
                status = "FAIL"
                detail = msg
                n_fail += 1

        print(f"[{i}/{len(pdfs)}] {status:14} {rel}  "
              f"(leaves={info['n_leaves']}, range={info['min_num']}..{info['max_num']}, "
              f"gaps={info['n_gaps']}, dupes={info['n_dupes']})  {detail}")

        rows.append({
            "relpath": str(rel),
            "status": status,
            "detail": detail,
            "src_pages": info["n_pages_src"],
            "out_leaves": info["n_leaves"],
            "min_num": info["min_num"],
            "max_num": info["max_num"],
            "gaps": info["n_gaps"],
            "dupes": info["n_dupes"],
        })

    with open(report_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    print(f"\nSummary: {n_ok} reordered/would-reorder, {n_skip} skipped, {n_fail} failed.")
    print(f"Report written to {report_path}")
    if n_skip and not args.dry_run:
        print("Skipped files were NOT modified — review the report before re-running.")


if __name__ == "__main__":
    main()