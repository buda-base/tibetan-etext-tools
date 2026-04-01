"""
TEI XML Generator Module

This module provides functions to generate TEI XML from parsed RTF content.
"""

import re
import hashlib
from pathlib import Path
from collections import Counter
import logging

from config import IE_ID
from tibetan_text_fixes import fix_phantom_volume_headers

logger = logging.getLogger(__name__)


def classify_font_sizes(converted_streams: list) -> dict:
    """
    Classify font sizes into large, regular, and small categories.
    """
    size_counts = Counter()
    
    for item in converted_streams:
        text = item.get("text", "")
        font_size = item.get("font_size", 12)
        tibetan_chars = len([c for c in text if 0x0F00 <= ord(c) <= 0x0FFF])
        if tibetan_chars > 0:
            size_counts[font_size] += tibetan_chars
    
    if not size_counts:
        return {}
    
    most_common = max(size_counts.items(), key=lambda x: x[1])[0]
    
    classifications = {}
    for fs in size_counts.keys():
        if fs == most_common:
            classifications[fs] = 'regular'
        elif fs > most_common:
            classifications[fs] = 'large'
        else:
            classifications[fs] = 'small'
    
    return classifications


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


def build_tei_body(converted_streams: list, enable_font_classification: bool = True) -> str:
    """Build the body content for TEI XML from converted streams."""
    tei_lines = []
    current_markup = None
    
    # Skip leading breaks (newlines and page_breaks) at the start
    # These can occur from RTF structure between header/footer definitions
    start_idx = 0
    for i, item in enumerate(converted_streams):
        if item.get("type") == "page_break":
            continue  # Skip leading page_breaks
        if item.get("text", "").strip() == "":
            continue  # Skip empty/whitespace-only items
        start_idx = i
        break
    
    # Always add initial page break at start
    tei_lines.append('<pb/>\n')
    
    # Process from start_idx
    if start_idx > 0:
        converted_streams = converted_streams[start_idx:]
    
    if enable_font_classification:
        classifications = classify_font_sizes(converted_streams)
        if classifications:
            logger.info(f"  Font classifications: {classifications}")
    else:
        classifications = {}
    
    for item in converted_streams:
        # Handle page break markers (from footer detection)
        if item.get("type") == "page_break":
            # Close any open markup tags before page break
            if current_markup == 'small':
                tei_lines.append('</hi>')
            elif current_markup == 'large':
                tei_lines.append('</hi>')
            current_markup = None
            tei_lines.append('\n<pb/>\n')
            continue
        
        # Skip items without text
        if "text" not in item:
            continue
        
        text = item["text"]
        font_size = item.get("font_size", 12)
        escaped_text = escape_xml(text)
        
        if enable_font_classification and classifications:
            classification = classifications.get(font_size, 'regular')
            
            if classification != current_markup:
                if current_markup == 'small':
                    tei_lines.append('</hi>')
                elif current_markup == 'large':
                    tei_lines.append('</hi>')
                
                if classification == 'small':
                    tei_lines.append('<hi rend="small">')
                elif classification == 'large':
                    tei_lines.append('<hi rend="head">')
                
                current_markup = classification if classification != 'regular' else None
        
        tei_lines.append(escaped_text)
    
    if current_markup == 'small':
        tei_lines.append('</hi>')
    elif current_markup == 'large':
        tei_lines.append('</hi>')
    
    body_content = ''.join(tei_lines)
    
    if enable_font_classification:
        body_content = re.sub(r'<hi rend="[^"]+"></hi>', '', body_content)
    
    return body_content


def fix_mixed_dedris_patterns(text: str) -> str:
    """
    Fix remaining mixed Dedris patterns that weren't converted during stream processing.
    
    This handles cases where ASCII Dedris characters and Tibetan Unicode were in
    separate text streams and thus not detected as mixed content.
    
    Patterns to fix:
    - .ེ → དེ (dot + Tibetan vowel sign e)
    - 0ོ → སོ (zero + Tibetan vowel sign o)
    - {འ → ཆའ (brace + Tibetan a-chung)
    - \ི → སི (backslash + Tibetan vowel sign i)
    - ག.ལ → གདུལ (consonant + dot + consonant becomes consonant + du + consonant)
    - མ,ན → མཐུན (consonant + comma + consonant becomes consonant + thu + consonant)
    - འགྲོ-བ → འགྲོ་བ (hyphen-minus as tsheg)
    """
    # Mapping: ASCII char before vowel sign → Tibetan consonant
    CONSONANT_BEFORE_VOWEL = {
        '.': 'ད',   # da - .ེ → དེ
        '0': 'ས',   # sa - 0ོ → སོ
        '{': 'ཆ',   # cha - {འ → ཆའ
        '\\': 'ས',  # sa - \ི → སི
        '/': 'ཤ',   # sha
        '(': 'ཡ',   # ya
        ')': 'འ',   # a-chung
        '}': 'ས',   # sa
        ',': 'ཐ',   # tha - ,ུ → ཐུ
    }
    
    # Mapping: ASCII char before consonant/tsheg → syllable (consonant + inherent u)
    SYLLABLE_BEFORE_CONSONANT = {
        '.': 'དུ',  # du - ག.ལ → གདུལ
        '0': 'སུ',  # su
        '{': 'ཆུ',  # chu
        '\\': 'སུ', # su
        '/': 'ཤུ',  # shu
        '(': 'ཡུ',  # yu
        ')': 'འུ',  # u
        '}': 'སུ',  # su
        ',': 'ཐུ',  # thu - མ,ན → མཐུན
    }
    
    # Tibetan vowel signs (combining marks)
    TIBETAN_VOWELS = 'ཱིེོུཾཿ'
    # Pattern: vowel signs including dependent vowel signs U+0F71-U+0F84
    VOWEL_PATTERN = '[' + TIBETAN_VOWELS + '\u0F71-\u0F84]'
    
    # Tibetan consonants and tsheg
    TIBETAN_CONSONANTS = 'ཀཁགངཅཆཇཉཏཐདནཔཕབམཙཚཛཝཞཟའཡརལཤསཧཨ'
    TSHEG = '་'
    SHAD = '།'
    
    result = text
    
    # Fix ASCII + vowel sign patterns
    for ascii_char, tibetan_consonant in CONSONANT_BEFORE_VOWEL.items():
        # Escape special regex chars
        escaped_char = re.escape(ascii_char)
        # Pattern: ASCII char followed by Tibetan vowel sign
        pattern = escaped_char + '(' + VOWEL_PATTERN + ')'
        replacement = tibetan_consonant + r'\1'
        result = re.sub(pattern, replacement, result)
    
    # Fix patterns where ASCII is between two Tibetan consonants: ག.ལ → གདུལ
    for ascii_char, tibetan_syllable in SYLLABLE_BEFORE_CONSONANT.items():
        escaped_char = re.escape(ascii_char)
        # Pattern: Tibetan consonant + ASCII + Tibetan consonant/tsheg
        pattern = '([' + TIBETAN_CONSONANTS + '])' + escaped_char + '([' + TIBETAN_CONSONANTS + TSHEG + '])'
        replacement = r'\1' + tibetan_syllable + r'\2'
        result = re.sub(pattern, replacement, result)
    
    # Fix ASCII followed by Tibetan consonant (after tsheg or at start): {འ → ཆའ
    # This handles cases like ས་{འི་རྒྱལ་ → ས་ཆའི་རྒྱལ་
    # NOTE: We ALLOW matches after tsheg since tsheg marks syllable boundary
    for ascii_char, tibetan_consonant in CONSONANT_BEFORE_VOWEL.items():
        escaped_char = re.escape(ascii_char)
        # Pattern: (tsheg or non-Tibetan) + ASCII + Tibetan consonant
        # Match after tsheg, space, start of line, or any non-Tibetan character
        pattern = '(?:^|[^' + TIBETAN_CONSONANTS + TIBETAN_VOWELS + '])' + escaped_char + '([' + TIBETAN_CONSONANTS + '])'
        replacement_func = lambda m, tc=tibetan_consonant: (m.group(0)[0] if m.group(0)[0] != escaped_char[0] else '') + tc + m.group(1)
        # Simpler approach: just match ASCII + consonant anywhere
        pattern = escaped_char + '([' + TIBETAN_CONSONANTS + '])'
        replacement = tibetan_consonant + r'\1'
        result = re.sub(pattern, replacement, result)
    
    # Fix ASCII directly followed by tsheg: {་ → ཆ་
    # This handles cases like {་རྒྱལ་ where { is a complete syllable
    for ascii_char, tibetan_consonant in CONSONANT_BEFORE_VOWEL.items():
        escaped_char = re.escape(ascii_char)
        # Pattern: ASCII + tsheg
        pattern = escaped_char + TSHEG
        replacement = tibetan_consonant + TSHEG
        result = re.sub(pattern, replacement, result)
    
    # Fix standalone ASCII before shad: འགོ.། → འགོད།
    for ascii_char, tibetan_consonant in CONSONANT_BEFORE_VOWEL.items():
        escaped_char = re.escape(ascii_char)
        # Pattern: Tibetan consonant/vowel + ASCII + shad
        pattern = '([' + TIBETAN_CONSONANTS + TIBETAN_VOWELS + '])' + escaped_char + '([' + SHAD + '])'
        replacement = r'\1' + tibetan_consonant + r'\2'
        result = re.sub(pattern, replacement, result)
    
    # Fix isolated .་ pattern (dot followed by tsheg): ས.་གནས → སད་གནས
    result = re.sub(r'\.་', 'ད་', result)
    
    # Fix hyphen-minus used as tsheg: འགྲོ-བ → འགྲོ་བ
    # Pattern: Any Tibetan character (U+0F00-U+0FFF) + hyphen-minus + any Tibetan character
    tibetan_range = '\u0F00-\u0FFF'
    hyphen_pattern = '([' + tibetan_range + '])-([' + tibetan_range + '])'
    tsheg = '་'  # U+0F0B
    
    result = re.sub(hyphen_pattern, r'\1' + tsheg + r'\2', result)
    
    # Second pass for nested hyphens (e.g., a-b-c → a་b་c)
    result = re.sub(hyphen_pattern, r'\1' + tsheg + r'\2', result)
    
    # Fix hyphens adjacent to HTML tags:
    # Pattern: Tibetan + hyphen + </hi> ... <hi> + Tibetan → Tibetan + tsheg + </hi> ... <hi> + Tibetan
    # First, fix hyphen before closing tag: རྗེ-</hi> → རྗེ་</hi>
    result = re.sub(r'([' + tibetan_range + '])-(<(?:/hi|lb))', r'\1་\2', result)
    
    # Fix hyphen after opening tag: <hi...>-བ → <hi...>་བ (hyphen at start of tag content)
    result = re.sub(r'(>)-([' + tibetan_range + '])', r'\1་\2', result)
    
    # Fix dots and commas adjacent to tags similarly
    # Dot before closing tag: བྱེ.</hi> → བྱེད</hi>
    for ascii_char, tibetan_consonant in CONSONANT_BEFORE_VOWEL.items():
        escaped_char = re.escape(ascii_char)
        result = re.sub(r'([' + TIBETAN_CONSONANTS + TIBETAN_VOWELS + '])' + escaped_char + r'(<(?:\/hi|lb|,))', 
                       r'\1' + tibetan_consonant + r'\2', result)
    
    # ASCII char before comma (often used as pause): བྱེ., → བྱེད,
    for ascii_char, tibetan_consonant in CONSONANT_BEFORE_VOWEL.items():
        escaped_char = re.escape(ascii_char)
        result = re.sub(r'([' + TIBETAN_CONSONANTS + TIBETAN_VOWELS + '])' + escaped_char + r',', 
                       r'\1' + tibetan_consonant + ',', result)
    
    # Convert comma to shad (།) when it follows Tibetan text
    # In Dedris encoding, comma represents the Tibetan shad punctuation
    tibetan_range = '\u0F00-\u0FFF'
    result = re.sub(r'([' + tibetan_range + ']),', r'\1།', result)
    
    # Also fix commas at end of hi tags: ཤིང་,</hi> → ཤིང་།</hi>
    result = re.sub(r'([' + tibetan_range + ']),(<)', r'\1།\2', result)
    
    return result


def post_process_body(body_content: str) -> str:
    """Post-process TEI body content with line breaks and tag fixes."""
    body_content = body_content.strip()
    
    # First pass: Fix Dedris patterns before tag processing
    body_content = fix_mixed_dedris_patterns(body_content)
    
    body_content = body_content.replace('\n', '\n<lb/>')
    body_content = re.sub(r' *<lb/> *', '\n<lb/>', body_content)
    body_content = re.sub(r'<lb/>\s*<pb/>', '<pb/>', body_content)
    body_content = re.sub(r'(<pb/>\s*){2,}', '<pb/>\n', body_content)
    body_content = body_content.strip()
    
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*(?:<lb/>[\s]*)*</hi>', '', body_content)
    body_content = re.sub(r'(<hi rend="[^"]+">)\s*\n<lb/>', r'\n<lb/>\1', body_content)
    body_content = re.sub(r'\n<lb/></hi>', r'</hi>\n<lb/>', body_content)
    body_content = re.sub(r'\n\n+', '\n', body_content)
    body_content = re.sub(r'<hi rend="[^"]+">[\s]*</hi>', '', body_content)
    body_content = body_content.strip()
    
    # Second pass: Fix Dedris patterns that may have been exposed by tag removal
    body_content = fix_mixed_dedris_patterns(body_content)
    
    # Fix numbered list markers where ) was incorrectly converted to འ
    # Pattern: (1འ → (1), (2འ → (2), etc.
    # This happens when numbered lists like (1), (2) were typed in Dedris font
    # and the ) character got converted to Tibetan a-chung འ
    body_content = re.sub(r'\((\d+)འ', r'(\1)', body_content)

    body_content = fix_phantom_volume_headers(body_content)

    return body_content


def generate_tei_xml(
    body_content: str,
    title: str,
    src_path: str,
    sha256: str,
    ve_id: str,
    ut_id: str,
) -> str:
    """Generate complete TEI XML document."""
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
<idno type="bdrc_ie">http://purl.bdrc.io/resource/{IE_ID}</idno>
<idno type="bdrc_ve">http://purl.bdrc.io/resource/{ve_id}</idno>
<idno type="bdrc_ut">http://purl.bdrc.io/resource/{ut_id}</idno>
</bibl>
</sourceDesc>
</fileDesc>
<encodingDesc>
<p>The TEI header does not contain any bibliographical data. It is instead accessible through the <ref target="http://purl.bdrc.io/resource/{IE_ID}">record in the BDRC database</ref>.</p>
</encodingDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p>
{body_content}
</p>
</body>
</text>
</TEI>
'''
    
    return tei_xml


