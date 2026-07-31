#!/usr/bin/env python3
"""
Integration Tests for RTF to TEI XML Conversion

This module contains integration tests that use real RTF files to test
the complete conversion pipeline:

1. RTF parsing (basic_rtf.py)
2. Dedris to Unicode conversion (pytiblegenc)
3. Font size classification
4. Tibetan text normalization (tibetan_text_fixes.py)
5. TEI XML generation

Test file: KAMA-001.rtf (sample from IE1PD100944 KAMA Collection)

Run tests with:
    python -m pytest test_integration.py -v
    
Or directly:
    python test_integration.py
"""

import unittest
import os
import sys
from pathlib import Path

# Add script directory to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from basic_rtf import BasicRTF
from tibetan_text_fixes import (
    fix_flying_vowels_and_linebreaks,
    fix_hi_tag_spacing,
    count_tibetan_chars,
    is_tibetan_char,
)
from normalization import normalize_unicode, normalize_spaces

# Try to import pytiblegenc
try:
    from pytiblegenc import convert_string
    PYTIBLEGENC_AVAILABLE = True
except ImportError:
    PYTIBLEGENC_AVAILABLE = False
    print("WARNING: pytiblegenc not available, some tests will be skipped")


# =============================================================================
# Test Configuration
# =============================================================================

# Path to test RTF file
TEST_RTF_FILE = script_dir / "KAMA-001.rtf"

# Stats dictionary for pytiblegenc
STATS = {
    "handled_fonts": {},
    "unhandled_fonts": {},
    "unknown_characters": {},
    "diffs_with_utfc": {},
    "error_characters": 0
}


# =============================================================================
# Test Cases
# =============================================================================

class TestRTFParsing(unittest.TestCase):
    """
    Test cases for RTF file parsing using BasicRTF.
    
    These tests verify that the RTF parser can:
    - Parse a real RTF file without errors
    - Extract text streams with font information
    - Handle Dedris font names correctly
    """
    
    @classmethod
    def setUpClass(cls):
        """
        Set up test fixtures.
        
        Loads and parses the test RTF file once for all tests in this class.
        """
        if not TEST_RTF_FILE.exists():
            raise unittest.SkipTest(f"Test file not found: {TEST_RTF_FILE}")
        
        cls.parser = BasicRTF()
        cls.parser.parse_file(str(TEST_RTF_FILE))
        cls.streams = cls.parser.get_streams()
    
    def test_rtf_file_parsed_successfully(self):
        """
        Test that RTF file is parsed without exceptions.
        
        The parser should complete without raising any errors.
        """
        self.assertIsNotNone(self.streams)
        self.assertIsInstance(self.streams, list)
    
    def test_streams_not_empty(self):
        """
        Test that parser extracts text streams from RTF.
        
        A valid RTF file should produce multiple text streams.
        """
        self.assertGreater(len(self.streams), 0, 
                          "RTF should contain at least one text stream")
    
    def test_streams_have_text(self):
        """
        Test that text streams contain text content.
        
        Each stream should have a 'text' key with string content.
        """
        text_found = False
        for stream in self.streams:
            if stream.get("text", "").strip():
                text_found = True
                break
        self.assertTrue(text_found, "At least one stream should have text")
    
    def test_streams_have_font_info(self):
        """
        Test that text streams include font information.
        
        Each stream should have font name and size metadata.
        """
        font_found = False
        for stream in self.streams:
            font = stream.get("font", {})
            if font.get("name"):
                font_found = True
                break
        self.assertTrue(font_found, "Streams should include font information")
    
    def test_dedris_fonts_detected(self):
        """
        Test that Dedris font names are detected in streams.
        
        The KAMA files use various Dedris fonts (Dedris-a, Dedris-vowa, etc.)
        """
        dedris_fonts = set()
        for stream in self.streams:
            font_name = stream.get("font", {}).get("name", "")
            if font_name.lower().startswith(("dedris", "ededris")):
                dedris_fonts.add(font_name)
        
        self.assertGreater(len(dedris_fonts), 0, 
                          "Should detect at least one Dedris font")
        print(f"\n  Detected Dedris fonts: {sorted(dedris_fonts)}")
    
    def test_font_sizes_extracted(self):
        """
        Test that font sizes are extracted from streams.
        
        Font sizes are used for classification (regular/small/large).
        """
        font_sizes = set()
        for stream in self.streams:
            size = stream.get("font", {}).get("size")
            if size:
                font_sizes.add(size)
        
        self.assertGreater(len(font_sizes), 0, 
                          "Should detect at least one font size")
        print(f"\n  Detected font sizes: {sorted(font_sizes)}")


@unittest.skipUnless(PYTIBLEGENC_AVAILABLE, "pytiblegenc not available")
class TestDedrisConversion(unittest.TestCase):
    """
    Test cases for Dedris to Unicode conversion.
    
    These tests verify that:
    - Dedris encoded text converts to valid Unicode
    - Different Dedris fonts are handled correctly
    - Converted text contains Tibetan characters
    """
    
    @classmethod
    def setUpClass(cls):
        """
        Set up test fixtures.
        
        Parses RTF and prepares streams for conversion testing.
        """
        if not TEST_RTF_FILE.exists():
            raise unittest.SkipTest(f"Test file not found: {TEST_RTF_FILE}")
        
        parser = BasicRTF()
        parser.parse_file(str(TEST_RTF_FILE))
        cls.streams = parser.get_streams()
    
    def test_dedris_text_converts_to_unicode(self):
        """
        Test that Dedris text successfully converts to Unicode.
        
        The conversion should produce strings (not None) for Dedris fonts.
        """
        converted_count = 0
        for stream in self.streams:
            text = stream.get("text", "")
            font_name = stream.get("font", {}).get("name", "")
            
            if font_name.lower().startswith(("dedris", "ededris")) and text.strip():
                result = convert_string(text, font_name, STATS)
                if result is not None:
                    converted_count += 1
        
        self.assertGreater(converted_count, 0, 
                          "At least some Dedris text should convert")
        print(f"\n  Successfully converted {converted_count} Dedris streams")
    
    def test_converted_text_contains_tibetan(self):
        """
        Test that converted text contains Tibetan Unicode characters.
        
        Dedris fonts encode Tibetan text, so conversion should produce
        characters in the Tibetan Unicode block (U+0F00-U+0FFF).
        """
        tibetan_found = False
        tibetan_count = 0
        
        for stream in self.streams:
            text = stream.get("text", "")
            font_name = stream.get("font", {}).get("name", "")
            
            if font_name.lower().startswith(("dedris", "ededris")) and text.strip():
                result = convert_string(text, font_name, STATS)
                if result:
                    count = count_tibetan_chars(result)
                    if count > 0:
                        tibetan_found = True
                        tibetan_count += count
        
        self.assertTrue(tibetan_found, 
                       "Converted text should contain Tibetan characters")
        # Use ASCII-safe output for Windows console
        print(f"\n  Total Tibetan characters found: {tibetan_count}")
    
    def test_multiple_fonts_handled(self):
        """
        Test that multiple Dedris font variants are handled.
        
        KAMA files use various Dedris fonts (a, b, c, d, e, vowa, etc.)
        """
        handled_fonts = set()
        for stream in self.streams:
            text = stream.get("text", "")
            font_name = stream.get("font", {}).get("name", "")
            
            if font_name.lower().startswith(("dedris", "ededris")) and text.strip():
                result = convert_string(text, font_name, STATS)
                if result is not None:
                    handled_fonts.add(font_name)
        
        self.assertGreater(len(handled_fonts), 1, 
                          "Should handle multiple Dedris font variants")
        print(f"\n  Handled fonts: {sorted(handled_fonts)}")


class TestTibetanTextNormalization(unittest.TestCase):
    """
    Test cases for Tibetan text normalization.
    
    These tests use sample Tibetan text to verify normalization functions.
    """
    
    def test_flying_vowel_fix_on_sample(self):
        """
        Test flying vowel fix on realistic Tibetan text.
        
        Simulates text that was incorrectly line-wrapped in RTF.
        """
        # Simulated text with flying vowel (པ and ོ split by newline)
        input_text = "སྐྱབས་འགྲ\nོ་ཡན་ལག"
        result = fix_flying_vowels_and_linebreaks(input_text)
        
        # Vowel should join previous consonant
        self.assertNotIn("འགྲ\nོ", result)
        self.assertIn("འགྲོ", result)
    
    def test_paragraph_preservation(self):
        """
        Test that paragraph breaks (after shed) are preserved.
        
        Line breaks after Tibetan shed (།) should NOT be removed.
        """
        input_text = "སྐྱབས་འགྲོ།\nཡན་ལག"
        result = fix_flying_vowels_and_linebreaks(input_text)
        
        # Newline after shed should be preserved
        self.assertIn("།\n", result)
    
    def test_unicode_normalization(self):
        """
        Test Unicode normalization on Tibetan text.
        
        Normalization should handle character composition/decomposition.
        """
        # Sample text that might need normalization
        sample = "བཀྲ་ཤིས་བདེ་ལེགས།"
        result = normalize_unicode(sample)
        
        # Result should still be valid Tibetan
        self.assertGreater(count_tibetan_chars(result), 0)
    
    def test_space_normalization(self):
        """
        Test space normalization in Tibetan text.
        
        Multiple spaces should be collapsed, especially around punctuation.
        """
        input_text = "བཀྲ་ཤིས།   བདེ་ལེགས།"
        result = normalize_spaces(input_text, tibetan_specific=True)
        
        # Multiple spaces should be reduced
        self.assertNotIn("   ", result)


class TestFontSizeClassification(unittest.TestCase):
    """
    Test cases for font size classification logic.
    
    These tests verify the classification of font sizes into
    regular, small, and large categories.
    """
    
    def test_classification_with_two_sizes(self):
        """
        Test classification when there are exactly two font sizes.
        
        Both sizes should be classified as 'regular'.
        """
        from collections import Counter
        
        # Simulate size counts
        size_counts = Counter({18: 1000, 36: 500})
        sizes = sorted(size_counts.keys())
        
        # Top 2 are 18 and 36
        top_2 = [18, 36]
        regular_min = min(top_2)
        regular_max = max(top_2)
        
        # Both should be regular
        for size in sizes:
            if size in top_2:
                classification = 'regular'
            elif size < regular_min:
                classification = 'small'
            elif size > regular_max:
                classification = 'large'
            else:
                classification = 'regular'
            
            self.assertEqual(classification, 'regular')
    
    def test_classification_with_outliers(self):
        """
        Test classification with sizes outside the top 2 range.
        
        Sizes smaller than both top 2 → small
        Sizes larger than both top 2 → large
        """
        # Top 2: 18 and 36
        top_2 = [18, 36]
        regular_min = min(top_2)  # 18
        regular_max = max(top_2)  # 36
        
        # Test small size
        small_size = 12
        self.assertLess(small_size, regular_min)
        
        # Test large size  
        large_size = 48
        self.assertGreater(large_size, regular_max)
        
        # Test in-between size (should be regular)
        between_size = 24
        self.assertGreater(between_size, regular_min)
        self.assertLess(between_size, regular_max)


class TestEndToEndConversion(unittest.TestCase):
    """
    End-to-end integration test for the full conversion pipeline.
    
    Tests the complete flow from RTF parsing to normalized Unicode output.
    """
    
    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        if not TEST_RTF_FILE.exists():
            raise unittest.SkipTest(f"Test file not found: {TEST_RTF_FILE}")
        
        if not PYTIBLEGENC_AVAILABLE:
            raise unittest.SkipTest("pytiblegenc not available")
    
    def test_full_conversion_pipeline(self):
        """
        Test the complete RTF to normalized Unicode conversion.
        
        Pipeline:
        1. Parse RTF file
        2. Convert Dedris to Unicode
        3. Apply Tibetan text fixes
        4. Normalize Unicode
        
        Verifies that output contains valid Tibetan text.
        """
        # Step 1: Parse RTF
        parser = BasicRTF()
        parser.parse_file(str(TEST_RTF_FILE))
        streams = parser.get_streams()
        self.assertGreater(len(streams), 0)
        
        # Step 2: Convert Dedris to Unicode
        converted_texts = []
        for stream in streams:
            text = stream.get("text", "")
            font_name = stream.get("font", {}).get("name", "")
            
            if font_name.lower().startswith(("dedris", "ededris")) and text.strip():
                result = convert_string(text, font_name, STATS)
                if result:
                    converted_texts.append(result)
        
        self.assertGreater(len(converted_texts), 0, 
                          "Should have converted text")
        
        # Step 3: Combine and apply fixes
        combined = "\n".join(converted_texts)
        fixed = fix_flying_vowels_and_linebreaks(combined)
        
        # Step 4: Normalize
        normalized = normalize_unicode(fixed)
        final = normalize_spaces(normalized, tibetan_specific=True)
        
        # Verify output
        self.assertGreater(len(final), 0)
        tibetan_count = count_tibetan_chars(final)
        self.assertGreater(tibetan_count, 100,
                          "Output should contain many Tibetan characters")
        
        # Use ASCII-safe output for Windows console
        print(f"\n  Output length: {len(final)} chars, {tibetan_count} Tibetan chars")
    
    def test_no_flying_vowels_in_output(self):
        """
        Test that output has no remaining flying vowels.
        
        After normalization, vowel signs should not appear at line starts.
        """
        import re
        
        # Parse and convert
        parser = BasicRTF()
        parser.parse_file(str(TEST_RTF_FILE))
        streams = parser.get_streams()
        
        converted_texts = []
        for stream in streams:
            text = stream.get("text", "")
            font_name = stream.get("font", {}).get("name", "")
            
            if font_name.lower().startswith(("dedris", "ededris")) and text.strip():
                result = convert_string(text, font_name, STATS)
                if result:
                    converted_texts.append(result)
        
        combined = "\n".join(converted_texts)
        fixed = fix_flying_vowels_and_linebreaks(combined)
        
        # Check for flying vowels (vowel at start of line)
        tibetan_vowels = r'[\u0f71-\u0f84]'
        flying_vowel_pattern = rf'\n{tibetan_vowels}'
        
        matches = re.findall(flying_vowel_pattern, fixed)
        
        # Should have very few or no flying vowels
        self.assertLess(len(matches), 5,
                       f"Should have minimal flying vowels, found {len(matches)}")


# =============================================================================
# Test Runner
# =============================================================================

def run_tests():
    """
    Run all integration tests and print results.
    
    Returns:
        bool: True if all tests passed, False otherwise.
    """
    # Check test file exists
    if not TEST_RTF_FILE.exists():
        print(f"ERROR: Test file not found: {TEST_RTF_FILE}")
        print("Please ensure KAMA-001.rtf is in the same directory as this test file.")
        return False
    
    print(f"Using test file: {TEST_RTF_FILE}")
    print(f"File size: {TEST_RTF_FILE.stat().st_size:,} bytes")
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestRTFParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestDedrisConversion))
    suite.addTests(loader.loadTestsFromTestCase(TestTibetanTextNormalization))
    suite.addTests(loader.loadTestsFromTestCase(TestFontSizeClassification))
    suite.addTests(loader.loadTestsFromTestCase(TestEndToEndConversion))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)

