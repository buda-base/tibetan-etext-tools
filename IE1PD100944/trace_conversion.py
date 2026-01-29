"""Trace the conversion pipeline to find where characters aren't converted."""
import sys
import os
import io
import re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from basic_rtf import BasicRTF
from pytiblegenc import convert_string

STATS = {
    'handled_fonts': {},
    'unhandled_fonts': {},
    'unknown_characters': {},
    'diffs_with_utfc': {},
    'error_characters': 0
}

def main():
    rtf_path = r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1PD100944_rtf\KAMA-001.rtf"
    
    print(f"Parsing: {rtf_path}")
    parser = BasicRTF()
    parser.parse_file(rtf_path, show_progress=False)
    streams = parser.get_streams()
    
    print(f"Total streams: {len(streams)}")
    
    # Convert all streams and look for unconverted '.' followed by converted vowels
    print("\n" + "="*60)
    print("Looking for problematic patterns after conversion...")
    print("="*60)
    
    converted_text = []
    problem_count = 0
    
    for i, s in enumerate(streams):
        if 'text' not in s:
            if s.get('type') == 'par_break':
                converted_text.append('\n')
            continue
        
        text = s['text']
        font_name = s['font'].get('name', '')
        
        # Convert if Dedris font
        if font_name.lower().startswith(('dedris', 'ededris')):
            result = convert_string(text, font_name, STATS)
            if result is None:
                converted_text.append(text)  # Keep original if conversion fails
            else:
                converted_text.append(result)
        else:
            converted_text.append(text)  # Keep non-Dedris as-is
    
    full_text = ''.join(converted_text)
    
    # Search for problematic patterns
    # ASCII char followed by Tibetan vowel
    tibetan_vowels = '[\u0f71-\u0f84]'
    
    patterns = [
        (r'[0-9]' + tibetan_vowels, 'Digit + Tibetan vowel'),
        (r'\.' + tibetan_vowels, 'Period + Tibetan vowel'),
    ]
    
    for pattern, desc in patterns:
        matches = re.findall(r'.{0,20}' + pattern + r'.{0,20}', full_text)
        if matches:
            print(f"\n{desc} ({len(matches)} found):")
            for m in matches[:5]:
                print(f"  {repr(m)}")
    
    # Now trace BACKWARDS: find where these patterns come from
    print("\n" + "="*60)
    print("Tracing source of problematic patterns...")
    print("="*60)
    
    # Find a specific problematic pattern
    problem_pattern = re.search(r'(.{0,30})\.[0-9ེོིུ](.{0,30})', full_text)
    if problem_pattern:
        context = problem_pattern.group(0)
        print(f"\nFound problematic pattern: {repr(context)}")
        
        # Find the position in full_text
        pos = problem_pattern.start()
        
        # Now trace which streams contributed to this position
        current_pos = 0
        print(f"\nStreams around position {pos}:")
        for i, s in enumerate(streams):
            if 'text' not in s:
                if s.get('type') == 'par_break':
                    current_pos += 1
                continue
            
            text = s['text']
            font_name = s['font'].get('name', '')
            
            # Convert for length calculation
            if font_name.lower().startswith(('dedris', 'ededris')):
                result = convert_string(text, font_name, STATS)
                converted = result if result else text
            else:
                converted = text
            
            stream_end = current_pos + len(converted)
            
            # Check if this stream overlaps with our problem position
            if current_pos <= pos < stream_end or (pos < current_pos < pos + 50):
                print(f"\n  Stream {i} (pos {current_pos}-{stream_end}):")
                print(f"    Font: {font_name}")
                print(f"    Original: {repr(text)}")
                print(f"    Converted: {repr(converted)}")
            
            current_pos = stream_end
            
            if current_pos > pos + 100:
                break

if __name__ == '__main__':
    main()

