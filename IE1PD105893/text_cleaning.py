"""
Text cleaning utilities for Tibetan text processing.

This module provides functions to clean and filter non-Tibetan content
from text extracted from RTF files.
"""

import re


def remove_non_tibetan(text: str) -> str:
    """
    Remove non-Tibetan characters and noise from text.
    
    This function performs the following cleaning operations:
    1. Removes PAGE MERGEFORMAT strings
    2. Removes PAGE number patterns (e.g., -PAGE 522-, --PAGE 67--, »- PAGE 68, PAGE 3, PAGE)
    3. Removes dash-number-dash patterns (e.g., -1-, -2-)
    4. Removes specific non-Tibetan characters: « » < > . ¡ · ¶ ¤ ¨
    
    Args:
        text: Input text to clean
        
    Returns:
        Cleaned text with non-Tibetan content removed
    """
    # Remove the PAGE MERGEFORMAT strings if they exist
    non_tibetan = r"PAGE\s*\*?\s*MERGEFORMAT\s*\d*"
    tibetan_only = re.sub(non_tibetan, "", text, flags=re.IGNORECASE)
    
    # Remove PAGE patterns like -PAGE 522-, --PAGE 67--, »- PAGE 68, PAGE 3, PAGE, etc.
    tibetan_only = re.sub(r'[»«]*\s*-*\s*PAGE\s*\d*\s*-*', '', tibetan_only, flags=re.IGNORECASE)

    # Remove patterns like -1-, -2-, -123-, etc.
    tibetan_only = re.sub(r'-\d+-', '', tibetan_only)
    
    # Remove guillemets « », angle brackets < >, periods ., inverted exclamation ¡, middle dot ·, pilcrow ¶, currency sign ¤, and pound sign £
    tibetan_only = re.sub(r'[«»<>.¡·¶¤¨]', '', tibetan_only)
    
    return tibetan_only
