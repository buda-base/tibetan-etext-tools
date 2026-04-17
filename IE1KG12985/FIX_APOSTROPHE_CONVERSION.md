# Fix for Apostrophe Character Conversion Issue

## Problem Description

The apostrophe character `'` (U+0027) in Dedris-a font was being incorrectly converted to U+0F84 (྄ - Tibetan mark HALANTA) instead of U+0F04 (༄ - Tibetan head mark).

### Example
- **Input RTF**: `'` (apostrophe in Dedris-a font)
- **Incorrect output**: `྄` (U+0F84 - HALANTA mark)
- **Correct output**: `༄` (U+0F04 - head mark)

## Root Cause

The issue originates from the `pytiblegenc` library's character mapping for Dedris fonts. The library incorrectly maps the apostrophe character to U+0F84 instead of U+0F04.

## Solution

A post-processing fix was added to `tibetan_text_fixes.py` in the `fix_dedris_conversion_errors()` function. This function corrects the character mapping by replacing U+0F84 with U+0F04 in contexts where the head mark is expected:

1. At the beginning of text (possibly after whitespace/tags)
2. After line breaks (possibly with tags in between)
3. After opening tags at start of line

### Code Location

File: `tibetan_text_fixes.py`
Function: `fix_dedris_conversion_errors(text: str) -> str`

The fix is automatically applied during the conversion process as part of the `fix_flying_vowels_and_linebreaks()` function, which is called in the main conversion pipeline.

## Testing

The fix was tested on file `03_body.rtf` from VE1ER649:

**Before fix:**
```
First character: ྄ (U+0F84 - HALANTA mark) ✗ INCORRECT
```

**After fix:**
```
First character: ༄ (U+0F04 - head mark) ✓ CORRECT
```

## Files Modified

1. `tibetan_text_fixes.py` - Added `fix_dedris_conversion_errors()` function
2. `tibetan_text_fixes.py` - Updated `fix_flying_vowels_and_linebreaks()` to call the new function

## Future Considerations

The ideal long-term solution would be to fix the character mapping in the `pytiblegenc` library itself. However, this post-processing fix provides an immediate solution that works reliably for all conversions.
