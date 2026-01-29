"""Test pytiblegenc conversion of Dedris characters."""
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from pytiblegenc import convert_string

# Test conversion of '.' in various Dedris fonts
test_fonts = ['Dedris-a', 'Dedris-a1', 'Dedris-b', 'Dedris-vowa', 'SimSun']
stats = {
    'handled_fonts': {},
    'unhandled_fonts': {},
    'unknown_characters': {},
    'diffs_with_utfc': {},
    'error_characters': 0
}

print('Testing conversion of . and 0 in Dedris fonts:')
print('='*60)

for font in test_fonts:
    result_dot = convert_string('.', font, stats)
    result_zero = convert_string('0', font, stats)
    
    # Show Unicode code points
    dot_codes = ' '.join(f'U+{ord(c):04X}' for c in (result_dot or '.'))
    zero_codes = ' '.join(f'U+{ord(c):04X}' for c in (result_zero or '0'))
    
    print(f'{font}:')
    print(f'  . -> {repr(result_dot)} ({dot_codes})')
    print(f'  0 -> {repr(result_zero)} ({zero_codes})')
    print()

# Test a full string
print('='*60)
print('Testing full string conversion:')
test_str = 'o- $<- {.- .'
result = convert_string(test_str, 'Dedris-a', stats)
print(f'Input:  {repr(test_str)}')
print(f'Output: {repr(result)}')
if result:
    codes = ' '.join(f'U+{ord(c):04X}' for c in result)
    print(f'Codes:  {codes}')

# Check stats
print('\n' + '='*60)
print('Stats:')
print(f'  Handled fonts: {list(stats["handled_fonts"].keys())}')
print(f'  Unhandled fonts: {list(stats["unhandled_fonts"].keys())}')
print(f'  Unknown chars: {stats["unknown_characters"]}')

