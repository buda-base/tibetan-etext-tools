#!/usr/bin/env python3
"""
RTF Cleaning Module

This module contains all cleaning functions for removing RTF commands and spurious text.
All cleaning operations are centralized here for easy maintenance and extension.

Module Structure:
- rtf_issue_detector.py: Defines patterns (RTF_COMMAND_PATTERNS, SPURIOUS_PATTERNS) and detection functions
- rtf_cleaner.py: This module - provides cleaning functions using patterns from detector
- rtf_check_fix.py: Main script that uses both detector and cleaner modules

To add new spurious elements:
1. Add the pattern to SPURIOUS_PATTERNS in rtf_issue_detector.py
2. The pattern will automatically be detected and cleaned by this module
3. No changes needed to rtf_cleaner.py or rtf_check_fix.py
"""

import re
from typing import Tuple, Dict, List
from pathlib import Path

# Import patterns from detector module
try:
    from rtf_issue_detector import (
        RTF_COMMAND_PATTERNS,
        SPURIOUS_PATTERNS,
        TIBETAN_RANGE
    )
except ImportError:
    print("Error: Could not import from rtf_issue_detector.py")
    raise
try:
    from tibetan_text_fixes import fix_dedris_corruption_with_count
except ImportError:
    fix_dedris_corruption_with_count = None


# Cap body length for regex so fixing never gets stuck on huge files (same idea as detector line cap)
MAX_BODY_LEN_FOR_REGEX = 400_000
# Cap lines processed for non-Tibetan removal so huge files don't slow fixing
MAX_LINES_FOR_NON_TIBETAN = 50_000

# Unwrap <hi rend="head"> (or rend='head') around single vowel/shad/tsek: keep the character, remove the tag.
# Vowels ིེོུ (U+0F72, 0F74, 0F7A, 0F7C), shad ། (U+0F0D), tsek ་ (U+0F0B) - belong on previous element.
HI_WRAPPER_CHARS = '\u0F0B\u0F0D\u0F72\u0F74\u0F7A\u0F7C'  # ་ ། ི ུ ེ ོ
HI_WRAPPER_PATTERNS = [
    # rend="head" or rend='head', single allowed character, replace with that character
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>([' + HI_WRAPPER_CHARS + r'])</hi>'), r'\1'),
]
# Short head: single dash, or 1-2 chars without shad (unwrap; keep content, remove tag)
SHAD_CHAR = '\u0F0D'  # །
HI_SHORT_HEAD_PATTERNS = [
    # Single ASCII dash
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>-</hi>'), r'-'),
    # Single Tibetan consonant བ or shad variant ༔ (U+0F14)
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>(བ)</hi>'), r'\1'),
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>(༔)</hi>'), r'\1'),
]
# 1-2 char fragment: unwrap only when content has no shad (use callback in cleaner)
HI_SHORT_HEAD_1_2_RE = re.compile(r'<hi\s+rend=["\']head["\']\s*>([^<]{1,2})</hi>')

# Empty <hi rend="..."></hi> (no content or only whitespace) — remove entirely
EMPTY_HI_RE = re.compile(r'<hi\s+rend=["\'][^"\']*["\']\s*>\s*</hi>')


class RTFCleaner:
    """
    Centralized RTF cleaning class.
    Pre-compiles regex; caps body length so fixing never hangs on huge files.
    """
    
    def __init__(self):
        """Initialize the cleaner with pre-compiled patterns from the detector module."""
        self.rtf_patterns = RTF_COMMAND_PATTERNS
        self.spurious_patterns = SPURIOUS_PATTERNS
        self.tibetan_range = TIBETAN_RANGE
        self._rtf_compiled = [(re.compile(p, re.I), desc) for p, desc in self.rtf_patterns]
        self._spurious_compiled = [(re.compile(p, re.I), desc) for p, desc in self.spurious_patterns]
        self._tibetan_re = re.compile(self.tibetan_range)
        self._ascii_3plus_re = re.compile(r'[A-Za-z]{3,}')
        self.additional_cleaning_patterns = []
        self._additional_compiled = []
    
    def _cap_body(self, text: str) -> Tuple[str, str]:
        """Return (prefix to process, suffix to keep) so we never hang on huge bodies."""
        if len(text) > MAX_BODY_LEN_FOR_REGEX:
            return text[:MAX_BODY_LEN_FOR_REGEX], text[MAX_BODY_LEN_FOR_REGEX:]
        return text, ''
    
    def clean_rtf_commands(self, text: str) -> Tuple[str, int]:
        """Remove RTF command patterns from text (one subn per pattern, capped length)."""
        prefix, suffix = self._cap_body(text)
        removal_count = 0
        for pattern_re, _ in self._rtf_compiled:
            prefix, n = pattern_re.subn('', prefix)
            removal_count += n
        return prefix + suffix, removal_count
    
    def clean_spurious_text(self, text: str) -> Tuple[str, int]:
        """Remove spurious text patterns (one subn per pattern, capped length)."""
        prefix, suffix = self._cap_body(text)
        removal_count = 0
        for pattern_re, _ in self._spurious_compiled:
            prefix, n = pattern_re.subn('', prefix)
            removal_count += n
        for pattern_re, _ in self._additional_compiled:
            prefix, n = pattern_re.subn('', prefix)
            removal_count += n
        return prefix + suffix, removal_count
    
    def clean_hi_wrappers(self, text: str) -> Tuple[str, int]:
        """Unwrap <hi rend="head"> around single vowel/shad/tsek (ི ུ ེ ོ ། ་); keep the character, remove the tag.
        Also unwraps short heads: single dash, བ, ༔, and 1-2 char fragments without shad.
        Removes empty <hi rend="..."></hi> tags (open/close with no content)."""
        prefix, suffix = self._cap_body(text)
        removal_count = 0
        # Remove empty <hi rend="small"></hi>, <hi rend="head"></hi>, etc.
        prefix, n = EMPTY_HI_RE.subn('', prefix)
        removal_count += n
        for pattern_re, repl in HI_WRAPPER_PATTERNS:
            prefix, n = pattern_re.subn(repl, prefix)
            removal_count += n
        for pattern_re, repl in HI_SHORT_HEAD_PATTERNS:
            prefix, n = pattern_re.subn(repl, prefix)
            removal_count += n
        # 1-2 char head: unwrap only if content has no shad
        def replace_short_head(m):
            content = m.group(1)
            return content if SHAD_CHAR not in content else m.group(0)
        for m in HI_SHORT_HEAD_1_2_RE.finditer(prefix):
            if SHAD_CHAR not in m.group(1):
                removal_count += 1
        prefix = HI_SHORT_HEAD_1_2_RE.sub(replace_short_head, prefix)
        return prefix + suffix, removal_count
    
    def clean_dedris_corruption(self, text: str) -> Tuple[str, int]:
        """Apply table-based Dedris corruption substitutions (e.g. ,ོ→དོ, ་.་→་ན་)."""
        if fix_dedris_corruption_with_count is None:
            return text, 0
        prefix, suffix = self._cap_body(text)
        prefix, count = fix_dedris_corruption_with_count(prefix)
        return prefix + suffix, count
    
    def clean_non_tibetan_lines(self, text: str) -> Tuple[str, int]:
        """Remove lines that contain no Tibetan characters (capped line count for huge files)."""
        lines = text.split('\n')
        if len(lines) > MAX_LINES_FOR_NON_TIBETAN:
            to_process = lines[:MAX_LINES_FOR_NON_TIBETAN]
            rest = lines[MAX_LINES_FOR_NON_TIBETAN:]
        else:
            to_process = lines
            rest = []
        cleaned_lines = []
        removal_count = 0
        for line in to_process:
            if not line.strip() or line.strip().startswith('<'):
                cleaned_lines.append(line)
                continue
            if not self._tibetan_re.search(line):
                stripped = line.strip()
                if stripped and not stripped.startswith('<') and not stripped.endswith('>') and self._ascii_3plus_re.search(stripped):
                    removal_count += 1
                    continue
            cleaned_lines.append(line)
        return '\n'.join(cleaned_lines + rest), removal_count
    
    def clean_all(self, text: str) -> Dict[str, int]:
        """
        Apply all cleaning operations to text.
        
        Args:
            text: Text to clean
            
        Returns:
            Dictionary with cleaning statistics:
            {
                'cleaned_text': str,
                'rtf_commands_removed': int,
                'spurious_text_removed': int,
                'non_tibetan_lines_removed': int,
                'total_fixes': int
            }
        """
        cleaned = text
        stats = {
            'rtf_commands_removed': 0,
            'spurious_text_removed': 0,
            'hi_wrappers_removed': 0,
            'dedris_corruption_fixes': 0,
            'non_tibetan_lines_removed': 0,
            'total_fixes': 0
        }
        
        # Clean RTF commands
        cleaned, rtf_count = self.clean_rtf_commands(cleaned)
        stats['rtf_commands_removed'] = rtf_count
        
        # Clean spurious text
        cleaned, spurious_count = self.clean_spurious_text(cleaned)
        stats['spurious_text_removed'] = spurious_count
        
        # Unwrap <hi rend="head"> around single vowel/shad and short heads
        cleaned, hi_wrappers_count = self.clean_hi_wrappers(cleaned)
        stats['hi_wrappers_removed'] = hi_wrappers_count
        
        # Dedris corruption substitution (e.g. ,ོ→དོ, ་.་→་ན་)
        cleaned, corruption_count = self.clean_dedris_corruption(cleaned)
        stats['dedris_corruption_fixes'] = corruption_count
        
        # Clean non-Tibetan lines
        cleaned, non_tibetan_count = self.clean_non_tibetan_lines(cleaned)
        stats['non_tibetan_lines_removed'] = non_tibetan_count
        
        stats['total_fixes'] = rtf_count + spurious_count + hi_wrappers_count + corruption_count + non_tibetan_count
        stats['cleaned_text'] = cleaned
        
        return stats
    
    def add_cleaning_pattern(self, pattern: str, description: str, pattern_type: str = 'spurious'):
        """Add a new cleaning pattern at runtime (compiles and caches)."""
        compiled = re.compile(pattern, re.I)
        if pattern_type == 'rtf':
            self.rtf_patterns.append((pattern, description))
            self._rtf_compiled.append((compiled, description))
        elif pattern_type == 'spurious':
            self.spurious_patterns.append((pattern, description))
            self._spurious_compiled.append((compiled, description))
        else:
            self.additional_cleaning_patterns.append((pattern, description))
            self._additional_compiled.append((compiled, description))


# Global cleaner instance for convenience
_cleaner_instance = None


def get_cleaner() -> RTFCleaner:
    """Get or create the global cleaner instance."""
    global _cleaner_instance
    if _cleaner_instance is None:
        _cleaner_instance = RTFCleaner()
    return _cleaner_instance


# Convenience functions that use the global cleaner
def clean_rtf_commands(text: str) -> Tuple[str, int]:
    """Remove RTF command patterns from text."""
    return get_cleaner().clean_rtf_commands(text)


def clean_spurious_text(text: str) -> Tuple[str, int]:
    """Remove spurious text patterns from text."""
    return get_cleaner().clean_spurious_text(text)


def clean_hi_wrappers(text: str) -> Tuple[str, int]:
    """Unwrap <hi rend="head"> around single vowel (ི) or shad (།); keep the character, remove the tag."""
    return get_cleaner().clean_hi_wrappers(text)


def clean_dedris_corruption(text: str) -> Tuple[str, int]:
    """Apply table-based Dedris corruption substitutions (e.g. ,ོ→དོ, ་.་→་ན་)."""
    return get_cleaner().clean_dedris_corruption(text)


def clean_non_tibetan_lines(text: str) -> Tuple[str, int]:
    """Remove lines that contain no Tibetan characters."""
    return get_cleaner().clean_non_tibetan_lines(text)


def clean_all(text: str) -> Dict[str, int]:
    """Apply all cleaning operations to text."""
    return get_cleaner().clean_all(text)

