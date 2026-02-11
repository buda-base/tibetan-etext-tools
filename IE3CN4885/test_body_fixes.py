#!/usr/bin/env python3
"""Test body-content fixes (spaces, flying vowels, Word field codes) on existing XML body."""
import re
import sys
from pathlib import Path

# Add script dir so we can import tibetan_text_fixes
sys.path.insert(0, str(Path(__file__).parent))
from tibetan_text_fixes import (
    remove_spaces_between_tibetan_chars,
    ensure_space_after_shad,
    fix_flying_vowels_and_linebreaks,
    fix_hi_tag_spacing,
)
from normalization import normalize_unicode


def strip_word_field_codes(text: str) -> str:
    # Allow optional backslash before * (Word can emit "PAGE \* MERGEFORMAT")
    text = re.sub(r'\s*PAGE\s+\\?\s*\*\s*MERGEFORMAT\s*\d*\s*', ' ', text)
    text = re.sub(r'\s*NUMPAGES\s+\\?\s*\*\s*MERGEFORMAT\s*', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text


def apply_fixes(body: str) -> str:
    """Apply the same fix pipeline as convert.py (field codes, spaces, ensure space after །, flying vowels, normalize, hi spacing)."""
    body = strip_word_field_codes(body)
    body = remove_spaces_between_tibetan_chars(body)
    body = ensure_space_after_shad(body)
    body = fix_flying_vowels_and_linebreaks(body)
    body = normalize_unicode(body)
    body = fix_hi_tag_spacing(body)
    return body


def main():
    import argparse
    p = argparse.ArgumentParser(description="Test or apply body-content fixes to TEI XML.")
    p.add_argument("--write", "-w", action="store_true", help="Write fixed body back to the XML file.")
    p.add_argument("xml", nargs="?", default=None, help="Path to TEI XML (default: UT3KG159_0001.xml)")
    args = p.parse_args()

    xml_path = Path(args.xml) if args.xml else (
        Path(__file__).parent.parent / "rtf/IE1KG4285/IE1KG4285_output/archive/VE3KG159/UT3KG159_0001.xml"
    )
    if not xml_path.exists():
        print("XML not found:", xml_path)
        return 1
    raw = xml_path.read_text(encoding="utf-8")
    # Extract <body> content: the <p>...</p> inside <text><body>
    body_start = raw.find("<body")
    if body_start == -1:
        print("No <body found")
        return 1
    p_start = raw.find("<p>", body_start) + 3
    p_end = raw.find("</p>", body_start)
    body = raw[p_start:p_end]

    print("=== BEFORE (first 400 chars) ===")
    print(repr(body[:400]))
    print()

    body = apply_fixes(body)

    print("=== AFTER (first 400 chars) ===")
    print(repr(body[:400]))
    print()

    # Check: "རྒ ྱ་" should become "རྒྱ་"
    if "རྒ ྱ" in body or " ྱ" in body[:100]:
        print("FAIL: still has space before ྱ in first 100 chars")
    else:
        print("OK: no ' ྱ' in first 100 chars")
    if "PAGE" in body and "MERGEFORMAT" in body:
        print("FAIL: PAGE MERGEFORMAT still present")
    else:
        print("OK: PAGE MERGEFORMAT stripped")

    if args.write:
        new_raw = raw[:p_start] + body + raw[p_end:]
        xml_path.write_text(new_raw, encoding="utf-8")
        print("Wrote fixed body to:", xml_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
