#!/usr/bin/env python3
"""
Test Suite for Tibetan Text Fixes Module

This module contains comprehensive test cases for all functions in 
tibetan_text_fixes.py, covering:

1. Flying vowel fixes
2. Flying subscript fixes
3. Mid-word line break fixes
4. XML tag spacing fixes
5. Utility functions (character counting, detection)

Run tests with:
    python -m pytest test_tibetan_text_fixes.py -v
    
Or directly:
    python test_tibetan_text_fixes.py
"""

import unittest
from tibetan_text_fixes import (
    # Main fix functions
    fix_flying_vowels,
    fix_flying_subscripts,
    fix_mid_word_breaks,
    fix_flying_vowels_and_linebreaks,
    fix_hi_tag_spacing,
    normalize_tibetan_text,
    # Utility functions
    is_tibetan_char,
    count_tibetan_chars,
    is_tibetan_punctuation,
    # Constants
    TIBETAN_TSEG,
    TIBETAN_SHED,
)


class TestFlyingVowels(unittest.TestCase):
    """
    Test cases for fix_flying_vowels() function.
    
    Flying vowels occur when a vowel sign (like ོ, ི, ུ, ེ) appears at the 
    start of a line but should attach to the consonant at the end of the 
    previous line. This typically happens due to RTF line wrapping.
    """
    
    def test_vowel_o_joins_previous_consonant(self):
        """
        Test that vowel ོ (o) at line start joins previous consonant པ.
        
        Input:  དང་པ\nོ་ནི།
        Output: དང་པོ་ནི།
        
        The པ (pa) + ོ (o vowel) should become པོ (po).
        """
        input_text = "དང་པ\nོ་ནི།"
        expected = "དང་པོ་ནི།"
        self.assertEqual(fix_flying_vowels(input_text), expected)
    
    def test_vowel_i_joins_previous_consonant(self):
        """
        Test that vowel ི (i) at line start joins previous consonant.
        
        Input:  ག\nི་དོན།
        Output: གི་དོན།
        """
        input_text = "ག\nི་དོན།"
        expected = "གི་དོན།"
        self.assertEqual(fix_flying_vowels(input_text), expected)
    
    def test_vowel_u_joins_previous_consonant(self):
        """
        Test that vowel ུ (u) at line start joins previous consonant.
        
        Input:  ད\nུ་མ།
        Output: དུ་མ།
        """
        input_text = "ད\nུ་མ།"
        expected = "དུ་མ།"
        self.assertEqual(fix_flying_vowels(input_text), expected)
    
    def test_vowel_e_joins_previous_consonant(self):
        """
        Test that vowel ེ (e) at line start joins previous consonant.
        
        Input:  ད\nེ་ནི།
        Output: དེ་ནི།
        """
        input_text = "ད\nེ་ནི།"
        expected = "དེ་ནི།"
        self.assertEqual(fix_flying_vowels(input_text), expected)
    
    def test_multiple_newlines_collapsed(self):
        """
        Test that multiple newlines between consonant and vowel are handled.
        
        Input:  པ\n\nོ
        Output: པོ
        """
        input_text = "པ\n\nོ"
        expected = "པོ"
        self.assertEqual(fix_flying_vowels(input_text), expected)
    
    def test_vowel_after_vowel(self):
        """
        Test vowel joining when previous character is also a vowel.
        
        Some syllables have stacked vowels (e.g., ཨོཾ).
        """
        input_text = "ཨ\nོ"
        expected = "ཨོ"
        self.assertEqual(fix_flying_vowels(input_text), expected)
    
    def test_with_xml_tags(self):
        """
        Test flying vowel fix works across XML tags.
        
        Input:  པ</hi>\n<hi>ོ
        Output: པ</hi><hi>ོ
        
        XML tags should be preserved but newline removed.
        """
        input_text = "པ</hi>\n<hi>ོ"
        expected = "པ</hi><hi>ོ"
        self.assertEqual(fix_flying_vowels(input_text), expected)
    
    def test_empty_string(self):
        """Test that empty string returns empty string."""
        self.assertEqual(fix_flying_vowels(""), "")
    
    def test_none_input(self):
        """Test that None input returns None."""
        self.assertIsNone(fix_flying_vowels(None))
    
    def test_no_flying_vowels(self):
        """Test text without flying vowels is unchanged."""
        input_text = "བཀྲ་ཤིས་བདེ་ལེགས།"
        self.assertEqual(fix_flying_vowels(input_text), input_text)


class TestFlyingSubscripts(unittest.TestCase):
    """
    Test cases for fix_flying_subscripts() function.
    
    Flying subscripts occur when a subscript consonant (like ྱ, ྲ, ླ) appears
    at the start of a line but should attach below the consonant at the end
    of the previous line.
    """
    
    def test_subscript_ya_joins_previous(self):
        """
        Test that subscript ྱ (ya) at line start joins previous consonant ག.
        
        Input:  ག\nྱི་
        Output: གྱི་
        
        The ག (ga) + ྱ (subjoined ya) should form གྱ (gya).
        """
        input_text = "ག\nྱི་"
        expected = "གྱི་"
        self.assertEqual(fix_flying_subscripts(input_text), expected)
    
    def test_subscript_ra_joins_previous(self):
        """
        Test that subscript ྲ (ra) at line start joins previous consonant.
        
        Input:  ད\nྲག
        Output: དྲག
        """
        input_text = "ད\nྲག"
        expected = "དྲག"
        self.assertEqual(fix_flying_subscripts(input_text), expected)
    
    def test_subscript_la_joins_previous(self):
        """
        Test that subscript ླ (la) at line start joins previous consonant.
        
        Input:  བ\nླ་མ
        Output: བླ་མ
        """
        input_text = "བ\nླ་མ"
        expected = "བླ་མ"
        self.assertEqual(fix_flying_subscripts(input_text), expected)
    
    def test_subscript_wa_joins_previous(self):
        """
        Test that subscript ྭ (wa) at line start joins previous consonant.
        
        Input:  ད\nྭངས
        Output: དྭངས
        """
        input_text = "ད\nྭངས"
        expected = "དྭངས"
        self.assertEqual(fix_flying_subscripts(input_text), expected)
    
    def test_with_xml_tags(self):
        """
        Test flying subscript fix works across XML tags.
        """
        input_text = "ག</hi>\n<hi>ྱི"
        expected = "ག</hi><hi>ྱི"
        self.assertEqual(fix_flying_subscripts(input_text), expected)
    
    def test_empty_string(self):
        """Test that empty string returns empty string."""
        self.assertEqual(fix_flying_subscripts(""), "")


class TestMidWordBreaks(unittest.TestCase):
    """
    Test cases for fix_mid_word_breaks() function.
    
    Mid-word breaks occur when a word is split across lines with a consonant
    at the end of one line and another consonant at the start of the next,
    without a tseg (་) or shed (།) between them.
    """
    
    def test_consonant_joins_previous_syllable(self):
        """
        Test that consonant at line start joins previous syllable.
        
        Input:  བྱི\nན་
        Output: བྱིན་
        
        The ན should join བྱི to form བྱིན.
        """
        input_text = "བྱི\nན་"
        expected = "བྱིན་"
        self.assertEqual(fix_mid_word_breaks(input_text), expected)
    
    def test_preserves_break_after_tseg(self):
        """
        Test that line break after tseg (་) is preserved.
        
        Input:  འབྱང་\nཞིང་
        Output: འབྱང་\nཞིང་  (unchanged - break after tseg is valid)
        
        Breaks after tseg represent legitimate word/syllable boundaries.
        """
        input_text = "འབྱང་\nཞིང་"
        expected = "འབྱང་\nཞིང་"
        self.assertEqual(fix_mid_word_breaks(input_text), expected)
    
    def test_preserves_break_after_shed(self):
        """
        Test that line break after shed (།) is preserved.
        
        Input:  བཤད།\nསྐྱབས
        Output: བཤད།\nསྐྱབས  (unchanged - break after shed is valid)
        
        Breaks after shed represent paragraph/section boundaries.
        """
        input_text = "བཤད།\nསྐྱབས"
        expected = "བཤད།\nསྐྱབས"
        self.assertEqual(fix_mid_word_breaks(input_text), expected)
    
    def test_consonant_after_vowel(self):
        """
        Test consonant joining when previous character is a vowel.
        
        Input:  མཐོ\nང་
        Output: མཐོང་
        """
        input_text = "མཐོ\nང་"
        expected = "མཐོང་"
        self.assertEqual(fix_mid_word_breaks(input_text), expected)
    
    def test_with_xml_tags(self):
        """
        Test mid-word break fix works across XML tags.
        """
        input_text = "བྱི</hi>\n<hi>ན"
        expected = "བྱི</hi><hi>ན"
        self.assertEqual(fix_mid_word_breaks(input_text), expected)


class TestFlyingVowelsAndLinebreaks(unittest.TestCase):
    """
    Test cases for fix_flying_vowels_and_linebreaks() - the main combined function.
    
    This function applies all three fixes in sequence:
    1. Flying vowels
    2. Flying subscripts  
    3. Mid-word breaks
    """
    
    def test_combined_fixes(self):
        """
        Test that all fix types are applied together.
        """
        # Flying vowel
        self.assertEqual(
            fix_flying_vowels_and_linebreaks("པ\nོ"),
            "པོ"
        )
        # Flying subscript
        self.assertEqual(
            fix_flying_vowels_and_linebreaks("ག\nྱི"),
            "གྱི"
        )
        # Mid-word break
        self.assertEqual(
            fix_flying_vowels_and_linebreaks("བྱི\nན"),
            "བྱིན"
        )
    
    def test_complex_text(self):
        """
        Test a more complex text with multiple issues.
        """
        input_text = "དང་པ\nོ་ག\nྱི་བྱི\nན།"
        # Should fix: པ+ོ, ག+ྱ, བྱི+ན
        expected = "དང་པོ་གྱི་བྱིན།"
        self.assertEqual(fix_flying_vowels_and_linebreaks(input_text), expected)
    
    def test_preserves_valid_breaks(self):
        """
        Test that valid paragraph breaks are preserved.
        """
        input_text = "བཤད། །\nསྐྱབས་འགྲོ།"
        # Break after ། should be preserved
        expected = "བཤད། །\nསྐྱབས་འགྲོ།"
        self.assertEqual(fix_flying_vowels_and_linebreaks(input_text), expected)
    
    def test_real_world_example(self):
        """
        Test with a realistic example from Tibetan text.
        """
        # Simulating text that was incorrectly line-wrapped
        input_text = "སྐྱབས་འགྲོ་ཡན་ལག་དྲུག་པ\nོ།"
        expected = "སྐྱབས་འགྲོ་ཡན་ལག་དྲུག་པོ།"
        self.assertEqual(fix_flying_vowels_and_linebreaks(input_text), expected)


class TestHiTagSpacing(unittest.TestCase):
    """
    Test cases for fix_hi_tag_spacing() function.
    
    This function ensures proper spacing around <hi> tags based on 
    Tibetan punctuation rules.
    """
    
    def test_add_space_before_hi_after_shed(self):
        """
        Test that space is added before <hi> when preceded by shed.
        
        Input:  །<hi rend="small">text
        Output: ། <hi rend="small">text
        """
        input_text = '།<hi rend="small">ཨོཾ'
        expected = '། <hi rend="small">ཨོཾ'
        self.assertEqual(fix_hi_tag_spacing(input_text), expected)
    
    def test_add_space_after_hi_ending_with_shed(self):
        """
        Test that space is added after </hi> when content ends with shed.
        
        Input:  །</hi>རྒྱ
        Output: །</hi> རྒྱ
        """
        input_text = "།</hi>རྒྱ"
        expected = "།</hi> རྒྱ"
        self.assertEqual(fix_hi_tag_spacing(input_text), expected)
    
    def test_no_space_when_already_present(self):
        """
        Test that extra space is not added when already present.
        """
        input_text = "། <hi>text</hi> next"
        # Should not add duplicate spaces
        result = fix_hi_tag_spacing(input_text)
        self.assertNotIn("།  <hi>", result)  # No double space
    
    def test_no_space_after_tseg_ending(self):
        """
        Test that no space is added when <hi> content ends with tseg.
        
        Tseg (་) doesn't require space after </hi>.
        """
        input_text = "་</hi>next"
        expected = "་</hi>next"
        self.assertEqual(fix_hi_tag_spacing(input_text), expected)
    
    def test_empty_string(self):
        """Test that empty string returns empty string."""
        self.assertEqual(fix_hi_tag_spacing(""), "")


class TestUtilityFunctions(unittest.TestCase):
    """
    Test cases for utility functions in the module.
    """
    
    def test_is_tibetan_char_consonant(self):
        """
        Test is_tibetan_char() with Tibetan consonants.
        """
        # Tibetan consonants should return True
        self.assertTrue(is_tibetan_char('ཀ'))  # ka
        self.assertTrue(is_tibetan_char('ག'))  # ga
        self.assertTrue(is_tibetan_char('ང'))  # nga
        self.assertTrue(is_tibetan_char('ད'))  # da
        self.assertTrue(is_tibetan_char('བ'))  # ba
    
    def test_is_tibetan_char_vowel(self):
        """
        Test is_tibetan_char() with Tibetan vowel signs.
        """
        self.assertTrue(is_tibetan_char('ི'))  # i vowel
        self.assertTrue(is_tibetan_char('ུ'))  # u vowel
        self.assertTrue(is_tibetan_char('ེ'))  # e vowel
        self.assertTrue(is_tibetan_char('ོ'))  # o vowel
    
    def test_is_tibetan_char_punctuation(self):
        """
        Test is_tibetan_char() with Tibetan punctuation.
        """
        self.assertTrue(is_tibetan_char('་'))  # tseg
        self.assertTrue(is_tibetan_char('།'))  # shed
        self.assertTrue(is_tibetan_char('༄'))  # initial yig mgo
    
    def test_is_tibetan_char_non_tibetan(self):
        """
        Test is_tibetan_char() with non-Tibetan characters.
        """
        self.assertFalse(is_tibetan_char('a'))
        self.assertFalse(is_tibetan_char('1'))
        self.assertFalse(is_tibetan_char(' '))
        self.assertFalse(is_tibetan_char('中'))  # Chinese
    
    def test_is_tibetan_char_empty_string(self):
        """
        Test is_tibetan_char() with empty or multi-char string.
        """
        self.assertFalse(is_tibetan_char(''))
        self.assertFalse(is_tibetan_char('ཀག'))  # Two chars
    
    def test_count_tibetan_chars(self):
        """
        Test count_tibetan_chars() with mixed text.
        """
        # Pure Tibetan
        self.assertEqual(count_tibetan_chars("བཀྲ་ཤིས།"), 8)  # 6 chars + tseg + shed
        
        # Mixed with spaces and Latin
        self.assertEqual(count_tibetan_chars("བཀྲ་ test ཤིས།"), 8)
        
        # Empty string
        self.assertEqual(count_tibetan_chars(""), 0)
        
        # No Tibetan
        self.assertEqual(count_tibetan_chars("Hello World"), 0)
    
    def test_is_tibetan_punctuation_tseg(self):
        """
        Test is_tibetan_punctuation() with tseg.
        """
        self.assertTrue(is_tibetan_punctuation('་'))  # tseg
    
    def test_is_tibetan_punctuation_shed(self):
        """
        Test is_tibetan_punctuation() with shed variants.
        """
        self.assertTrue(is_tibetan_punctuation('།'))  # single shed
        self.assertTrue(is_tibetan_punctuation('༎'))  # double shed
    
    def test_is_tibetan_punctuation_non_punct(self):
        """
        Test is_tibetan_punctuation() with non-punctuation.
        """
        self.assertFalse(is_tibetan_punctuation('ཀ'))  # consonant
        self.assertFalse(is_tibetan_punctuation('ོ'))  # vowel
        self.assertFalse(is_tibetan_punctuation('.'))  # Latin period


class TestNormalizeTibetanText(unittest.TestCase):
    """
    Test cases for normalize_tibetan_text() convenience function.
    """
    
    def test_all_fixes_applied(self):
        """
        Test that all fixes are applied by default.
        """
        input_text = "པ\nོ། །<hi>text</hi>"
        result = normalize_tibetan_text(input_text)
        # Flying vowel should be fixed
        self.assertIn("པོ", result)
    
    def test_disable_linebreak_fixes(self):
        """
        Test that linebreak fixes can be disabled.
        """
        input_text = "པ\nོ"
        result = normalize_tibetan_text(input_text, fix_linebreaks=False)
        # Flying vowel should NOT be fixed
        self.assertEqual(result, input_text)
    
    def test_disable_tag_spacing(self):
        """
        Test that tag spacing fixes can be disabled.
        """
        input_text = "།<hi>text</hi>"
        result = normalize_tibetan_text(input_text, fix_tag_spacing=False)
        # Space should NOT be added
        self.assertEqual(result, input_text)
    
    def test_empty_string(self):
        """Test that empty string returns empty string."""
        self.assertEqual(normalize_tibetan_text(""), "")


class TestEdgeCases(unittest.TestCase):
    """
    Test edge cases and boundary conditions.
    """
    
    def test_only_newlines(self):
        """Test text that is only newlines."""
        result = fix_flying_vowels_and_linebreaks("\n\n\n")
        self.assertEqual(result, "\n\n\n")
    
    def test_only_tibetan_text_no_breaks(self):
        """Test properly formatted Tibetan text without issues."""
        input_text = "བཀྲ་ཤིས་བདེ་ལེགས།"
        result = fix_flying_vowels_and_linebreaks(input_text)
        self.assertEqual(result, input_text)
    
    def test_long_text_with_many_breaks(self):
        """Test longer text with multiple line breaks."""
        input_text = "དང་པ\nོ་ནི། གཉིས་པ\nོ། གསུམ་པ\nོ།"
        expected = "དང་པོ་ནི། གཉིས་པོ། གསུམ་པོ།"
        result = fix_flying_vowels_and_linebreaks(input_text)
        self.assertEqual(result, expected)
    
    def test_nested_xml_tags(self):
        """Test with nested XML tags."""
        input_text = "པ</hi></p>\n<p><hi>ོ"
        expected = "པ</hi></p><p><hi>ོ"
        result = fix_flying_vowels(input_text)
        self.assertEqual(result, expected)
    
    def test_mixed_scripts(self):
        """Test text with mixed Tibetan and Latin scripts."""
        input_text = "Title: དང་པ\nོ་ནི། (Section 1)"
        expected = "Title: དང་པོ་ནི། (Section 1)"
        result = fix_flying_vowels_and_linebreaks(input_text)
        self.assertEqual(result, expected)


# =============================================================================
# Test Runner
# =============================================================================

def run_tests():
    """
    Run all tests and print results.
    
    Returns:
        bool: True if all tests passed, False otherwise.
    """
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestFlyingVowels))
    suite.addTests(loader.loadTestsFromTestCase(TestFlyingSubscripts))
    suite.addTests(loader.loadTestsFromTestCase(TestMidWordBreaks))
    suite.addTests(loader.loadTestsFromTestCase(TestFlyingVowelsAndLinebreaks))
    suite.addTests(loader.loadTestsFromTestCase(TestHiTagSpacing))
    suite.addTests(loader.loadTestsFromTestCase(TestUtilityFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestNormalizeTibetanText))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)

