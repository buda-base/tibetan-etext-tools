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
    
    def __init__(self):
        """Initialize the cleaner with patterns from the detector module."""
        self.rtf_patterns = RTF_COMMAND_PATTERNS
        self.spurious_patterns = SPURIOUS_PATTERNS
        self.tibetan_range = TIBETAN_RANGE
        
        # Additional cleaning patterns that are only used for cleaning (not detection)
        # These can be added here without affecting detection
        self.additional_cleaning_patterns = [
            # Add any patterns here that should be cleaned but not necessarily detected
            # Format: (pattern, description)
        ]
    
    def clean_rtf_commands(self, text: str) -> Tuple[str, int]:
        """
        Remove RTF command patterns from text.
        
        Args:
            text: Text to clean
            
        Returns:
            Tuple of (cleaned_text, removal_count)
        """
        cleaned = text
        removal_count = 0
        
        # Process patterns in reverse order to maintain string indices
        for pattern, description in self.rtf_patterns:
            matches = list(re.finditer(pattern, cleaned, re.IGNORECASE))
            if matches:
                # Process matches in reverse to maintain correct indices
                for match in reversed(matches):
                    cleaned = cleaned[:match.start()] + cleaned[match.end():]
                    removal_count += 1
        
        return cleaned, removal_count
    
    def clean_spurious_text(self, text: str) -> Tuple[str, int]:
        """
        Remove spurious text patterns from text.
        
        Args:
            text: Text to clean
            
        Returns:
            Tuple of (cleaned_text, removal_count)
        """
        cleaned = text
        removal_count = 0
        
        # Clean spurious patterns
        for pattern, description in self.spurious_patterns:
            matches = list(re.finditer(pattern, cleaned, re.IGNORECASE))
            if matches:
                for match in reversed(matches):
                    cleaned = cleaned[:match.start()] + cleaned[match.end():]
                    removal_count += 1
        
        # Clean additional patterns (if any)
        for pattern, description in self.additional_cleaning_patterns:
            matches = list(re.finditer(pattern, cleaned, re.IGNORECASE))
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
        
        for line in lines:
            # Keep empty lines and XML tags
            if not line.strip() or line.strip().startswith('<'):
                cleaned_lines.append(line)
                continue
            
            # Check if line has Tibetan characters
            if not re.search(self.tibetan_range, line):
                stripped = line.strip()
                # Remove lines that are not XML and contain ASCII text
                if stripped and not stripped.startswith('<') and not stripped.endswith('>'):
                    if re.search(r'[A-Za-z]{3,}', stripped):
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
        if pattern_type == 'rtf':
            self.rtf_patterns.append((pattern, description))
        elif pattern_type == 'spurious':
            self.spurious_patterns.append((pattern, description))
        else:
            self.additional_cleaning_patterns.append((pattern, description))


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

