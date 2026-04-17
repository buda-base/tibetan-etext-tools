import fitz  # PyMuPDF
import sys

# Update this to the actual path of your PDF file
pdf_path = "/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5/1-11/IE2KG209991/sources/VE1ER1019/TI994-01-001.pdf"

try:
    doc = fitz.open(pdf_path)
    print(f"Opened {pdf_path} successfully.")
except Exception as e:
    print(f"Error opening PDF: {e}")
    sys.exit(1)

cmap_count = 0

# Scan through all objects in the PDF xref table
for xref in range(1, doc.xref_length()):
    # We only care about stream objects
    if doc.xref_is_stream(xref):
        try:
            # PyMuPDF automatically decompresses the stream here
            stream_bytes = doc.xref_stream(xref)
            
            # Identify ToUnicode CMaps by their standard PostScript markers
            if b"beginbfchar" in stream_bytes or b"beginbfrange" in stream_bytes:
                cmap_count += 1
                output_filename = f"qomolangma_cmap_{cmap_count}.txt"
                
                with open(output_filename, "wb") as f:
                    f.write(stream_bytes)
                print(f"Extracted ToUnicode CMap to: {output_filename}")
        except Exception:
            # Silently skip any corrupted or unreadable streams
            pass 

doc.close()

if cmap_count == 0:
    print("No ToUnicode CMaps found in the document.")
else:
    print(f"\nDone! Extracted {cmap_count} CMap(s).")