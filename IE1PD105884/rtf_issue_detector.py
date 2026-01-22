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
    
    # Multiple PAGE numbers in one line
    (r'[^<]*PAGE\s+\d+[^<]*PAGE\s+\d+', 'Multiple PAGE numbers in one line'),
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
    # PAGE patterns with double dashes and spaces
    (r'»-?\s*PAGE\s+\d+\s*--\s*PAGE\s+\d+', 'PAGE numbers with » prefix and double dashes with spaces'),
    (r'PAGE\s+\d+\s*--\s*PAGE\s+\d+\s*--\s*PAGE\s+\d+', 'Three PAGE numbers with double dashes and spaces'),
    # Standalone numbers (4 digits, likely years or page numbers)
    (r'(?<![\u0F00-\u0FFF])\b\d{4}\b(?![\u0F00-\u0FFF])', 'Standalone 4-digit number'),
    
    # RTF control characters appearing as text
    (r'\\u\d+\?', 'RTF Unicode escape sequence'),
    (r'\\u\d+\'[a-z]+', 'RTF control character'),
    
    # Duplicate text patterns
    (r'([\u0F00-\u0FFF]{5,})\1', 'Duplicate Tibetan text'),
    
    # Volume/file name patterns
    (r'volume_\d+_\d+', 'Volume file name pattern'),
    (r'[¡\u00A1][¤\u00A4]([¡\u00A1][¤\u00A4])+', 'Repeating inverted exclamation and currency symbol pattern'),
    (r'[¡\u00A1][¤\u00A4]\d+', 'Inverted exclamation-currency symbol followed by number'),
    
    # Also catch the RTF encoded version if it appears in XML
    (r'\\u161[\\\'a1]*\\u164[\\\'a4]*', 'RTF encoded inverted exclamation-currency pattern'),
    (r'««', 'Double French quotation marks (guillemets)'),
(r'«»', 'Mixed French quotation marks'),
    # Add more spurious patterns here as needed
    # Example:
    # (r'pattern_to_match', 'Description of what this pattern matches'),
]

# Non-Tibetan text patterns (lines with no Tibetan characters)
TIBETAN_RANGE = r'[\u0F00-\u0FFF]'
NON_TIBETAN_PATTERN = re.compile(rf'^[^{TIBETAN_RANGE}\s<>&;]*$', re.MULTILINE)


def find_rtf_commands(text: str, file_path: Path) -> List[Tuple[int, str, str, str]]:
    """Find RTF command patterns in text."""
    issues = []
    lines = text.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Check RTF command patterns
        for pattern, description in RTF_COMMAND_PATTERNS:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                # Get context (surrounding text, max 50 chars each side)
                start = max(0, match.start() - 20)
                end = min(len(line), match.end() + 20)
                context = line[start:end].strip()
                
                issues.append((
                    line_num,
                    description,
                    match.group(0),
                    context  # Add context
                ))
        
        # Check spurious patterns
        for pattern, description in SPURIOUS_PATTERNS:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                # Get context
                start = max(0, match.start() - 20)
                end = min(len(line), match.end() + 20)
                context = line[start:end].strip()
                
                issues.append((
                    line_num,
                    description,
                    match.group(0),
                    context  # Add context
                ))
    
    return issues


def find_non_tibetan_lines(text: str, file_path: Path) -> List[Tuple[int, str]]:
    """Find lines that contain no Tibetan characters (potential RTF artifacts)."""
    issues = []
    lines = text.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Skip XML tags and empty lines
        if not line.strip() or line.strip().startswith('<'):
            continue
        
        # Check if line has any Tibetan characters
        if not re.search(TIBETAN_RANGE, line):
            # Check if it's not just whitespace or XML
            stripped = line.strip()
            if stripped and not stripped.startswith('<') and not stripped.endswith('>'):
                # Check if it contains ASCII text (potential RTF command)
                if re.search(r'[A-Za-z]{3,}', stripped):
                    issues.append((
                        line_num,
                        stripped[:50]  # First 50 chars
                    ))
    
    return issues

