#!/usr/bin/env python3
"""
RTF Cleaning Module

All cleaning logic lives here. Patterns and shared constants (e.g. TIBETAN_TSHEG,
SHAD, EMPTY_HI_RE) are imported from rtf_issue_detector; this module only performs
removal/substitution. rtf_check_fix calls these cleaners after using the detector
to decide what to fix.

- rtf_issue_detector.py: detection patterns and functions (no cleaning)
- rtf_cleaner.py: this module — cleaning only
- rtf_check_fix.py: orchestrates scan (detector) and fix (cleaner)
"""

import re
from typing import Tuple, Dict, List
from pathlib import Path

# Import patterns and shared constants from detector (single source for detection + cleaning)
try:
    from rtf_issue_detector import (
        RTF_COMMAND_PATTERNS,
        SPURIOUS_PATTERNS,
        TIBETAN_RANGE,
        HI_WRAPPER_CHARS,
        SHAD,
        TIBETAN_TSHEG,
        EMPTY_HI_RE,
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

# --- Cleaning: HI (head) unwrap patterns (use HI_WRAPPER_CHARS, SHAD, EMPTY_HI_RE from detector) ---
HI_WRAPPER_PATTERNS = [
    # rend="head" or rend='head', single allowed character, replace with that character
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>([' + HI_WRAPPER_CHARS + r'])</hi>'), r'\1'),
]
HI_SHORT_HEAD_PATTERNS = [
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>-</hi>'), r'-'),
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>(བ)</hi>'), r'\1'),
    (re.compile(r'<hi\s+rend=["\']head["\']\s*>(༔)</hi>'), r'\1'),
]
HI_SHORT_HEAD_1_2_RE = re.compile(r'<hi\s+rend=["\']head["\']\s*>([^<]{1,2})</hi>')


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
        """Remove RTF command patterns from text (one subn per pattern). Processes in chunks so the whole body is cleaned."""
        removal_count = 0
        parts = []
        rest = text
        while rest:
            chunk = rest[:MAX_BODY_LEN_FOR_REGEX]
            rest = rest[MAX_BODY_LEN_FOR_REGEX:]
            for pattern_re, _ in self._rtf_compiled:
                chunk, n = pattern_re.subn('', chunk)
                removal_count += n
            parts.append(chunk)
        return ''.join(parts), removal_count

    def clean_spurious_text(self, text: str) -> Tuple[str, int]:
        """Remove spurious text patterns (one subn per pattern). Processes in chunks so the whole body is cleaned (e.g. underscores in tail of large files)."""
        removal_count = 0
        parts = []
        rest = text
        while rest:
            chunk = rest[:MAX_BODY_LEN_FOR_REGEX]
            rest = rest[MAX_BODY_LEN_FOR_REGEX:]
            for pattern_re, _ in self._spurious_compiled:
                chunk, n = pattern_re.subn('', chunk)
                removal_count += n
            for pattern_re, _ in self._additional_compiled:
                chunk, n = pattern_re.subn('', chunk)
                removal_count += n
            parts.append(chunk)
        return ''.join(parts), removal_count

    def clean_hi_wrappers(self, text: str) -> Tuple[str, int]:
        """Unwrap <hi rend="head"> around single vowel/shad/tsek (ི ུ ེ ོ ། ་); keep the character, remove the tag.
        Also unwraps short heads: single dash, བ, ༔, and 1-2 char fragments without shad.
        Removes empty <hi rend="..."></hi> tags (open/close with no content). Processes in chunks so the whole body is cleaned."""
        def replace_short_head(m):
            content = m.group(1)
            return content if SHAD not in content else m.group(0)
        removal_count = 0
        parts = []
        rest = text
        while rest:
            chunk = rest[:MAX_BODY_LEN_FOR_REGEX]
            rest = rest[MAX_BODY_LEN_FOR_REGEX:]
            chunk, n = EMPTY_HI_RE.subn('', chunk)
            removal_count += n
            for pattern_re, repl in HI_WRAPPER_PATTERNS:
                chunk, n = pattern_re.subn(repl, chunk)
                removal_count += n
            for pattern_re, repl in HI_SHORT_HEAD_PATTERNS:
                chunk, n = pattern_re.subn(repl, chunk)
                removal_count += n
            for m in HI_SHORT_HEAD_1_2_RE.finditer(chunk):
                if SHAD not in m.group(1):
                    removal_count += 1
            chunk = HI_SHORT_HEAD_1_2_RE.sub(replace_short_head, chunk)
            parts.append(chunk)
        return ''.join(parts), removal_count

    def clean_dedris_corruption(self, text: str) -> Tuple[str, int]:
        """Apply table-based Dedris corruption substitutions (e.g. ,ོ→དོ, ་.་→་ན་). Processes in chunks so the whole body is cleaned."""
        if fix_dedris_corruption_with_count is None:
            return text, 0
        total_count = 0
        parts = []
        rest = text
        while rest:
            chunk = rest[:MAX_BODY_LEN_FOR_REGEX]
            rest = rest[MAX_BODY_LEN_FOR_REGEX:]
            chunk, count = fix_dedris_corruption_with_count(chunk)
            total_count += count
            parts.append(chunk)
        return ''.join(parts), total_count
    
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
    
    def clean_tsheg_run_spaces(self, text: str) -> Tuple[str, int]:
        """
        Remove single space/tab after ་ (tsheg) and after ། (shad) when the next
        character is Tibetan. Call only when body_has_many_tsheg_spaces(text) is True.
        Returns (cleaned_text, replacement_count).
        """
        count = 0
        cleaned, n1 = re.subn(r'་[\s\t](?=[\u0F00-\u0FFF])', TIBETAN_TSHEG, text)
        count += n1
        cleaned, n2 = re.subn(r'།[\s\t](?=[\u0F00-\u0FFF])', SHAD, cleaned)
        count += n2
        return cleaned, count

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


def clean_tsheg_run_spaces(text: str) -> Tuple[str, int]:
    """
    Remove space/tab after ་ and ། when next char is Tibetan.
    Call only when body_has_many_tsheg_spaces(body_text) is True.
    """
    return get_cleaner().clean_tsheg_run_spaces(text)


def clean_all(text: str) -> Dict[str, int]:
    """Apply all cleaning operations to text."""
    return get_cleaner().clean_all(text)

