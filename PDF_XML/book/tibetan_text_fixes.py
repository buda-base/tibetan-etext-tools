#!/usr/bin/env python3
"""Utilities for fixing Tibetan text extraction ordering issues."""

import re


def fix_tibetan_mark_order(text: str) -> str:
    """
    Fix common OCR/PDF ordering issues in Tibetan text.

    Handles:
      - tsheg before combining mark (e.g. འ་ི -> འི་)
      - suffix before vowel sign (e.g. བདོ་ -> བོད་)
      - vowel sign before achung (e.g. པིའ་ -> པའི་)
    """
    tsheg = "\u0F0B"
    chars = list(text)
    i = 0
    while i < len(chars) - 1:
        cur = chars[i]
        nxt = chars[i + 1]
        if cur == tsheg and ("\u0F71" <= nxt <= "\u0FBC"):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
            i += 2
            continue
        i += 1
    fixed = "".join(chars)
    # Normalize curly quotes to plain double quotes for consistency.
    fixed = fixed.replace("“", '"').replace("”", '"')

    suffix = r"[\u0F42\u0F44\u0F51\u0F53\u0F56\u0F58\u0F60\u0F62\u0F63\u0F66]"
    vowels = r"[\u0F71-\u0F7D\u0F80\u0F81]"
    delim = r"(?=[\u0F0B\u0F0C\u0F0D\u0F0E\u0F11\s,.;:!?]|$)"
    for _ in range(3):
        prev = fixed
        fixed = re.sub(
            rf"([\u0F40-\u0FBC]+?)({suffix})({vowels}){delim}",
            r"\1\3\2",
            fixed,
        )
        # Restrict this swap to "i-vowel + achung" only; broader swaps can
        # corrupt valid forms like བོའི into བའོི.
        fixed = re.sub(
            rf"([\u0F40-\u0FBC]+?)([\u0F72])(\u0F60){delim}",
            r"\1\3\2",
            fixed,
        )
        # Repair common over-ordered form: བའོི -> བོའི
        fixed = re.sub(
            rf"([\u0F40-\u0FBC]+?)\u0F60([\u0F7A-\u0F7D])\u0F72{delim}",
            lambda m: m.group(1) + m.group(2) + "\u0F60" + "\u0F72",
            fixed,
        )
        # Sequence like ལེུའ -> ལེའུ (e.g. ལེའུ, རེའུ)
        fixed = re.sub(
            rf"([\u0F40-\u0FBC]+?)([\u0F7A-\u0F7D])(\u0F74)(\u0F60){delim}",
            r"\1\2\4\3",
            fixed,
        )
        # Quote inserted before vowel sign: ལ"ོ -> ལོ་"
        fixed = re.sub(
            r'([\u0F40-\u0FBC])"([\u0F71-\u0F7D\u0F80\u0F81])',
            lambda m: m.group(1) + m.group(2) + "\u0F0B" + '"',
            fixed,
        )
        if fixed == prev:
            break

    return fixed
