"""
Convert legacy .doc files to .docx using Microsoft Word COM automation.

Input structure:
  {IE_ID}/toprocess/{IE_ID-VE_ID}/*.doc

Output:
  Saves .docx next to each source file (same folder, same base name).

Example:
  python doc_docx/convert.py --root "D:/data"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

try:
    from comtypes import COMError, CoInitialize, CoUninitialize
    import comtypes.client
    COMTYPES_AVAILABLE = True
except ModuleNotFoundError:
    COMTYPES_AVAILABLE = False
    COMError = Exception  # type: ignore[assignment]


# Word save format constant for .docx
# Equivalent to wdFormatDocumentDefault
WD_FORMAT_DOCX = 16


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert all .doc files to .docx under {IE_ID}/toprocess/{IE_ID-VE_ID}."
    )
    parser.add_argument(
        "--root",
        default=".",
        help="Root directory containing IE_ID folders (default: current directory).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing .docx files if they already exist.",
    )
    return parser.parse_args()


def discover_doc_files(root: Path) -> List[Path]:
    """
    Find .doc files in this shape:
      root/{IE_ID}/toprocess/{IE_ID-VE_ID}/*.doc
    """
    docs: List[Path] = []
    if not root.exists():
        return docs

    # Support both:
    # 1) root = parent directory containing many IE_ID folders
    # 2) root = one IE_ID folder
    # We still match the expected shape: */toprocess/*/*.doc
    for path in root.glob("**/toprocess/*/*.doc"):
        if path.is_file():
            docs.append(path)
    docs.sort()
    return docs


def likely_open_in_word(doc_path: Path) -> bool:
    """
    Heuristic: Word usually creates a lock file named '~$<filename>.doc'
    in the same folder while the document is open.
    """
    lock_name = f"~${doc_path.name}"
    lock_path = doc_path.with_name(lock_name)
    return lock_path.exists()


def classify_com_error(err: COMError, doc_path: Path) -> str:
    message = str(err).lower()
    if likely_open_in_word(doc_path):
        return "open_or_locked"
    if any(token in message for token in ("cannot access", "permission", "denied", "locked")):
        return "open_or_locked"
    if any(token in message for token in ("corrupt", "damaged", "unreadable", "cannot open")):
        return "corrupted"
    return "failed"


def convert_doc_to_docx(word_app, src: Path, dst: Path) -> None:
    doc = None
    try:
        doc = word_app.Documents.Open(
            str(src.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            Visible=False,
            OpenAndRepair=True,
            NoEncodingDialog=True,
        )
        doc.SaveAs2(str(dst.resolve()), FileFormat=WD_FORMAT_DOCX)
    finally:
        if doc is not None:
            doc.Close(SaveChanges=False)


def run_conversion(root: Path, overwrite: bool) -> int:
    docs = discover_doc_files(root)
    total = len(docs)

    if total == 0:
        print(f"No .doc files found under: {root}")
        print("Expected pattern: {IE_ID}/toprocess/{IE_ID-VE_ID}/*.doc")
        return 0

    print(f"Found {total} .doc file(s) to process.")

    stats: Dict[str, int] = {
        "converted": 0,
        "skipped_exists": 0,
        "open_or_locked": 0,
        "corrupted": 0,
        "failed": 0,
    }

    CoInitialize()
    word = None
    try:
        word = comtypes.client.CreateObject("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0  # Suppress popups for batch mode.

        for index, src in enumerate(docs, start=1):
            dst = src.with_suffix(".docx")
            progress = f"[{index}/{total}]"

            if dst.exists() and not overwrite:
                print(f"{progress} SKIP  {src} -> {dst} (already exists)")
                stats["skipped_exists"] += 1
                continue

            if likely_open_in_word(src):
                print(f"{progress} ERROR {src} (file appears open in Word)")
                stats["open_or_locked"] += 1
                continue

            try:
                convert_doc_to_docx(word, src, dst)
                print(f"{progress} OK    {src} -> {dst}")
                stats["converted"] += 1
            except COMError as err:
                category = classify_com_error(err, src)
                stats[category] += 1
                print(f"{progress} ERROR {src} ({category}): {err}")
            except Exception as err:  # noqa: BLE001
                stats["failed"] += 1
                print(f"{progress} ERROR {src} (failed): {err}")
    finally:
        try:
            if word is not None:
                word.Quit()
        finally:
            CoUninitialize()

    print("\nDone.")
    print(f"Converted     : {stats['converted']}")
    print(f"Skipped exists: {stats['skipped_exists']}")
    print(f"Open/locked   : {stats['open_or_locked']}")
    print(f"Corrupted     : {stats['corrupted']}")
    print(f"Failed        : {stats['failed']}")

    # Non-zero exit code only when failures occurred.
    return 1 if (stats["open_or_locked"] + stats["corrupted"] + stats["failed"]) > 0 else 0


def main() -> int:
    if not COMTYPES_AVAILABLE:
        print("Missing dependency: comtypes")
        print("Install it with:")
        print("  python -m pip install comtypes")
        return 2

    args = parse_args()
    root = Path(args.root).resolve()
    return run_conversion(root=root, overwrite=args.overwrite)


if __name__ == "__main__":
    sys.exit(main())
