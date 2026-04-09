#!/usr/bin/env python3
"""
Recursively sum the byte size of all .xml files under a folder.

By default walks the entire tree under the root. With --subfolders and/or
--subfolders-file, only direct children of the root whose names match the
list are scanned (each match is walked recursively, including nested dirs
like archive/).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def human_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}" if unit != "B" else f"{n} {unit}"
        n /= 1024
    return f"{n:.2f} TiB"


def format_decimal_gb(n: int) -> str:
    """SI gigabytes: 1 GB = 1e9 bytes."""
    if n == 0:
        return "0 GB"
    gb = n / 1_000_000_000
    s = f"{gb:.12f}".rstrip("0").rstrip(".")
    return f"{s} GB"


def xml_stats(root: Path) -> tuple[int, int]:
    total = 0
    count = 0
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".xml":
            total += path.stat().st_size
            count += 1
    return total, count


def read_subfolder_names(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def resolve_subdir(root_resolved: Path, name: str) -> Path | None:
    """Return root_resolved / name if it exists, is a dir, and stays under root."""
    if not name or name == "." or ".." in Path(name).parts:
        return None
    cand = (root_resolved / name).resolve()
    try:
        cand.relative_to(root_resolved)
    except ValueError:
        return None
    return cand if cand.is_dir() else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Total size of all .xml files under a folder (recursive), "
        "optionally limited to named direct subfolders of the root."
    )
    parser.add_argument(
        "folder",
        type=Path,
        nargs="?",
        default=Path("."),
        help="Root folder to scan (default: current directory)",
    )
    parser.add_argument(
        "-s",
        "--subfolders",
        action="append",
        nargs="+",
        metavar="NAME",
        default=None,
        help="Direct subfolder name(s) under the root (repeat -s for more groups)",
    )
    parser.add_argument(
        "-f",
        "--subfolders-file",
        type=Path,
        metavar="PATH",
        help="Text file: one subfolder name per line (# starts a comment)",
    )
    parser.add_argument(
        "-H",
        "--human",
        action="store_true",
        help="Print total size in human-readable units (KiB, MiB, GiB, …)",
    )
    parser.add_argument(
        "--gb",
        action="store_true",
        help="Print sizes in decimal GB (1 GB = 10^9 bytes); use with -v for per-subfolder lines",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print per-subfolder bytes and file count",
    )
    args = parser.parse_args()
    root = args.folder.expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    names: list[str] = []
    if args.subfolders is not None:
        for group in args.subfolders:
            names.extend(group)
    if args.subfolders_file is not None:
        sf = args.subfolders_file.expanduser().resolve()
        if not sf.is_file():
            raise SystemExit(f"Not a file: {sf}")
        names.extend(read_subfolder_names(sf))

    use_filter = args.subfolders is not None or args.subfolders_file is not None
    if use_filter:
        # Preserve order, drop duplicates
        seen: set[str] = set()
        unique_names: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                unique_names.append(n)
        names = unique_names

    if not use_filter:
        total_bytes, file_count = xml_stats(root)
        if args.verbose:
            if args.gb:
                print(
                    f"{root}: {format_decimal_gb(total_bytes)} ({total_bytes} bytes), "
                    f"{file_count} xml files"
                )
            else:
                print(f"{root}: {total_bytes} bytes, {file_count} xml files")
    else:
        if not names:
            raise SystemExit(
                "No subfolder names given. Use -s NAME [...] and/or -f FILE."
            )
        total_bytes = 0
        file_count = 0
        missing: list[str] = []
        for name in names:
            target = resolve_subdir(root, name)
            if target is None:
                missing.append(name)
                continue
            b, c = xml_stats(target)
            total_bytes += b
            file_count += c
            if args.verbose:
                rel = target.relative_to(root)
                if args.gb:
                    print(
                        f"{rel}: {format_decimal_gb(b)} ({b} bytes), {c} xml files"
                    )
                else:
                    print(f"{rel}: {b} bytes, {c} xml files")
        for name in missing:
            print(
                f"Warning: missing or not a directory under root: {name!r} ({root / name})",
                file=sys.stderr,
            )

    if args.gb:
        print(f"Total: {format_decimal_gb(total_bytes)} ({total_bytes} bytes)")
    elif args.human:
        print(f"Total: {human_size(total_bytes)} ({total_bytes} bytes)")
    else:
        print(f"Total: {total_bytes} bytes")
    print(f"XML files: {file_count}")


if __name__ == "__main__":
    main()
