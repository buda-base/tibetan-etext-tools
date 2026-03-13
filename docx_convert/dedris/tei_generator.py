#!/usr/bin/env python3
"""
TEI XML Generation Module

This module provides functions for generating TEI XML from converted text streams.
It handles font size classification, body content building, and XML generation.
"""

import re
import hashlib
from pathlib import Path
from collections import Counter
from tibetan_text_fixes import count_tibetan_chars


def classify_font_sizes(converted_streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    
    Uses frequency analysis: the font size with the MOST Tibetan characters 
    is classified as "regular" (body text). Larger sizes become "large" (headers),
    smaller sizes become "small" (footnotes).
    
    Args:
        converted_streams: List of dicts with 'text' (Unicode) and 'font_size'
        
    Returns:
        dict: Mapping of font_size -> classification ('large', 'regular', 'small')
        
    Example:
        Input streams with font sizes: 10 (200 chars), 12 (5000 chars), 16 (50 chars)
        Returns: {10: 'small', 12: 'regular', 16: 'large'}
    """
    size_counts = Counter()
    
    for item in converted_streams:
        text = item.get("text", "")
        font_size = item.get("font_size", 12)
        
        # Count Tibetan characters (U+0F00-U+0FFF)
        tibetan_chars = count_tibetan_chars(text)
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    
    if not size_counts:
        return {}
    
    # Find the font size with the most Tibetan characters - that's "regular" (body text)
    most_common_size = max(size_counts.items(), key=lambda x: x[1])[0]
    
    # Classify all sizes relative to most common
    classifications = {}
    for fs in size_counts.keys():
        if fs == most_common_size:
            classifications[fs] = 'regular'
        elif fs > most_common_size:
            classifications[fs] = 'large'
        else:
            classifications[fs] = 'small'
    
    return classifications


def is_watermark(text: str) -> bool:
    """
    Detect if text is a watermark/copyright pattern.
    
    Watermarks typically have:
    - Mix of Tibetan characters with ASCII digits
    - Hex-like patterns (e.g., "3cac58c", "a1c58c")
    - High ratio of digits/letters to Tibetan characters
    - Long repeating patterns of 'f' characters
    
    Args:
        text: Text to check
        
    Returns:
        True if text appears to be a watermark
    """
    if not text or len(text) < 10:
        return False

    # Count different character types
    tibetan_count = sum(1 for c in text if '\u0f00' <= c <= '\u0fff')
    digit_count = sum(1 for c in text if c.isdigit() and ord(c) < 128)  # ASCII digits only
    letter_count = sum(1 for c in text if c.isalpha() and ord(c) < 128)  # ASCII letters

    # Pattern 1: High density of ASCII digits mixed with Tibetan
    if tibetan_count > 0 and digit_count > tibetan_count * 0.3:
        return True
    
    # Pattern 2: Contains hex-like patterns with Tibetan
    if tibetan_count > 0 and re.search(r'[a-f0-9]{6,}', text, re.IGNORECASE):
        return True
    
    # Pattern 3: Very long repeating patterns of same character (but not Tibetan tsheg ་)
    # Tsheg (U+0F0B) is legitimately used as dot leaders in TOC
    if re.search(r'([^\u0f0b])\1{50,}', text):
        return True
    
    # Pattern 4: Mix of Tibetan with ASCII letters (not spaces/punctuation)
    if tibetan_count > 0 and letter_count > 0 and letter_count > tibetan_count * 0.2:
        return True
    
    return False


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        return sha256_hash.hexdigest()
    except FileNotFoundError:
        return "FILE_NOT_FOUND"


def build_tei_body(converted_streams: list, enable_font_classification: bool = True, footnotes: dict = None) -> str:
    """
    Build TEI body content from converted text streams.
    
    Args:
        converted_streams: List of dicts with 'text' and 'font_size'
        enable_font_classification: Whether to apply font size classification
        footnotes: Dictionary mapping footnote ID to footnote text
        
    Returns:
        TEI body content as string
    """
    if footnotes is None:
        footnotes = {}
    
    # Classify font sizes if enabled
    classifications = {}
    if enable_font_classification:
        classifications = classify_font_sizes(converted_streams)
    
    tei_lines = []
    current_markup = None
    
    for item in converted_streams:
        text = item.get("text", "")
        font_size = item.get("font_size", 12)
        is_footnote_marker = item.get("is_footnote_marker", False)
        footnote_id = item.get("footnote_id")
        
        if not text:
            continue
        
        # Handle footnote markers
        if is_footnote_marker and footnote_id and footnote_id in footnotes:
            footnote_text = footnotes[footnote_id]
            # Normalize and clean footnote text
            footnote_text = escape_xml(footnote_text)
            
            # Extract footnote number from the ID (usually just the ID itself)
            footnote_num = footnote_id
            
            # Insert <note> tag inline with NO extra whitespace
            note_tag = f'<note n="{footnote_num}" place="foot">{footnote_text}</note>'
            tei_lines.append(note_tag)
            continue
        
        # Skip lines that contain only dashes (e.g., "- - - - -")
        if re.match(r'^[\s\-]+$', text) and '-' in text and '…' not in text:
            continue
        
        # Skip watermark/copyright patterns
        if is_watermark(text):
            continue
        
        # Escape XML
        escaped_text = escape_xml(text)
        
        # Special handling for newlines - don't change classification
        is_newline = text.strip() == ''
        
        # Apply font size classification if enabled (but not for newlines)
        if enable_font_classification and classifications and not is_newline:
            classification = classifications.get(font_size, 'regular')
            
            # Handle markup changes
            if classification != current_markup:
                if current_markup in ('small', 'large'):
                    tei_lines.append('</hi>')
                
                if classification == 'small':
                    tei_lines.append('<hi rend="small">')
                elif classification == 'large':
                    tei_lines.append('<hi rend="head">')
                
                current_markup = classification if classification != 'regular' else None
        
        tei_lines.append(escaped_text)
    
    # Close any open markup
    if current_markup in ('small', 'large'):
        tei_lines.append('</hi>')
    
    # Join
    body_content = ''.join(tei_lines)
    
    return body_content


def post_process_body(body_content: str) -> str:
    """
    Post-process TEI body content.
    
    This includes:
    - Removing empty hi tags
    - Adding line breaks
    - Cleaning up whitespace
    - Normalizing tag placement (keeping <lb/> INSIDE <hi> tags)
    - Preserving <note> tags without adding extra whitespace
    
    Args:
        body_content: Raw body content
        
    Returns:
        Processed body content
    """
    # Remove empty hi tags
    body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    # Strip
    body_content = body_content.strip()
    
    # Replace newlines with <lb/> at the start of the next line
    body_content = body_content.replace('\n', '\n<lb/>')
    
    # Remove spaces around <lb/> tags (but not around <note> tags)
    body_content = re.sub(r' *<lb/> *', '<lb/>', body_content)
    
    # Remove any spaces that may have been added around <note> tags
    body_content = re.sub(r' *(<note [^>]+>)', r'\1', body_content)
    body_content = re.sub(r'(</note>) *', r'\1', body_content)
    
    # Remove <hi> tags that contain only whitespace/newlines/lb tags
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', '', body_content)
    
    # Fix pattern: </hi><lb/><hi rend="X"> -> <lb/> (keep inside same hi tag)
    # This merges consecutive <hi> tags of the same type across line breaks
    body_content = re.sub(r'</hi>\s*<lb/>\s*<hi rend="([^"]+)">', r'<lb/>', body_content)
    
    # Clean up any remaining empty <hi> tags after the moves
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', '', body_content)
    
    # Remove multiple consecutive <lb/> tags, keeping only one
    body_content = re.sub(r'(<lb/>\s*)+', '<lb/>', body_content)
    
    # Remove leading <lb/> at the very start
    body_content = re.sub(r'^\s*<lb/>', '', body_content)
    
    # Final strip
    body_content = body_content.strip()
    
    return body_content


def generate_tei_xml(body_content: str, title: str, src_path: str, sha256: str, 
                     ve_id: str, ut_id: str, ie_id: str = "IE1AB2") -> str:
    """
    Generate complete TEI XML document.
    
    Args:
        body_content: Processed body content
        title: Document title
        src_path: Source file path
        sha256: SHA256 hash of source file
        ve_id: Volume Entity ID
        ut_id: Unit Text ID
        ie_id: Image Entity ID (default: IE1AB2)
        
    Returns:
        Complete TEI XML string
    """
    tei_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
<fileDesc>
<titleStmt>
<title>{escape_xml(title)}</title>
</titleStmt>
<publicationStmt>
<p>File from the archive of the Buddhist Digital Resource Center (BDRC), converted into TEI from a file not created by BDRC.</p>
</publicationStmt>
<sourceDesc>
<bibl>
<idno type="src_path">{src_path}</idno>
<idno type="src_sha256">{sha256}</idno>
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{ie_id}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl>
</sourceDesc>
</fileDesc>
<encodingDesc>
<p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{ie_id}">record in the BDRC database</ref>.</p>
</encodingDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p xml:space="preserve">{body_content}</p>
</body>
</text>
</TEI>
'''
    
    return tei_xml
