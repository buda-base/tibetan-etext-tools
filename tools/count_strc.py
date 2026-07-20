#!/usr/bin/env python3
"""
Flatten IE_ID folder structure.

Before:
    main_folder/IE3KG193/to_convert/
    main_folder/IE3KG193/IE3KG193/archive/

After:
    main_folder/IE3KG193/archive/
Usage:
    python3 cnt_strc.py /path/to/main_folder
"""

import sys
import shutil
from pathlib import Path


def cnt_struct(ie_folder: Path) -> bool:
    """Process a single IE_ID folder. Returns True on success."""
    ie_id = ie_folder.name
    nested = ie_folder / ie_id
    to_convert = ie_folder / "to_convert"

    if not nested.is_dir():
        print(f"[SKIP] {ie_folder}: no nested '{ie_id}' folder found")
        return False

    # Files we can safely overwrite/ignore (macOS / system noise)
    IGNORE = {".DS_Store", "Thumbs.db", ".localized"}

    # Check for name collisions before moving anything (ignoring system files)
    existing = {
        p.name for p in ie_folder.iterdir()
        if p.name not in (ie_id, "to_convert") and p.name not in IGNORE
    }
    incoming = {p.name for p in nested.iterdir() if p.name not in IGNORE}
    collisions = existing & incoming
    if collisions:
        print(f"[ERROR] {ie_folder}: name collisions detected, refusing to overwrite: {sorted(collisions)}")
        return False

    # Move every item from nested IE_ID up one level.
    # For IGNORE files, remove any existing copy at the parent first so the move succeeds.
    moved = 0
    for item in list(nested.iterdir()):
        target = ie_folder / item.name
        if item.name in IGNORE and target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        shutil.move(str(item), str(target))
        moved += 1

    # Remove the now-empty nested folder
    nested.rmdir()
    print(f"[OK]   {ie_folder}: moved {moved} item(s) up, removed nested '{ie_id}'")

    # Delete to_convert if present
    if to_convert.exists():
        shutil.rmtree(to_convert)
        print(f"[OK]   {ie_folder}: deleted 'to_convert'")

    return True


def main():
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} /path/to/main_folder")
        sys.exit(1)

    main_folder = Path(sys.argv[1]).resolve()
    if not main_folder.is_dir():
        print(f"Error: {main_folder} is not a directory")
        sys.exit(1)

    ie_folders = [p for p in main_folder.iterdir() if p.is_dir()]
    if not ie_folders:
        print(f"No subfolders found in {main_folder}")
        return

    print(f"Processing {len(ie_folders)} folder(s) in {main_folder}\n")

    ok = 0
    failed = 0
    for ie_folder in sorted(ie_folders):
        try:
            if cnt_struct(ie_folder):
                ok += 1
            else:
                failed += 1
        except Exception as e:
            print(f"[ERROR] {ie_folder}: {e}")
            failed += 1

    print(f"\nDone. Success: {ok}, Failed/Skipped: {failed}")


if __name__ == "__main__":
    main()