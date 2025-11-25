#!/usr/bin/env python3
"""
Script to simplify font size markup in txt files.
Removes noise from font size changes that are about layout rather than semantics.

This is step 1a in the processing pipeline, executed before Unicode normalization.
The goal is to reduce font size markup to only semantically meaningful changes,
preparing for step 2 where we'll convert to semantic tags like <small>, <large>, etc.

Usage:
    python3 step1_fs.py              # Process all files
    python3 step1_fs.py --test       # Run tests
    
Or import and use the simplify_font_sizes() function directly.
"""

import re
import csv
from pathlib import Path
from collections import Counter


def simplify_font_sizes(text):
    """
    Simplify font size markup by removing layout-related changes.
    
    Rules:
    1. Remove font size changes without tsheg (་) or shad (།) before next change
    2. Merge parentheses ༼ and ༽ with adjacent font sizes
    
    Args:
        text: Input text with <fs:xx> markup
        
    Returns:
        Simplified text with reduced font size markup
    """
    
    # Step 1: Parse text into segments of (font_size, content) pairs
    # Split by <fs:xx> tags
    pattern = r'<fs:(\d+)>'
    parts = re.split(pattern, text)
    
    # Build list of (font_size, content) tuples
    segments = []
    current_fs = None
    
    for i, part in enumerate(parts):
        if i % 2 == 0:
            # This is content
            if part:  # Only add non-empty content
                segments.append((current_fs, part))
        else:
            # This is a font size number
            current_fs = part
    
    if not segments:
        return text
    
    # Step 2: Process segments to handle parentheses
    # ༼ that is standalone (just "༼") should use the next font size
    # ༼ that is part of longer content should stay with current font size
    # ༽ should be merged with previous content (acts as a separator)
    processed_segments = []
    
    for i, (fs, content) in enumerate(segments):
        # Skip segments marked as processed (empty content)
        if not content:
            continue
            
        # Handle opening parenthesis ༼ - only if it's standalone
        if content == '༼' and i + 1 < len(segments):
            # Standalone ༼ followed by another segment - merge with next font size
            next_fs, next_content = segments[i + 1]
            processed_segments.append((next_fs, '༼' + next_content))
            segments[i + 1] = (None, '')  # Mark as processed
        # Handle closing parenthesis ༽
        elif content.startswith('༽') and processed_segments:
            # ༽ at start of content (after font size change) - merge with previous segment
            prev_fs, prev_content = processed_segments[-1]
            processed_segments[-1] = (prev_fs, prev_content + content)
        elif content == '༽' and processed_segments:
            # Standalone ༽ - merge with previous segment
            prev_fs, prev_content = processed_segments[-1]
            processed_segments[-1] = (prev_fs, prev_content + '༽')
        else:
            # Keep segment as is (including segments with fs=None)
            processed_segments.append((fs, content))
    
    segments = [(fs, c) for fs, c in processed_segments if c]
    
    # Step 3: Merge segments without tsheg/shad with previous segments
    merged_segments = []
    
    for i, (fs, content) in enumerate(segments):
        # Check if current content has tsheg, shad, or closing parenthesis
        # Closing parenthesis ༽ acts as a separator
        has_separator = '་' in content or '།' in content or content.endswith('༽')
        
        # If no separator and we have previous segments, merge with previous
        if not has_separator and merged_segments:
            # Merge with previous segment (use previous font size)
            prev_fs, prev_content = merged_segments[-1]
            merged_segments[-1] = (prev_fs, prev_content + content)
        # Special case: first segment that is only whitespace - keep without font size tag
        elif not has_separator and not merged_segments and not content.strip():
            merged_segments.append((None, content))
        else:
            # Has separator or first segment with non-whitespace content - keep as is
            merged_segments.append((fs, content))
    
    # Step 4: Remove consecutive segments with same font size
    final_segments = []
    for fs, content in merged_segments:
        if final_segments and final_segments[-1][0] == fs:
            # Merge with previous segment
            prev_fs, prev_content = final_segments[-1]
            final_segments[-1] = (fs, prev_content + content)
        else:
            final_segments.append((fs, content))
    
    # Step 5: Rebuild text
    result = []
    for fs, content in final_segments:
        if fs is not None:
            result.append(f'<fs:{fs}>{content}')
        else:
            # Content without font size (e.g., leading spaces before first tag)
            result.append(content)
    
    return ''.join(result)


def classify_font_sizes(text, file_path):
    """
    Classify font sizes in text into large, regular, and small categories.
    
    Uses heuristics to determine classification:
    - Analyzes frequency of each font size (large is typically rare)
    - Looks at relative ratios between sizes
    - Typical ratios: 24/18 for regular/small, 26/22 for large/regular
    
    Args:
        text: Input text with <fs:xx> markup
        file_path: Path to the file being processed (for CSV output)
        
    Returns:
        List of tuples: (font_size, classification, confidence)
        where classification is 'large', 'regular', or 'small'
        and confidence is '' or '?' if unsure
    """
    
    # Extract all font sizes and their character counts
    pattern = r'<fs:(\d+)>([^<]*)'
    matches = re.findall(pattern, text)
    
    if not matches:
        return []
    
    # Count characters for each font size
    size_counts = Counter()
    for fs, content in matches:
        # Count actual Tibetan characters, not spaces or punctuation
        char_count = len([c for c in content if ord(c) > 3840])  # Tibetan Unicode range starts at 3840
        if char_count > 0:
            size_counts[int(fs)] += char_count
    
    if not size_counts:
        return []
    
    # Get sorted list of font sizes
    sizes = sorted(size_counts.keys())
    total_chars = sum(size_counts.values())
    
    # Calculate percentages
    size_percentages = {fs: (count / total_chars * 100) for fs, count in size_counts.items()}
    
    # Classification logic
    classifications = {}
    
    if len(sizes) == 1:
        # Only one size - it's regular
        classifications[sizes[0]] = ('regular', '')
    
    elif len(sizes) == 2:
        # Two sizes - determine which is regular and which is small/large
        fs1, fs2 = sizes
        pct1, pct2 = size_percentages[fs1], size_percentages[fs2]
        
        # The one with higher percentage is likely regular
        if pct1 > pct2:
            # fs1 is regular, fs2 is either small or large
            if fs2 > fs1:
                classifications[fs1] = ('regular', '')
                classifications[fs2] = ('large', '?' if pct2 > 15 else '')
            else:
                classifications[fs1] = ('regular', '')
                classifications[fs2] = ('small', '')
        else:
            # fs2 is regular, fs1 is either small or large
            if fs1 > fs2:
                classifications[fs2] = ('regular', '')
                classifications[fs1] = ('large', '?' if pct1 > 15 else '')
            else:
                classifications[fs2] = ('regular', '')
                classifications[fs1] = ('small', '')
    
    else:
        # Three or more sizes
        # Find the most common size - that's regular
        most_common_fs = max(size_counts.items(), key=lambda x: x[1])[0]
        classifications[most_common_fs] = ('regular', '')
        
        # Classify others relative to regular
        for fs in sizes:
            if fs == most_common_fs:
                continue
            
            pct = size_percentages[fs]
            
            if fs > most_common_fs:
                # Larger than regular
                ratio = fs / most_common_fs
                # Large titles are typically rare (< 10% of text)
                if pct < 10:
                    classifications[fs] = ('large', '')
                elif ratio > 1.15:  # Significant size difference
                    classifications[fs] = ('large', '?')
                else:
                    # Might be regular variant
                    classifications[fs] = ('regular', '?')
            
            else:
                # Smaller than regular
                ratio = most_common_fs / fs
                # Small text (footnotes, etc.) can vary in frequency
                if ratio > 1.2:  # Significant size difference
                    classifications[fs] = ('small', '')
                else:
                    # Might be regular variant
                    classifications[fs] = ('small', '?')
    
    # Return as list of tuples
    return [(fs, classifications[fs][0], classifications[fs][1]) for fs in sorted(classifications.keys())]


def process_files_and_classify(input_dir='DKCC/step0', output_csv='DKCC/font_size_classification.csv'):
    """
    Process all txt files, simplify font sizes, and classify them.
    Writes classification results to a CSV file.
    
    Args:
        input_dir: Directory containing txt files to process
        output_csv: Path to output CSV file
    """
    
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Error: Input directory {input_dir} does not exist")
        return
    
    # Collect all txt files
    txt_files = list(input_path.rglob('*.txt'))
    print(f"Found {len(txt_files)} txt files to process")
    
    # Open CSV file for writing
    csv_rows = []
    csv_rows.append(['PDF File Path', 'Font Size', 'Classification', 'Confidence'])
    
    processed = 0
    for txt_file in txt_files:
        try:
            # Read file
            with open(txt_file, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # Simplify font sizes first
            simplified_text = simplify_font_sizes(text)
            
            # Classify font sizes
            classifications = classify_font_sizes(simplified_text, str(txt_file))
            
            # Add to CSV
            for fs, classification, confidence in classifications:
                csv_rows.append([
                    str(txt_file.relative_to(input_path.parent)),
                    fs,
                    classification,
                    confidence
                ])
            
            processed += 1
            if processed % 100 == 0:
                print(f"Processed {processed}/{len(txt_files)} files...")
        
        except Exception as e:
            print(f"Error processing {txt_file}: {e}")
            continue
    
    # Write CSV file
    with open(output_csv, 'w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerows(csv_rows)
    
    print(f"\nProcessing complete!")
    print(f"Processed {processed} files")
    print(f"Classification results written to: {output_csv}")


def run_tests():
    """Run tests for font size simplification."""
    
    print("Running tests...")
    print("="*60)
    
    tests = [
        # Test 1: Remove intermediate font size without tsheg/shad
        ("<fs:24>༄༅།       །ཁ་<fs:22>ཊྭཱ<fs:24>ཾ་ག་",
         "<fs:24>༄༅།       །ཁ་ཊྭཱཾ་ག་",
         "Remove intermediate font size without tsheg/shad"),
        
        # Test 2: Remove initial font size without tsheg/shad (keep spaces)
        ("<fs:24>      <fs:26>༄༅། །བཀའ་བརྒྱུད་རིན་པོའི་ཆེའི་མགུར་མཚོ་ཡེ་ཤེས་བྱིན་འབེབ་ཅེས་བྱ་བ་བཞུགས་སོ། །",
         "      <fs:26>༄༅། །བཀའ་བརྒྱུད་རིན་པོའི་ཆེའི་མགུར་མཚོ་ཡེ་ཤེས་བྱིན་འབེབ་ཅེས་བྱ་བ་བཞུགས་སོ། །",
         "Remove initial font size without tsheg/shad"),
        
        # Test 3: Merge opening parenthesis with following font size
        ("<fs:22>༨  <fs:21>༼<fs:22>དབང་",
         "<fs:22>༨  ༼དབང་",
         "Merge opening parenthesis with following font size"),
        
        # Test 4: Complex parenthesis case with spaces
        ("<fs:22>༼<fs:25>ཀ<fs:22>༽<fs:20> <fs:25> <fs:26>གདམས་",
         "<fs:25>༼ཀ༽  <fs:26>གདམས་",
         "Complex parenthesis case with spaces"),
        
        # Test 5: Page numbers without tsheg/shad get merged
        ("<fs:22>༧   གྲུབ་རྒྱལ་ཚེ་སྒྲུབ་ཀྱི་བརྒྱུད་འདེབས།་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་<fs:13>169<fs:22>༨",
         "<fs:22>༧   གྲུབ་རྒྱལ་ཚེ་སྒྲུབ་ཀྱི་བརྒྱུད་འདེབས།་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་169༨",
         "Page numbers without tsheg/shad get merged"),
        
        # Test 6: Multiple consecutive changes without separators
        ("<fs:20>ཀ<fs:22>ཁ<fs:24>ག<fs:26>ང་",
         "<fs:20>ཀཁག<fs:26>ང་",
         "Multiple consecutive changes without separators - merge backward"),
        
        # Test 7: Keep changes with separators
        ("<fs:20>ཀ་<fs:22>ཁ་<fs:24>ག་",
         "<fs:20>ཀ་<fs:22>ཁ་<fs:24>ག་",
         "Keep changes with separators"),
        
        # Test 8: Remove trailing font size tag without separator
        ("<fs:22>༦ གསང་ཆེན་རྒྱུད་སྡེ་བཅུ་གསུམ་གྱི་དཀྱིལ་འཁོར་དུ་དབང་བསྐུར་བའི་ཆོ་གའི་མཚམས་སྦྱོར་བཻཌཱུཪྱའི་བུམ་བཟང་།་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་<fs:13>521ZZZZ",
         "<fs:22>༦ གསང་ཆེན་རྒྱུད་སྡེ་བཅུ་གསུམ་གྱི་དཀྱིལ་འཁོར་དུ་དབང་བསྐུར་བའི་ཆོ་གའི་མཚམས་སྦྱོར་བཻཌཱུཪྱའི་བུམ་བཟང་།་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་་521ZZZZ",
         "Remove trailing font size tag without separator"),
        
        # Test 9: Merge font size inside parentheses
        ("་ཚིག་དེས་ <fs:22>༼ཚེ་དང་ལྡན་པ་འདི་རྣམས་ཀྱི་ནད་གདོན་སྡིག་སྒྲིབ་འགལ་རྐྱེན་བར་གཅོད་མི་མཐུན་པའི་ཕྱོགས་ཐམས་ཅད་འདིར་མཆིས་པར་གྱུར་ཅིག<fs:16>༽ <fs:24>འཇིག་རྟེ",
         "་ཚིག་དེས་ <fs:22>༼ཚེ་དང་ལྡན་པ་འདི་རྣམས་ཀྱི་ནད་གདོན་སྡིག་སྒྲིབ་འགལ་རྐྱེན་བར་གཅོད་མི་མཐུན་པའི་ཕྱོགས་ཐམས་ཅད་འདིར་མཆིས་པར་གྱུར་ཅིག༽ <fs:24>འཇིག་རྟེ",
         "Merge font size inside parentheses with closing parenthesis"),
    ]
    
    passed = 0
    failed = 0
    
    for i, (test_input, expected, description) in enumerate(tests, 1):
        result = simplify_font_sizes(test_input)
        is_pass = result == expected
        
        if is_pass:
            passed += 1
        else:
            failed += 1
        
        print(f"Test {i}: {'PASS' if is_pass else 'FAIL'} - {description}")
        if not is_pass or len(test_input) > 100:
            # Show details for failed tests or long inputs
            print(f"  Input:    {test_input[:80]}{'...' if len(test_input) > 80 else ''}")
            print(f"  Expected: {expected[:80]}{'...' if len(expected) > 80 else ''}")
            print(f"  Got:      {result[:80]}{'...' if len(result) > 80 else ''}")
        print()
    
    print("="*60)
    print(f"Results: {passed} passed, {failed} failed")
    print("="*60)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        run_tests()
    elif len(sys.argv) > 1 and sys.argv[1] == "--classify":
        # Run classification on all files
        input_dir = sys.argv[2] if len(sys.argv) > 2 else 'DKCC/step0'
        output_csv = sys.argv[3] if len(sys.argv) > 3 else 'DKCC/font_size_classification.csv'
        process_files_and_classify(input_dir, output_csv)
    else:
        print("Usage:")
        print("  python3 step1_fs.py --test                    # Run tests")
        print("  python3 step1_fs.py --classify [input_dir] [output_csv]  # Classify font sizes")
        print("\nExample:")
        print("  python3 step1_fs.py --classify DKCC/step0 DKCC/font_size_classification.csv")
