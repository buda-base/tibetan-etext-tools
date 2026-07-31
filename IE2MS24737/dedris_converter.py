"""
Dedris to Unicode Converter Module

This module provides functions to convert Dedris legacy-encoded Tibetan text
to Unicode using the pytiblegenc library.
"""

import logging

logger = logging.getLogger(__name__)

# Global stats for tracking conversion results
STATS = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0,
    "skipped_non_dedris": [],
    "converted_suspicious": [],
}


def reset_stats():
    """Reset conversion statistics."""
    global STATS
    STATS = {
        "handled_fonts": {},
        "unhandled_fonts": {},
        "unknown_characters": {},
        "diffs_with_utfc": {},
        "error_characters": 0,
        "skipped_non_dedris": [],
        "converted_suspicious": [],
    }


def get_stats():
    """Get current conversion statistics."""
    return STATS


# Try to import pytiblegenc
try:
    from pytiblegenc import convert_string
    PYTIBLEGENC_AVAILABLE = True
except ImportError:
    PYTIBLEGENC_AVAILABLE = False
    logger.warning(
        "pytiblegenc not available. Install with:\n"
        "  pip install -U git+https://github.com/buda-base/py-tiblegenc.git"
    )
    
    def convert_string(text, font_name, stats):
        """Fallback when pytiblegenc is not available."""
        return text


SUSPICIOUS_FONTS = ('simsun', '@simsun', 'simsun western')


def is_dedris_font(font_name: str) -> bool:
    """Check if a font name is a Dedris font."""
    if not font_name:
        return False
    lower_name = font_name.lower()
    return lower_name.startswith(('dedris', 'ededris'))


def is_suspicious_font(font_name: str) -> bool:
    """Check if a font might contain misattributed Dedris text."""
    if not font_name:
        return False
    return font_name.lower() in SUSPICIOUS_FONTS


def dedris_to_unicode(text: str, font_name: str) -> str:
    """
    Convert Dedris encoded string to Unicode using pytiblegenc.
    
    Args:
        text: Text in Dedris encoding
        font_name: Font name from RTF (e.g., "Dedris-a", "Dedris-vowa")
        
    Returns:
        Unicode text
    """
    if not text or not text.strip():
        return text
    
    is_dedris = is_dedris_font(font_name)
    is_suspicious = is_suspicious_font(font_name)
    
    if not is_dedris and not is_suspicious:
        has_suspicious = any(c in text for c in '{}0123456789.,;:!?@#$%^&*()[]<>')
        if has_suspicious and len(text.strip()) > 0:
            preview = text[:50].replace('\n', '\\n')
            if len(STATS["skipped_non_dedris"]) < 100:
                STATS["skipped_non_dedris"].append({
                    "font": font_name or "(no font)",
                    "text": preview,
                    "chars": [f"'{c}'({ord(c)})" for c in text[:20] if ord(c) < 128]
                })
        return text
    
    effective_font = font_name if is_dedris else 'Dedris-a'
    
    try:
        result = convert_string(text, effective_font, STATS)
        if result is None:
            preview = text[:50].replace('\n', '\\n')
            logger.warning(f"UNHANDLED FONT: '{effective_font}' (original: '{font_name}') | text: '{preview}'")
            return text
        
        if is_suspicious:
            if len(STATS["converted_suspicious"]) < 50:
                STATS["converted_suspicious"].append({
                    "font": font_name,
                    "text": text[:30],
                    "result": result[:30]
                })
        
        return result
    except Exception as e:
        logger.warning(f"Error converting with font {effective_font}: {e}")
        return text


def print_conversion_stats():
    """Print comprehensive debug information about the conversion."""
    logger.info("")
    logger.info("=" * 60)
    logger.info("CONVERSION STATISTICS")
    logger.info("=" * 60)
    
    if STATS["handled_fonts"]:
        logger.info("")
        logger.info("HANDLED FONTS (successfully converted):")
        for font, count in sorted(STATS["handled_fonts"].items()):
            logger.info(f"  {font}: {count} characters")
    
    if STATS["unhandled_fonts"]:
        logger.info("")
        logger.info("UNHANDLED FONTS (not in pytiblegenc tables):")
        for font, count in sorted(STATS["unhandled_fonts"].items()):
            logger.info(f"  {font}: {count} characters NOT converted")
    
    if STATS["unknown_characters"]:
        logger.info("")
        logger.info("UNKNOWN CHARACTERS BY FONT:")
        for font, chars in sorted(STATS["unknown_characters"].items()):
            sample_chars = list(chars)[:20]
            char_info = [f"'{c}'({ord(c) if len(c) == 1 else 'multi'})" for c in sample_chars]
            logger.info(f"  {font}: {len(chars)} unknown chars")
            logger.info(f"    Samples: {', '.join(char_info)}")
    
    if STATS["error_characters"] > 0:
        logger.info(f"\nERROR CHARACTERS: {STATS['error_characters']} conversion errors")
    
    logger.info("=" * 60)


def write_stats_file(output_path):
    """Write conversion statistics to a file."""
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("CONVERSION STATISTICS\n")
            f.write("=" * 60 + "\n\n")
            
            f.write("HANDLED FONTS:\n")
            if STATS["handled_fonts"]:
                for font, count in sorted(STATS["handled_fonts"].items()):
                    f.write(f"  {font}: {count} characters\n")
            else:
                f.write("  None recorded\n")
            
            f.write("\nUNHANDLED FONTS:\n")
            if STATS["unhandled_fonts"]:
                for font, count in sorted(STATS["unhandled_fonts"].items()):
                    f.write(f"  {font}: {count} characters NOT converted\n")
            else:
                f.write("  None (all fonts were handled)\n")
            
            f.write(f"\nERROR CHARACTERS: {STATS['error_characters']}\n")
            
        logger.info(f"Stats written to: {output_path}")
    except Exception as e:
        logger.warning(f"Could not write stats file: {e}")


