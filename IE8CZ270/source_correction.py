#!/usr/bin/env python3
"""
Source-based correction for Dedris corruption in TEI XML.

Resolves source RTF path from TEI header, parses RTF to get runs (text + font),
and can re-convert runs with alternate fonts when corruption is detected.
Used optionally by rtf_check_fix when --fix-from-source is set.
"""

import re
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Corruption patterns (presence in converted text suggests wrong font)
CORRUPTION_PATTERNS = [
    re.compile(r',ོ'),
    re.compile(r'་\.་'),
    re.compile(r'[{}]'),
    re.compile(r'\.[\u0F71-\u0F84]'),   # dot + Tibetan vowel (.ེ .ོ etc.)
    re.compile(r'[\u0F00-\u0FFF]\.'),   # Tibetan + dot (འ. མེ. etc.)
    re.compile(r'0་'),                   # digit 0 + tsheg
]

ALTERNATE_FONTS = ['Dedris-a', 'Dedris-vowa', 'Dedris-b', 'Dedris-c']


def _has_corruption(text: str) -> bool:
    """Return True if text contains known corruption patterns."""
    return any(p.search(text) for p in CORRUPTION_PATTERNS)


def resolve_source_path(
    xml_path: Path,
    src_path_value: str,
    output_dir: Path,
    rtf_dir: Path,
) -> Optional[Path]:
    """
    Resolve the source file (DOC or RTF) for an XML file.
    src_path_value is from TEI: e.g. "sources/VE001/volume_001_018.doc"
    Tries: (1) output_dir / src_path_value, (2) rtf_dir / sources / volume_XXX / <stem>.rtf
    """
    # Try output_dir / src_path
    candidate = output_dir / src_path_value
    if candidate.exists():
        return candidate
    # Try same path but .rtf
    candidate_rtf = candidate.with_suffix('.rtf')
    if candidate_rtf.exists():
        return candidate_rtf
    # Derive volume folder from VE id: sources/VE001/volume_001_018.doc -> VE001, stem volume_001_018
    parts = src_path_value.replace('\\', '/').split('/')
    stem = Path(src_path_value).stem  # e.g. volume_001_018
    # volume_001_018 -> volume_001
    if '_' in stem:
        volume_part = stem.rsplit('_', 1)[0]  # volume_001
    else:
        volume_part = stem
    # Try rtf_dir / sources / volume_001 / volume_001_018.rtf
    for base in (rtf_dir, output_dir):
        for ext in ('.rtf', '.doc'):
            p = base / 'sources' / volume_part / f"{stem}{ext}"
            if p.exists():
                return p
        # Some layouts: rtf_dir/sources/volume_001/volume_001_018.rtf
        p = base / 'sources' / volume_part / f"{stem}.rtf"
        if p.exists():
            return p
    return None


def get_runs_from_rtf(rtf_path: Path) -> List[Dict]:
    """
    Parse RTF and return list of runs with raw text and font name.
    Mirrors convert.py filtering: skip header/footer/pict, emit newlines for par/cell/line breaks.
    """
    from basic_rtf import BasicRTF
    parser = BasicRTF()
    parser.parse_file(str(rtf_path))
    streams = parser.get_streams()
    runs = []
    for stream in streams:
        if stream.get("type") in ("header", "footer", "pict"):
            continue
        if stream.get("type") == "par_break":
            runs.append({"text": "\n", "font_name": "", "is_break": True})
            continue
        if stream.get("type") == "line_break":
            runs.append({"text": "\n", "font_name": "", "is_break": True})
            continue
        if stream.get("type") == "cell_break":
            runs.append({"text": "\n", "font_name": "", "is_break": True})
            continue
        if stream.get("type") == "row_break":
            continue
        text = stream.get("text", "")
        font_name = stream.get("font", {}).get("name", "")
        runs.append({"text": text, "font_name": font_name, "is_break": False})
    return runs


def try_alternate_fonts_for_run(raw_text: str, font_name: str) -> Tuple[str, str]:
    """
    Convert run with given font; if result has corruption, try alternate Dedris fonts.
    Returns (best_unicode, font_used).
    """
    try:
        from convert import dedris_to_unicode
    except ImportError:
        return (raw_text, font_name)
    current = dedris_to_unicode(raw_text, font_name)
    if not _has_corruption(current):
        return (current, font_name)
    for alt in ALTERNATE_FONTS:
        if alt.lower() == (font_name or "").lower():
            continue
        candidate = dedris_to_unicode(raw_text, alt)
        if candidate and not _has_corruption(candidate):
            return (candidate, alt)
    return (current, font_name)


def get_src_path_from_xml(content: str) -> Optional[str]:
    """Extract src_path from TEI header: <idno type="src_path">...</idno>."""
    m = re.search(r'<idno\s+type=["\']src_path["\']\s*>([^<]+)</idno>', content)
    return m.group(1).strip() if m else None


def strip_body_tags(body: str) -> str:
    """Remove all XML tags from body to get plain text (tags removed, content kept)."""
    return re.sub(r'<[^>]+>', '', body)


def build_plain_to_body_offsets(body: str) -> List[int]:
    """
    For each character index in the plain text (tags stripped), store the start
    offset in the original body. So plain_to_body[i] = body offset where plain char i starts.
    """
    plain_to_body = []
    i = 0
    length = len(body)
    while i < length:
        if body[i] == '<':
            j = body.find('>', i + 1)
            if j == -1:
                plain_to_body.append(i)
                i += 1
            else:
                i = j + 1
            continue
        plain_to_body.append(i)
        i += 1
    return plain_to_body


def fix_corruption_from_source(body: str, runs: List[Dict]) -> Tuple[str, int]:
    """
    For each run, convert with dedris_to_unicode; if result has corruption,
    try alternate fonts. Build expected plain text from (possibly corrected) run outputs.
    Then map back to body and substitute only where we have a different run text.
    Returns (new_body, number_of_substitutions).
    """
    try:
        from convert import dedris_to_unicode
    except ImportError:
        return (body, 0)
    converted = []
    for r in runs:
        if r.get("is_break"):
            converted.append(r["text"])
            continue
        raw = r["text"]
        font = r["font_name"]
        best, _ = try_alternate_fonts_for_run(raw, font)
        converted.append(best)
    expected_plain = "".join(converted)
    body_plain = strip_body_tags(body)
    # If lengths differ a lot, skip (normalization or structure mismatch)
    if abs(len(expected_plain) - len(body_plain)) > max(50, len(body_plain) // 10):
        return (body, 0)
    # Build mapping: plain index -> body (start, end) for each run
    plain_to_body = build_plain_to_body_offsets(body)
    if len(plain_to_body) != len(body_plain):
        return (body, 0)
    # Run boundaries in plain text
    run_starts = [0]
    for c in converted:
        run_starts.append(run_starts[-1] + len(c))
    # Collect substitutions: (start_body, end_body, best) for runs where we used alternate font
    replacements = []
    for i, r in enumerate(runs):
        if r.get("is_break"):
            continue
        orig = dedris_to_unicode(r["text"], r["font_name"])
        best = converted[i]
        if orig == best or not best:
            continue
        start_plain = run_starts[i]
        end_plain = run_starts[i + 1]
        if end_plain > len(plain_to_body):
            continue
        start_body = plain_to_body[start_plain]
        end_body = plain_to_body[end_plain] if end_plain < len(plain_to_body) else len(body)
        old_slice = body[start_body:end_body]
        # Only replace if the slice (without tags) equals original run text
        if re.sub(r'<[^>]+>', '', old_slice) == orig:
            replacements.append((start_body, end_body, best))
    # Apply from end to start so indices remain valid
    replacements.sort(key=lambda x: x[0], reverse=True)
    result_body = body
    for start_body, end_body, best in replacements:
        result_body = result_body[:start_body] + best + result_body[end_body:]
    return (result_body, len(replacements))
