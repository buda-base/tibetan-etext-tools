#!/usr/bin/env python3
"""Check failed PDF conversions."""

from pathlib import Path
from pytiblegenc import pdf_to_txt
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfpage import PDFPage

BASE_DIR = Path(__file__).parent.parent.parent / "IE1KG14" / "IE1KG14"
SOURCES_DIR = BASE_DIR / "sources"

# Find failed PDFs by name pattern
failed_names = ["TERDZO-'I P25.pdf", "TERDZO-MANGALAM P5-G.pdf", "TERDZO-ZHI P61.pdf", "TERZOD KARCHAK-P-1-60.pdf"]
failed_pdfs = []
for pdf in SOURCES_DIR.rglob("*.pdf"):
    if pdf.name in failed_names or any(n in pdf.name for n in ["P25", "P5-G", "ZHI P61", "KARCHAK-P-1-60"]):
        if "P25" in pdf.name and "53" in str(pdf):
            failed_pdfs.append(pdf)
        elif "P5-G" in pdf.name and "66" in str(pdf):
            failed_pdfs.append(pdf)
        elif "ZHI P61" in pdf.name:
            failed_pdfs.append(pdf)
        elif "KARCHAK-P-1-60" in pdf.name:
            failed_pdfs.append(pdf)

for pdf_path in failed_pdfs:
    print(f"\n{'='*60}")
    print(f"File: {pdf_path.name}")
    print(f"Path: {pdf_path}")
    print(f"Exists: {pdf_path.exists()}")
    
    if pdf_path.exists():
        print(f"Size: {pdf_path.stat().st_size / 1024:.1f} KB")
        
        try:
            with open(pdf_path, 'rb') as f:
                parser = PDFParser(f)
                doc = PDFDocument(parser)
                pages = list(PDFPage.create_pages(doc))
                print(f"Pages: {len(pages)}")
        except Exception as e:
            print(f"Error reading PDF structure: {e}")
        
        # Try to extract text
        try:
            text = pdf_to_txt(str(pdf_path), normalize=False)
            tibetan_chars = len([c for c in text if ord(c) >= 0x0F00 and ord(c) <= 0x0FFF])
            print(f"Extracted text length: {len(text)} chars")
            print(f"Tibetan chars: {tibetan_chars}")
            if text.strip():
                print(f"First 300 chars: {repr(text[:300])}")
            else:
                print("NO TEXT EXTRACTED - likely image-only PDF")
        except Exception as e:
            print(f"Error extracting text: {e}")

