#!/usr/bin/env python3
"""Test script for convert_ndl.py"""

import os
import sys
import shutil
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from convert_ndl import (
    parse_txt_file, 
    parse_divisions, 
    calculate_sha256,
    process_ie_folder
)


def test_parse_txt_file():
    """Test parsing of txt file."""
    print("Testing parse_txt_file...")
    test_file = Path(__file__).parent / 'test_data' / 'IE001' / 'toprocess' / 'IE001-VE001' / 'GSP001.txt'
    
    metadata, text_content = parse_txt_file(test_file)
    
    assert 'Title' in metadata, "Title not found in metadata"
    assert 'Author' in metadata, "Author not found in metadata"
    assert 'སེང་ཆེན་ནོར་བུ' in metadata['Title'], "Title content incorrect"
    assert '#div1' in text_content, "Text content should contain div markers"
    
    print("✓ parse_txt_file test passed")


def test_parse_divisions():
    """Test parsing of divisions."""
    print("Testing parse_divisions...")
    
    text_content = """#div1 མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།
༄༅། མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།
སྒྲུང་བ་རིག་འཛིན་བཟང་པོའམ་ཁྱི་ཤུལ་རིག་བཟང་ནི།
#div1 འཁྲུང་གླིང་།
#div2 ཀླུ་མོ་ཡ་དཀར་མཛེས་ལྡན།
༄༅། སེང་ཆེན་ནོར་བུ།"""
    
    divisions = parse_divisions(text_content)
    
    assert len(divisions) == 3, f"Expected 3 divisions, got {len(divisions)}"
    assert divisions[0]['level'] == 1, "First division should be level 1"
    assert divisions[1]['level'] == 1, "Second division should be level 1"
    assert divisions[2]['level'] == 2, "Third division should be level 2"
    assert 'མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།' in divisions[0]['title'], "Title incorrect"
    
    print("✓ parse_divisions test passed")


def test_calculate_sha256():
    """Test SHA256 calculation."""
    print("Testing calculate_sha256...")
    test_file = Path(__file__).parent / 'test_data' / 'IE001' / 'toprocess' / 'IE001-VE001' / 'GSP001.txt'
    
    sha256_hash = calculate_sha256(test_file)
    
    assert len(sha256_hash) == 64, "SHA256 hash should be 64 characters"
    assert all(c in '0123456789abcdef' for c in sha256_hash), "SHA256 should be hex"
    
    print("✓ calculate_sha256 test passed")


def test_full_conversion():
    """Test full conversion process."""
    print("\nTesting full conversion...")
    
    test_dir = Path(__file__).parent / 'test_data'
    output_dir = Path(__file__).parent / 'test_output'
    
    # Clean up previous test output
    if output_dir.exists():
        shutil.rmtree(output_dir)
    
    # Run conversion
    process_ie_folder(test_dir, output_dir, 'IE001')
    
    # Check outputs
    ie_output = output_dir / 'IE001'
    assert ie_output.exists(), "IE output directory not created"
    
    # Check sources
    sources_txt = ie_output / 'sources' / 'VE001' / 'GSP001.txt'
    assert sources_txt.exists(), f"Source txt file not copied: {sources_txt}"
    
    # Check archive XML
    archive_xml = ie_output / 'archive' / 'VE001' / 'UT001_0001.xml'
    assert archive_xml.exists(), f"Archive XML not created: {archive_xml}"
    
    # Check CSV
    csv_file = ie_output / 'IE001.csv'
    assert csv_file.exists(), f"CSV file not created: {csv_file}"
    
    # Verify XML content
    with open(archive_xml, 'r', encoding='utf-8') as f:
        xml_content = f.read()
        assert 'TEI xmlns="http://www.tei-c.org/ns/1.0"' in xml_content, "TEI namespace not found"
        assert 'སེང་ཆེན་ནོར་བུ' in xml_content, "Title not in XML"
        assert 'div1_0001' in xml_content, "Division ID not in XML"
        assert 'milestone' in xml_content, "Milestone not in XML"
    
    # Verify CSV content
    with open(csv_file, 'r', encoding='utf-8') as f:
        csv_content = f.read()
        assert 'མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།' in csv_content, "Text title not in CSV"
        assert 'འཁྲུང་གླིང་།' in csv_content, "Chapter title not in CSV"
        assert '1#div1_0001' in csv_content, "Division reference not in CSV"
        assert ',T,' in csv_content, "Text type marker not in CSV"
        assert ',C,' in csv_content, "Chapter type marker not in CSV"
    
    print("✓ Full conversion test passed")
    print(f"\nTest output created in: {output_dir}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Running NDL Converter Tests")
    print("=" * 60)
    
    try:
        test_parse_txt_file()
        test_parse_divisions()
        test_calculate_sha256()
        test_full_conversion()
        
        print("\n" + "=" * 60)
        print("All tests passed! ✓")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
