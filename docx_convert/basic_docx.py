"""
BasicDOCX Parser Module

Parser for DOCX files that extracts text runs with font information.
DOCX files are ZIP archives containing XML. The main content is in:
- word/document.xml - Main document content with text runs
- word/styles.xml - Style definitions
- word/fontTable.xml - Font table

Output format matches BasicRTF for compatibility:
{
    "text": "raw text content",
    "font": {
        "id": font_id,
        "name": "font-name",
        "size": 12
    }
}
"""

import zipfile
import xml.etree.ElementTree as ET
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# OpenXML namespaces
NSMAP = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'wp': 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing',
}


def _get_tag(ns_prefix: str, local_name: str) -> str:
    """Build a fully qualified XML tag name."""
    return f"{{{NSMAP[ns_prefix]}}}{local_name}"


class BasicDOCX:
    """
    Parser for DOCX files that extracts text runs with font information.
    
    DOCX files are ZIP archives containing XML. The main content is in:
    - word/document.xml - Main document content with text runs
    - word/styles.xml - Style definitions
    - word/fontTable.xml - Font table
    
    Output format matches BasicRTF for compatibility:
    {
        "text": "raw text content",
        "font": {
            "id": font_id,
            "name": "font-name",
            "size": 12
        }
    }
    """
    
    def __init__(self):
        self._streams = []
        self._fonts = []
        self._font_map = {}
        self._styles = {}
        self._default_font = "Times New Roman"
        self._default_size = 12
        self._show_progress = False
    
    def parse_file(self, file_path: str, show_progress: bool = True):
        """
        Parse a DOCX file and extract text streams with font information.
        
        Args:
            file_path: Path to the DOCX file
            show_progress: Whether to show progress messages
        """
        self._streams = []
        self._fonts = []
        self._font_map = {}
        self._styles = {}
        self._show_progress = show_progress
        
        if show_progress:
            logger.info(f"  Parsing DOCX: {Path(file_path).name}")
        
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                # Parse font table
                if 'word/fontTable.xml' in zf.namelist():
                    self._parse_font_table(zf.read('word/fontTable.xml'))
                
                # Parse styles
                if 'word/styles.xml' in zf.namelist():
                    self._parse_styles(zf.read('word/styles.xml'))
                
                # Parse headers and footers first (before main document)
                for name in zf.namelist():
                    if name.startswith('word/header') and name.endswith('.xml'):
                        self._parse_header_footer(zf.read(name), 'header')
                    elif name.startswith('word/footer') and name.endswith('.xml'):
                        self._parse_header_footer(zf.read(name), 'footer')
                
                # Parse main document
                if 'word/document.xml' in zf.namelist():
                    self._parse_document(zf.read('word/document.xml'))
                else:
                    logger.error(f"No word/document.xml found in {file_path}")
        except zipfile.BadZipFile:
            logger.error(f"Invalid DOCX file (not a valid ZIP): {file_path}")
        except Exception as e:
            logger.error(f"Error parsing DOCX file {file_path}: {e}")
            import traceback
            traceback.print_exc()
        
        if show_progress:
            logger.info(f"  Parsed {len(self._streams)} text streams")
    
    def _parse_font_table(self, xml_data: bytes):
        """Parse word/fontTable.xml to extract font definitions."""
        try:
            root = ET.fromstring(xml_data)
            font_id = 0
            
            # Find all font elements
            for font_elem in root.iter(_get_tag('w', 'font')):
                font_name = font_elem.get(_get_tag('w', 'name'))
                if not font_name:
                    # Try without namespace (some DOCX files)
                    font_name = font_elem.get('name')
                
                if font_name:
                    self._fonts.append({"id": font_id, "name": font_name})
                    self._font_map[font_id] = {"id": font_id, "name": font_name}
                    self._font_map[font_name] = {"id": font_id, "name": font_name}
                    font_id += 1
                    
        except ET.ParseError as e:
            logger.warning(f"Error parsing fontTable.xml: {e}")
    
    def _parse_styles(self, xml_data: bytes):
        """Parse word/styles.xml to extract style definitions with font info."""
        try:
            root = ET.fromstring(xml_data)
            
            # Parse document defaults
            doc_defaults = root.find(_get_tag('w', 'docDefaults'))
            if doc_defaults is not None:
                rpr_default = doc_defaults.find('.//' + _get_tag('w', 'rPrDefault') + '/' + _get_tag('w', 'rPr'))
                if rpr_default is not None:
                    font_name, font_size = self._extract_font_from_rpr(rpr_default)
                    if font_name:
                        self._default_font = font_name
                    if font_size:
                        self._default_size = font_size
            
            # Parse styles
            for style_elem in root.iter(_get_tag('w', 'style')):
                style_id = style_elem.get(_get_tag('w', 'styleId'))
                if not style_id:
                    style_id = style_elem.get('styleId')
                
                if style_id:
                    rpr = style_elem.find(_get_tag('w', 'rPr'))
                    if rpr is not None:
                        font_name, font_size = self._extract_font_from_rpr(rpr)
                        self._styles[style_id] = {
                            "font_name": font_name,
                            "font_size": font_size
                        }
                        
        except ET.ParseError as e:
            logger.warning(f"Error parsing styles.xml: {e}")
    
    def _extract_font_from_rpr(self, rpr_elem) -> tuple:
        """
        Extract font name and size from a run properties (rPr) element.
        
        Args:
            rpr_elem: XML element for <w:rPr>
            
        Returns:
            Tuple of (font_name, font_size) - either may be None
        """
        font_name = None
        font_size = None
        
        # Font name from <w:rFonts>
        rfonts = rpr_elem.find(_get_tag('w', 'rFonts'))
        if rfonts is not None:
            # Priority: cs (complex script) > ascii > hAnsi
            font_name = (
                rfonts.get(_get_tag('w', 'cs')) or
                rfonts.get(_get_tag('w', 'ascii')) or
                rfonts.get(_get_tag('w', 'hAnsi')) or
                rfonts.get('cs') or
                rfonts.get('ascii') or
                rfonts.get('hAnsi')
            )
        
        # Font size from <w:sz> or <w:szCs> (in half-points)
        sz = rpr_elem.find(_get_tag('w', 'szCs'))  # Complex script size first
        if sz is None:
            sz = rpr_elem.find(_get_tag('w', 'sz'))
        
        if sz is not None:
            val = sz.get(_get_tag('w', 'val')) or sz.get('val')
            if val:
                try:
                    font_size = int(val) // 2  # Convert half-points to points
                except ValueError:
                    pass
        
        return font_name, font_size
    
    def _parse_document(self, xml_data: bytes):
        """Parse word/document.xml to extract text runs with font information."""
        try:
            root = ET.fromstring(xml_data)
            
            # Find body
            body = root.find(_get_tag('w', 'body'))
            if body is None:
                logger.warning("No body element found in document.xml")
                return
            
            font_id_counter = 0
            
            # Process all paragraphs
            for para in body.iter(_get_tag('w', 'p')):
                # Get paragraph properties for default font
                para_font = None
                para_size = None
                
                ppr = para.find(_get_tag('w', 'pPr'))
                if ppr is not None:
                    # Check for paragraph style
                    pstyle = ppr.find(_get_tag('w', 'pStyle'))
                    if pstyle is not None:
                        style_id = pstyle.get(_get_tag('w', 'val')) or pstyle.get('val')
                        if style_id and style_id in self._styles:
                            style = self._styles[style_id]
                            para_font = style.get("font_name")
                            para_size = style.get("font_size")
                    
                    # Check for run properties in paragraph
                    rpr = ppr.find(_get_tag('w', 'rPr'))
                    if rpr is not None:
                        font_name, font_size = self._extract_font_from_rpr(rpr)
                        if font_name:
                            para_font = font_name
                        if font_size:
                            para_size = font_size
                
                # Process runs in paragraph
                para_has_content = False
                for run in para.iter(_get_tag('w', 'r')):
                    # Get run properties
                    run_font = para_font or self._default_font
                    run_size = para_size or self._default_size
                    
                    rpr = run.find(_get_tag('w', 'rPr'))
                    if rpr is not None:
                        # Check for character style
                        rstyle = rpr.find(_get_tag('w', 'rStyle'))
                        if rstyle is not None:
                            style_id = rstyle.get(_get_tag('w', 'val')) or rstyle.get('val')
                            if style_id and style_id in self._styles:
                                style = self._styles[style_id]
                                if style.get("font_name"):
                                    run_font = style["font_name"]
                                if style.get("font_size"):
                                    run_size = style["font_size"]
                        
                        # Direct run formatting overrides
                        font_name, font_size = self._extract_font_from_rpr(rpr)
                        if font_name:
                            run_font = font_name
                        if font_size:
                            run_size = font_size
                    
                    # Extract text content
                    text_content = []
                    for text_elem in run.iter(_get_tag('w', 't')):
                        if text_elem.text:
                            text_content.append(text_elem.text)
                    
                    # Handle special elements
                    for tab in run.iter(_get_tag('w', 'tab')):
                        text_content.append('\t')
                    
                    for br in run.iter(_get_tag('w', 'br')):
                        text_content.append('\n')
                    
                    if text_content:
                        text = ''.join(text_content)
                        
                        # Create stream entry
                        if run_font not in self._font_map:
                            self._font_map[run_font] = {"id": font_id_counter, "name": run_font}
                            font_id_counter += 1
                        
                        font_info = self._font_map.get(run_font, {"id": 0, "name": run_font})
                        
                        self._streams.append({
                            "text": text,
                            "font": {
                                "id": font_info["id"],
                                "name": run_font,
                                "size": run_size
                            }
                        })
                        para_has_content = True
                
                # Add paragraph break (newline) after each paragraph with content
                if para_has_content:
                    # Add a newline stream to preserve paragraph structure
                    self._streams.append({
                        "text": "\n",
                        "font": {
                            "id": 0,
                            "name": self._default_font,
                            "size": self._default_size
                        }
                    })
                        
        except ET.ParseError as e:
            logger.error(f"Error parsing document.xml: {e}")
    
    def _parse_header_footer(self, xml_data: bytes, hf_type: str):
        """
        Parse word/header*.xml or word/footer*.xml to extract text runs.
        
        Args:
            xml_data: XML content of header or footer
            hf_type: 'header' or 'footer'
        """
        try:
            root = ET.fromstring(xml_data)
            
            # Find body (headers/footers use same structure as document body)
            body = root.find(_get_tag('w', 'body'))
            if body is None:
                return
            
            font_id_counter = len(self._font_map)
            
            # Process all paragraphs
            for para in body.iter(_get_tag('w', 'p')):
                # Get paragraph properties for default font
                para_font = None
                para_size = None
                
                ppr = para.find(_get_tag('w', 'pPr'))
                if ppr is not None:
                    # Check for paragraph style
                    pstyle = ppr.find(_get_tag('w', 'pStyle'))
                    if pstyle is not None:
                        style_id = pstyle.get(_get_tag('w', 'val')) or pstyle.get('val')
                        if style_id and style_id in self._styles:
                            style = self._styles[style_id]
                            para_font = style.get("font_name")
                            para_size = style.get("font_size")
                    
                    # Check for run properties in paragraph
                    rpr = ppr.find(_get_tag('w', 'rPr'))
                    if rpr is not None:
                        font_name, font_size = self._extract_font_from_rpr(rpr)
                        if font_name:
                            para_font = font_name
                        if font_size:
                            para_size = font_size
                
                # Process runs in paragraph
                para_has_content = False
                for run in para.iter(_get_tag('w', 'r')):
                    # Get run properties
                    run_font = para_font or self._default_font
                    run_size = para_size or self._default_size
                    
                    rpr = run.find(_get_tag('w', 'rPr'))
                    if rpr is not None:
                        # Check for character style
                        rstyle = rpr.find(_get_tag('w', 'rStyle'))
                        if rstyle is not None:
                            style_id = rstyle.get(_get_tag('w', 'val')) or rstyle.get('val')
                            if style_id and style_id in self._styles:
                                style = self._styles[style_id]
                                if style.get("font_name"):
                                    run_font = style["font_name"]
                                if style.get("font_size"):
                                    run_size = style["font_size"]
                        
                        # Direct run formatting overrides
                        font_name, font_size = self._extract_font_from_rpr(rpr)
                        if font_name:
                            run_font = font_name
                        if font_size:
                            run_size = font_size
                    
                    # Extract text content
                    text_content = []
                    for text_elem in run.iter(_get_tag('w', 't')):
                        if text_elem.text:
                            text_content.append(text_elem.text)
                    
                    # Handle special elements
                    for tab in run.iter(_get_tag('w', 'tab')):
                        text_content.append('\t')
                    
                    for br in run.iter(_get_tag('w', 'br')):
                        text_content.append('\n')
                    
                    if text_content:
                        text = ''.join(text_content)
                        
                        # Create stream entry
                        if run_font not in self._font_map:
                            self._font_map[run_font] = {"id": font_id_counter, "name": run_font}
                            font_id_counter += 1
                        
                        font_info = self._font_map.get(run_font, {"id": 0, "name": run_font})
                        
                        self._streams.append({
                            "text": text,
                            "type": hf_type,  # Mark as header or footer
                            "font": {
                                "id": font_info["id"],
                                "name": run_font,
                                "size": run_size
                            }
                        })
                        para_has_content = True
                
                # Add paragraph break (newline) after each paragraph with content
                if para_has_content:
                    self._streams.append({
                        "text": "\n",
                        "type": hf_type,
                        "font": {
                            "id": 0,
                            "name": self._default_font,
                            "size": self._default_size
                        }
                    })
                        
        except ET.ParseError as e:
            logger.warning(f"Error parsing {hf_type} XML: {e}")
    
    def get_streams(self):
        """Return list of text streams with font information."""
        return self._streams
    
    def get_fonts(self):
        """Return list of fonts found in the document."""
        return self._fonts
