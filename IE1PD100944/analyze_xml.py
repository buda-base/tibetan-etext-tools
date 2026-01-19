"""Analyze XML output for unconverted Dedris characters."""
import re
import sys
import io

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def analyze_xml(xml_path):
    with open(xml_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Extract body content between <body> tags
    body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL)
    if not body_match:
        print('No body content found')
        return
    
    body = body_match.group(1)
    print(f"Body length: {len(body)} characters")
    
    # Find ASCII characters that appear with Tibetan vowels (suspicious unconverted)
    # Tibetan vowels: U+0F71-U+0F84
    vowels = '[\u0f71-\u0f84]'
    
    print('\nSearching for unconverted Dedris characters...')
    print('='*60)
    
    # Search for digit + vowel
    matches = re.findall(r'.{0,15}[0-9]' + vowels + r'.{0,15}', body)
    if matches:
        print(f'\nDigit + vowel ({len(matches)} found):')
        for m in matches[:10]:
            print(f'  {repr(m)}')
    
    # Search for period + vowel
    matches = re.findall(r'.{0,15}\.' + vowels + r'.{0,15}', body)
    if matches:
        print(f'\nPeriod + vowel ({len(matches)} found):')
        for m in matches[:10]:
            print(f'  {repr(m)}')
    
    # Search for uppercase + vowel
    matches = re.findall(r'.{0,15}[A-Z]' + vowels + r'.{0,15}', body)
    if matches:
        print(f'\nUppercase + vowel ({len(matches)} found):')
        for m in matches[:10]:
            print(f'  {repr(m)}')
    
    # All ASCII chars in body
    print('\n' + '='*60)
    print('Distinct ASCII chars in body (may be unconverted):')
    ascii_chars = set()
    for c in body:
        if 32 <= ord(c) < 127 and c not in ' <>/="':
            ascii_chars.add(c)
    print(f'  {sorted(ascii_chars)}')
    
    # Show first 500 chars of body
    print('\n' + '='*60)
    print('First 500 characters of body:')
    print(body[:500])

if __name__ == '__main__':
    xml_path = sys.argv[1] if len(sys.argv) > 1 else r'C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\IE1PD100944_output\archive\VE3KG466\UT3KG466_0001.xml'
    analyze_xml(xml_path)

