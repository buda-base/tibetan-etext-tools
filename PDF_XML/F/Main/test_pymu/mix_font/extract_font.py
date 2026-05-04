#!/usr/bin/env python3
"""
extract_pdf_fonts.py — Extract all fonts used in a PDF file.

Output format:
    {
        'font_ref_name': {'CleanFontFamily'},
        ...
    }

  - Key   : the internal PDF resource name for the font (e.g. 'C2_3', 'PPXGPU+Dedris-vowa', 'TT3')
  - Value : a set containing the clean base-font name, i.e. the part after the
            6-char subset prefix + '+' (if present), otherwise the full BaseFont string.

Usage:
    python extract_pdf_fonts.py <input.pdf>

Dependencies:
    pip install pypdf --break-system-packages
"""

import sys
import re
from pathlib import Path


# Subset prefixes look like "ABCDEF+" (six uppercase letters followed by a plus sign).
_SUBSET_RE = re.compile(r'^[A-Z]{6}\+')


def clean_font_name(base_font: str) -> str:
    """Strip a PDF subset prefix (e.g. 'PPXGPU+') from a BaseFont name."""
    return _SUBSET_RE.sub("", base_font)


def extract_fonts(pdf_path: str) -> dict[str, set]:
    """
    Return a dict mapping every PDF font resource name to a set containing
    the clean (un-prefixed) base font family name.

    Visits every page's /Resources/Font dictionary and collects:
      resource_name  -> /BaseFont value (cleaned)
    """
    from pypdf import PdfReader

    reader = PdfReader(pdf_path)
    result: dict[str, set] = {}

    for page in reader.pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        if hasattr(resources, "get_object"):
            resources = resources.get_object()

        font_dict = resources.get("/Font")
        if not font_dict:
            continue
        if hasattr(font_dict, "get_object"):
            font_dict = font_dict.get_object()

        for res_name, font_obj in font_dict.items():
            if hasattr(font_obj, "get_object"):
                font_obj = font_obj.get_object()

            # res_name comes in as '/C2_3'; strip the leading slash
            key = str(res_name).lstrip("/")

            base_font_raw = str(font_obj.get("/BaseFont", "Unknown")).lstrip("/")
            family = clean_font_name(base_font_raw)

            if key not in result:
                result[key] = set()
            result[key].add(family)

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_pdf_fonts.py <input.pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]

    if not Path(pdf_path).exists():
        print(f"Error: File not found — {pdf_path}")
        sys.exit(1)

    fonts = extract_fonts(pdf_path)
    print(fonts)          # prints the dict with set literals, matching the requested format


if __name__ == "__main__":
    main()