#!/usr/bin/env python3
"""
Text Cleaning Library for Tibetan RTF Processing

This module provides comprehensive text cleaning functions to remove
scanning/OCR artifacts, page markers, and other non-Tibetan noise from
RTF text before conversion to Unicode TEI XML.

Functions:
    - remove_page_markers(): Remove page number markers
    - remove_page_mergeformat(): Remove PAGE MERGEFORMAT strings
    - remove_embed_objects(): Remove EMBED object codes (CorelDRAW, etc.)
    - normalize_guillemets(): Normalize duplicated quotation marks
    - remove_non_tibetan_symbols(): Remove specific non-Tibetan characters
    - clean_text(): Apply all cleaning operations
    
Usage:
    from text_cleaning import clean_text
    
    text = "Some text -PAGE 42- with ««guillemets»»"
    cleaned = clean_text(text)
"""

import re


# =============================================================================
# Page Marker Removal
# =============================================================================

def remove_page_markers(text: str) -> str:
    """
    Remove page markers from RTF text.
    
    Removes various page marker formats including:
    - Standard: -PAGE 138-
    - With guillemets: »- PAGE 68, «PAGE 42»
    - Multiple dashes: --PAGE 67--
    - No dashes: PAGE 3
    - Just PAGE keyword
    
    This is a comprehensive pattern that handles all common variations.
    
    Args:
        text: Input text that may contain page markers
        
    Returns:
        Text with page markers removed
        
    Examples:
        >>> remove_page_markers("-PAGE 138--PAGE 137--PAGE 1-")
        ''
        >>> remove_page_markers("»- PAGE 68 text")
        ' text'
        >>> remove_page_markers("text --PAGE 67-- more")
        'text  more'
    """
    if not text:
        return text
    
    # Comprehensive pattern that matches:
    # [»«]* - Optional leading guillemets
    # \s*   - Optional whitespace
    # -*    - Optional dashes
    # \s*   - Optional whitespace
    # PAGE  - Literal "PAGE" (case insensitive)
    # \s*   - Optional whitespace
    # \d*   - Optional digits (page number)
    # \s*   - Optional whitespace
    # -*    - Optional trailing dashes
    pattern = r'[»«]*\s*-*\s*PAGE\s*\d*\s*-*'
    
    # Remove all page markers (case insensitive)
    cleaned = re.sub(pattern, '', text, flags=re.IGNORECASE)
    
    return cleaned


def remove_page_mergeformat(text: str) -> str:
    """
    Remove PAGE MERGEFORMAT strings from RTF text.
    
    These are Microsoft Word field codes that sometimes appear in RTF files:
    - PAGE MERGEFORMAT
    - PAGE * MERGEFORMAT
    - PAGE MERGEFORMAT 123
    
    Args:
        text: Input text that may contain MERGEFORMAT strings
        
    Returns:
        Text with MERGEFORMAT strings removed
        
    Examples:
        >>> remove_page_mergeformat("text PAGE MERGEFORMAT more")
        'text  more'
        >>> remove_page_mergeformat("PAGE * MERGEFORMAT 123")
        ''
    """
    if not text:
        return text
    
    # Pattern matches:
    # PAGE      - Literal "PAGE"
    # \s*       - Optional whitespace
    # \*?       - Optional asterisk
    # \s*       - Optional whitespace
    # MERGEFORMAT - Literal "MERGEFORMAT"
    # \s*       - Optional whitespace
    # \d*       - Optional digits
    pattern = r"PAGE\s*\*?\s*MERGEFORMAT\s*\d*"
    
    cleaned = re.sub(pattern, "", text, flags=re.IGNORECASE)
    
    return cleaned


def remove_embed_objects(text: str) -> str:
    """
    Remove embedded object codes from RTF text.
    
    These are OLE object embed codes that appear in RTF files:
    - EMBED CorelDRAW.Graphic.9
    - EMBED Word.Picture.8
    - EMBED PBrush
    - And other EMBED variants
    
    Args:
        text: Input text that may contain EMBED codes
        
    Returns:
        Text with EMBED codes removed
        
    Examples:
        >>> remove_embed_objects("text EMBED CorelDRAW.Graphic.9 more")
        'text  more'
        >>> remove_embed_objects("EMBED CorelDRAW.Graphic.9   EMBED ")
        '   '
    """
    if not text:
        return text
    
    # Pattern matches:
    # EMBED     - Literal "EMBED"
    # \s+       - Required whitespace
    # [^\s]+    - One or more non-whitespace characters (the object type)
    # This will match things like:
    # - EMBED CorelDRAW.Graphic.9
    # - EMBED Word.Picture.8
    # - EMBED PBrush
    pattern = r"EMBED\s+[^\s]+"
    
    cleaned = re.sub(pattern, "", text, flags=re.IGNORECASE)
    
    # Also remove standalone "EMBED" without object type
    cleaned = re.sub(r"\bEMBED\b", "", cleaned, flags=re.IGNORECASE)
    
    return cleaned


# =============================================================================
# Guillemet Normalization
# =============================================================================

def normalize_guillemets(text: str) -> str:
    """
    Normalize duplicated guillemets (French quotation marks).
    
    RTF processing sometimes duplicates guillemets in various patterns:
    - «« → «
    - »» → »
    - ཐ།«« ལེག → ཐ།« ལེག (remove first smaller one)
    - རྗོད་པའི་«      «རྟོགས → རྗོད་པའི་«རྟོགས (remove first with spaces)
    
    This happens when guillemets appear in both RTF control codes
    and the text stream.
    
    Args:
        text: Input text that may contain duplicated guillemets
        
    Returns:
        Text with normalized guillemets
        
    Examples:
        >>> normalize_guillemets("།མངྒ་ལཾ། ««མེས་པོའི")
        '།མངྒ་ལཾ། «མེས་པོའི'
        >>> normalize_guillemets("ཐ།«« ལེག")
        'ཐ།« ལེག'
        >>> normalize_guillemets("རྗོད་པའི་«      «རྟོགས")
        'རྗོད་པའི་«རྟོགས'
    """
    if not text:
        return text
    
    # Pattern 1: Remove single « followed by spaces and another «
    # Example: རྗོད་པའི་«      «རྟོགས → རྗོད་པའི་«རྟོགས
    text = re.sub(r'«\s+«', '«', text)
    
    # Pattern 2: Remove single » followed by spaces and another »
    # Example: text»      » more → text» more
    text = re.sub(r'»\s+»', '»', text)
    
    # Pattern 3: Replace consecutive duplicated opening guillemets
    # Example: ««« → «, «« → «
    text = re.sub(r'«+', '«', text)
    
    # Pattern 4: Replace consecutive duplicated closing guillemets
    # Example: »»» → », »» → »
    text = re.sub(r'»+', '»', text)
    
    return text


def remove_guillemets(text: str) -> str:
    """
    Remove all guillemets from text.
    
    Use this when guillemets are noise rather than meaningful quotation marks.
    For normalization (keeping single guillemets), use normalize_guillemets() instead.
    
    Args:
        text: Input text that may contain guillemets
        
    Returns:
        Text with guillemets removed
        
    Examples:
        >>> remove_guillemets("«text» more")
        'text more'
        >>> remove_guillemets("««།»»")
        '།'
    """
    if not text:
        return text
    
    # Remove both opening and closing guillemets
    text = text.replace('«', '')
    text = text.replace('»', '')
    
    return text


# =============================================================================
# Non-Tibetan Symbol Removal
# =============================================================================

def remove_non_tibetan_symbols(text: str) -> str:
    """
    Remove specific non-Tibetan characters that appear as noise in RTF files.
    
    Removes:
    - Guillemets: « »
    - Angle brackets: < >
    - Period: .
    - Inverted exclamation: ¡
    - Middle dot: ·
    - Pilcrow (paragraph mark): ¶
    - Currency sign: ¤
    - Diaeresis: ¨
    
    Note: This is aggressive cleaning. Use carefully as some of these
    characters might be legitimate in certain contexts.
    
    Args:
        text: Input text to clean
        
    Returns:
        Text with non-Tibetan symbols removed
        
    Examples:
        >>> remove_non_tibetan_symbols("text·with¶noise")
        'textwithnoise'
        >>> remove_non_tibetan_symbols("«quoted»")
        'quoted'
    """
    if not text:
        return text
    
    # Remove all specified non-Tibetan characters
    cleaned = re.sub(r'[«»<>.¡·¶¤¨]', '', text)
    
    return cleaned


# =============================================================================
# Whitespace Normalization
# =============================================================================

def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.
    
    Operations:
    1. Replace multiple spaces with single space
    2. Remove leading/trailing whitespace
    3. Normalize line breaks
    
    Args:
        text: Input text with irregular whitespace
        
    Returns:
        Text with normalized whitespace
        
    Examples:
        >>> normalize_whitespace("text    with   spaces")
        'text with spaces'
        >>> normalize_whitespace("  leading and trailing  ")
        'leading and trailing'
    """
    if not text:
        return text
    
    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)
    
    # Replace multiple line breaks with single line break
    text = re.sub(r'\n+', '\n', text)
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text


# =============================================================================
# Comprehensive Cleaning
# =============================================================================

def clean_text(text: str, 
               remove_page_marks: bool = True,
               remove_mergeformat: bool = True,
               remove_embeds: bool = True,
               normalize_quotes: bool = True,
               remove_symbols: bool = False,
               normalize_spaces: bool = True) -> str:
    """
    Apply comprehensive text cleaning operations.
    
    This is the main function that applies all cleaning operations
    in the correct order. You can enable/disable specific operations
    using the boolean flags.
    
    Args:
        text: Input text to clean
        remove_page_marks: Remove page markers (default: True)
        remove_mergeformat: Remove MERGEFORMAT strings (default: True)
        remove_embeds: Remove EMBED object codes (default: True)
        normalize_quotes: Normalize guillemets (default: True)
        remove_symbols: Remove non-Tibetan symbols (default: False)
        normalize_spaces: Normalize whitespace (default: True)
        
    Returns:
        Cleaned text
        
    Examples:
        >>> clean_text("text -PAGE 42- with ««guillemets»»")
        'text  with «guillemets»'
        >>> clean_text("text -PAGE 42-", normalize_quotes=False)
        'text'
    """
    if not text:
        return text
    
    # Step 1: Remove PAGE MERGEFORMAT strings
    if remove_mergeformat:
        text = remove_page_mergeformat(text)
    
    # Step 2: Remove EMBED object codes
    if remove_embeds:
        text = remove_embed_objects(text)
    
    # Step 3: Remove page markers
    if remove_page_marks:
        text = remove_page_markers(text)
    
    # Step 4: Normalize or remove guillemets
    if normalize_quotes:
        text = normalize_guillemets(text)
    
    # Step 5: Remove non-Tibetan symbols (optional, aggressive)
    if remove_symbols:
        text = remove_non_tibetan_symbols(text)
    
    # Step 6: Normalize whitespace
    if normalize_spaces:
        text = normalize_whitespace(text)
    
    return text


def remove_non_tibetan(text: str) -> str:
    """
    Remove non-Tibetan characters and noise from text.
    
    This is a convenience function that applies aggressive cleaning,
    removing all page markers, MERGEFORMAT strings, guillemets,
    and non-Tibetan symbols.
    
    Equivalent to:
        clean_text(text, remove_symbols=True, normalize_quotes=False)
        followed by remove_guillemets()
    
    Args:
        text: Input text to clean
        
    Returns:
        Cleaned text with non-Tibetan content removed
        
    Examples:
        >>> remove_non_tibetan("text -PAGE 42- «with» noise·")
        'text with noise'
    """
    if not text:
        return text
    
    # Remove PAGE MERGEFORMAT strings
    text = remove_page_mergeformat(text)
    
    # Remove page markers
    text = remove_page_markers(text)
    
    # Remove guillemets completely
    text = remove_guillemets(text)
    
    # Remove non-Tibetan symbols
    text = remove_non_tibetan_symbols(text)
    
    # Normalize whitespace
    text = normalize_whitespace(text)
    
    return text


# =============================================================================
# Testing
# =============================================================================

if __name__ == "__main__":
    print("Testing Text Cleaning Library")
    print("=" * 70)
    
    # Test 1: Page markers
    print("\n1. Testing remove_page_markers():")
    print("-" * 70)
    test_cases = [
        ("-PAGE 138--PAGE 137--PAGE 1-", ""),
        ("»- PAGE 68 text", " text"),
        ("text --PAGE 67-- more", "text  more"),
        ("PAGE 3", ""),
        ("Some text -PAGE 42- more text", "Some text  more text"),
    ]
    
    for input_text, expected in test_cases:
        result = remove_page_markers(input_text)
        status = "✓" if result == expected else "✗"
        print(f"{status} Input:    {repr(input_text)}")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(result)}")
        print()
    
    # Test 2: MERGEFORMAT
    print("\n2. Testing remove_page_mergeformat():")
    print("-" * 70)
    test_cases = [
        ("text PAGE MERGEFORMAT more", "text  more"),
        ("PAGE * MERGEFORMAT 123", ""),
        ("PAGE MERGEFORMAT", ""),
    ]
    
    for input_text, expected in test_cases:
        result = remove_page_mergeformat(input_text)
        status = "✓" if result == expected else "✗"
        print(f"{status} Input:    {repr(input_text)}")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(result)}")
        print()
    
    # Test 3: Guillemets
    print("\n3. Testing normalize_guillemets():")
    print("-" * 70)
    test_cases = [
        ("།མངྒ་ལཾ། ««མེས་པོའི", "།མངྒ་ལཾ། «མེས་པོའི"),
        ("ཐ།«« ལེག", "ཐ།« ལེག"),
        ("རྗོད་པའི་«      «རྟོགས", "རྗོད་པའི་«རྟོགས"),
        ("text »» more", "text » more"),
        ("««།»»", "«།»"),
        ("text «  « more", "text « more"),
    ]
    
    for input_text, expected in test_cases:
        result = normalize_guillemets(input_text)
        status = "✓" if result == expected else "✗"
        print(f"{status} Input:    {repr(input_text)}")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(result)}")
        print()
    
    # Test 4: Comprehensive cleaning
    print("\n4. Testing clean_text():")
    print("-" * 70)
    test_cases = [
        ("text -PAGE 42- with ««guillemets»»", "text with «guillemets»"),
        ("PAGE MERGEFORMAT text", "text"),
        ("»- PAGE 68 ««text»»", "«text»"),
    ]
    
    for input_text, expected in test_cases:
        result = clean_text(input_text)
        status = "✓" if result == expected else "✗"
        print(f"{status} Input:    {repr(input_text)}")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(result)}")
        print()
    
    # Test 5: Aggressive cleaning
    print("\n5. Testing remove_non_tibetan():")
    print("-" * 70)
    test_cases = [
        ("text -PAGE 42- «with» noise·", "text with noise"),
        ("PAGE MERGEFORMAT ««text»» ¶", "text"),
    ]
    
    for input_text, expected in test_cases:
        result = remove_non_tibetan(input_text)
        status = "✓" if result == expected else "✗"
        print(f"{status} Input:    {repr(input_text)}")
        print(f"  Expected: {repr(expected)}")
        print(f"  Got:      {repr(result)}")
        print()
    
    print("\n" + "=" * 70)
    print("All tests completed!")
