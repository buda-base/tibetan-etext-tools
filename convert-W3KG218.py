from io import StringIO
import re
from pathlib import Path
import json
import logging
import os
import natsort
import threading
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from pytiblegenc import DuffedTextConverter, get_glyph_db_path, build_font_hash_index_from_csv, identify_pdf_fonts_from_db
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

BL = {
    "W3KG218/W3KG218-I3KG749/2-40-7.pdf": 200, 
    "W3KG218/W3KG218-I3KG749/2-40-8.pdf": 200, 
    "W3KG218/W3KG218-I3KG749/2-40-9.pdf": 148, 
    "W3KG218/W3KG218-I3KG785/4-6-1.pdf": 468
}

PAGE_BREAK_STRING_PATTERN = "\nZZZZ\n"

# Number of threads for parallel processing
NUM_THREADS = 8

def get_converted_str(pdf_file_name, glyph_index):
    single_page = "I3KG692" in pdf_file_name
    if pdf_file_name in BL:
        if pdf_file_name == "W3KG218/W3KG218-I3KG785/4-6-1.pdf":
            single_page = True
        else:
            return
    # get the total number of pages and the number of blank pages
    stats = {
        "unhandled_fonts": {},
        "handled_fonts": {},
        "unknown_characters": {},
        "error_characters": 0,
        "diffs_with_utfc": {},
        "nb_non_horizontal_removed": 0
    }
    output_string = StringIO()
    with open(pdf_file_name, 'rb') as in_file:
        parser = PDFParser(in_file)
        doc = PDFDocument(parser)
        font_normalization = identify_pdf_fonts_from_db(doc, glyph_index)
        rsrcmgr = PDFResourceManager()
        device_r0 = DuffedTextConverter(rsrcmgr, output_string, stats, region = None, pbs = PAGE_BREAK_STRING_PATTERN, remove_non_hz=True, font_normalization=font_normalization, track_font_size=True)
        interpreter_r0 = PDFPageInterpreter(rsrcmgr, device_r0)
        device_r1 = DuffedTextConverter(rsrcmgr, output_string, stats, region = REGION_P1, pbs = PAGE_BREAK_STRING_PATTERN, remove_non_hz=True, font_normalization=font_normalization, track_font_size=True)
        interpreter_r1 = PDFPageInterpreter(rsrcmgr, device_r1)
        device_r2 = DuffedTextConverter(rsrcmgr, output_string, stats, region = REGION_P2, pbs = PAGE_BREAK_STRING_PATTERN, remove_non_hz=True, font_normalization=font_normalization, track_font_size=True)
        interpreter_r2 = PDFPageInterpreter(rsrcmgr, device_r2)
        device_r3 = DuffedTextConverter(rsrcmgr, output_string, stats, region = REGION_P3, pbs = PAGE_BREAK_STRING_PATTERN, remove_non_hz=True, font_normalization=font_normalization, track_font_size=True)
        interpreter_r3 = PDFPageInterpreter(rsrcmgr, device_r3)
        for page in PDFPage.create_pages(doc):
            if single_page:
                interpreter_r0.process_page(page)
            else:
                interpreter_r1.process_page(page)
                interpreter_r2.process_page(page)
                interpreter_r3.process_page(page)
        res = re.sub("\n\n+", "\n", output_string.getvalue())
        #res = re.sub("\n*ZZZZ\n*", "\n\n", res)
        return res
        #return output_string.getvalue()
        #return re.sub("\n\n+", "\n", output_string.getvalue())

def process_single_pdf(pdf_path, converted_dir, pdf_file, glyph_index):
    """Process a single PDF file and write the converted text to a file."""
    thread_id = threading.current_thread().ident
    start_time = time.time()
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    
    filename = converted_dir + pdf_file[:-4] + ".txt"
    if Path(filename).is_file():
        print("[%s] [Thread-%d] SKIP: %s" % (timestamp, thread_id, pdf_path))
        return
    
    print("[%s] [Thread-%d] START: %s" % (timestamp, thread_id, pdf_path))
    
    converted_str = get_converted_str(pdf_path, glyph_index)
    if converted_str is None:
        elapsed = time.time() - start_time
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print("[%s] [Thread-%d] NO_STRING (%.2fs): %s" % (timestamp, thread_id, elapsed, pdf_path))
        return
    
    with open(filename, "w") as text_file:
        text_file.write(converted_str)
    
    elapsed = time.time() - start_time
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print("[%s] [Thread-%d] DONE (%.2fs): %s" % (timestamp, thread_id, elapsed, pdf_path))

def convert_all():
    # List to store all blank page jpeg names
    blank_page_jpegs = []
    
    glyph_db_path = get_glyph_db_path()
    glyph_index = build_font_hash_index_from_csv(str(glyph_db_path))

    # Collect all PDF files that need processing
    pdf_tasks = []
    
    # Iterate through all subdirectories in the base directory
    for subdir in natsort.natsorted(os.listdir("W3KG218/")):
        full_subdir_path = os.path.join("W3KG218/", subdir)
        
        # Skip if not a directory
        if not os.path.isdir(full_subdir_path):
            continue
        
        converted_dir = "W3KG218-step0/"+subdir+"/"
        os.makedirs(converted_dir, exist_ok=True)
        
        # Find all PDF files in the subdirectory
        pdf_files = [f for f in natsort.natsorted(os.listdir(full_subdir_path)) 
                     if f.endswith('.pdf')]
        
        # Add PDF files to the task list
        for pdf_file in pdf_files:
            pdf_path = os.path.join(full_subdir_path, pdf_file)
            pdf_tasks.append((pdf_path, converted_dir, pdf_file))
    
    # Process PDFs in parallel
    print("\n=== Starting parallel conversion ===")
    print(f"Total PDFs to process: {len(pdf_tasks)}")
    print(f"Number of threads: {NUM_THREADS}")
    print("=" * 50 + "\n")
    
    with ThreadPoolExecutor(max_workers=NUM_THREADS) as executor:
        futures = [
            executor.submit(process_single_pdf, pdf_path, converted_dir, pdf_file, glyph_index)
            for pdf_path, converted_dir, pdf_file in pdf_tasks
        ]
        
        # Wait for all tasks to complete
        completed = 0
        for future in as_completed(futures):
            try:
                future.result()
                completed += 1
                if completed % 10 == 0:
                    print(f"\n[Progress] {completed}/{len(pdf_tasks)} PDFs completed\n")
            except Exception as e:
                print(f"Error processing PDF: {e}")
    
    print(f"\n=== Conversion complete: {completed}/{len(pdf_tasks)} PDFs processed ===\n")

# Example usage
blank_pages = convert_all()
