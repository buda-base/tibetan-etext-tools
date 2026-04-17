#!/usr/bin/env python3
"""
Test script to verify footnote extraction from DOCX files.

This script tests the footnote parsing functionality by:
1. Parsing a DOCX file with footnotes
2. Extracting and displaying the footnotes
3. Showing where footnote markers appear in the text streams

Usage:
    python test_footnotes.py path/to/file.docx
"""

import sys
from pathlib import Path
from basic_docx import BasicDOCX, FOOTNOTE_MARKER

def test_footnote_extraction(docx_path: str):
    """Test footnote extraction from a DOCX file."""
    print(f"Testing footnote extraction from: {docx_path}")
    print("=" * 60)
    
    parser = BasicDOCX()
    parser.parse_file(docx_path, show_progress=True)
    
    streams = parser.get_streams()
    footnotes = parser.get_footnotes()
    
    print(f"\nTotal streams: {len(streams)}")
    print(f"Total footnotes: {len(footnotes)}")
    
    if footnotes:
        print("\n" + "=" * 60)
        print("FOOTNOTES FOUND:")
        print("=" * 60)
        for footnote_id, footnote_text in footnotes.items():
            print(f"\nFootnote ID: {footnote_id}")
            print(f"Text: {footnote_text}")
            print(f"Length: {len(footnote_text)} characters")
    
    # Find streams with footnote markers
    footnote_markers = [s for s in streams if s.get("is_footnote_marker", False)]
    
    if footnote_markers:
        print("\n" + "=" * 60)
        print("FOOTNOTE MARKERS IN TEXT:")
        print("=" * 60)
        for i, marker_stream in enumerate(footnote_markers, 1):
            footnote_id = marker_stream.get("footnote_id")
            print(f"\n{i}. Footnote ID: {footnote_id}")
            print(f"   Marker: {marker_stream.get('text')}")
            if footnote_id in footnotes:
                print(f"   Text: {footnotes[footnote_id][:100]}...")
    
    # Show context around footnote markers
    print("\n" + "=" * 60)
    print("TEXT CONTEXT AROUND FOOTNOTES:")
    print("=" * 60)
    
    for i, stream in enumerate(streams):
        if stream.get("is_footnote_marker", False):
            # Show 2 streams before and 2 after
            start = max(0, i - 2)
            end = min(len(streams), i + 3)
            
            print(f"\nContext around footnote {stream.get('footnote_id')}:")
            for j in range(start, end):
                s = streams[j]
                text = s.get("text", "")
                if j == i:
                    print(f"  >>> [FOOTNOTE {s.get('footnote_id')}]")
                else:
                    # Show first 50 chars
                    display_text = text.replace('\n', '\\n')[:50]
                    print(f"  {j}: {display_text}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_footnotes.py path/to/file.docx")
        sys.exit(1)
    
    docx_path = sys.argv[1]
    if not Path(docx_path).exists():
        print(f"Error: File not found: {docx_path}")
        sys.exit(1)
    
    test_footnote_extraction(docx_path)
