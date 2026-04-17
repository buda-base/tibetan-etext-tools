#!/usr/bin/env python3
"""
Step 1: DOC to DOCX Converter using Microsoft Word COM Automation
note :GANGA's script
This script converts DOC files to DOCX format using Microsoft Word.
It processes all DOC files in the toprocess/{IE_ID}-{VE_ID}/ folders
and outputs DOCX files alongside the original DOC files in the same folder.

Input structure:  toprocess/{IE_ID}-{VE_ID}/*.doc
Output structure: toprocess/{IE_ID}-{VE_ID}/*.docx  (converted)
                  toprocess/{IE_ID}-{VE_ID}/*.doc   (original, untouched)

Usage:
    python convert1.py                             # Convert all DOC files
    python convert1.py --sample-files             # Convert only 1st, 4th, and 5th files per volume
    python convert1.py --only-first               # Convert only 1st file per volume
    python convert1.py --only-fifth               # Convert only 5th file per volume
    python convert1.py --single IE2PD17465-VE5CN239/file.doc  # Convert single file
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
    IE_ID, TOPROCESS_DIR, DOC_TO_DOCX_LOG, DOC_TO_DOCX_CHECKPOINT,
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


def get_all_word_files(sample_files: bool = False, only_first: bool = False, only_fifth: bool = False) -> list:
    """Get all DOC files from toprocess/{IE_ID}-{VE_ID}/ folders.
    
    Args:
        sample_files: If True, only return the 1st, 4th, and 5th files from each volume
        only_first: If True, only return the 1st file from each volume
        only_fifth: If True, only return the 5th file from each volume
    """
    if not TOPROCESS_DIR.exists():
        logger.error(f"toprocess directory not found: {TOPROCESS_DIR}")
        return []
    
    files_by_ve = {}
    
    for ve_folder in TOPROCESS_DIR.iterdir():
        if ve_folder.is_dir():
            ve_id = extract_ve_id_from_folder(ve_folder.name)
            if ve_id:
                ve_files = [
                    doc_file for doc_file in ve_folder.glob("*.doc")
                    if not doc_file.name.startswith('~')
                ]
                
                if ve_files:
                    files_by_ve[ve_id] = natsorted(ve_files, key=lambda p: p.name)
    
    word_files = []
    for ve_id in natsorted(files_by_ve.keys()):
        ve_files = files_by_ve[ve_id]
        
        if only_first:
            if len(ve_files) >= 1:
                word_files.append((ve_files[0], ve_id))  # 1st file (index 0)
            else:
                logger.warning(f"  {ve_id}: No files found, skipping")
        elif only_fifth:
            if len(ve_files) >= 5:
                word_files.append((ve_files[4], ve_id))  # 5th file (index 4)
            else:
                logger.warning(f"  {ve_id}: Less than 5 files, skipping")
        elif sample_files:
            selected = []
            if len(ve_files) >= 1:
                selected.append(ve_files[0])   # 1st file
            if len(ve_files) >= 4:
                selected.append(ve_files[3])   # 4th file
            if len(ve_files) >= 5:
                selected.append(ve_files[4])   # 5th file
            
            if len(selected) < 3 and len(ve_files) >= 1:
                logger.warning(f"  {ve_id}: Only {len(ve_files)} files, selecting available")
            
            for f in selected:
                word_files.append((f, ve_id))
        else:
            for f in ve_files:
                word_files.append((f, ve_id))
    
    return word_files


def get_output_path(word_path: Path, ve_id: str = None) -> Path:
    """Get the output DOCX path for a DOC file (same folder as the source)."""
    return word_path.parent / (word_path.stem + ".docx")


def convert_with_word(word_app, word_path: Path, output_path: Path) -> bool:
    """Convert a single DOC file to DOCX using Microsoft Word."""
    doc = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        abs_word_path = str(word_path.absolute())
        abs_output_path = str(output_path.absolute())
        
        doc = word_app.Documents.Open(
            abs_word_path,
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            PasswordDocument="",
            PasswordTemplate="",
            Revert=False,
            WritePasswordDocument="",
            WritePasswordTemplate="",
            Format=0,
            Visible=False,
            OpenAndRepair=False,
            NoEncodingDialog=True
        )
        
        try:
            doc.UpdateStylesOnOpen = False
        except:
            pass
        
        try:
            doc.SaveAs2(abs_output_path, FileFormat=WD_FORMAT_DOCX, AddToRecentFiles=False)
        except AttributeError:
            doc.SaveAs(abs_output_path, FileFormat=WD_FORMAT_DOCX)
        
        return True
        
    except Exception as e:
        logger.error(f"Word conversion failed for {word_path.name}: {e}")
        return False
        
    finally:
        if doc:
            try:
                doc.Close(SaveChanges=False)
            except:
                pass


def initialize_word():
    """Initialize Microsoft Word application."""
    logger.info("Starting Microsoft Word...")
    try:
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        word_app.Options.ConfirmConversions = False
        word_app.Options.DoNotPromptForConvert = True
        
        try:
            word_app.Options.SaveInterval = 0
        except:
            pass
        
        try:
            word_app.Options.WarnBeforeSavingPrintingSendingMarkup = False
        except:
            pass
        
        logger.info("Word initialized successfully")
        return word_app
        
    except Exception as e:
        logger.error(f"Could not start Microsoft Word: {e}")
        return None


def convert_single(relative_path: str):
    """Convert a single DOC file."""
    parts = Path(relative_path).parts
    if len(parts) < 2:
        logger.error(f"Invalid path format. Expected: IE2PD17465-VE5CN239/file.doc")
        return
    
    folder_name = parts[0]
    filename = parts[-1]
    
    ve_id = extract_ve_id_from_folder(folder_name)
    if not ve_id:
        logger.error(f"Could not extract VE ID from folder name: {folder_name}")
        return
    
    word_path = TOPROCESS_DIR / folder_name / filename
    
    if not word_path.exists():
        logger.error(f"File not found: {word_path}")
        return
    
    output_path = get_output_path(word_path)
    
    word_app = initialize_word()
    if not word_app:
        return
    
    try:
        logger.info(f"Converting: {word_path.name}")
        logger.info(f"  VE ID: {ve_id}")
        logger.info(f"  Output: {output_path}")
        
        if convert_with_word(word_app, word_path, output_path):
            if output_path.exists() and output_path.stat().st_size > 0:
                save_checkpoint(str(word_path))
                logger.info(f"  SUCCESS: {output_path.name}")
            else:
                logger.error(f"  FAILED: Output file empty or missing")
        else:
            logger.error(f"  FAILED: Conversion error")
            
    finally:
        logger.info("Closing Word...")
        try:
            word_app.Quit()
        except:
            pass


def convert_all(sample_files: bool = False, only_first: bool = False, only_fifth: bool = False):
    """Convert all DOC files to DOCX.
    
    Args:
        sample_files: If True, only convert the 1st, 4th, and 5th files from each volume
        only_first: If True, only convert the 1st file from each volume
        only_fifth: If True, only convert the 5th file from each volume
    """
    logger.info("=" * 70)
    logger.info("DOC to DOCX Converter (Microsoft Word Version)")
    logger.info(f"Project: {IE_ID}")
    if only_first:
        logger.info("Mode: Only 1st file per volume")
    elif only_fifth:
        logger.info("Mode: Only 5th file per volume")
    elif sample_files:
        logger.info("Mode: Sample files only (positions 1, 4, and 5)")
    logger.info("=" * 70)
    
    ensure_directories()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    word_files = get_all_word_files(sample_files=sample_files, only_first=only_first, only_fifth=only_fifth)
    logger.info(f"Total DOC files found: {len(word_files)}")
    
    if not word_files:
        logger.warning("No DOC files found in toprocess directory")
        return
    
    to_convert = []
    for word_path, ve_id in word_files:
        word_path_str = str(word_path)
        output_path = get_output_path(word_path, ve_id)
        
        if word_path_str not in checkpoints:
            if not output_path.exists() or output_path.stat().st_size == 0:
                to_convert.append((word_path, ve_id))
            else:
                save_checkpoint(word_path_str)
                checkpoints.add(word_path_str)
    
    logger.info(f"Files to convert: {len(to_convert)}")
    
    if not to_convert:
        logger.info("All files already converted!")
        return
    
    word_app = initialize_word()
    if not word_app:
        return
    
    success_count = 0
    failed_count = 0
    
    try:
        if TQDM_AVAILABLE:
            iterator = tqdm(to_convert, desc="Converting with Word")
        else:
            iterator = to_convert
        
        for word_path, ve_id in iterator:
            output_path = get_output_path(word_path, ve_id)
            
            if not TQDM_AVAILABLE:
                logger.info(f"Converting: {word_path.name} (VE: {ve_id})")
            
            if convert_with_word(word_app, word_path, output_path):
                if output_path.exists() and output_path.stat().st_size > 0:
                    save_checkpoint(str(word_path))
                    success_count += 1
                else:
                    logger.error(f"Output file empty or missing: {word_path.name}")
                    failed_count += 1
            else:
                failed_count += 1
            
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
        
    finally:
        logger.info("Closing Word...")
        try:
            word_app.Quit()
        except:
            pass
    
    logger.info("=" * 70)
    logger.info("CONVERSION COMPLETE!")
    logger.info(f"  Converted: {success_count}")
    logger.info(f"  Failed: {failed_count}")
    logger.info(f"  Output: {TOPROCESS_DIR} (alongside source .doc files)")
    logger.info("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Convert DOC files to DOCX using Microsoft Word")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single DOC file (path relative to toprocess/, e.g., IE2PD17465-VE5CN239/file.doc)")
    parser.add_argument("--sample-files", action="store_true", help="Convert only the 1st, 4th, and 5th files from each volume")
    parser.add_argument("--only-first", action="store_true", help="Convert only the 1st file from each volume")
    parser.add_argument("--only-fifth", action="store_true", help="Convert only the 5th file from each volume")
    args = parser.parse_args()
    
    if args.single:
        convert_single(args.single)
    else:
        convert_all(sample_files=args.sample_files, only_first=args.only_first, only_fifth=args.only_fifth)


if __name__ == "__main__":
    main()