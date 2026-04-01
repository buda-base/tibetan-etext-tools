#!/usr/bin/env python3
"""
Extract all unmapped CIDs from a PDF file.

This script helps identify which CIDs need to be added to the glyph_decoder module.
Run this on your PDF to see which CIDs are not yet mapped.

Usage:
    python extract_unmapped_cids.py path/to/your.pdf
"""

import sys
from pathlib import Path
from collections import Counter

# Add current directory to path to import glyph_decoder
sys.path.insert(0, str(Path(__file__).parent))

from glyph_decoder import patch_pytiblegenc_cid_decoder, DEFAULT_CID_TO_UNICODE_OVERRIDES
from pytiblegenc import pdf_to_txt
import pytiblegenc.pdfminer_text_converter as pmc


def extract_unmapped_cids(pdf_path: Path):
    """Extract all CIDs that are not yet mapped."""
    
    # Track all CIDs encountered
    cid_counter = Counter()
    
    # Patch to capture all CIDs
    original_convert = pmc.convert_string
    
    def capture_cids(s, font_name, stats, error_chr_fun=None, glyph_lookup=None):
        if s.startswith("(cid:") and s.endswith(")"):
            try:
                cid = int(s[5:-1])
                key = (font_name, cid)
                cid_counter[key] += 1
            except ValueError:
                pass
        # Handle both old (4 args) and new (5 args) signatures
        try:
            return original_convert(s, font_name, stats, error_chr_fun, glyph_lookup)
        except TypeError:
            return original_convert(s, font_name, stats, error_chr_fun)
    
    pmc.convert_string = capture_cids
    
    try:
        # Extract text (this will trigger CID capture)
        with patch_pytiblegenc_cid_decoder(pdf_path, pmc):
            _ = pdf_to_txt(
                str(pdf_path),
                page_break_str="\n",
                track_font_size=False,
                normalize=False,
                simplify_font_sizes_option=False,
            )
    finally:
        pmc.convert_string = original_convert
    
    # Find unmapped CIDs
    unmapped = []
    for (font_name, cid), count in cid_counter.items():
        if (font_name, cid) not in DEFAULT_CID_TO_UNICODE_OVERRIDES:
            unmapped.append((font_name, cid, count))
    
    return sorted(unmapped, key=lambda x: (x[0], x[1]))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"Error: PDF file not found: {pdf_path}")
        sys.exit(1)
    
    print(f"Extracting unmapped CIDs from: {pdf_path.name}")
    print()
    
    unmapped = extract_unmapped_cids(pdf_path)
    
    if not unmapped:
        print("✓ All CIDs are mapped!")
        return
    
    print(f"Found {len(unmapped)} unmapped CIDs:\n")
    
    # Group by font
    current_font = None
    for font_name, cid, count in unmapped:
        if font_name != current_font:
            if current_font is not None:
                print()
            print(f"# {font_name}")
            current_font = font_name
        print(f'("{font_name}", {cid}): "",  # {count} occurrences')
    
    print()
    print("To map these CIDs:")
    print("1. Open the PDF and find examples of text containing these CIDs")
    print("2. Visually identify what Tibetan text each CID represents")
    print("3. Add the mappings to glyph_decoder.py DEFAULT_CID_TO_UNICODE_OVERRIDES")
    print()
    print("Example:")
    print('    ("MonlamUniOuChan1", 299): "སུ",')


if __name__ == "__main__":
    main()
