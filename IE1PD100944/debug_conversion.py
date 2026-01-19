"""Debug script to trace where unconverted characters come from."""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from basic_rtf import BasicRTF

def main():
    # Parse the RTF file that produces the problematic output
    rtf_path = r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1PD100944_rtf\KAMA-001.rtf"
    
    print(f"Parsing: {rtf_path}")
    parser = BasicRTF()
    parser.parse_file(rtf_path, show_progress=False)
    streams = parser.get_streams()
    
    print(f"Total streams: {len(streams)}")
    
    # Find streams containing the problematic patterns
    # Looking for '.' or '0' which should be Dedris characters
    print("\n" + "="*60)
    print("Streams containing '.' (should be Dedris ད):")
    print("="*60)
    
    count = 0
    for i, s in enumerate(streams):
        if 'text' not in s:
            continue
        text = s['text']
        if '.' in text:
            font_name = s['font'].get('name', 'UNKNOWN')
            font_id = s['font'].get('id', -1)
            count += 1
            if count <= 20:
                print(f"\n[Stream {i}] Font: {font_name} (id={font_id})")
                print(f"  Text: {repr(text[:100])}")
    
    print(f"\nTotal streams with '.': {count}")
    
    # Check what fonts contain these characters
    print("\n" + "="*60)
    print("Font distribution for streams with '.':")
    print("="*60)
    
    font_counts = {}
    for s in streams:
        if 'text' not in s:
            continue
        if '.' in s['text']:
            font_name = s['font'].get('name', 'UNKNOWN')
            font_counts[font_name] = font_counts.get(font_name, 0) + 1
    
    for font, count in sorted(font_counts.items(), key=lambda x: -x[1]):
        print(f"  {font}: {count} streams")
    
    # Now check for '0'
    print("\n" + "="*60)
    print("Streams containing '0':")
    print("="*60)
    
    count = 0
    for i, s in enumerate(streams):
        if 'text' not in s:
            continue
        text = s['text']
        if '0' in text:
            font_name = s['font'].get('name', 'UNKNOWN')
            font_id = s['font'].get('id', -1)
            count += 1
            if count <= 10:
                print(f"\n[Stream {i}] Font: {font_name} (id={font_id})")
                print(f"  Text: {repr(text[:100])}")
    
    print(f"\nTotal streams with '0': {count}")

if __name__ == '__main__':
    main()

