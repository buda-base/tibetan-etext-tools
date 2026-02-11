#!/usr/bin/env python3
"""
RTF Issue Detection Module

This module contains all the patterns and functions for detecting RTF commands
and spurious text in XML files.
"""

import re
from pathlib import Path
from typing import List, Tuple

# RTF command patterns to detect
# To add new RTF command patterns, simply add them to this list.
# Format: (regex_pattern, description)
RTF_COMMAND_PATTERNS = [
    # Page number commands
    (r'PAGE\s+\*\s+MERGEFORMAT\s+\d+', 'PAGE * MERGEFORMAT'),
    (r'NUMPAGES\s+\*\s+MERGEFORMAT', 'NUMPAGES * MERGEFORMAT'),
    (r'PAGE\s+OF\s+NUMPAGES', 'PAGE OF NUMPAGES'),
    (r'\u2026\u00A1', 'Spurious ellipsis + inverted exclamation'),
    
    # Date/time commands
    (r'DATE\s+\*\s+MERGEFORMAT', 'DATE * MERGEFORMAT'),
    (r'TIME\s+\*\s+MERGEFORMAT', 'TIME * MERGEFORMAT'),
    
    # Reference commands
    (r'REF\s+\w+\s+\*\s+MERGEFORMAT', 'REF * MERGEFORMAT'),
    
    # Other common RTF field codes
    (r'SEQ\s+\w+', 'SEQ field'),
    (r'STYLEREF\s+\d+', 'STYLEREF'),
    (r'TOC\s+\\', 'TOC field'),
    
    # General MERGEFORMAT pattern
    (r'\w+\s+\*\s+MERGEFORMAT', 'MERGEFORMAT field'),
    
    # New patterns for PAGE numbers
    (r'PAGE\s+\d+', 'PAGE followed by number'),
    # PAGE with dashes before and after (e.g., -PAGE 228-, --PAGE 229-)
    # Use negative lookahead to catch each occurrence separately even when adjacent
    (r'[-–—]+PAGE\s+\d+[-–—]+(?![–—]*PAGE)', 'PAGE with dashes before and after'),
    
    # Multiple PAGE numbers in one line (bounded [^<]{0,500} to avoid catastrophic backtracking)
    (r'[^<]{0,500}PAGE\s+\d+[^<]{0,500}PAGE\s+\d+', 'Multiple PAGE numbers in one line'),
    (r'»-PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'PAGE numbers with » prefix and three PAGE markers'),
(r'»-PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'PAGE numbers with » prefix and two PAGE markers'),
(r'»PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'PAGE numbers with » prefix (no leading dash)'),
(r'PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'PAGE numbers without leading dash or »'),
    # French quotation marks (guillemets)
(r'[«»]', 'French quotation marks (guillemets)'),

# Multiple PAGE numbers with dashes in sequence
(r'[-–—]+PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'Multiple PAGE numbers with dashes in sequence'),
(r'[-–—]+PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'Two PAGE numbers with dashes in sequence'),

# PAGE PAGE pattern
(r'PAGE\s+PAGE\s+[-–—]+PAGE\s+\d+[-–—]+', 'PAGE PAGE followed by PAGE number pattern'),
# French quotation marks (guillemets)
(r'[«»]', 'French quotation marks (guillemets)'),

# Multiple PAGE numbers with dashes in sequence
(r'[-–—]+PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'Multiple PAGE numbers with dashes in sequence'),
(r'[-–—]+PAGE\s+\d+[-–—]+PAGE\s+\d+[-–—]+', 'Two PAGE numbers with dashes in sequence'),

# PAGE PAGE patterns (various forms)
(r'PAGE\s+PAGE\s+[-–—]+PAGE\s+\d+[-–—]+', 'PAGE PAGE followed by PAGE number pattern'),
(r'\d+PAGE\s+PAGE\s+[-–—]+', 'Number followed by PAGE PAGE and dashes'),
(r'PAGE\s+PAGE\s+[-–—]+', 'PAGE PAGE followed by dashes'),
# Standalone dashes (multiple dashes that are spurious)
(r'[-–—]{3,}', 'Standalone multiple dashes'),
]

# Spurious text patterns
# To add new spurious elements, simply add them to this list.
# Format: (regex_pattern, description)
SPURIOUS_PATTERNS = [
    (r'Got these', 'Spurious "Got these" text'),
    # Semicolon patterns - one, two, or three
    (r'<lb/>\s*;', '<lb/> followed by single semicolon'),
    (r'<lb/>\s*;;', '<lb/> followed by two semicolons'),
    (r'<lb/>\s*;;;', '<lb/> followed by three semicolons'),
    (r'<lb/>\s*;{4,}', '<lb/> followed by four or more semicolons'),
    # Standalone semicolons (not part of Tibetan text)
    (r'(?<![\u0F00-\u0FFF])\s*;\s*(?![\u0F00-\u0FFF])', 'Standalone semicolon'),
    # <lb/> followed by single letter (like 'p', 'r', etc.)
    (r'<lb/>\s*([a-zA-Z])(?:\s|$)', '<lb/> followed by single letter'),
    # Multiple line breaks with semicolons
    (r'<lb/>\s*<lb/>\s*;+', 'Multiple line breaks with semicolons'),
    # <lb/> followed by non-Tibetan text
    (r'<lb/>\s*([A-Za-z]{2,})(?:\s|$)', '<lb/> followed by ASCII text'),
    # PAGE numbers with various dash patterns
    (r'[-–—]+\s*PAGE\s+\d+\s*[-–—]+', 'PAGE number with dashes'),
    (r'PAGE\s+\d+\s*[-–—]+\s*PAGE\s+\d+', 'Multiple PAGE numbers with dashes'),
    
    # Standalone numbers (4 digits, likely years or page numbers)
    (r'(?<![\u0F00-\u0FFF])\b\d{4}\b(?![\u0F00-\u0FFF])', 'Standalone 4-digit number'),
    
    # RTF control characters appearing as text
    (r'\\u\d+\?', 'RTF Unicode escape sequence'),
    (r'\\u\d+\'[a-z]+', 'RTF control character'),
    
    # Volume/file name patterns
    (r'volume_\d+_\d+', 'Volume file name pattern'),
    (r'[¡\u00A1][¤\u00A4]([¡\u00A1][¤\u00A4])+', 'Repeating inverted exclamation and currency symbol pattern'),
    (r'(·\u00A1\u00A4)+', 'Middle dot with inverted exclamation-currency sequence'),
    (r'\u00B7+', 'Standalone middle dot(s)'),
    (r'[¡\u00A1][¤\u00A4]\d+', 'Inverted exclamation-currency symbol followed by number'),
    
    # Also catch the RTF encoded version if it appears in XML
    (r'\\u161[\\\'a1]*\\u164[\\\'a4]*', 'RTF encoded inverted exclamation-currency pattern'),
    (r'««', 'Double French quotation marks (guillemets)'),
    (r'«»', 'Mixed French quotation marks'),
    # Mojibake/RTF artifacts (¡ = U+00A1, Ã = U+00C3, ¶ = U+00B6)
    (r'¡¡ÃÃ', 'Inverted exclamation + A-tilde mojibake'),
    (r'¡¡¶¶', 'Inverted exclamation + pilcrow mojibake'),
    # Two or more ¡ immediately after Tibetan (artifact from bad encoding)
    (r'(?<=[\u0F00-\u0FFF])¡{2,}', 'Inverted exclamation run after Tibetan'),
    # Standalone PAGE between <lb/> and </p> (fixed-length lookbehind so we only remove PAGE)
    (r'(?<=<lb/>)PAGE(?=</p>)', 'Lone PAGE between <lb/> and </p>'),
    (r'(?<=<lb/> )PAGE(?=</p>)', 'Lone PAGE between <lb/> and </p> (with space)'),
    (r'PAGE\s+PAGE(?=\s*<)', 'PAGE PAGE immediately before tag'),
    # Add more spurious patterns here as needed
    # Example:
    # (r'pattern_to_match', 'Description of what this pattern matches'),
]

# <hi rend="head"> around single vowel/shad/tsek (should be unwrapped: keep char, remove tag)
# Same character set as rtf_cleaner.HI_WRAPPER_CHARS: ་ ། ི ུ ེ ོ
HI_WRAPPER_CHARS = '\u0F0B\u0F0D\u0F72\u0F74\u0F7A\u0F7C'
HI_WRAPPER_DETECT_RE = re.compile(
    r'<hi\s+rend=["\']head["\']\s*>([' + HI_WRAPPER_CHARS + r'])</hi>'
)
# <hi rend="head"> around short multi-char fragment (no shad ། = not a real heading; unwrap)
HI_HEAD_MULTI_DETECT_RE = re.compile(
    r'<hi\s+rend=["\']head["\']\s*>([^<]{2,20})</hi>'
)
# Short head: single dash, single Tibetan consonant/vowel/shad (བ ི ོ ༔ etc.), or 1-2 chars without shad
HI_HEAD_SHORT_DETECT_RE = re.compile(
    r'<hi\s+rend=["\']head["\']\s*>([^<]{1,2})</hi>'
)
SHAD = '\u0F0D'  # ། — real headings typically contain this

# Dedris corruption: comma/dot/curly/0 in Tibetan context (used by rtf_check_fix to mark files for cleaning)
DEDRIS_CORRUPTION_RE = re.compile(
    r',ོ|་\.་|[{}]'
    r'|\.[\u0F71-\u0F84]'   # dot + Tibetan vowel (.ེ .ོ etc.)
    r'|[\u0F00-\u0FFF]\.'   # Tibetan + dot (འ. མེ. etc.)
    r'|0་'                   # digit 0 + tsheg
)

# Non-Tibetan text patterns (lines with no Tibetan characters)
TIBETAN_RANGE = r'[\u0F00-\u0FFF]'
NON_TIBETAN_PATTERN = re.compile(rf'^[^{TIBETAN_RANGE}\s<>&;]*$', re.MULTILINE)

# Pre-compile patterns once for speed (avoid recompiling on every file/line)
RTF_COMMAND_PATTERNS_COMPILED = [(re.compile(p, re.I), desc) for p, desc in RTF_COMMAND_PATTERNS]
SPURIOUS_PATTERNS_COMPILED = [(re.compile(p, re.I), desc) for p, desc in SPURIOUS_PATTERNS]
_TIBETAN_RE = re.compile(TIBETAN_RANGE)
_ASCII_3PLUS_RE = re.compile(r'[A-Za-z]{3,}')


# Cap line length for regex to avoid runaway time/memory on huge lines (like convert: one file at a time)
MAX_LINE_LEN_FOR_REGEX = 8000


def find_rtf_commands(text: str, file_path: Path) -> List[Tuple[int, str, str, str]]:
    """Find RTF command patterns in text (pre-compiled regex; long lines capped to avoid CPU/memory blowup)."""
    issues = []
    lines = text.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Avoid catastrophic backtracking on very long lines (same memory/speed as convert)
        line_to_scan = line[:MAX_LINE_LEN_FOR_REGEX] if len(line) > MAX_LINE_LEN_FOR_REGEX else line
        for pattern_re, description in RTF_COMMAND_PATTERNS_COMPILED:
            for match in pattern_re.finditer(line_to_scan):
                start = max(0, match.start() - 20)
                end = min(len(line_to_scan), match.end() + 20)
                context = line_to_scan[start:end].strip()
                issues.append((line_num, description, match.group(0), context))
        for pattern_re, description in SPURIOUS_PATTERNS_COMPILED:
            for match in pattern_re.finditer(line_to_scan):
                start = max(0, match.start() - 20)
                end = min(len(line_to_scan), match.end() + 20)
                context = line_to_scan[start:end].strip()
                issues.append((line_num, description, match.group(0), context))
        for match in HI_WRAPPER_DETECT_RE.finditer(line_to_scan):
            start = max(0, match.start() - 20)
            end = min(len(line_to_scan), match.end() + 20)
            context = line_to_scan[start:end].strip()
            issues.append((line_num, 'HI wrapper (unwrap)', match.group(0), context))
        for match in HI_HEAD_SHORT_DETECT_RE.finditer(line_to_scan):
            content = match.group(1)
            if SHAD not in content:  # no shad = short head to unwrap
                start = max(0, match.start() - 20)
                end = min(len(line_to_scan), match.end() + 20)
                context = line_to_scan[start:end].strip()
                issues.append((line_num, 'Short head (unwrap)', match.group(0), context))
    
    return issues


def find_non_tibetan_lines(text: str, file_path: Path) -> List[Tuple[int, str]]:
    """Find lines that contain no Tibetan characters (uses pre-compiled regex)."""
    issues = []
    lines = text.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        if not line.strip() or line.strip().startswith('<'):
            continue
        if _TIBETAN_RE.search(line):
            continue
        stripped = line.strip()
        if stripped and not stripped.startswith('<') and not stripped.endswith('>') and _ASCII_3PLUS_RE.search(stripped):
            issues.append((line_num, stripped[:50]))
    
    return issues

