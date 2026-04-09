#!/usr/bin/env python3
"""
Run ``convert_pdf_to_xml.py`` for many workset folders under one parent directory.

Layout (each direct child named like ``IE1KG25273``)::

    ROOT/
      IE1KG25273/sources/, IE1KG25273/toprocess/
      IE2KG209991/sources/, ...
      → output: ROOT/IE1KG25273_output/, ROOT/IE2KG209991_output/, ...

Each worker process sets ``PDF_BULK_BASE_DIR`` and ``PDF_BULK_IE_ID`` so ``config.py``
picks the right paths. Checkpoints and logs are under ``ROOT/checkpoints/<IE_ID>/`` and
``ROOT/logs/<IE_ID>/``.

Examples::

    python bulk_multi_ie.py -r /path/to/parent
    python bulk_multi_ie.py -r /path/to/parent -j 4
    python bulk_multi_ie.py -r /path/to/parent --ie IE1KG25273 --ie IE2KG209991
    python bulk_multi_ie.py -r /path/to/parent -- --extractor pytiblegenc --no-font-tags

Any arguments after ``--`` are forwarded to ``convert_pdf_to_xml.py`` (batch mode).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path
from typing import Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONVERT = _SCRIPT_DIR / "convert_pdf_to_xml.py"

# BUDA-style image group folders: IE + digits/letters (e.g. IE1KG25273).
_IE_NAME_RE = re.compile(r"^IE[A-Z0-9]+$", re.IGNORECASE)


def discover_ie_dirs(root: Path, only: Sequence[str] | None) -> list[Path]:
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    want_cf = {x.strip().casefold() for x in only} if only else None
    out: list[Path] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir():
            continue
        if not _IE_NAME_RE.match(child.name):
            continue
        if want_cf is not None and child.name.casefold() not in want_cf:
            continue
        src = child / "sources"
        if not src.is_dir():
            continue
        out.append(child)
    return out


def _run_one(payload: tuple[str, str, list[str]]) -> tuple[str, int, str]:
    """Run conversion for one IE; module-level for pickling on some platforms."""
    root_s, ie_id, forward_args = payload
    env = os.environ.copy()
    env["PDF_BULK_BASE_DIR"] = root_s
    env["PDF_BULK_IE_ID"] = ie_id
    cmd = [sys.executable, str(_CONVERT), *forward_args]
    proc = subprocess.run(
        cmd,
        env=env,
        cwd=str(_SCRIPT_DIR),
        capture_output=True,
        text=True,
    )
    tail = ""
    if proc.stdout:
        lines = proc.stdout.strip().splitlines()
        tail = "\n".join(lines[-40:]) if len(lines) > 40 else proc.stdout.strip()
    if proc.stderr and proc.returncode != 0:
        err = proc.stderr.strip()
        tail = (tail + "\n--- stderr ---\n" + err) if tail else err
    rc = proc.returncode if proc.returncode is not None else -1
    return ie_id, rc, tail


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-run PDF→TEI for every IE*/ folder under a parent (multiprocessing). "
            "Forward extras after -- to convert_pdf_to_xml.py."
        )
    )
    parser.add_argument(
        "-r",
        "--root",
        type=Path,
        required=True,
        help="Parent directory containing IE1KG25273/, IE2KG…/, each with sources/",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="Parallel worker processes (default: min(CPU count, 8))",
    )
    parser.add_argument(
        "--ie",
        action="append",
        dest="ie_only",
        metavar="IE_ID",
        help="Process only this folder name (repeatable). Default: all matching IE*/ with sources/",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List IE folders that would run, without converting",
    )
    args, forward = parser.parse_known_args()

    if "--" in forward:
        idx = forward.index("--")
        forward = forward[idx + 1 :]

    try:
        ie_dirs = discover_ie_dirs(args.root, args.ie_only)
    except NotADirectoryError as e:
        print(e, file=sys.stderr)
        return 2

    if not ie_dirs:
        print(
            f"No IE worksets under {args.root.resolve()!s} "
            "(need direct children matching IE… with a sources/ directory).",
            file=sys.stderr,
        )
        return 1

    root_s = str(args.root.resolve())
    print(f"Root: {root_s}")
    print(f"Worksets ({len(ie_dirs)}): " + ", ".join(p.name for p in ie_dirs))

    if args.dry_run:
        return 0

    if not _CONVERT.is_file():
        print(f"Missing converter: {_CONVERT}", file=sys.stderr)
        return 2

    ncpu = os.cpu_count() or 1
    jobs = args.jobs if args.jobs is not None else min(ncpu, 8)
    if jobs < 1:
        jobs = 1

    payloads = [(root_s, p.name, forward) for p in ie_dirs]

    failures: list[tuple[str, int, str]] = []
    if jobs == 1:
        for pl in payloads:
            ie_id, rc, tail = _run_one(pl)
            print(f"\n========== {ie_id} (exit {rc}) ==========")
            if tail:
                print(tail)
            if rc != 0:
                failures.append((ie_id, rc, tail))
    else:
        with Pool(processes=jobs) as pool:
            for ie_id, rc, tail in pool.imap_unordered(_run_one, payloads):
                print(f"\n========== {ie_id} (exit {rc}) ==========")
                if tail:
                    print(tail)
                if rc != 0:
                    failures.append((ie_id, rc, tail))

    print("\n" + "=" * 60)
    if failures:
        print(f"Finished with {len(failures)} failure(s): " + ", ".join(f[0] for f in failures))
        return 1
    print("All worksets completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())