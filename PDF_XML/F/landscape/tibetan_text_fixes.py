#!/usr/bin/env python3
"""
Tibetan Text Fixes Module

This module provides functions to fix common issues in Tibetan text that occur
during PDF/RTF extraction and Dedris-related conversion.
"""

import re

# Tibetan character ranges
TIBETAN_VOWELS = r'[\u0f71-\u0f84]'
TIBETAN_CONSONANTS = r'[\u0f40-\u0f6c]'
TIBETAN_SUBSCRIPTS = r'[\u0f90-\u0fbc]'
TIBETAN_TSEG = '\u0f0b'
TIBETAN_SHED = '\u0f0d'
TIBETAN_SHEDS = r'[\u0f0d-\u0f11]'
XML_TAGS_PATTERN = r'(?:<[^>]*>)*'


def fix_flying_vowels(text: str) -> str:
    """Fix flying vowels - vowels at start of line that should join previous consonant."""
    if not text:
        return text
    pattern = rf'({TIBETAN_CONSONANTS}|{TIBETAN_SUBSCRIPTS}|{TIBETAN_VOWELS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_VOWELS})'
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_subscripts(text: str) -> str:
    """Fix flying subscripts - subscript consonants at start of line that should join previous."""
    if not text:
        return text
    pattern = rf'({TIBETAN_CONSONANTS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_SUBSCRIPTS})'
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_tseg(text: str) -> str:
    """Fix flying tseg - tseg at start of line that should join previous text."""
    if not text:
        return text
    pattern = rf'({TIBETAN_CONSONANTS}|{TIBETAN_SUBSCRIPTS}|{TIBETAN_VOWELS})({XML_TAGS_PATTERN})\n+({XML_TAGS_PATTERN})({TIBETAN_TSEG})'
    return re.sub(pattern, r'\1\2\3\4', text)


def fix_flying_vowels_and_linebreaks(text: str) -> str:
    """Fix all flying vowel and line break issues in Tibetan text."""
    if not text:
        return text
    result = fix_flying_vowels(text)
    result = fix_flying_subscripts(result)
    result = fix_flying_tseg(result)
    return result


def fix_hi_tag_spacing(text: str) -> str:
    """Fix spacing around <hi> tags based on Tibetan punctuation rules."""
    if not text:
        return text
    text = re.sub(rf'({TIBETAN_SHED})(<hi[^>]*>)', r'\1 \2', text)
    text = re.sub(rf'({TIBETAN_SHED})(</hi>)([^\s])', r'\1\2 \3', text)
    return text


def fix_toc_leader_dots(text: str) -> str:
    """
    Fix TOC leader dots - repeated DA (ད) characters used as dots in table of contents.
    
    In Dedris encoding, the 'd' character maps to DA (ད), but when used as
    leader dots in TOC entries (to connect title to page number), they should
    be tseg (་) characters instead.
    
    This converts 3+ consecutive ད characters to ་ characters.
    """
    if not text:
        return text
    # Replace 3 or more consecutive ད with the same number of ་
    pattern = r'ད{3,}'
    def replace_with_tseg(match):
        return TIBETAN_TSEG * len(match.group())
    return re.sub(pattern, replace_with_tseg, text)


def is_tibetan_char(char: str) -> bool:
    """Check if a character is in the Tibetan Unicode block."""
    if len(char) != 1:
        return False
    code = ord(char)
    return 0x0F00 <= code <= 0x0FFF


def count_tibetan_chars(text: str) -> int:
    """Count the number of Tibetan characters in a string."""
    return sum(1 for c in text if is_tibetan_char(c))


# Repeated volume title that often appears as a running header between TOC lines (wrongly merged into <small>).
_VOLUME_RUNNING_TITLE = "ཀུན་མཁྱེན་མི་ཕམ་རྒྱ་མཚོའི་གསུང་འབུམ།"


def fix_small_wrapped_volume_running_title(text: str) -> str:
    """
    Close <hi rend="small"> before a digit-only line + volume running title.

    Extraction can leave the repeated title inside a small-font span; the closing
    </hi> then appears on the title line without a matching open on that line.
    """
    if not text:
        return text
    esc = re.escape(_VOLUME_RUNNING_TITLE)
    # Close small on the TOC line when followed by page-number line + volume title + stray </hi>
    text = re.sub(
        rf'(<hi rend="small">[^\n]+)(?=\n<lb/>[0-9\u0f20-\u0f33]+\n<lb/>{esc}</hi>)',
        lambda m: m.group(1) if m.group(1).rstrip().endswith("</hi>") else m.group(1) + "</hi>",
        text,
    )
    # Retag the volume line as head (remove orphan </hi> semantics)
    text = re.sub(
        rf'\n<lb/>([0-9\u0f20-\u0f33]+)\n<lb/>{esc}</hi>',
        rf'\n<lb/>\1\n<lb/><hi rend="head">{_VOLUME_RUNNING_TITLE}</hi>',
        text,
    )
    return text


def strip_standalone_dkar_chag_kha_lines(text: str) -> str:
    """
    Drop lines that are only the repeated TOC column marker 'དཀར་ཆག ཀ༽'.

    These sit in the body (not in the top crop band) and duplicate real headings.
    Lines that wrap the same phrase inside <hi> are left unchanged.
    """
    if not text:
        return text
    pattern = r'(?:^|\n)\s*<lb/>དཀར་ཆག ཀ༽\s*(?=\n|$)'
    text = re.sub(pattern, "", text)
    return re.sub(r"\n{3,}", "\n\n", text)


# Unclosed <hi> on a line, next line is only leaked Latin page number + closing tag.
_SPLIT_HI_DIGIT_FOOTER = re.compile(
    r'^(\s*<lb/>[^\n]*<hi rend="(?:small|head)">(?:(?!</hi>).)*?)(\n<lb/>[0-9\uFF10-\uFF19]+</hi>)',
    re.MULTILINE,
)

# Same footer leak, but the opening <hi> was on an earlier line: previous line is only
# <lb/> + text with no '<' (no tags on that line), then <lb/>digits</hi>.
_SPLIT_PLAIN_LINE_DIGIT_FOOTER = re.compile(
    r"^(\s*<lb/>[^<\n]+)(\n<lb/>[0-9\uFF10-\uFF19]+</hi>)",
    re.MULTILINE,
)


def fix_split_hi_close_digit_footer_line(text: str) -> str:
    """
    When extraction splits ``</hi>`` across lines so the next line is ``<lb/>N</hi>`` (ASCII
    or fullwidth page leak), move ``</hi>`` to the end of the previous line and turn the
    footer line into ``<pb/>``.

    Handles (1) previous line still contains ``<hi rend="small|head">`` without ``</hi>``,
    and (2) previous line is plain ``<lb/>`` + text with no tags (``<hi>`` opened above).
    """
    if not text:
        return text
    text = _SPLIT_HI_DIGIT_FOOTER.sub(r"\1</hi>\n<pb/>", text)
    return _SPLIT_PLAIN_LINE_DIGIT_FOOTER.sub(r"\1</hi>\n<pb/>", text)


# Standalone leaked footer page numbers (ASCII / fullwidth only — not Tibetan ༡༢༣).
_FOOTER_PAGE_LINE = re.compile(
    r"^(\s*)<lb/>\s*([0-9\uFF10-\uFF19]+)\s*(</hi>)?\s*$",
    re.MULTILINE,
)


def _ascii_fw_digits_to_int(s: str) -> int:
    out = []
    for c in s:
        if "0" <= c <= "9":
            out.append(c)
        elif "\uFF10" <= c <= "\uFF19":
            out.append(chr(ord(c) - 0xFF10 + ord("0")))
    return int("".join(out)) if out else -1


def replace_odd_footer_page_lines_with_pb(text: str) -> str:
    """
    Replace stray footer lines that contain only a Latin page number with <pb/>.

    Extraction can leave lines like ``<lb/>1</hi>``, ``<lb/>3``, ``<lb/>5</hi>`` (ASCII or
    fullwidth digits). When the integer is **odd**, treat as a verso-style footer leak
    and emit a page break instead. Tibetan numerals (e.g. ༡) are left unchanged so TOC
    lines and body numbering are not affected.
    """

    def repl(m) -> str:
        n = _ascii_fw_digits_to_int(m.group(2))
        if n < 0 or n % 2 != 1:
            return m.group(0)
        return f"{m.group(1)}<pb/>"

    return _FOOTER_PAGE_LINE.sub(repl, text)


def fix_hi_balance(text: str) -> str:
    """Drop orphan </hi> and append missing </hi> so <hi rend=\"head|small\"> counts match."""
    if not text:
        return text
    pattern = re.compile(r'<hi rend="(?:head|small)">|</hi>')
    pos = 0
    parts = []
    depth = 0
    for m in pattern.finditer(text):
        parts.append(text[pos : m.start()])
        tok = m.group(0)
        if tok.startswith("<hi"):
            depth += 1
            parts.append(tok)
        else:
            if depth > 0:
                depth -= 1
                parts.append(tok)
        pos = m.end()
    parts.append(text[pos:])
    while depth > 0:
        parts.append("</hi>")
        depth -= 1
    return "".join(parts)


def fix_mixed_dedris_patterns(text: str) -> str:
    """
    Fix remaining mixed Dedris patterns that weren't converted during stream processing.

    Handles cases where ASCII Dedris stand-ins and Tibetan Unicode were in separate
    text streams and thus not detected as mixed content during conversion.

    Maps ASCII ``(`` / ``)`` to Tibetan ཡ / འ in these repairs, along with other stand-ins.
    """
    consonant_before_vowel = {
        '.': 'ད',
        '0': 'ས',
        '{': 'ཆ',
        '\\': 'ས',
        '/': 'ཤ',
        '(': 'ཡ',
        ')': 'འ',
        '}': 'ས',
        ',': 'ཐ',
    }

    syllable_before_consonant = {
        '.': 'དུ',
        '0': 'སུ',
        '{': 'ཆུ',
        '\\': 'སུ',
        '/': 'ཤུ',
        '(': 'ཡུ',
        ')': 'འུ',
        '}': 'སུ',
        ',': 'ཐུ',
    }

    tibetan_vowels_literal = 'ཱིེོུཾཿ'
    vowel_pattern = '[' + tibetan_vowels_literal + '\u0F71-\u0F84]'

    tibetan_consonants = 'ཀཁགངཅཆཇཉཏཐདནཔཕབམཙཚཛཝཞཟའཡརལཤསཧཨ'
    tsheg = '་'
    shad = '།'

    result = text

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = escaped_char + '(' + vowel_pattern + ')'
        result = re.sub(pattern, tibetan_consonant + r'\1', result)

    for ascii_char, tibetan_syllable in syllable_before_consonant.items():
        escaped_char = re.escape(ascii_char)
        pattern = (
            '([' + tibetan_consonants + '])'
            + escaped_char
            + '([' + tibetan_consonants + tsheg + '])'
        )
        result = re.sub(pattern, r'\1' + tibetan_syllable + r'\2', result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = escaped_char + '([' + tibetan_consonants + '])'
        result = re.sub(pattern, tibetan_consonant + r'\1', result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = escaped_char + tsheg
        result = re.sub(pattern, tibetan_consonant + tsheg, result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        pattern = (
            '([' + tibetan_consonants + tibetan_vowels_literal + '])'
            + escaped_char
            + '([' + shad + '])'
        )
        result = re.sub(pattern, r'\1' + tibetan_consonant + r'\2', result)

    result = re.sub(r'\.་', 'ད་', result)

    tibetan_range = '\u0F00-\u0FFF'
    hyphen_pattern = '([' + tibetan_range + '])-([' + tibetan_range + '])'

    result = re.sub(hyphen_pattern, r'\1' + tsheg + r'\2', result)
    result = re.sub(hyphen_pattern, r'\1' + tsheg + r'\2', result)

    result = re.sub(r'([' + tibetan_range + '])-(<(?:/hi|lb))', r'\1་\2', result)
    result = re.sub(r'(>)-([' + tibetan_range + '])', r'\1་\2', result)

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        result = re.sub(
            r'([' + tibetan_consonants + tibetan_vowels_literal + '])'
            + escaped_char
            + r'(<(?:\/hi|lb|,))',
            r'\1' + tibetan_consonant + r'\2',
            result,
        )

    for ascii_char, tibetan_consonant in consonant_before_vowel.items():
        escaped_char = re.escape(ascii_char)
        result = re.sub(
            r'([' + tibetan_consonants + tibetan_vowels_literal + '])' + escaped_char + r',',
            r'\1' + tibetan_consonant + ',',
            result,
        )

    result = re.sub(r'([' + tibetan_range + ']),', r'\1།', result)
    result = re.sub(r'([' + tibetan_range + ']),(<)', r'\1།\2', result)

    return result

