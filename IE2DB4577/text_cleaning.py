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
    2. Removes PAGE number patterns (e.g., -PAGE 522-)
    3. Removes specific non-Tibetan characters: « » < > . ¡ · ¶
    
    Args:
        text: Input text to clean
        
    Returns:
        Cleaned text with non-Tibetan content removed
    """
    # Remove the PAGE MERGEFORMAT strings if they exist
    non_tibetan = r"PAGE\s*\*?\s*MERGEFORMAT\s*\d*"
    tibetan_only = re.sub(non_tibetan, "", text, flags=re.IGNORECASE)
    
    # Remove PAGE patterns like -PAGE 522- or -PAGE 521-
    tibetan_only = re.sub(r'-?PAGE\s+\d+-?', '', tibetan_only, flags=re.IGNORECASE)
        
    # Remove inverted exclamation ¡, middle dot ·, and pilcrow ¶
    tibetan_only = re.sub(r'[«»<>.¡·¶]', '', tibetan_only)
    
    return tibetan_only
