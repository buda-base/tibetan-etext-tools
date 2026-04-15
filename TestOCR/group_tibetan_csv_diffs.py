"""
Read a CSV with columns left_value, right_value, page_left, page_right.

For each row, extract differing Tibetan fragments. When both sides split into the
same number of tsek (U+0F0B) syllable segments, each differing syllable pair is
recorded as ``<syllable>་`` vs ``<syllable>་``. Otherwise one contiguous block is
taken by stripping shared prefix and suffix (Unicode code points). Identical
unordered pairs are grouped and counted.

Usage:
  python group_tibetan_csv_diffs.py
  python group_tibetan_csv_diffs.py path/to/diffs.csv

Writes: path/to/diffs_diff_groups.csv (same directory as input).
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

# --- set your input here (used when no path is passed on the command line) ---
INPUT_CSV = Path(r"D:\Work\OpenPecha\conversion\IE3KG694\lb_diff_pairs.csv")

_TSEK = "\u0f0b"  # Tibetan syllable delimiter


def _tsek_tokens(s: str) -> list[str]:
    return [t for t in s.split(_TSEK) if t]


def _lcp_lcs_pair(left: str, right: str) -> tuple[str, str]:
    """Minimal contiguous diff: strip shared prefix and suffix (Unicode code points)."""
    if left == right:
        return ("", "")
    i = 0
    n, m = len(left), len(right)
    while i < n and i < m and left[i] == right[i]:
        i += 1
    j = 0
    while j < (n - i) and j < (m - i) and left[n - 1 - j] == right[m - 1 - j]:
        j += 1
    return left[i : n - j], right[i : m - j]


def diff_pairs_for_row(left: str, right: str) -> list[tuple[str, str]]:
    """
    Prefer tsek-aligned syllable differences when both sides have the same number
    of syllable segments; otherwise fall back to one LCP/LCS block on the full
    string (handles length mismatches or multiple edits per syllable cluster).
    """
    if left == right:
        return []
    tl, tr = _tsek_tokens(left), _tsek_tokens(right)
    if len(tl) == len(tr):
        pairs = [
            (f"{a}{_TSEK}", f"{b}{_TSEK}")
            for a, b in zip(tl, tr)
            if a != b
        ]
        if pairs:
            return pairs
    a, b = _lcp_lcs_pair(left, right)
    if a or b:
        return [(a, b)]
    return []


def normalized_pair(a: str, b: str) -> tuple[str, str]:
    """Unordered pair: smaller string first (Unicode code point order)."""
    return (a, b) if a <= b else (b, a)


def main() -> None:
    p = argparse.ArgumentParser(description="Group minimal Tibetan text diffs from CSV.")
    p.add_argument(
        "csv_path",
        nargs="?",
        type=Path,
        default=None,
        help="Input CSV (default: INPUT_CSV in this file)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output CSV path (default: <input_stem>_diff_groups.csv beside input)",
    )
    args = p.parse_args()
    inp = (args.csv_path or INPUT_CSV).resolve()
    if not inp.is_file():
        raise SystemExit(f"Not found: {inp}")

    out = args.output
    if out is None:
        out = inp.with_name(f"{inp.stem}_diff_groups{inp.suffix}")
    else:
        out = out.resolve()

    counts: Counter[tuple[str, str]] = Counter()
    with inp.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit("Empty or invalid CSV")
        # tolerate column name variants
        def col(row: dict[str, str], *names: str) -> str:
            for name in names:
                if name in row and row[name] is not None:
                    return row[name]
            return ""

        for row in reader:
            lv = col(row, "left_value", "left")
            rv = col(row, "right_value", "right")
            for d1, d2 in diff_pairs_for_row(lv, rv):
                if d1 == "" and d2 == "":
                    continue
                counts[normalized_pair(d1, d2)] += 1

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["left_diff", "right_diff", "count"])
        for (a, b), n in sorted(counts.items(), key=lambda x: (-x[1], x[0][0], x[0][1])):
            w.writerow([a, b, n])

    print(f"Wrote {len(counts)} group(s) to {out}")


if __name__ == "__main__":
    main()
