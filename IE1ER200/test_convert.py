#!/usr/bin/env python3
"""Test script for convert_tengyur.py"""

import os
import sys
import shutil
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from convert_tengyur import (
    parse_derge_file,
    process_annotations,
    calculate_sha256,
    get_ve_ids_from_toprocess,
    get_ut_id,
    generate_tei_body,
    generate_tei_xml,
    convert_ie1er200,
    escape_xml
)


def test_escape_xml():
    """Test XML escaping."""
    print("Testing escape_xml...")
    
    assert escape_xml('&') == '&amp;', "Ampersand not escaped"
    assert escape_xml('<') == '&lt;', "Less than not escaped"
    assert escape_xml('>') == '&gt;', "Greater than not escaped"
    assert escape_xml('"') == '&quot;', "Quote not escaped"
    assert escape_xml("'") == '&apos;', "Apostrophe not escaped"
    assert escape_xml('བོད་ཡིག') == 'བོད་ཡིག', "Tibetan should not be escaped"
    
    print("✓ escape_xml test passed")


def test_get_ut_id():
    """Test UT ID generation from VE ID."""
    print("Testing get_ut_id...")
    
    assert get_ut_id('VE1ER251') == 'UT1ER251_0001', "UT ID generation incorrect"
    assert get_ut_id('VE1ER463') == 'UT1ER463_0001', "UT ID generation incorrect"
    # VE001 -> UT001_0001 (replaces VE with UT, keeps everything after VE)
    assert get_ut_id('VE001') == 'UT001_0001', "UT ID generation for short VE incorrect"
    
    print("✓ get_ut_id test passed")


def test_process_annotations():
    """Test annotation processing."""
    print("Testing process_annotations...")
    
    # Test Derge milestone {D###}
    result = process_annotations('{D3786}text')
    assert '<milestone xml:id="D3786" unit="section"/>' in result, "D3786 milestone not converted"
    
    # Test Derge milestone with sub-index {D1-1}
    result = process_annotations('{D3786-1}text')
    assert '<milestone xml:id="D3786-1" unit="section"/>' in result, "D3786-1 milestone not converted"
    
    # Test error annotation (X,Y)
    result = process_annotations('མཁའ་ལ་(མི་,མེ་)ཏོག')
    assert '<choice><orig>མི་</orig><corr>མེ་</corr></choice>' in result, "Error annotation not converted"
    
    # Test variant annotation {X,Y}
    result = process_annotations('{རི་དགས་,རི་དྭགས་}')
    assert '<choice><orig>རི་དགས་</orig><reg>རི་དྭགས་</reg></choice>' in result, "Variant annotation not converted"
    
    # Test [X] error candidate with Tibetan
    result = process_annotations('text[ལ་]more')
    assert '<unclear reason="illegible">ལ་</unclear>' in result, "Error candidate not converted"
    
    # Test that page markers [1a] are NOT converted (they don't contain Tibetan)
    result = process_annotations('[1a]')
    assert '<unclear' not in result, "Page marker should not be converted to unclear"
    
    print("✓ process_annotations test passed")


def test_parse_derge_file():
    """Test parsing of Derge source file."""
    print("Testing parse_derge_file...")
    
    # Create test file
    test_dir = Path(__file__).parent / 'test_data'
    test_dir.mkdir(parents=True, exist_ok=True)
    
    test_content = """[1a]
[1a.1]
[1b]
[1b.1]{D3786}༄༅༅། །རྒྱ་གར་སྐད་དུ།
[1b.2]བོད་སྐད་དུ། བཅོམ་ལྡན་འདས་མ་ཤེས་རབ་ཀྱི་ཕ་རོལ་ཏུ་ཕྱིན་པའི་སྙིང་པོ།
[2a]
[2a.1]{D3786-1}དཀོན་མཆོག་གསུམ་ལ་ཕྱག་འཚལ་ལོ།
"""
    
    test_file = test_dir / 'test_source.txt'
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_content)
    
    # Parse file
    parsed = parse_derge_file(str(test_file))
    
    # Check pages
    assert len(parsed['pages']) == 3, f"Expected 3 pages, got {len(parsed['pages'])}"
    assert parsed['pages'][0]['page_num'] == '1a', "First page should be 1a"
    assert parsed['pages'][1]['page_num'] == '1b', "Second page should be 1b"
    assert parsed['pages'][2]['page_num'] == '2a', "Third page should be 2a"
    
    # Check milestones
    assert len(parsed['milestones']) == 2, f"Expected 2 milestones, got {len(parsed['milestones'])}"
    assert parsed['milestones'][0]['id'] == 'D3786', "First milestone should be D3786"
    assert parsed['milestones'][1]['id'] == 'D3786-1', "Second milestone should be D3786-1"
    
    # Check line content
    assert len(parsed['pages'][1]['lines']) == 2, "Page 1b should have 2 lines"
    assert '{D3786}' in parsed['pages'][1]['lines'][0]['content'], "Line content should contain {D3786}"
    
    # Cleanup
    test_file.unlink()
    
    print("✓ parse_derge_file test passed")


def test_parse_duplicate_pages():
    """Test parsing of duplicate page markers like [93xa]."""
    print("Testing parse_derge_file with duplicate pages...")
    
    test_dir = Path(__file__).parent / 'test_data'
    test_dir.mkdir(parents=True, exist_ok=True)
    
    test_content = """[93a]
[93a.1]Content on page 93a
[93b]
[93b.1]Content on page 93b
[93xa]
[93xa.1]Content on duplicate page 93xa
[93xb]
[93xb.1]Content on duplicate page 93xb
"""
    
    test_file = test_dir / 'test_duplicate.txt'
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write(test_content)
    
    parsed = parse_derge_file(str(test_file))
    
    # Check pages
    page_nums = [p['page_num'] for p in parsed['pages']]
    assert '93xa' in page_nums, "Page 93xa not found"
    assert '93xb' in page_nums, "Page 93xb not found"
    
    # Cleanup
    test_file.unlink()
    
    print("✓ parse_derge_file duplicate pages test passed")


def test_calculate_sha256():
    """Test SHA256 calculation."""
    print("Testing calculate_sha256...")
    
    test_dir = Path(__file__).parent / 'test_data'
    test_dir.mkdir(parents=True, exist_ok=True)
    
    test_file = test_dir / 'test_sha.txt'
    with open(test_file, 'w', encoding='utf-8') as f:
        f.write('Test content')
    
    sha256_hash = calculate_sha256(str(test_file))
    
    assert len(sha256_hash) == 64, "SHA256 hash should be 64 characters"
    assert all(c in '0123456789abcdef' for c in sha256_hash), "SHA256 should be hex"
    
    # Cleanup
    test_file.unlink()
    
    print("✓ calculate_sha256 test passed")


def test_generate_tei_body():
    """Test TEI body generation."""
    print("Testing generate_tei_body...")
    
    parsed_data = {
        'pages': [
            {
                'page_num': '1a',
                'lines': []  # Empty page
            },
            {
                'page_num': '1b',
                'lines': [
                    {'line_num': '1', 'content': '{D3786}༄༅༅། །རྒྱ་གར་སྐད་དུ།'},
                    {'line_num': '2', 'content': 'བོད་སྐད་དུ། བཅོམ་ལྡན་འདས་མ་ཤེས་རབ་ཀྱི་ཕ་རོལ་ཏུ་ཕྱིན་པའི་སྙིང་པོ།'}
                ]
            }
        ],
        'milestones': []
    }
    
    body = generate_tei_body(parsed_data)
    
    # Check page breaks
    assert '<pb n="1a"/>' in body, "Page break 1a not found"
    assert '<pb n="1b"/>' in body, "Page break 1b not found"
    
    # Check line breaks
    assert '<lb/>' in body, "Line break not found"
    
    # Check milestone conversion
    assert '<milestone xml:id="D3786" unit="section"/>' in body, "Milestone not converted"
    
    # Check no empty lines
    lines = body.split('\n')
    for line in lines:
        if line.startswith('<lb/>'):
            assert line != '<lb/>', "Empty line break should not exist"
    
    print("✓ generate_tei_body test passed")


def test_full_conversion():
    """Test full conversion process."""
    print("\nTesting full conversion...")
    
    test_dir = Path(__file__).parent / 'test_data'
    test_input = test_dir / 'IE1ER200'
    test_output = Path(__file__).parent / 'test_output'
    
    # Clean up previous test
    if test_output.exists():
        shutil.rmtree(test_output)
    
    # Create test input structure (IE1ER200 has sources directly, not sources/text)
    sources = test_input / 'sources'
    toprocess = test_input / 'toprocess'
    sources.mkdir(parents=True, exist_ok=True)
    toprocess.mkdir(parents=True, exist_ok=True)
    
    # Create test source file
    test_content = """[1a]
[1a.1]
[1b]
[1b.1]{D3786}༄༅༅། །རྒྱ་གར་སྐད་དུ། བི་ན་ཡ་བསྟུ།
[1b.2]བོད་སྐད་དུ། བཅོམ་ལྡན་འདས་མ་ཤེས་རབ་ཀྱི་ཕ་རོལ་ཏུ་ཕྱིན་པའི་སྙིང་པོ།
[2a]
[2a.1]{D3786-1}དཀོན་མཆོག་གསུམ་ལ་ཕྱག་འཚལ་ལོ།
"""
    
    source_file = sources / '001_test_volume.txt'
    with open(source_file, 'w', encoding='utf-8') as f:
        f.write(test_content)
    
    # Create test toprocess folder (VE identifier)
    ve_folder = toprocess / 'IE1ER200-VE1ER251'
    ve_folder.mkdir(parents=True, exist_ok=True)
    
    # Run conversion
    convert_ie1er200(str(test_input), str(test_output))
    
    # Check outputs
    assert test_output.exists(), "Output directory not created"
    
    # Check sources
    sources_txt = test_output / 'sources' / 'VE1ER251' / '001_test_volume.txt'
    assert sources_txt.exists(), f"Source txt file not copied: {sources_txt}"
    
    # Check archive XML
    archive_xml = test_output / 'archive' / 'VE1ER251' / 'UT1ER251_0001.xml'
    assert archive_xml.exists(), f"Archive XML not created: {archive_xml}"
    
    # Check CSV
    csv_file = test_output / 'IE1ER200.csv'
    assert csv_file.exists(), f"CSV file not created: {csv_file}"
    
    # Verify XML content
    with open(archive_xml, 'r', encoding='utf-8') as f:
        xml_content = f.read()
        assert 'TEI xmlns="http://www.tei-c.org/ns/1.0"' in xml_content, "TEI namespace not found"
        assert '<pb n="1a"/>' in xml_content, "Page break not in XML"
        assert '<pb n="1b"/>' in xml_content, "Page break not in XML"
        assert '<lb/>' in xml_content, "Line break not in XML"
        assert '<milestone xml:id="D3786" unit="section"/>' in xml_content, "Milestone not in XML"
        assert 'xml:space="preserve"' in xml_content, "xml:space preserve not in XML"
        assert 'src_sha256' in xml_content, "SHA256 not in XML"
        assert 'VE1ER251' in xml_content, "VE ID not in XML"
        assert 'UT1ER251_0001' in xml_content, "UT ID not in XML"
        assert 'IE1ER200' in xml_content, "IE ID not in XML"
    
    # Verify CSV content
    with open(csv_file, 'r', encoding='utf-8') as f:
        csv_content = f.read()
        assert 'D3786' in csv_content, "D3786 milestone not in CSV"
        assert 'D3786-1' in csv_content, "D3786-1 milestone not in CSV"
        assert ',V,' in csv_content, "Volume marker not in CSV"
        assert ',T,' in csv_content, "Text marker not in CSV"
    
    print("✓ Full conversion test passed")
    print(f"\nTest output created in: {test_output}")


def test_get_ve_ids_from_toprocess():
    """Test VE ID extraction from toprocess folder."""
    print("Testing get_ve_ids_from_toprocess...")
    
    test_dir = Path(__file__).parent / 'test_data' / 'toprocess_test'
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Create test VE folders
    (test_dir / 'IE1ER200-VE1ER251').mkdir(exist_ok=True)
    (test_dir / 'IE1ER200-VE1ER252').mkdir(exist_ok=True)
    (test_dir / 'IE1ER200-VE1ER253').mkdir(exist_ok=True)
    
    volumes = get_ve_ids_from_toprocess(test_dir)
    
    assert len(volumes) == 3, f"Expected 3 volumes, got {len(volumes)}"
    assert volumes[0]['ve_id'] == 'VE1ER251', "First VE ID incorrect"
    assert volumes[1]['ve_id'] == 'VE1ER252', "Second VE ID incorrect"
    assert volumes[2]['ve_id'] == 'VE1ER253', "Third VE ID incorrect"
    assert volumes[0]['volume_number'] == 1, "First volume number incorrect"
    assert volumes[2]['volume_number'] == 3, "Third volume number incorrect"
    
    # Cleanup
    shutil.rmtree(test_dir)
    
    print("✓ get_ve_ids_from_toprocess test passed")


def cleanup_test_data():
    """Clean up test data directories."""
    test_dir = Path(__file__).parent / 'test_data'
    if test_dir.exists():
        shutil.rmtree(test_dir)
    
    test_output = Path(__file__).parent / 'test_output'
    if test_output.exists():
        shutil.rmtree(test_output)


def main():
    """Run all tests."""
    print("=" * 60)
    print("Running Derge Tengyur Converter Tests (IE1ER200)")
    print("=" * 60)
    
    try:
        test_escape_xml()
        test_get_ut_id()
        test_process_annotations()
        test_parse_derge_file()
        test_parse_duplicate_pages()
        test_calculate_sha256()
        test_generate_tei_body()
        test_get_ve_ids_from_toprocess()
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
    finally:
        # Ask before cleanup
        print("\nNote: Test data directories created:")
        print(f"  - {Path(__file__).parent / 'test_data'}")
        print(f"  - {Path(__file__).parent / 'test_output'}")
        print("Run with --cleanup to remove them.")
        
        if '--cleanup' in sys.argv:
            cleanup_test_data()
            print("Test data cleaned up.")


if __name__ == '__main__':
    main()


