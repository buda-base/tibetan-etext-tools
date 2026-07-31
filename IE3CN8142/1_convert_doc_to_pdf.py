#!/usr/bin/env python3
"""
Step 1: DOC to PDF Converter using Microsoft Word COM Automation

This script converts DOC files to PDF format using Microsoft Word.
IE3CN8142 has DOC files in subfolders:
  toprocess/{IE_ID}-{VE_ID}/*.doc

Usage:
    python 1_convert_doc_to_pdf.py           # Convert all DOC files
    python 1_convert_doc_to_pdf.py --single IE3CN8142-VE5CN1134/file.doc
    python 1_convert_doc_to_pdf.py --ve VE5CN1134  # Convert specific VE only
"""

import os
import sys
import time
import logging
import argparse
import threading
from pathlib import Path
from natsort import natsorted

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from config import (
    IE_ID, TOPROCESS_DIR, PDF_DIR, DOC_TO_PDF_LOG, DOC_TO_PDF_CHECKPOINT,
    WD_FORMAT_PDF, ensure_directories, extract_ve_id_from_folder
)

try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False
    print("ERROR: pywin32 is required. Install with: pip install pywin32")
    sys.exit(1)

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


def setup_logging():
    """Configure logging with file and console output."""
    ensure_directories()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(DOC_TO_PDF_LOG, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()
checkpoint_lock = threading.Lock()


def load_checkpoints() -> set:
    """Load previously converted files from checkpoint."""
    if DOC_TO_PDF_CHECKPOINT.exists():
        try:
            content = DOC_TO_PDF_CHECKPOINT.read_text(encoding='utf-8').strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error(f"Error reading checkpoint file: {e}")
    return set()


def save_checkpoint(file_path: str):
    """Save a converted file to checkpoint."""
    with checkpoint_lock:
        DOC_TO_PDF_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        with open(DOC_TO_PDF_CHECKPOINT, "a", encoding='utf-8') as f:
            f.write(f"{file_path}\n")


def sanitize_filename(name: str) -> str:
    """Sanitize filename to avoid Windows issues."""
    name = name.rstrip('.')
    while '..' in name:
        name = name.replace('..', '.')
    return name


def get_all_word_files(ve_filter: str = None) -> list:
    """Get all DOC files from toprocess/{IE_ID}-{VE_ID}/ folders.
    
    Args:
        ve_filter: Optional VE ID to filter (e.g., 'VE5CN1134')
    
    Returns:
        List of tuples: (doc_path, ve_id)
    """
    if not TOPROCESS_DIR.exists():
        logger.error(f"toprocess directory not found: {TOPROCESS_DIR}")
        return []
    
    files_by_ve = {}
    
    for ve_folder in TOPROCESS_DIR.iterdir():
        if ve_folder.is_dir() and ve_folder.name.startswith(f"{IE_ID}-"):
            ve_id = extract_ve_id_from_folder(ve_folder.name)
            if ve_id:
                if ve_filter and ve_id != ve_filter:
                    continue
                
                doc_files = []
                for doc_path in ve_folder.glob("*.doc"):
                    if doc_path.is_file() and not doc_path.name.startswith('~'):
                        doc_files.append(doc_path)
                
                if doc_files:
                    files_by_ve[ve_id] = natsorted(doc_files, key=lambda x: x.name)
    
    result = []
    for ve_id in natsorted(files_by_ve.keys()):
        for doc_path in files_by_ve[ve_id]:
            result.append((doc_path, ve_id))
    
    return result


def convert_doc_to_pdf(doc_path: Path, ve_id: str, word_app) -> Path:
    """Convert a single DOC file to PDF using Word COM automation."""
    pdf_ve_dir = PDF_DIR / ve_id
    pdf_ve_dir.mkdir(parents=True, exist_ok=True)
    
    pdf_filename = sanitize_filename(doc_path.stem) + ".pdf"
    pdf_path = pdf_ve_dir / pdf_filename
    
    doc = None
    try:
        doc = word_app.Documents.Open(
            str(doc_path.absolute()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            Revert=False,
            Format=0,
            NoEncodingDialog=True
        )
        doc.SaveAs2(str(pdf_path.absolute()), FileFormat=WD_FORMAT_PDF, AddToRecentFiles=False)
        return pdf_path
    finally:
        if doc:
            try:
                doc.Close(SaveChanges=False)
            except:
                pass


def convert_single_file(relative_path: str):
    """Convert a single DOC file to PDF."""
    doc_path = TOPROCESS_DIR / relative_path
    
    if not doc_path.exists():
        logger.error(f"DOC file not found: {doc_path}")
        return
    
    parts = Path(relative_path).parts
    if len(parts) < 1:
        logger.error(f"Invalid path: {relative_path}")
        return
    
    folder_name = parts[0]
    ve_id = extract_ve_id_from_folder(folder_name)
    if not ve_id:
        logger.error(f"Could not determine VE ID from path: {relative_path}")
        return
    
    logger.info(f"Converting: {doc_path.name}")
    logger.info(f"  VE ID: {ve_id}")
    
    word_app = None
    try:
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        
        pdf_path = convert_doc_to_pdf(doc_path, ve_id, word_app)
        logger.info(f"  Output: {pdf_path}")
        
    except Exception as e:
        logger.error(f"Error converting {doc_path.name}: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if word_app:
            try:
                word_app.Quit()
            except:
                pass


def convert_all_files(ve_filter: str = None):
    """Convert all DOC files to PDF."""
    logger.info("=" * 60)
    logger.info(f"DOC to PDF Converter for {IE_ID}")
    if ve_filter:
        logger.info(f"Filtering: {ve_filter} only")
    logger.info(f"Input: {TOPROCESS_DIR}")
    logger.info(f"Output: {PDF_DIR}")
    logger.info("=" * 60)
    
    ensure_directories()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    all_files = get_all_word_files(ve_filter)
    
    if not all_files:
        logger.error("No DOC files found")
        return
    
    logger.info(f"Found {len(all_files)} DOC files")
    
    ve_counts = {}
    for _, ve_id in all_files:
        ve_counts[ve_id] = ve_counts.get(ve_id, 0) + 1
    for ve_id in natsorted(ve_counts.keys()):
        logger.info(f"  {ve_id}: {ve_counts[ve_id]} files")
    
    word_app = None
    success_count = 0
    failed_count = 0
    skipped_count = 0
    
    try:
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        word_app.Options.ConfirmConversions = False
        word_app.Options.DoNotPromptForConvert = True
        
        iterator = tqdm(all_files, desc="Converting") if TQDM_AVAILABLE else all_files
        
        for doc_path, ve_id in iterator:
            doc_path_str = str(doc_path)
            
            if doc_path_str in checkpoints:
                logger.info(f"Skipping (already converted): {doc_path.name}")
                skipped_count += 1
                continue
            
            try:
                logger.info(f"Converting: {doc_path.name} ({ve_id})")
                pdf_path = convert_doc_to_pdf(doc_path, ve_id, word_app)
                save_checkpoint(doc_path_str)
                success_count += 1
                logger.info(f"  -> {pdf_path.name}")
                
            except Exception as e:
                logger.error(f"Error converting {doc_path.name}: {e}")
                failed_count += 1
                
    except Exception as e:
        logger.error(f"Error initializing Word: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if word_app:
            try:
                word_app.Quit()
            except:
                pass
    
    logger.info("\n" + "=" * 60)
    logger.info("CONVERSION COMPLETE!")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Failed: {failed_count}")
    logger.info(f"  Skipped: {skipped_count}")
    logger.info(f"  Output: {PDF_DIR}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Convert DOC files to PDF")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single file (path relative to toprocess/)")
    parser.add_argument("--ve", metavar="VE_ID", help="Convert all files for a specific VE ID (e.g., VE5CN1134)")
    args = parser.parse_args()
    
    if args.single:
        convert_single_file(args.single)
    else:
        convert_all_files(args.ve)


if __name__ == "__main__":
    main()
