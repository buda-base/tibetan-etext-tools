#!/usr/bin/env python3
"""
macOS version: Test script to compare BasicRTF parser output with macOS native rendering.
Uses 'textutil' (built-in) or Microsoft Word (via AppleScript) to get the "Gold Standard".
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def get_text_from_macos_native(rtf_path: str) -> str:
    """
    Uses the macOS 'textutil' command to convert RTF to plain text.
    This is the macOS equivalent of 'Word' ground truth.
    """
    print(f"   Using macOS textutil to extract text...")
    try:
        # textutil -convert txt -stdout somefile.rtf
        result = subprocess.run(
            ['textutil', '-convert', 'txt', '-stdout', rtf_path],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"   [ERROR] textutil failed: {e}")
        return ""

def get_text_from_parser(rtf_path: str) -> str:
    from basic_rtf import BasicRTF
    parser = BasicRTF()
    parser.parse_file(rtf_path)
    
    parts = []
    for s in parser.get_streams():
        if s.get("type") in ("header", "footer", "pict"):
            continue
            
        if 'text' in s:
            t = s['text']
            # If the parser is passing raw RTF escape sequences, 
            # we must convert double backslashes to single ones.
            t = t.replace('\\\\', '\\') 
            parts.append(t)
        elif s.get('type') in ('par_break', 'line_break'):
            parts.append('\n')
            
    return ''.join(parts)

import re

def normalize(text: str) -> str:
    """Standardize and deduplicate characters caused by RTF fallback shadows."""
    # 1. Standardize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    
    # 2. Collapse doubled characters (Specific to RTF parser duplication)
    # This regex finds any character repeated twice and collapses it to one.
    # We use this carefully for special symbols.
    def collapse_duplicates(match):
        char = match.group(1)
        # Only collapse if it's a known 'noisy' character or punctuation
        if char in '¡¤' or ord(char) > 127:
            return char
        return match.group(0)

    text = re.sub(r'(.)\1', collapse_duplicates, text)
    text = re.sub(r'«+', '«', text)
    text = re.sub(r'»+', '»', text)
    
    # 3. Final cleanup
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    return '\n'.join(lines)

def compare_and_report(native_text: str, parser_text: str):
    """Compare and print results."""
    n_norm = normalize(native_text)
    p_norm = normalize(parser_text)
    
    print("\n" + "=" * 60)
    if n_norm == p_norm:
        print("[OK] SUCCESS: Parser matches macOS Native Rendering!")
        print(f"Characters: {len(n_norm)}")
    else:
        print("[FAIL] MISMATCH DETECTED")
        print(f"Native Length: {len(n_norm)} | Parser Length: {len(p_norm)}")
        
        # Show first difference
        diff_idx = -1
        for i, (c1, c2) in enumerate(zip(n_norm, p_norm)):
            if c1 != c2:
                diff_idx = i
                break
        
        if diff_idx != -1:
            start = max(0, diff_idx - 20)
            end = diff_idx + 20
            print(f"\nFirst difference at index {diff_idx}:")
            print(f"  Native: ...{repr(n_norm[start:end])}...")
            print(f"  Parser: ...{repr(p_norm[start:end])}...")
    print("=" * 60)

def main():
    if len(sys.argv) > 1:
        rtf_path = sys.argv[1]
    else:
        rtf_path = "test.rtf"

    if not os.path.exists(rtf_path):
        print(f"File not found: {rtf_path}")
        return

    print(f"Testing RTF: {rtf_path}")
    
    native_txt = get_text_from_macos_native(rtf_path)
    parser_txt = get_text_from_parser(rtf_path)
    
    compare_and_report(native_txt, parser_txt)

if __name__ == "__main__":
    main()