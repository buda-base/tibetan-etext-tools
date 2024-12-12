from io import StringIO
import re
from pathlib import Path
import json
import logging
import os
import natsort

from pytiblegenc import DuffedTextConverter
from pdfminer.pdfdocument import PDFDocument
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import LTPage
from pdfminer.pdfparser import PDFParser
from pdfminer.layout import LAParams

# uncomment to debug region
#logging.basicConfig(level=logging.DEBUG)

REGION = None

# total = 1353*957
# REGION_P1 = [128, 110, 1260-128, 354-110]
# REGION_P2 = [128, 362, 1260-128, 590-362]
# REGION_P3 = [128, 605, 1260-128, 831-605]

REGION_P1 = [0.094, 0.645, 0.836, 0.24]
REGION_P2 = [0.094, 0.382, 0.836, 0.24]
REGION_P3 = [0.094, 0.128, 0.836, 0.24]

# some PDFs like I3KG712/2-2-25.pdf have a blank page that should be kept (with frame, marginalia, etc.)

def get_total_nb_blank(pdf_file_name):
    # get the total number of pages and the number of blank pages
    stats = {
        "unhandled_fonts": {},
        "handled_fonts": {},
        "unknown_characters": {},
        "error_characters": 0,
        "diffs_with_utfc": {},
        "nb_non_horizontal_removed": 0
    }
    output_string_r2 = StringIO()
    output_string_r3 = StringIO()
    with open(pdf_file_name, 'rb') as in_file:
        parser = PDFParser(in_file)
        doc = PDFDocument(parser)
        rsrcmgr_r2 = PDFResourceManager()
        device_r2 = DuffedTextConverter(rsrcmgr_r2, output_string_r2, stats, region = REGION_P2, pbs = "{}", remove_non_hz=False)
        interpreter_r2 = PDFPageInterpreter(rsrcmgr_r2, device_r2)
        rsrcmgr_r3 = PDFResourceManager()
        device_r3 = DuffedTextConverter(rsrcmgr_r3, output_string_r3, stats, region = REGION_P3, pbs = "{}", remove_non_hz=False)
        interpreter_r3 = PDFPageInterpreter(rsrcmgr_r3, device_r3)
        res = 0
        last_page = None
        nb_pages_total = 0
        for page in PDFPage.create_pages(doc):
            last_page = page
            nb_pages_total += 3
        interpreter_r2.process_page(last_page)
        output_r2 = output_string_r2.getvalue().replace("\n", "")
        if (len(output_r2) < 4):
            res = 1
        interpreter_r3.process_page(last_page)
        output_r3 = output_string_r3.getvalue().replace("\n", "")
        if (len(output_r3) < 4):
            res += 1
        return nb_pages_total, res

def list_all_blank_pages(base_directory='W3KG218/'):
    # List to store all blank page jpeg names
    blank_page_jpegs = []
    
    # Iterate through all subdirectories in the base directory
    for subdir in natsort.natsorted(os.listdir(base_directory)):
        # Full path to the subdirectory
        cur_jpg_idx = 3
        ilname = subdir.split("-")[-1]
        full_subdir_path = os.path.join(base_directory, subdir)
        
        # Skip if not a directory
        if not os.path.isdir(full_subdir_path):
            continue
        
        # Find all PDF files in the subdirectory
        pdf_files = [f for f in natsort.natsorted(os.listdir(full_subdir_path)) 
                     if f.endswith('.pdf')]
        
        # Process each PDF
        for pdf_file in pdf_files:
            # Full path to the PDF
            pdf_path = os.path.join(full_subdir_path, pdf_file)
            
            # Count total pages and blank pages
            total_pages, blank_pages = get_total_nb_blank(pdf_path)
            
            cur_jpg_idx += total_pages - blank_pages
            for i in range(blank_pages):
                cur_jpg_idx += 1
                blank_page_jpegs.append("%s/%s%04d.jpg" % (subdir, ilname, cur_jpg_idx))
        break
    
    return blank_page_jpegs

# Example usage
blank_pages = list_all_blank_pages()
print("Blank Page JPEGs:")
for page in blank_pages:
    print(page)

