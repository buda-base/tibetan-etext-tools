#!/usr/bin/env python3
"""
Step 1: DOC to DOCX Converter using Microsoft Word COM Automation

This script converts DOC files to DOCX format using Microsoft Word.
IE3CN3334 has DOC files directly in toprocess/{IE_ID}-{VE_ID}/ folders.

Usage:
    python 1_convert_doc_to_docx.py           # Convert all DOC files
    python 1_convert_doc_to_docx.py --single IE3CN3334-VE5CN1/file.doc  # Convert single file
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
    IE_ID, TOPROCESS_DIR, DOCX_DIR, DOC_TO_DOCX_LOG, DOC_TO_DOCX_CHECKPOINT,
    WD_FORMAT_DOCX, ensure_directories, extract_ve_id_from_folder
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
            logging.FileHandler(DOC_TO_DOCX_LOG, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()
checkpoint_lock = threading.Lock()


def load_checkpoints() -> set:
    """Load previously converted files from checkpoint."""
    if DOC_TO_DOCX_CHECKPOINT.exists():
        try:
            content = DOC_TO_DOCX_CHECKPOINT.read_text(encoding='utf-8').strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error(f"Error reading checkpoint file: {e}")
    return set()


def save_checkpoint(file_path: str):
    """Save a converted file to checkpoint."""
    with checkpoint_lock:
        DOC_TO_DOCX_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        with open(DOC_TO_DOCX_CHECKPOINT, "a", encoding='utf-8') as f:
            f.write(f"{file_path}\n")


def get_all_word_files() -> list:
    """Get all DOC files from toprocess/{IE_ID}-{VE_ID}/ folders.
    
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
                doc_files = list(ve_folder.glob("*.doc"))
                if doc_files:
                    files_by_ve[ve_id] = natsorted(doc_files, key=lambda x: x.name)
    
    result = []
    for ve_id in natsorted(files_by_ve.keys()):
        for doc_path in files_by_ve[ve_id]:
            result.append((doc_path, ve_id))
    
    return result


def convert_doc_to_docx(doc_path: Path, ve_id: str, word_app) -> Path:
    """Convert a single DOC file to DOCX using Word COM automation.
    
    Args:
        doc_path: Path to the DOC file
        ve_id: VE ID for organizing output
        word_app: Word application COM object
        
    Returns:
        Path to the converted DOCX file
    """
    docx_ve_dir = DOCX_DIR / ve_id
    docx_ve_dir.mkdir(parents=True, exist_ok=True)
    
    docx_filename = doc_path.stem + ".docx"
    docx_path = docx_ve_dir / docx_filename
    
    doc = None
    try:
        doc = word_app.Documents.Open(str(doc_path))
        doc.SaveAs2(str(docx_path), FileFormat=WD_FORMAT_DOCX)
        return docx_path
    finally:
        if doc:
            try:
                doc.Close(SaveChanges=False)
            except:
                pass


def convert_single_file(relative_path: str):
    """Convert a single DOC file to DOCX.
    
    Args:
        relative_path: Path to DOC file relative to toprocess/
                      e.g., "IE3CN3334-VE5CN1/file.doc"
    """
    doc_path = TOPROCESS_DIR / relative_path
    
    if not doc_path.exists():
        logger.error(f"DOC file not found: {doc_path}")
        return
    
    folder_name = doc_path.parent.name
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
        word_app.DisplayAlerts = False
        
        docx_path = convert_doc_to_docx(doc_path, ve_id, word_app)
        logger.info(f"  Output: {docx_path}")
        
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


def convert_all_files():
    """Convert all DOC files to DOCX."""
    logger.info("=" * 60)
    logger.info(f"DOC to DOCX Converter for {IE_ID}")
    logger.info(f"Input: {TOPROCESS_DIR}")
    logger.info(f"Output: {DOCX_DIR}")
    logger.info("=" * 60)
    
    ensure_directories()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    all_files = get_all_word_files()
    
    if not all_files:
        logger.error("No DOC files found")
        return
    
    logger.info(f"Found {len(all_files)} DOC files")
    
    word_app = None
    success_count = 0
    failed_count = 0
    skipped_count = 0
    
    try:
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = False
        
        iterator = tqdm(all_files, desc="Converting") if TQDM_AVAILABLE else all_files
        
        for doc_path, ve_id in iterator:
            doc_path_str = str(doc_path)
            
            if doc_path_str in checkpoints:
                logger.info(f"Skipping (already converted): {doc_path.name}")
                skipped_count += 1
                continue
            
            try:
                logger.info(f"Converting: {doc_path.name} ({ve_id})")
                docx_path = convert_doc_to_docx(doc_path, ve_id, word_app)
                save_checkpoint(doc_path_str)
                success_count += 1
                logger.info(f"  -> {docx_path.name}")
                
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
    logger.info(f"  Output: {DOCX_DIR}")
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Convert DOC files to DOCX")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single file (path relative to toprocess/)")
    args = parser.parse_args()
    
    if args.single:
        convert_single_file(args.single)
    else:
        convert_all_files()


if __name__ == "__main__":
    main()
