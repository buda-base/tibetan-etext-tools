import fitz
import xml.etree.ElementTree as ET
from xml.dom import minidom
import os


def _is_xml_10_char(code: int) -> bool:
    """Whether codepoint is allowed in XML 1.0 character data (W3C Char production)."""
    if code in (0x9, 0xA, 0xD):
        return True
    if 0x20 <= code <= 0xD7FF:
        return True
    if 0xE000 <= code <= 0xFFFD:
        return True
    if 0x10000 <= code <= 0x10FFFF:
        return True
    return False


def xml_safe_text(s: str) -> str:
    """Replace disallowed XML 1.0 characters so minidom.parseString succeeds."""
    if not s:
        return s
    out = []
    for ch in s:
        o = ord(ch)
        if _is_xml_10_char(o):
            out.append(ch)
        else:
            out.append(f"\\u{o:04X}")
    return "".join(out)


def extract_cids_to_structured_xml(pdf_path, output_xml_path):
    print(f"Opening {pdf_path}...")
    doc = fitz.open(pdf_path)
    
    # Create the root XML element
    root = ET.Element("pdf_document", filename=os.path.basename(pdf_path))
    
    for page_num, page in enumerate(doc):
        # Create a <page> element
        page_elem = ET.SubElement(root, "page", number=str(page_num + 1))
        
        # rawdict gives us the deepest level of physical PDF data
        page_dict = page.get_text("rawdict")
        
        for block_num, block in enumerate(page_dict.get("blocks", [])):
            # Type 0 is text. Ignore images (Type 1)
            if block.get("type", 1) != 0: 
                continue 
            
            # Create a <block> element (usually represents a paragraph)
            block_elem = ET.SubElement(page_elem, "block", id=str(block_num))
            
            for line_num, line in enumerate(block.get("lines", [])):
                # Create a <line> element
                line_elem = ET.SubElement(block_elem, "line", id=str(line_num))
                
                for span_num, span in enumerate(line.get("spans", [])):
                    font_name = xml_safe_text(str(span.get("font", "unknown")))
                    font_size = str(round(span.get("size", 0), 1))
                    
                    # Create a <span> element to capture font changes
                    span_elem = ET.SubElement(line_elem, "span", font=font_name, size=font_size)
                    
                    for char in span.get("chars", []):
                        c = char.get("c", "")
                        if not c.strip(): # Skip empty spaces to keep XML clean
                            if c == " ":
                                ET.SubElement(span_elem, "space")
                            continue
                            
                        cid = str(ord(c))
                        
                        # Create the deepest <char> element holding the text and CID
                        char_elem = ET.SubElement(span_elem, "char", cid=cid)
                        char_elem.text = xml_safe_text(c)

    # Convert the ElementTree to a pretty-formatted XML string
    print("Formatting XML structure...")
    xml_str = ET.tostring(root, encoding='utf-8')
    parsed_xml = minidom.parseString(xml_str)
    pretty_xml = parsed_xml.toprettyxml(indent="  ")
    
    # Save to file
    with open(output_xml_path, "w", encoding="utf-8") as f:
        f.write(pretty_xml)
        
    print(f"Success! Structured XML saved to {output_xml_path}")

# --- Run the Script ---
if __name__ == "__main__":
    # Point this to your target PDF
    INPUT_PDF = "/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5/1-11/IE1KG15934/sources/VE1ER998/TI924-01-001.pdf" 
    OUTPUT_XML = "TI924-01-001_structural_cids.xml"
    
    extract_cids_to_structured_xml(INPUT_PDF, OUTPUT_XML)