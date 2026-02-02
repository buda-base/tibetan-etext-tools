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


class RTFCleaner:
    """
    Centralized RTF cleaning class.
    All cleaning operations are performed through this class.
    """
    
    # Precompiled regexes (shared across instances)
    _TIBETAN_RE = re.compile(TIBETAN_RANGE)
    _ASCII_WORD_RE = re.compile(r'[A-Za-z]{3,}')
    
    _MAX_LINE_LEN_FOR_BACKREF = 500
    _MAX_LINE_LEN_OPEN_ENDED = 2000

    def __init__(self):
        """Initialize the cleaner with patterns from the detector module."""
        self.rtf_patterns = RTF_COMMAND_PATTERNS
        self.spurious_patterns = SPURIOUS_PATTERNS
        self.tibetan_range = TIBETAN_RANGE
        self._rtf_compiled = [(re.compile(p, re.IGNORECASE), d) for p, d in self.rtf_patterns]
        self._rtf_safe = [(r, d) for r, d in self._rtf_compiled if 'Multiple PAGE numbers in one line' not in d]
        self._rtf_long_line_unsafe = [(r, d) for r, d in self._rtf_compiled if 'Multiple PAGE numbers in one line' in d]
        self._spurious_compiled = [(re.compile(p, re.IGNORECASE), d) for p, d in self.spurious_patterns]
        self._spurious_safe = [(r, d) for r, d in self._spurious_compiled if 'Duplicate Tibetan' not in d]
        self._spurious_long_line_unsafe = [(r, d) for r, d in self._spurious_compiled if 'Duplicate Tibetan' in d]
        self.additional_cleaning_patterns = []
        self._additional_compiled = []
    
    def clean_rtf_commands(self, text: str) -> Tuple[str, int]:
        """
        Remove RTF command patterns from text.
        Open-ended patterns (e.g. [^<]*) run only on short lines to avoid slowdown.
        """
        cleaned = text
        removal_count = 0
        for regex, _ in self._rtf_safe:
            matches = list(regex.finditer(cleaned))
            if matches:
                for match in reversed(matches):
                    cleaned = cleaned[:match.start()] + cleaned[match.end():]
                    removal_count += 1
        if self._rtf_long_line_unsafe:
            lines = cleaned.split('\n')
            new_lines = []
            for line in lines:
                if len(line) <= RTFCleaner._MAX_LINE_LEN_OPEN_ENDED:
                    for regex, _ in self._rtf_long_line_unsafe:
                        matches = list(regex.finditer(line))
                        if matches:
                            for match in reversed(matches):
                                line = line[:match.start()] + line[match.end():]
                                removal_count += 1
                new_lines.append(line)
            cleaned = '\n'.join(new_lines)
        return cleaned, removal_count
    
    def clean_spurious_text(self, text: str) -> Tuple[str, int]:
        """
        Remove spurious text patterns from text.
        Backref-heavy patterns (e.g. Duplicate Tibetan) run only on short lines to avoid slowdown.
        """
        cleaned = text
        removal_count = 0
        for regex, _ in self._spurious_safe:
            matches = list(regex.finditer(cleaned))
            if matches:
                for match in reversed(matches):
                    cleaned = cleaned[:match.start()] + cleaned[match.end():]
                    removal_count += 1
        # Run backref-heavy patterns per line and only on short lines
        if self._spurious_long_line_unsafe:
            lines = cleaned.split('\n')
            new_lines = []
            for line in lines:
                if len(line) <= self._MAX_LINE_LEN_FOR_BACKREF:
                    for regex, _ in self._spurious_long_line_unsafe:
                        matches = list(regex.finditer(line))
                        if matches:
                            for match in reversed(matches):
                                line = line[:match.start()] + line[match.end():]
                                removal_count += 1
                new_lines.append(line)
            cleaned = '\n'.join(new_lines)
        for regex, _ in self._additional_compiled:
            matches = list(regex.finditer(cleaned))
            if matches:
                for match in reversed(matches):
                    cleaned = cleaned[:match.start()] + cleaned[match.end():]
                    removal_count += 1
        return cleaned, removal_count
    
    def clean_non_tibetan_lines(self, text: str) -> Tuple[str, int]:
        """
        Remove lines that contain no Tibetan characters.
        
        Args:
            text: Text to clean
            
        Returns:
            Tuple of (cleaned_text, removal_count)
        """
        lines = text.split('\n')
        cleaned_lines = []
        removal_count = 0
        tibetan_re = self._TIBETAN_RE
        ascii_re = self._ASCII_WORD_RE
        for line in lines:
            if not line.strip() or line.strip().startswith('<'):
                cleaned_lines.append(line)
                continue
            if tibetan_re.search(line):
                cleaned_lines.append(line)
                continue
            stripped = line.strip()
            if stripped and not stripped.startswith('<') and not stripped.endswith('>'):
                if ascii_re.search(stripped):
                    removal_count += 1
                    continue
            cleaned_lines.append(line)
        return '\n'.join(cleaned_lines), removal_count
    
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
            'non_tibetan_lines_removed': 0,
            'total_fixes': 0
        }
        
        # Clean RTF commands
        cleaned, rtf_count = self.clean_rtf_commands(cleaned)
        stats['rtf_commands_removed'] = rtf_count
        
        # Clean spurious text
        cleaned, spurious_count = self.clean_spurious_text(cleaned)
        stats['spurious_text_removed'] = spurious_count
        
        # Clean non-Tibetan lines
        cleaned, non_tibetan_count = self.clean_non_tibetan_lines(cleaned)
        stats['non_tibetan_lines_removed'] = non_tibetan_count
        
        stats['total_fixes'] = rtf_count + spurious_count + non_tibetan_count
        stats['cleaned_text'] = cleaned
        
        return stats
    
    def add_cleaning_pattern(self, pattern: str, description: str, pattern_type: str = 'spurious'):
        """
        Add a new cleaning pattern at runtime.
        
        Args:
            pattern: Regex pattern to match
            description: Human-readable description
            pattern_type: 'rtf' or 'spurious' (default: 'spurious')
        """
        compiled = re.compile(pattern, re.IGNORECASE)
        if pattern_type == 'rtf':
            self.rtf_patterns.append((pattern, description))
            self._rtf_compiled.append((compiled, description))
            self._rtf_safe.append((compiled, description))
        elif pattern_type == 'spurious':
            self.spurious_patterns.append((pattern, description))
            self._spurious_compiled.append((compiled, description))
            self._spurious_safe.append((compiled, description))  # new patterns treated as safe
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


def clean_non_tibetan_lines(text: str) -> Tuple[str, int]:
    """Remove lines that contain no Tibetan characters."""
    return get_cleaner().clean_non_tibetan_lines(text)


def clean_all(text: str) -> Dict[str, int]:
    """Apply all cleaning operations to text."""
    return get_cleaner().clean_all(text)

