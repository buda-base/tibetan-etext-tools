"""
Group ``lb_diff_pairs_correction_dataset.csv`` (from ``compare_tei_lb.py``) by
``(left_token, right_token)``, with every ``[page_index, line_index, token_index]``.

The third value is ``left_token_index`` when that column exists (preferred for
``replace_diff.py``); otherwise ``aligned_index`` (legacy; may not match token
position). Input columns: ``page_index``, ``line_index``, ``left_token_index``,
``aligned_index``, ``left_token``, ``right_token`` (aliases: ``left``, ``right``,
``page``, ``line``, ``aligned``).

Writes beside the input:
  ``<stem>_grouped.csv`` — ``left_token``, ``right_token``, ``count`` only
  ``<stem>_grouped.json`` — list of objects with ``left_token``, ``right_token``,
  ``count``, ``occurrences``

Usage:
  python group_tibetan_csv_diffs.py
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

# Input CSV path (Output file name is same as input file name with _grouped.csv and _grouped.json)
INPUT_CSV = Path(r"D:\Work\OpenPecha\conversion\IE3KG694\IE3KG694_output\archive\VE1ER1074\lb_diff_pairs_correction_dataset.csv")


def _col(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return ""


def load_occurrence_groups(inp: Path) -> dict[tuple[str, str], list[list[int]]]:
    groups: dict[tuple[str, str], list[list[int]]] = defaultdict(list)
    with inp.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise SystemExit("Empty or invalid CSV")
        for row in reader:
            left = _col(row, "left_token", "left")
            right = _col(row, "right_token", "right")
            pi = _col(row, "page_index", "page")
            li = _col(row, "line_index", "line")
            lti = _col(row, "left_token_index", "left_token_idx")
            ai = _col(row, "aligned_index", "aligned")
            if not left and not right:
                continue
            idx_src = lti if str(lti).strip() != "" else ai
            try:
                triple = [int(pi), int(li), int(idx_src)]
            except ValueError as e:
                raise SystemExit(
                    f"Non-integer page/line/token index: page={pi!r} line={li!r} idx={idx_src!r}"
                ) from e
            groups[(left, right)].append(triple)
    return groups


def main() -> None:
    inp = INPUT_CSV.resolve()
    if not inp.is_file():
        raise SystemExit(f"Not found: {inp}")

    json_out = inp.with_name(f"{inp.stem}_grouped.json")
    csv_out = inp.with_name(f"{inp.stem}_grouped.csv")

    groups = load_occurrence_groups(inp)
    rows: list[dict] = []
    for (left_tok, right_tok), occs in groups.items():
        rows.append(
            {
                "left_token": left_tok,
                "right_token": right_tok,
                "count": len(occs),
                "occurrences": occs,
            }
        )
    rows.sort(key=lambda r: (-r["count"], r["left_token"], r["right_token"]))

    json_out.parent.mkdir(parents=True, exist_ok=True)
    with json_out.open("w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["left_token", "right_token", "count"])
        for r in rows:
            w.writerow([r["left_token"], r["right_token"], r["count"]])

    print(f"Wrote {len(rows)} pair(s) to {json_out}")
    print(f"Wrote {len(rows)} pair(s) to {csv_out}")


if __name__ == "__main__":
    main()
