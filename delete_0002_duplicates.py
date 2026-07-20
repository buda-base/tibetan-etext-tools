#!/usr/bin/env python3
"""
Recursively find archive/VE_ID groups that contain exactly two files
(e.g. UT1ER2118_0001.xxx and UT1ER2118_0002.xxx) and delete the "_0002" one.

Usage:
    python delete_0002_duplicates.py "D:\\monlam_dharmaduta\\task\\archive_filtered_pdf\\IE3CN26447_output"
    python delete_0002_duplicates.py "<path>" --execute   # actually delete (default is dry-run)

By default this is a DRY RUN: it only prints what would be deleted.
Pass --execute to actually delete the files.
"""

import argparse
import os
import re
from collections import defaultdict

# Matches: <base_id>_<4-digit-number><extension>
PATTERN = re.compile(r'^(?P<base>.+)_(?P<num>\d{4})(?P<ext>\.[^.]+)$')


def find_targets(root):
    """
    Walk root recursively. Within each directory, group files by base_id
    (part before the _NNNN suffix). For groups that contain exactly two
    files where one ends in _0001 and the other in _0002, mark the
    _0002 file for deletion.
    """
    targets = []

    for dirpath, _dirnames, filenames in os.walk(root):
        # Only touch files that live inside a folder named exactly "archive"
        path_parts = os.path.normpath(dirpath).split(os.sep)
        if 'archive' not in path_parts:
            continue

        groups = defaultdict(dict)  # base_id -> {num: filename}

        for fname in filenames:
            m = PATTERN.match(fname)
            if not m:
                continue
            base = m.group('base')
            num = m.group('num')
            groups[base][num] = fname

        for base, nums in groups.items():
            if set(nums.keys()) == {'0001', '0002'}:
                targets.append(os.path.join(dirpath, nums['0002']))

    return targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', help='Root folder to scan recursively')
    parser.add_argument('--execute', action='store_true',
                         help='Actually delete files (default is dry-run, prints only)')
    args = parser.parse_args()

    if not os.path.isdir(args.root):
        print(f"Not a directory: {args.root}")
        return

    targets = find_targets(args.root)

    if not targets:
        print("No matching _0002 files found.")
        return

    print(f"Found {len(targets)} file(s) to delete:")
    for t in targets:
        print(f"  {t}")

    if args.execute:
        deleted = 0
        for t in targets:
            try:
                os.remove(t)
                deleted += 1
            except OSError as e:
                print(f"  FAILED to delete {t}: {e}")
        print(f"\nDeleted {deleted}/{len(targets)} file(s).")
    else:
        print("\nDry run only — no files deleted. Re-run with --execute to delete them.")


if __name__ == '__main__':
    main()
