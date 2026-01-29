"""Test that SimSun font text is now converted as Dedris."""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from convert import dedris_to_unicode, STATS

# Test conversion with SimSun font (should now convert as Dedris-a)
test_cases = [
    ('SimSun', '.0'),
    ('SimSun', '.'),
    ('@SimSun', '.0'),
    ('SimSun Western', '.'),
    ('Dedris-a', '.0'),
    ('Dedris-vowa', 'J'),
]

print('Testing conversion with SimSun fix:')
print('='*60)

for font, text in test_cases:
    result = dedris_to_unicode(text, font)
    codes = ' '.join(f'U+{ord(c):04X}' for c in result) if result else 'N/A'
    print(f'{font:15s} + {repr(text):6s} -> {repr(result):10s} ({codes})')

print()
print('Stats - converted suspicious:')
for item in STATS.get('converted_suspicious', []):
    print(f"  {item}")

