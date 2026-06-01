#!/usr/bin/env python3
"""
font_bridge — test whether an unsupported Tibetan font's byte layout matches
an existing pytiblegenc table.

The idea
--------
Many "new" Tibetan fonts are byte-identical reskins of fonts pytiblegenc
already knows.  The bytes 32-255 produce the same Tibetan glyphs as some
existing table — only the PDF font name differs.  In that case there's no
need to write a 200-row CSV; one alias entry covers it.

The complication is that fonts use different *base encodings*.  Two fonts
can share the byte→Tibetan layout but, when PyMuPDF extracts text from each,
yield different surface characters for the same underlying byte.  For
example:

  byte 244 in TB-Youtso (Mac-Roman base)  → extracted as 'Ù'  → Tibetan ོ
  byte 244 in TCRC Bod-Yig (Latin-1 base) → extracted as 'ô'  → Tibetan ོ

Same byte, same Tibetan — but pytiblegenc's table is keyed by the
extracted character, so the two fonts can't share a table without
translation.

This tool tries several translations between extracted-character views,
testing each against every pytiblegenc table, and reports the match rate
per table.  A match rate above ~90% means the new font is a byte-layout
clone of an existing table and you should add an alias.  A lower rate
means it's genuinely a new layout and you need a custom CSV.

Strategies tested
-----------------
1. **direct** — extracted char is the key.  Works if both fonts use the same
   base encoding (typically Latin-1/WinAnsi).
2. **mac_to_latin1** — re-encode the extracted char to Mac-Roman, decode the
   byte as Latin-1, use that as the key.  Bridges Mac-Roman fonts to
   Latin-1-keyed tables (the TB-Youtso → TCRC Bod-Yig case).
3. **latin1_to_mac** — reverse: re-encode as Latin-1, decode as Mac-Roman.
   For the (rare) inverse case.

Usage
-----
    python tools/font_bridge.py path/to/font.cff
    python tools/font_bridge.py path/to/font.cff --base "TCRC Bod-Yig"
    python tools/font_bridge.py path/to/font.cff --min-match 0.85 --verbose

Exit code: 0 if any table reaches the --min-match threshold, 1 otherwise.
"""
from __future__ import annotations

import argparse
import logging
import sys
from io import BytesIO
from pathlib import Path

# Allow running as `python tools/font_bridge.py` from project root.
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR.parent))

from fontTools.agl import toUnicode
from fontTools.cffLib import CFFFontSet
from fontTools.ttLib import TTFont

logger = logging.getLogger("font_bridge")


# ---------------------------------------------------------------------------
# Read what byte-to-extracted-char the font produces
# ---------------------------------------------------------------------------

def read_font_encoding(font_path: Path) -> dict[int, str]:
    """
    Return {byte: extracted_unicode_char} for the embedded font.

    For CFF/Type1: byte → glyph_name (from CFF Encoding) → Unicode (via AGL).
    For TrueType: byte → glyph_name (from cmap) — but this is keyed by
        Unicode codepoint, so we need to invert it.  We assume MacRoman
        base for the byte→codepoint step.

    Empty returns mean no usable encoding was found.
    """
    suffix = font_path.suffix.lower()
    out: dict[int, str] = {}

    if suffix == ".cff" or font_path.read_bytes()[:4] in (b"\x01\x00\x04\x00",):
        try:
            cff = CFFFontSet()
            cff.decompile(BytesIO(font_path.read_bytes()), None, isCFF2=False)
            top = cff[cff.fontNames[0]]
            enc = top.Encoding
            for b in range(0x20, 0x100):
                if b >= len(enc):
                    break
                g = enc[b]
                if not g or g == ".notdef":
                    continue
                u = toUnicode(g)
                if u and len(u) >= 1:
                    out[b] = u[0]
            return out
        except Exception as e:
            logger.debug("CFF parse failed: %s", e)

    # TrueType fallback: walk cmap and recover byte → char via Mac-Roman
    try:
        font = TTFont(str(font_path))
        cmap = font.getBestCmap()
        for b in range(0x20, 0x100):
            try:
                ch = bytes([b]).decode("mac_roman")
            except UnicodeDecodeError:
                continue
            if ord(ch) in cmap:
                out[b] = ch
        return out
    except Exception as e:
        logger.warning("Could not read font %s: %s", font_path, e)
        return {}


# ---------------------------------------------------------------------------
# Bridge strategies
# ---------------------------------------------------------------------------

def _strategy_direct(ch: str) -> str | None:
    """Identity. Works when the PDF reader's extracted char IS the table key."""
    return ch


def _strategy_mac_to_latin1(ch: str) -> str | None:
    """For Mac-Roman-sourced PDFs whose target table was built from Latin-1."""
    if ord(ch) < 0x80:
        return ch
    try:
        b = ch.encode("mac_roman")
        if len(b) == 1 and b[0] >= 0x80:
            return bytes([b[0]]).decode("latin-1", errors="replace")
    except UnicodeEncodeError:
        pass
    return None


def _strategy_latin1_to_mac(ch: str) -> str | None:
    """Inverse of mac_to_latin1.  Rarely needed but cheap to check."""
    if ord(ch) < 0x80:
        return ch
    try:
        b = ch.encode("latin-1")
        if len(b) == 1 and b[0] >= 0x80:
            return bytes([b[0]]).decode("mac_roman", errors="replace")
    except UnicodeEncodeError:
        pass
    return None


STRATEGIES = {
    "direct":         _strategy_direct,
    "mac_to_latin1":  _strategy_mac_to_latin1,
    "latin1_to_mac":  _strategy_latin1_to_mac,
}


# ---------------------------------------------------------------------------
# Score a single font against a single pytiblegenc table
# ---------------------------------------------------------------------------

def score_table(
    font_encoding: dict[int, str],
    table: dict[str, str],
    strategy_fn,
) -> tuple[int, int, list[str], int]:
    """
    For each byte in *font_encoding*, transform its extracted char through
    *strategy_fn*, look up the result in *table*.

    Returns (hits, total, sample_mappings, distinct_values).

    *hits* counts bytes where the lookup returned a non-empty Tibetan string.
    *total* is the number of bytes considered.
    *sample_mappings* is a few human-readable examples for diagnostic output.
    *distinct_values* is the number of unique Tibetan strings hit — useful
    for tie-breaking, since a table that produces many different values is
    more likely to actually be the right one (rather than coincidentally
    matching one common vowel across many bytes).
    """
    hits = 0
    total = 0
    samples: list[str] = []
    distinct_vals: set[str] = set()
    for b in sorted(font_encoding):
        if 0x20 <= b < 0x7F and b not in (ord("-"),):
            ext = font_encoding[b]
            key = strategy_fn(ext)
            v = table.get(key) if key is not None else None
            if v:
                hits += 1
                distinct_vals.add(v)
            total += 1
            continue
        ext = font_encoding[b]
        key = strategy_fn(ext)
        if key is None:
            total += 1
            continue
        v = table.get(key)
        if v:
            hits += 1
            distinct_vals.add(v)
            if len(samples) < 5:
                samples.append(f"byte {b} ({ext!r}) → key {key!r} → {v!r}")
        total += 1
    return hits, total, samples, len(distinct_vals)


# ---------------------------------------------------------------------------
# Search across all pytiblegenc tables
# ---------------------------------------------------------------------------

def search_all_tables(
    font_encoding: dict[int, str],
    min_high_byte_hits: int = 5,
) -> list[dict]:
    """
    Try every (strategy × pytiblegenc table) combination.  Return a list of
    result dicts sorted by descending match rate.

    *min_high_byte_hits* filters out tables that only matched ASCII (which
    every table does trivially).  A real candidate must hit at least N
    high-byte (≥0x80) bytes.

    Tables that are identical (same id() of the underlying dict — pytiblegenc
    sometimes registers one table under multiple names like "TCRC Bod-Yig",
    "TCRC Youtso", "TCRC Youtsoweb") are deduplicated; we keep one
    representative and concatenate aliases.
    """
    from pytiblegenc.char_converter import get_base, get_utfc_base
    all_tables: dict[str, dict] = {}
    all_tables.update(get_base())
    all_tables.update(get_utfc_base())

    # Dedupe by table identity
    by_id: dict[int, list[str]] = {}
    for name, tbl in all_tables.items():
        by_id.setdefault(id(tbl), []).append(name)
    canonical = {names[0]: all_tables[names[0]] for names in by_id.values()}
    aliases = {names[0]: names for names in by_id.values()}

    results = []
    for strat_name, strat_fn in STRATEGIES.items():
        for table_name, table in canonical.items():
            hits, total, samples, distinct = score_table(font_encoding, table, strat_fn)
            high_hits = 0
            for b in font_encoding:
                if b < 0x80:
                    continue
                ext = font_encoding[b]
                key = strat_fn(ext)
                if key is not None and table.get(key):
                    high_hits += 1
            if high_hits < min_high_byte_hits:
                continue
            results.append({
                "strategy": strat_name,
                "table": table_name,
                "aliases": aliases[table_name],
                "hits": hits,
                "total": total,
                "high_byte_hits": high_hits,
                "rate": hits / total if total else 0.0,
                "distinct": distinct,
                "samples": samples,
            })

    # Rank by raw hit rate primarily; distinctness only as tie-breaker.
    # (Earlier I tried distinct-first sorting but found it misled — DBu-can
    # has many entries but they're not the right entries for TB-Youtso.)
    results.sort(key=lambda r: (-r["rate"], -r["distinct"]))
    return results


# ---------------------------------------------------------------------------
# CLI driver
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test whether a Tibetan font matches an existing "
                    "pytiblegenc table via byte-layout analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("font", type=Path, help="Path to a .cff/.otf/.ttf font file.")
    parser.add_argument(
        "--base", default=None,
        help="Test only against this specific pytiblegenc table name.",
    )
    parser.add_argument(
        "--min-match", type=float, default=0.85,
        help="Match-rate threshold for the 'alias OK' recommendation "
             "(default: 0.85).",
    )
    parser.add_argument(
        "--top", type=int, default=5,
        help="Show this many top results (default: 5).",
    )
    parser.add_argument(
        "--ground-truth", nargs=2, metavar=("RAW", "EXPECTED"),
        action="append", default=[],
        help="Verify each candidate table by decoding RAW (the raw extracted "
             "text from the PDF) and comparing to EXPECTED (the correct "
             "Tibetan). Pass multiple times to test multiple phrases. "
             "This is the most reliable disambiguator when several "
             "candidates score similarly. Example: --ground-truth "
             "'qa-VÔm' 'པཎ་ཆེན'",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    if not args.font.is_file():
        print(f"error: font file not found: {args.font}", file=sys.stderr)
        return 2

    print(f"\nFont: {args.font}")
    encoding = read_font_encoding(args.font)
    if not encoding:
        print("  Could not extract a byte-to-character mapping from this font.")
        return 2
    print(f"  Encoded bytes: {len(encoding)} (range "
          f"{min(encoding):#x}..{max(encoding):#x})")
    high_bytes = [b for b in encoding if b >= 0x80]
    print(f"  High bytes (≥0x80): {len(high_bytes)}\n")

    if args.base:
        from pytiblegenc.char_converter import get_base, get_utfc_base
        all_tables = {**get_base(), **get_utfc_base()}
        if args.base not in all_tables:
            print(f"error: table {args.base!r} not in pytiblegenc.", file=sys.stderr)
            return 2
        target = {args.base: all_tables[args.base]}
        # Override search to use only this one
        results = []
        for strat_name, strat_fn in STRATEGIES.items():
            hits, total, samples, distinct = score_table(
                encoding, all_tables[args.base], strat_fn
            )
            high_hits = sum(
                1 for b in encoding if b >= 0x80
                and strat_fn(encoding[b]) is not None
                and all_tables[args.base].get(strat_fn(encoding[b]))
            )
            results.append({
                "strategy": strat_name,
                "table": args.base,
                "aliases": [args.base],
                "hits": hits,
                "total": total,
                "high_byte_hits": high_hits,
                "rate": hits / total if total else 0.0,
                "distinct": distinct,
                "samples": samples,
            })
        results.sort(key=lambda r: (-r["rate"], -r["distinct"]))
    else:
        results = search_all_tables(encoding)

    if not results:
        print("No pytiblegenc table is a plausible match (all <5 high-byte hits).")
        print("This font likely needs a fresh CSV — build it from the contact")
        print("sheet and Rosetta-stone analysis.")
        return 1

    print(f"Top {min(args.top, len(results))} candidates (by raw hit-rate):\n")
    print(f"  {'#':>2}  {'rate':>6}  {'high':>5}  {'distinct':>8}  {'strategy':<16}  table")
    print("  " + "-" * 80)
    for i, r in enumerate(results[: args.top], 1):
        aliases_str = ""
        if len(r.get("aliases", [r["table"]])) > 1:
            aliases_str = "  (= " + ", ".join(
                a for a in r["aliases"] if a != r["table"]
            ) + ")"
        print(f"  {i:>2}  {r['rate'] * 100:5.1f}%  {r['high_byte_hits']:>5}  "
              f"{r['distinct']:>8}  {r['strategy']:<16}  {r['table']}{aliases_str}")

    print()
    if not args.ground_truth:
        print("Match rate alone is unreliable — multiple tables can score >90% by")
        print("happening to have entries at the right byte slots, even when those")
        print("entries are wrong for this font.  Re-run with --ground-truth to")
        print("decode a known phrase against each candidate and pick the one")
        print("whose output exactly matches your expected Tibetan.")

    best = results[0]
    print()
    print(f"Best raw rate: {best['table']!r} via '{best['strategy']}' "
          f"({best['rate'] * 100:.1f}% overall, "
          f"{best['high_byte_hits']} high-byte hits, "
          f"{best['distinct']} distinct Tibetan values)")
    if best["samples"]:
        print("Sample mappings under the top-rate strategy:")
        for s in best["samples"]:
            print(f"  {s}")

    # --- Ground-truth verification: this is the real disambiguator ----
    if args.ground_truth:
        from pytiblegenc.char_converter import get_base, get_utfc_base
        all_tables = {**get_base(), **get_utfc_base()}
        print()
        print("=" * 70)
        print("Ground-truth verification")
        print("=" * 70)
        for raw_text, expected in args.ground_truth:
            print(f"\nRaw:      {raw_text!r}")
            print(f"Expected: {expected}")
            print()
            print(f"  {'#':>2}  {'match':<6}  {'strategy':<16}  {'table':<25}  decoded")
            print("  " + "-" * 95)
            for i, r in enumerate(results[: args.top], 1):
                strat_fn = STRATEGIES[r["strategy"]]
                tbl = all_tables[r["table"]]
                decoded_chars: list[str] = []
                for ch in raw_text:
                    key = strat_fn(ch)
                    v = tbl.get(key) if key is not None else None
                    if v is None and ch in tbl:
                        # Fall back to direct lookup (ASCII case)
                        v = tbl.get(ch)
                    decoded_chars.append(v if v is not None else ch)
                decoded = "".join(decoded_chars)
                match = "✓" if decoded == expected else "✗"
                print(f"  {i:>2}  {match:<6}  {r['strategy']:<16}  "
                      f"{r['table']:<25}  {decoded}")
        print()
        print("Pick the candidate whose decoded text exactly matches your")
        print("ground truth.  Match-rate alone is unreliable — tables that")
        print("happen to have entries at the right byte slots will score high")
        print("even if the entries themselves are for a different font.")

    # --- Final recommendation ----------------------------------------
    # If ground-truth was provided, pick the candidate whose decoded text
    # exactly matched the expected Tibetan for ALL provided phrases.
    gt_winner = None
    if args.ground_truth:
        from pytiblegenc.char_converter import get_base, get_utfc_base
        all_tables = {**get_base(), **get_utfc_base()}
        for r in results:
            strat_fn = STRATEGIES[r["strategy"]]
            tbl = all_tables[r["table"]]
            all_ok = True
            for raw_text, expected in args.ground_truth:
                decoded = "".join(
                    (tbl.get(strat_fn(ch) or "") or tbl.get(ch) or ch)
                    for ch in raw_text
                )
                if decoded != expected:
                    all_ok = False
                    break
            if all_ok:
                gt_winner = r
                break

    print()
    if gt_winner:
        print("Recommendation (based on ground-truth match):")
        print(f"  Table:     {gt_winner['table']}")
        print(f"  Strategy:  {gt_winner['strategy']}")
        if gt_winner["strategy"] == "direct":
            print()
            print(f"  → Add to local_font_tables/_aliases.csv:")
            print(f"      {Path(args.font).stem.split('+', 1)[-1]},{gt_winner['table']}")
        else:
            print()
            print(f"  → A direct alias won't work; the byte→Tibetan mapping is")
            print(f"    the same as {gt_winner['table']!r} but the surface character")
            print(f"    encoding differs (strategy: {gt_winner['strategy']}).")
            print(f"    Build a translated CSV using the byte-bridge — see the")
            print(f"    TB-Youtso example in local_font_tables/tb_youtso.csv for")
            print(f"    the pattern.")
    elif args.ground_truth:
        print("Recommendation:")
        print(f"  No candidate matched all ground-truth phrases.  Either:")
        print(f"    (a) the ground-truth expected text has typos, or")
        print(f"    (b) the font's byte layout is genuinely new and not in any")
        print(f"        pytiblegenc table — you'll need to build a custom CSV.")
        print(f"  Inspect the contact sheet from font_inspect and identify")
        print(f"  glyphs by hand.")
        return 1
    elif best["rate"] >= args.min_match:
        print("Recommendation:")
        print(f"  '{best['table']}' via '{best['strategy']}' is the strongest")
        print(f"  raw-rate candidate.  BUT this can be misleading — re-run with")
        print(f"  --ground-truth <raw> <expected> using a known phrase from")
        print(f"  the PDF to confirm.")
        if best["strategy"] == "direct":
            print()
            print(f"  If verified, add to local_font_tables/_aliases.csv:")
            print(f"      {Path(args.font).stem.split('+', 1)[-1]},{best['table']}")
        else:
            print()
            print(f"  If verified, the alias path won't work and you'll need a")
            print(f"  translated CSV.  See local_font_tables/tb_youtso.csv for")
            print(f"  the pattern.")
    else:
        print("Recommendation:")
        print(f"  No high-confidence match.  Best is {best['rate'] * 100:.1f}% which is")
        print(f"  below the --min-match threshold ({args.min_match * 100:.0f}%).")
        print(f"  This font probably needs a custom mapping. Inspect the contact")
        print(f"  sheet from font_inspect and identify glyphs by hand.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
