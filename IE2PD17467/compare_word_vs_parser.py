"""
Compare text extracted from Word vs RTF parser.
This helps identify where the parser might be missing content.
"""

import win32com.client
import os
import sys
import re
from pathlib import Path

# Set UTF-8 output
sys.stdout.reconfigure(encoding='utf-8')

def extract_text_from_word(rtf_path):
    """Extract all text from RTF file using Word."""
    word = win32com.client.Dispatch('Word.Application')
    word.Visible = False
    
    try:
        doc = word.Documents.Open(str(rtf_path))
        text = doc.Content.Text
        doc.Close(False)
        return text
    finally:
        word.Quit()


def extract_text_from_parser(rtf_path):
    """Extract text using our basic_rtf parser."""
    from basic_rtf import BasicRTF
    
    parser = BasicRTF()
    parser.parse_file(str(rtf_path), show_progress=True)
    streams = parser.get_streams()
    
    # Concatenate all text streams
    text_parts = []
    for stream in streams:
        if 'text' in stream:
            text_parts.append(stream['text'])
    return ''.join(text_parts), streams


def find_differences(word_text, parser_text):
    """Find characters in Word text that don't appear in parser text."""
    word_chars = set(word_text)
    parser_chars = set(parser_text)
    
    # Find characters only in Word output
    only_in_word = word_chars - parser_chars
    
    return only_in_word


def find_dedris_patterns(text, context_chars=20):
    """Find potential unconverted Dedris patterns."""
    # Look for ASCII chars mixed with Tibetan
    tibetan_range = r'[\u0F00-\u0FFF]'
    dedris_ascii = r'[.{}0\\/()\-,]'
    
    patterns = []
    
    # Pattern: Tibetan + ASCII + Tibetan
    pattern = f'({tibetan_range})({dedris_ascii})({tibetan_range})'
    for match in re.finditer(pattern, text):
        start = max(0, match.start() - context_chars)
        end = min(len(text), match.end() + context_chars)
        context = text[start:end]
        patterns.append({
            'match': match.group(),
            'context': context,
            'position': match.start()
        })
    
    return patterns


def main():
    rtf_dir = Path(r'C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE2PD17467\IE2PD17467\rtf\VE5CN237')
    
    # Find the file
    rtf_file = None
    for f in rtf_dir.iterdir():
        if f.name.startswith('6') and f.suffix == '.rtf':
            rtf_file = f
            break
    
    if not rtf_file:
        print("RTF file not found!")
        return
    
    print(f"Processing: {rtf_file.name}")
    
    # Extract text from Word
    print("\n=== Extracting text from Word ===")
    word_text = extract_text_from_word(rtf_file)
    print(f"Word text length: {len(word_text)} characters")
    
    # Save Word text
    word_output = Path('word_extracted_text.txt')
    word_output.write_text(word_text, encoding='utf-8')
    print(f"Saved to: {word_output}")
    
    # Extract text from parser
    print("\n=== Extracting text from RTF Parser ===")
    parser_text, parser_streams = extract_text_from_parser(rtf_file)
    print(f"Parser text length: {len(parser_text)} characters")
    print(f"Total streams: {len(parser_streams)}")
    
    # Save parser text
    parser_output = Path('parser_extracted_text.txt')
    parser_output.write_text(parser_text, encoding='utf-8')
    print(f"Saved to: {parser_output}")
    
    # Find Dedris patterns in Word text
    print("\n=== Finding Dedris patterns in Word text ===")
    word_patterns = find_dedris_patterns(word_text)
    print(f"Found {len(word_patterns)} potential Dedris patterns in Word text")
    
    if word_patterns[:10]:
        print("\nFirst 10 patterns:")
        for p in word_patterns[:10]:
            print(f"  '{p['match']}' at position {p['position']}")
            print(f"    Context: ...{p['context']}...")
    
    # Find Dedris patterns in parser text
    print("\n=== Finding Dedris patterns in Parser text ===")
    parser_patterns = find_dedris_patterns(parser_text)
    print(f"Found {len(parser_patterns)} potential Dedris patterns in Parser text")
    
    if parser_patterns[:10]:
        print("\nFirst 10 patterns:")
        for p in parser_patterns[:10]:
            print(f"  '{p['match']}' at position {p['position']}")
            print(f"    Context: ...{p['context']}...")
    
    # Analyze Dedris streams
    print("\n=== Analyzing Dedris Streams ===")
    dedris_streams = [s for s in parser_streams if 'font' in s and s['font'].get('name', '').startswith('Dedris')]
    print(f"Total Dedris streams: {len(dedris_streams)}")
    
    # Show sample Dedris streams with ASCII patterns
    dedris_with_ascii = []
    ascii_chars = set('.{}0\\/()\-,;:-')
    for s in dedris_streams:
        text = s.get('text', '')
        has_ascii = any(c in ascii_chars for c in text)
        if has_ascii:
            dedris_with_ascii.append(s)
    
    print(f"Dedris streams with ASCII chars: {len(dedris_with_ascii)}")
    if dedris_with_ascii[:10]:
        print("\nFirst 10 Dedris streams with ASCII:")
        for s in dedris_with_ascii[:10]:
            print(f"  Font: {s['font']['name']}")
            print(f"  Text: '{s['text']}'")
            print()
    
    # Save Dedris streams to a file for analysis
    dedris_output = Path('dedris_streams.txt')
    with dedris_output.open('w', encoding='utf-8') as f:
        for i, s in enumerate(dedris_streams):
            f.write(f"=== Stream {i} ===\n")
            f.write(f"Font: {s['font']['name']} (id: {s['font']['id']})\n")
            f.write(f"Text: {s['text']}\n")
            f.write(f"Char range: {s['char_start']}-{s['char_end']}\n\n")
    print(f"Saved Dedris streams to: {dedris_output}")
    
    # Compare lengths
    print("\n=== Summary ===")
    print(f"Word text length:   {len(word_text)}")
    print(f"Parser text length: {len(parser_text)}")
    print(f"Difference:         {abs(len(word_text) - len(parser_text))}")
    print(f"Dedris patterns in Word:   {len(word_patterns)}")
    print(f"Dedris patterns in Parser: {len(parser_patterns)}")


if __name__ == '__main__':
    main()
