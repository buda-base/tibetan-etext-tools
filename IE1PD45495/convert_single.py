#!/usr/bin/env python3
"""
Convert a single RTF file to TEI XML.

Usage:
    python convert_single.py <input.rtf> <output.xml>
    
Example:
    python convert_single.py volume_028_263.rtf output.xml
"""

import sys
from pathlib import Path

# Add script directory to path
script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from convert import convert_rtf_to_tei

def main():
    if len(sys.argv) != 3:
        print("Usage: python convert_single.py <input.rtf> <output.xml>")
        print("\nExample:")
        print("  python convert_single.py volume_028_263.rtf output.xml")
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    
    if not input_file.exists():
        print(f"Error: Input file not found: {input_file}")
        sys.exit(1)
    
    print(f"Converting: {input_file}")
    print(f"Output to: {output_file}")
    
    # Use generic IDs for single file conversion
    ie_id = "IE_SINGLE"
    ve_id = "VE_SINGLE"
    ut_id = "UT_SINGLE"
    src_path = str(input_file.name)
    
    # Convert
    tei_xml = convert_rtf_to_tei(input_file, ie_id, ve_id, ut_id, src_path)
    
    # Write output
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(tei_xml, encoding='utf-8')
    
    print(f"✓ Conversion complete!")
    print(f"  Output: {output_file.absolute()}")

if __name__ == "__main__":
    main()
