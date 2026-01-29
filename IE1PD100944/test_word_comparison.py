"""
Test script to compare BasicRTF parser output with Microsoft Word's rendering.

This script:
1. Opens an RTF file in Word
2. Selects all text and copies it (Dedris encoding)
3. Compares it with the parser output

Usage:
    python test_word_comparison.py [rtf_file]
    
If no rtf_file is specified, uses test.rtf in the same directory.
"""

import os
import sys
import time

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def get_text_from_word(rtf_path: str) -> str:
    """Open RTF in Word and extract text directly (no clipboard needed)."""
    import win32com.client
    
    word = None
    doc = None
    try:
        print(f"   Opening Word application...")
        # Start Word (hidden)
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        
        print(f"   Opening document: {rtf_path}")
        # Open the RTF file
        doc = word.Documents.Open(os.path.abspath(rtf_path))
        
        # Wait for document to fully load (important for large files)
        file_size_mb = os.path.getsize(rtf_path) / (1024 * 1024)
        wait_time = max(2, int(file_size_mb / 2))  # At least 2 seconds, more for larger files
        print(f"   Waiting {wait_time}s for document to load ({file_size_mb:.1f} MB)...")
        time.sleep(wait_time)
        
        print(f"   Extracting text from document...")
        # Get text directly from document content (much faster than clipboard)
        # This gets the raw text as Word sees it
        text = doc.Content.Text
        
        return text
        
    finally:
        if doc:
            try:
                doc.Close(SaveChanges=False)
            except:
                pass
        if word:
            try:
                word.Quit()
            except:
                pass


def get_text_from_parser(rtf_path: str) -> str:
    """Parse RTF with BasicRTF and concatenate all streams."""
    from basic_rtf import BasicRTF
    
    parser = BasicRTF()
    parser.parse_file(rtf_path, show_progress=False)
    
    parts = []
    for s in parser.get_streams():
        if 'text' in s:
            parts.append(s['text'])
        elif s.get('type') == 'par_break':
            parts.append('\n')
        elif s.get('type') == 'cell_break':
            # Word shows cell boundaries as \x07 (BEL character) with newline
            parts.append('\n\x07')
        elif s.get('type') == 'row_break':
            # Row breaks - Word doesn't add extra newline for these
            pass
    
    return ''.join(parts)


def normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison (handle Windows line endings, etc)."""
    # Replace Windows line endings
    text = text.replace('\r\n', '\n')
    text = text.replace('\r', '\n')
    # Strip trailing whitespace from each line
    lines = [line.rstrip() for line in text.split('\n')]
    # Remove empty lines at start/end
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)

def normalize_text_only(text: str) -> str:
    """Extract only the text content, ignoring cell markers and extra whitespace."""
    # Remove cell markers (ASCII 7 / BEL character)
    text = text.replace('\x07', '')
    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    # Collapse multiple newlines into single newline
    while '\n\n' in text:
        text = text.replace('\n\n', '\n')
    # Strip leading/trailing whitespace
    return text.strip()


def find_differences(text1: str, text2: str, max_diffs: int = 5):
    """Find and return details about differences between two texts."""
    differences = []
    
    # Split into lines for line-by-line comparison
    lines1 = text1.split('\n')
    lines2 = text2.split('\n')
    
    max_lines = max(len(lines1), len(lines2))
    
    for i in range(max_lines):
        line1 = lines1[i] if i < len(lines1) else '<missing>'
        line2 = lines2[i] if i < len(lines2) else '<missing>'
        
        if line1 != line2:
            differences.append({
                'line': i + 1,
                'word': line1,
                'parser': line2
            })
            
            if len(differences) >= max_diffs:
                break
    
    return differences


def compare_texts(word_text: str, parser_text: str) -> bool:
    """Compare two texts and show differences."""
    word_norm = normalize_for_comparison(word_text)
    parser_norm = normalize_for_comparison(parser_text)
    
    # Also compare text-only (ignoring cell markers)
    word_text_only = normalize_text_only(word_text)
    parser_text_only = normalize_text_only(parser_text)
    text_only_match = word_text_only == parser_text_only
    
    if word_norm == parser_norm:
        print("\n" + "=" * 60)
        print("[OK] SUCCESS: Parser output matches Word output exactly!")
        print("=" * 60)
        return True
    
    print("\n" + "=" * 60)
    print("[FAIL] MISMATCH DETECTED (with cell markers)")
    print("=" * 60)
    
    # Find first character difference
    min_len = min(len(word_norm), len(parser_norm))
    first_diff = -1
    for i in range(min_len):
        if word_norm[i] != parser_norm[i]:
            first_diff = i
            break
    if first_diff == -1:
        first_diff = min_len
    
    # Show context around first difference
    context_start = max(0, first_diff - 40)
    context_end = min(max(len(word_norm), len(parser_norm)), first_diff + 40)
    
    print(f"\nFirst difference at character position {first_diff}:")
    print(f"  Word:   ...{repr(word_norm[context_start:min(context_end, len(word_norm))])}...")
    print(f"  Parser: ...{repr(parser_norm[context_start:min(context_end, len(parser_norm))])}...")
    
    # Length comparison
    print(f"\nLength comparison:")
    print(f"  Word output:   {len(word_norm)} characters")
    print(f"  Parser output: {len(parser_norm)} characters")
    print(f"  Difference:    {abs(len(word_norm) - len(parser_norm))} characters")
    
    # Line-by-line differences
    diffs = find_differences(word_norm, parser_norm, max_diffs=3)
    if diffs:
        print(f"\nFirst {len(diffs)} line differences:")
        for d in diffs:
            print(f"\n  Line {d['line']}:")
            print(f"    Word:   {repr(d['word'][:80])}{'...' if len(d['word']) > 80 else ''}")
            print(f"    Parser: {repr(d['parser'][:80])}{'...' if len(d['parser']) > 80 else ''}")
    
    # Text-only comparison (ignore cell markers for table handling)
    print("\n" + "-" * 60)
    print("TEXT-ONLY COMPARISON (ignoring cell markers):")
    print("-" * 60)
    if text_only_match:
        print("[OK] Text content matches! (Differences are only cell markers)")
        print(f"  Text-only length: {len(word_text_only)} characters")
        return True  # Consider this a success for Dedris conversion
    else:
        print("[FAIL] Text content differs even without cell markers")
        print(f"  Word text-only:   {len(word_text_only)} characters")
        print(f"  Parser text-only: {len(parser_text_only)} characters")
        print(f"  Difference:       {abs(len(word_text_only) - len(parser_text_only))} characters")
        # Find first difference in text-only
        min_len_to = min(len(word_text_only), len(parser_text_only))
        for i in range(min_len_to):
            if word_text_only[i] != parser_text_only[i]:
                ctx_start = max(0, i - 30)
                ctx_end = min(min_len_to, i + 30)
                print(f"\n  First text-only difference at position {i}:")
                print(f"    Word:   ...{repr(word_text_only[ctx_start:ctx_end])}...")
                print(f"    Parser: ...{repr(parser_text_only[ctx_start:ctx_end])}...")
                break
    
    return False


def save_outputs(word_text: str, parser_text: str, base_path: str):
    """Save both outputs to files for manual inspection."""
    word_file = base_path.replace('.rtf', '-word-output.txt')
    parser_file = base_path.replace('.rtf', '-parser-output.txt')
    
    with open(word_file, 'w', encoding='utf-8') as f:
        f.write(word_text)
    print(f"   Saved Word output to: {word_file}")
    
    with open(parser_file, 'w', encoding='utf-8') as f:
        f.write(parser_text)
    print(f"   Saved Parser output to: {parser_file}")


def main():
    # Determine RTF file path
    if len(sys.argv) > 1:
        rtf_path = sys.argv[1]
    else:
        rtf_path = os.path.join(os.path.dirname(__file__), "test.rtf")
    
    if not os.path.exists(rtf_path):
        print(f"Error: RTF file not found: {rtf_path}")
        sys.exit(1)
    
    print("=" * 60)
    print("RTF Parser vs Microsoft Word Comparison Test")
    print("=" * 60)
    print(f"\nTesting: {rtf_path}")
    print(f"File size: {os.path.getsize(rtf_path):,} bytes")
    
    # Step 1: Get Word output
    print("\n[1/3] Getting text from Microsoft Word...")
    try:
        word_text = get_text_from_word(rtf_path)
        print(f"   [OK] Got {len(word_text):,} characters from Word")
    except Exception as e:
        print(f"   [ERROR] Error getting Word output: {e}")
        print("\n   Make sure Microsoft Word is installed and pywin32 is available.")
        print("   Install with: pip install pywin32")
        sys.exit(1)
    
    # Step 2: Get parser output
    print("\n[2/3] Getting text from BasicRTF parser...")
    try:
        parser_text = get_text_from_parser(rtf_path)
        print(f"   [OK] Got {len(parser_text):,} characters from parser")
    except Exception as e:
        print(f"   [ERROR] Error getting parser output: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Save outputs for inspection
    print("\n[3/3] Saving outputs for inspection...")
    save_outputs(word_text, parser_text, rtf_path)
    
    # Compare
    print("\nComparing outputs...")
    success = compare_texts(word_text, parser_text)
    
    # Also save to test-streams.txt for reference
    streams_path = os.path.join(os.path.dirname(rtf_path), "test-streams.txt")
    with open(streams_path, 'w', encoding='utf-8') as f:
        f.write(word_text)
    print(f"\nWord output also saved to: {streams_path}")
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

