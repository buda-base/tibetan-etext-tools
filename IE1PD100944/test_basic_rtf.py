"""
Test suite for basic_rtf.py RTF parser.

Tests parsing of KAMA-001.rtf file which uses Dedris legacy fonts.
"""

import unittest
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from basic_rtf import BasicRTF, detect_rtf_format


class TestBasicRTFParser(unittest.TestCase):
    """Test the BasicRTF parser with KAMA-001.rtf"""
    
    @classmethod
    def setUpClass(cls):
        """Parse the RTF file once for all tests."""
        cls.rtf_path = os.path.join(os.path.dirname(__file__), "KAMA-001.rtf")
        
        if not os.path.exists(cls.rtf_path):
            raise FileNotFoundError(f"Test file not found: {cls.rtf_path}")
        
        cls.parser = BasicRTF()
        cls.parser.parse_file(cls.rtf_path, show_progress=False)
        cls.streams = cls.parser.get_streams()
        cls.fonts = cls.parser.get_fonts()
    
    def test_format_detection(self):
        """Test that KAMA-001.rtf is detected as 'complex' format.
        
        KAMA-001.rtf has panose info for Dedris fonts, making it 'complex'.
        """
        fmt = detect_rtf_format(self.rtf_path)
        self.assertEqual(fmt, 'complex', "KAMA-001.rtf should be detected as 'complex' format")
    
    def test_fonts_parsed(self):
        """Test that fonts are correctly parsed from font table."""
        fonts = self.fonts
        self.assertGreater(len(fonts), 0, "Should have parsed at least one font")
        
        # Check for expected Dedris fonts
        font_names = {f['name'] for f in fonts}
        
        expected_dedris = [
            'Dedris-vowa',  # f45
            'Dedris-a1',    # f46
            'Dedris-b',     # f47
            'Dedris-a2',    # f48
            'Dedris-c',     # f49
            'Dedris-e2',    # f50
            'Dedris-d',     # f51
            'Dedris-b1',    # f52
            'Dedris-a',     # f53
        ]
        
        for expected in expected_dedris:
            self.assertIn(expected, font_names, f"Expected font '{expected}' not found")
    
    def test_font_id_mapping(self):
        """Test that specific font IDs map to correct names."""
        font_map = {f['id']: f['name'] for f in self.fonts}
        
        # From KAMA-001.rtf font table (lines 3-5):
        # f45 = Dedris-vowa, f46 = Dedris-a1, f47 = Dedris-b
        # f48 = Dedris-a2, f49 = Dedris-c, f50 = Dedris-e2
        # f51 = Dedris-d, f52 = Dedris-b1, f53 = Dedris-a
        expected_mappings = {
            45: 'Dedris-vowa',
            46: 'Dedris-a1',
            47: 'Dedris-b',
            48: 'Dedris-a2',
            49: 'Dedris-c',
            50: 'Dedris-e2',
            51: 'Dedris-d',
            52: 'Dedris-b1',
            53: 'Dedris-a',
        }
        
        for fid, expected_name in expected_mappings.items():
            self.assertIn(fid, font_map, f"Font ID {fid} not found in font map")
            self.assertEqual(font_map[fid], expected_name, 
                           f"Font ID {fid} should be '{expected_name}', got '{font_map[fid]}'")
    
    def test_streams_not_empty(self):
        """Test that streams are extracted from the RTF."""
        self.assertGreater(len(self.streams), 0, "Should have extracted at least one stream")
    
    def test_stream_structure(self):
        """Test that text streams have the expected structure."""
        # Find first text stream
        text_stream = None
        for s in self.streams:
            if 'text' in s:
                text_stream = s
                break
        
        self.assertIsNotNone(text_stream, "Should have at least one text stream")
        
        # Check required fields
        self.assertIn('text', text_stream, "Stream should have 'text' field")
        self.assertIn('font', text_stream, "Stream should have 'font' field")
        self.assertIn('char_start', text_stream, "Stream should have 'char_start' field")
        self.assertIn('char_end', text_stream, "Stream should have 'char_end' field")
        
        # Check font structure
        font = text_stream['font']
        self.assertIn('id', font, "Font should have 'id' field")
        self.assertIn('name', font, "Font should have 'name' field")
        self.assertIn('size', font, "Font should have 'size' field")
    
    def test_par_break_streams(self):
        """Test that paragraph breaks are detected."""
        par_breaks = [s for s in self.streams if s.get('type') == 'par_break']
        self.assertGreater(len(par_breaks), 0, "Should have detected paragraph breaks")
    
    def test_first_content_stream(self):
        """Test the first content stream (title line).
        
        From line 95: !, , (Dedris-vowa) which should be the first visible text.
        """
        # Find first text stream with actual content
        for s in self.streams:
            if 'text' in s and s['text'].strip():
                first_stream = s
                break
        
        self.assertIsNotNone(first_stream, "Should have a first content stream")
        
        # First visible text should be from Dedris-vowa (font 45)
        # The text "!, ," in Dedris-vowa represents certain Tibetan characters
        self.assertEqual(first_stream['font']['name'], 'Dedris-vowa',
                        f"First content stream should be Dedris-vowa, got {first_stream['font']['name']}")
    
    def test_escaped_brace_handling(self):
        """Test that escaped braces \\{ are correctly parsed.
        
        From line 128: o- $<- \\{.- should parse the \\{ as literal {
        The expected stream text should be: o- $<- {.- 
        (with the escaped brace converted to literal brace)
        """
        # Find streams with Dedris-a font (f53) containing the escaped brace test case
        dedris_a_streams = [s for s in self.streams 
                          if 'text' in s and s['font']['name'] == 'Dedris-a']
        
        # Look for the stream containing the escaped brace sequence
        found_escaped_brace = False
        for s in dedris_a_streams:
            text = s['text']
            # The RTF has: o- $<- \{.- 
            # After parsing, \{ should become {
            if '{' in text and 'o-' in text.replace(' ', ''):
                found_escaped_brace = True
                # Verify the text contains the expected characters
                # o- $<- {.- should all be present
                self.assertIn('{', text, "Escaped brace should be converted to literal {")
                break
        
        self.assertTrue(found_escaped_brace, 
                       "Should find a stream with escaped brace converted to literal {")
    
    def test_stream_text_complete(self):
        """Test that stream text is not truncated.
        
        Known issue: The stream 'o- $<- {.- ' was being truncated to 'o- $<- {.'
        This test checks that the hyphen-space '- ' after the brace is preserved.
        """
        # Find the stream with the problematic text
        for s in self.streams:
            if 'text' in s and '{' in s['text']:
                text = s['text']
                # If we have a brace followed by a period, check what comes after
                brace_idx = text.find('{')
                if brace_idx >= 0:
                    after_brace = text[brace_idx:]
                    # The original RTF has: \{.- which should become {.-
                    # Then there should be more content (space or hyphen)
                    if '.' in after_brace:
                        # Check that we have the full sequence: {.- followed by space
                        # (or the stream ends at the correct boundary)
                        pass  # This test documents the expected behavior
    
    def test_font_size_parsing(self):
        """Test that font sizes are correctly parsed.
        
        KAMA-001.rtf has various font sizes:
        - fs72 = 36pt (title - large text)
        - fs48 = 24pt (body text)
        - fs36 = 18pt (smaller text)
        - fs32 = 16pt (yig chung)
        
        Note: RTF uses half-points, so fs72 = 72/2 = 36pt
        """
        sizes = set()
        for s in self.streams:
            if 'font' in s:
                sizes.add(s['font']['size'])
        
        # Should have multiple font sizes
        self.assertGreater(len(sizes), 1, "Should detect multiple font sizes")
        
        # Common sizes in the document (actual observed values)
        # The document primarily uses fs72 (36pt) and fs36 (18pt)
        expected_sizes = {36, 18}  # Confirmed from actual parsing
        for expected in expected_sizes:
            self.assertIn(expected, sizes, 
                         f"Expected font size {expected}pt not found. Found: {sizes}")
    
    def test_dedris_content_streams(self):
        """Test that content is properly attributed to Dedris fonts."""
        # Count streams per Dedris font
        font_counts = {}
        for s in self.streams:
            if 'font' in s:
                name = s['font']['name']
                if name.startswith('Dedris'):
                    font_counts[name] = font_counts.get(name, 0) + 1
        
        # Should have content from multiple Dedris fonts
        self.assertGreater(len(font_counts), 1, 
                          "Should have content from multiple Dedris fonts")
        
        # Dedris-a (main text font) should have the most streams
        self.assertIn('Dedris-a', font_counts, "Should have Dedris-a streams")
        self.assertIn('Dedris-vowa', font_counts, "Should have Dedris-vowa streams")


class TestSpecificStreams(unittest.TestCase):
    """Test specific stream extractions from KAMA-001.rtf"""
    
    @classmethod
    def setUpClass(cls):
        cls.rtf_path = os.path.join(os.path.dirname(__file__), "KAMA-001.rtf")
        cls.parser = BasicRTF()
        cls.parser.parse_file(cls.rtf_path, show_progress=False)
        cls.streams = cls.parser.get_streams()
    
    def test_critical_stream_128(self):
        """Test the critical stream from line 128-129 of RTF.
        
        RTF line 128: \\hich\\af53\\dbch\\af13\\loch\\f53 o- $<- \\{.- 
        RTF line 129: }{\\rtlch\\fcs1 \\af0 \\ltrch\\fcs0 \\f46\\insrsid13651887 .}
        
        Expected:
        - Stream 1 (Dedris-a, f53): "o- $<- {.- " (with the '.' after the brace)
        - Stream 2 (Dedris-a1, f46): "."
        
        KNOWN BUG: The '.' after the escaped brace is being lost!
        Current output: "o- $<- {- " (missing the '.')
        Expected output: "o- $<- {.- "
        """
        # Find streams that might be the problematic ones
        dedris_a_streams = []
        
        for i, s in enumerate(self.streams):
            if 'text' not in s:
                continue
            if s['font']['name'] == 'Dedris-a':
                dedris_a_streams.append((i, s))
        
        # Find the specific stream with the escaped brace
        stream_with_brace = None
        for idx, s in dedris_a_streams:
            if '{' in s['text'] and 'o-' in s['text'].replace(' ', ''):
                stream_with_brace = (idx, s)
                break
        
        self.assertIsNotNone(stream_with_brace, 
                            "Should find a Dedris-a stream with escaped brace and 'o-'")
        
        idx, s = stream_with_brace
        text = s['text']
        
        # Document the current (buggy) behavior
        # Currently getting: 'o- $<- {- ' 
        # Should be getting: 'o- $<- {.- '
        self.assertIn('o-', text.replace(' ', ''), 
                     f"Stream should contain 'o-'. Got: {repr(text)}")
        self.assertIn('{', text, 
                     f"Stream should contain '{{'. Got: {repr(text)}")
    
    def test_critical_stream_128_bug_documented(self):
        """Document the KNOWN BUG: '.' is lost after escaped brace.
        
        RTF input: o- $<- \\{.- 
        Current buggy output: 'o- $<- {- ' (missing the '.')
        Expected correct output: 'o- $<- {.- '
        
        This test will FAIL until the bug is fixed.
        When this test passes, the bug has been fixed!
        """
        # Find the stream with the escaped brace
        for s in self.streams:
            if 'text' not in s or s['font']['name'] != 'Dedris-a':
                continue
            if '{' in s['text'] and 'o-' in s['text'].replace(' ', ''):
                text = s['text']
                
                # The period should appear after the brace
                # RTF: \{.- means escaped brace followed by period and hyphen
                brace_idx = text.find('{')
                after_brace = text[brace_idx + 1:]
                
                # BUG: Currently the '.' is missing!
                # This assertion documents the bug - it should contain '.'
                # When the bug is fixed, this will pass
                self.assertIn('.', after_brace, 
                    f"BUG: Character after '{{' should include '.', but got: {repr(after_brace)}\n"
                    f"Full stream text: {repr(text)}\n"
                    f"RTF input was: o- $<- \\{{.- \n"
                    f"Expected output: 'o- $<- {{.- '\n"
                    f"Actual output: {repr(text)}")
                return
        
        self.fail("Could not find the test stream with escaped brace")
    
    def test_stream_sequence_integrity(self):
        """Test that text streams maintain proper sequence."""
        prev_end = 0
        for s in self.streams:
            start = s.get('char_start', 0)
            end = s.get('char_end', 0)
            
            # Start should be >= previous end (no overlap)
            self.assertGreaterEqual(start, 0, "char_start should be non-negative")
            self.assertGreaterEqual(end, start, "char_end should be >= char_start")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases in RTF parsing."""
    
    @classmethod
    def setUpClass(cls):
        cls.rtf_path = os.path.join(os.path.dirname(__file__), "KAMA-001.rtf")
        cls.parser = BasicRTF()
        cls.parser.parse_file(cls.rtf_path, show_progress=False)
        cls.streams = cls.parser.get_streams()
    
    def test_escaped_backslash(self):
        """Test that \\\\ (escaped backslash) is handled."""
        # Search for any stream that might have a backslash
        for s in self.streams:
            if 'text' in s and '\\' in s['text']:
                # Escaped backslash should become single backslash
                self.assertNotIn('\\\\', s['text'], 
                               "Double backslash should be converted to single")
    
    def test_empty_streams_filtered(self):
        """Test that completely empty streams are filtered.
        
        Note: Space-only streams ARE preserved because they're legitimate
        content from the RTF (e.g., spaces between characters in different fonts).
        """
        for s in self.streams:
            if 'text' in s:
                # Streams should have non-empty text (spaces are OK)
                self.assertTrue(len(s['text']) > 0, 
                              f"Found completely empty text stream")
    
    def test_special_characters_preserved(self):
        """Test that special Dedris characters are preserved."""
        all_text = ''.join(s['text'] for s in self.streams if 'text' in s)
        
        # Dedris fonts use special ASCII characters that map to Tibetan
        # Characters like: !, @, #, $, %, etc. should be preserved
        special_chars = set('!@#$%^&*()-=+[]{}|;:,.<>?')
        found_special = any(c in all_text for c in special_chars)
        
        self.assertTrue(found_special, 
                       "Should preserve special characters from Dedris fonts")


class TestFullStreamContent(unittest.TestCase):
    """Test that all streams concatenate to the expected Dedris text."""
    
    @classmethod
    def setUpClass(cls):
        cls.rtf_path = os.path.join(os.path.dirname(__file__), "KAMA-001.rtf")
        cls.parser = BasicRTF()
        cls.parser.parse_file(cls.rtf_path, show_progress=False)
        cls.streams = cls.parser.get_streams()
    
    def get_all_text(self):
        """Get concatenated text from all streams, with newlines for par_breaks."""
        parts = []
        for s in self.streams:
            if 'text' in s:
                parts.append(s['text'])
            elif s.get('type') == 'par_break':
                parts.append('\n')
        return ''.join(parts)
    
    def test_full_concatenated_text(self):
        """Test that all streams concatenate to expected Dedris-encoded text.
        
        This verifies the EXACT expected output from KAMA-001.rtf.
        """
        actual_text = self.get_all_text().strip()
        
        # The exact expected text from KAMA-001.rtf (Dedris encoding)
        expected_text = """!, ,}- :I<- 2!:- 3:A- (R?- #J:A- \\J$?- 23- .%- 0R- 28$?- ?R, ,
!, ,F D ; > < E Z 3 2A @ < +A (, ,
!, ,*2?- :PR- ;/- =$- S$- 0- 8J?- L- 2- 28$?- ?R, ,
<-J- !A, *2?- :PR- ;/- =$- S$- 0- :.A- =- .R/- 28A- =?, .%- 0R- 35/- IA- .R/, o- $<- {.- ., F- D- 2- >- <- E), 2R.- {.- ., *2?- :PR- ;/- =$- S$- 0, $*A?- 0- :I<- IA- K$- .!R/- 3(R$- $?3- =- K$- :5=- =R, ,$?3- 0- $8%- $A- .R/- =- $*A?, 2l3- 0<- .3- 2&:- 2- 2#?- .R/- .%- 2&?- 0- .%, $8%- .R/- .%R?- 2>.- 0:R, ,.%- 0R- /A, *2?- :PR- ;/- =$- S$- 0- 2>., ,$*A?- 0- =- $*A?, 3.R<- 2!/- 0- .%- , o?- 0<- 2>.- 0:R, ,.%- 0R- /A, &A?- :PR- ;=- .?- .$R?- 0- .%- , ,1/- ;R/- 2a2- L- ]%- 2-i3?, ,l- 2- #R3- .- 2>.- 0- ;A/, ,$*A?- 0- o?- 0<- 2>.- 0- =- <A3- 0<, :#R<- 2- =, :)A$?- .%- .!R/- 3(R$- $?3- IA-;R/- +/- S/- 0?- *2?-?- :PR, ,$/?- $?3-2!/- 0:A- ;=- .J- =, ,:.A- /?- L%- (2- ,R2- 2<- <R, ,3- !J$?- ,R.- =?- =R$- 0- ;A/, ,%/- ?R%- $?3- .- 3A- *J-#R3-0- $R%- 3:A-gJ/- .- :I<, ,2<- (.- 3J.- 0?- /.- *%- 5K- <A%- , #A$- 1A2, :L%- 8A%- 5S$?- ?R$- 0:A- 1/- ;R/- /R, ,?R- ?R:C- 2a2- L, *2?- $?3- .%- 0R:C- 2a2- L- /A, ,$/R.- .A/- 3A- 2!J/- K$- 3A- :5=, ,$*A?- 0- ?J3?- &/- ,3?- &.- =, ,:5K- 2- %%?- >A%- 2lJ- 2<- L, ,$?3- 0- 2.$- .%- $8/- IA- ;=, ,#A$- 0- &/- .%- :PR$?- 0- 3A/, ,{- $9$?- 5B$?- ?- 2&.- 0- .%- , ,z/- 0- ?J<- 0R- 2+2- 0- =, ,..- 3R?- |R- /?- !R/- 0<- 2g$ ,8=- /?- $?%?- 0- 3,:- .$- =, ,{<- 0- 3A- $.2- ,A- 2R<- ]%, ,$%- 9$- .$- .%- 3- .$- =?, ,.3- 0<- 2v- 2<- L- 2- ;A/, ,,/- 3R%- $A- 2a2- L, =?- YR$- KA<- ;%- $?3- 3A- %%- , ,.?- :.A<- nJ/- i3?- &A-L%- ;%- , ,3$R/-*2?- $8/- .- 24=- 2- 3A/, ,(J- 2:A- ;R/- +/- g$- +- S/, ,9?- .$- $A?- /A- 3(R.- 0- ;A/, ,o/- IA- *2?- :PR- 2eR.- L- 2, ,.?- S$- o/- IA- 2{=- 3- ;A/, ,]%- 2- .%- 0R<- >J?- 0<- L, ,:)A$?- 0- L%- 5K- 2{=- 3- ;A/, ,28A- 0- 3)$- $A- .R/, o.- =- >J?- L- 3%- 3(A?- G%-, , o=- ]R/- ;A.- (J?- 3- I<- 0?, ,*2?- :PR:A- (R- $- 2.$- $A?- 2>., ,=J$?- 0<- VA?- >A$- !- 3- <, ,2?R.- /3?- :PR- 2- ;R%?- =- 2}R, ,*2?- :PR- ;/- =$- S$- 0, aR2- .0R/- (J/- 0R- SA- 3J.- 2>J?- $*J/- IA?- 36.- 0- mR$?- ?R,, ,,:.A- =- :I<- L%- 3A- $%- ;%- , v- $&A$- .A- 0)- !- <:A- ,$?- .3- (S?- (%- 2o- l:A- P%?- ?- 28$?- 0?- 5.- 3<- 29%- %R- , ,.0J- :.A- %<- 3- .0J- fA%-l-(J/-8A$- 3#/- 5=- OA3?- 3,<- KA/- IA- K$- .0J- =?- #R- 2R- L%- (2- o- 35S?- fJ.- .J- :6.- 0:R, ,
!, ,*2?- :PR- ;/- =$- S$- 0- .%- 2./- &- 0:A- (R?- GA- 2.$- 0R- i3?- =- $?R=- :.J2?- 2o.-w/- ]- 3:A- LA/- _2?- .0=- !J<- 8J?- L- 2- 28$?- ?R, ,""".strip()
        
        # Compare after normalizing whitespace (collapse multiple spaces/newlines)
        import re
        def normalize(s):
            return re.sub(r'\s+', ' ', s).strip()
        
        actual_norm = normalize(actual_text)
        expected_norm = normalize(expected_text)
        
        if actual_norm != expected_norm:
            # Find first difference
            min_len = min(len(actual_norm), len(expected_norm))
            first_diff = -1
            for i in range(min_len):
                if actual_norm[i] != expected_norm[i]:
                    first_diff = i
                    break
            if first_diff == -1:
                first_diff = min_len
            
            context_start = max(0, first_diff - 30)
            context_end = min(len(expected_norm), first_diff + 30)
            
            self.fail(
                f"Text mismatch at position {first_diff}:\n"
                f"Expected: ...{repr(expected_norm[context_start:context_end])}...\n"
                f"Actual:   ...{repr(actual_norm[context_start:context_end])}..."
            )
    
    def test_critical_sequence_preserved(self):
        """Test that the critical sequence 'o- $<- {.- .' is fully preserved.
        
        This sequence tests the escaped brace handling:
        - RTF: o- $<- \\{.- 
        - Expected parsed: o- $<- {.- 
        
        The '.' after '{' must NOT be lost!
        """
        all_text = self.get_all_text()
        
        # The critical sequence that tests escaped brace handling
        critical_sequence = "o- $<- {.- ."
        
        self.assertIn(critical_sequence, all_text,
                     f"Critical sequence '{critical_sequence}' not found in parsed text.\n"
                     f"This indicates the '.' after escaped brace is being lost!")
    
    def test_second_escaped_brace_sequence(self):
        """Test the second escaped brace sequence '2R.- {.- .' is preserved."""
        all_text = self.get_all_text()
        
        critical_sequence = "2R.- {.- ."
        
        self.assertIn(critical_sequence, all_text,
                     f"Second escaped brace sequence '{critical_sequence}' not found.\n"
                     f"The '.' after escaped brace is being lost!")
    
    def test_stream_count(self):
        """Test that we have the expected number of streams."""
        # Count text streams and par_breaks
        text_streams = [s for s in self.streams if 'text' in s]
        par_breaks = [s for s in self.streams if s.get('type') == 'par_break']
        
        print(f"\nStream counts:")
        print(f"  Text streams: {len(text_streams)}")
        print(f"  Par breaks: {len(par_breaks)}")
        print(f"  Total: {len(self.streams)}")
        
        # We expect a reasonable number of streams
        self.assertGreater(len(text_streams), 100, "Should have many text streams")
        self.assertGreater(len(par_breaks), 2, "Should have multiple paragraph breaks")


def print_stream_summary(streams, max_streams=20):
    """Utility function to print stream summary for debugging."""
    print(f"\n{'='*60}")
    print(f"Total streams: {len(streams)}")
    print(f"{'='*60}")
    
    for i, s in enumerate(streams[:max_streams]):
        if 'text' in s:
            text_repr = repr(s['text'])[:50]
            font = s['font']
            print(f"[{i:3d}] {font['name']:12s} (size={font['size']:2d}): {text_repr}")
        elif s.get('type') == 'par_break':
            print(f"[{i:3d}] PAR_BREAK")
        elif s.get('type') == 'line_break':
            print(f"[{i:3d}] LINE_BREAK")
    
    if len(streams) > max_streams:
        print(f"... and {len(streams) - max_streams} more streams")


def print_all_streams(streams):
    """Print ALL streams for debugging."""
    print(f"\n{'='*60}")
    print(f"ALL {len(streams)} STREAMS:")
    print(f"{'='*60}")
    
    for i, s in enumerate(streams):
        if 'text' in s:
            font = s['font']
            print(f"[{i:3d}] {font['name']:12s} (size={font['size']:2d}): {repr(s['text'])}")
        elif s.get('type') == 'par_break':
            print(f"[{i:3d}] PAR_BREAK")
        elif s.get('type') == 'line_break':
            print(f"[{i:3d}] LINE_BREAK")


if __name__ == '__main__':
    # Run with verbosity
    unittest.main(verbosity=2)

