#!/usr/bin/env python3
"""
Step 1: DOC to DOCX Converter using Microsoft Word COM Automation

This script converts DOC files to DOCX format using Microsoft Word.
IE3CN18525 has DOC files directly in toprocess/{IE_ID}-{VE_ID}/ folders
(no numbered subfolders).

Usage:
    python 1_convert_doc_to_docx.py           # Convert all DOC files
    python 1_convert_doc_to_docx.py --single IE3CN18525-VE5CN976/file.doc  # Convert single file
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
    
    IE3CN18525 has files directly in VE folders (no numbered subfolders).
    
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
                ve_files = [f for f in doc_files if not f.name.startswith('~')]
                
                if ve_files:
                    files_by_ve[ve_id] = natsorted(ve_files, key=lambda p: p.name)
    
    word_files = []
    for ve_id in natsorted(files_by_ve.keys()):
        for f in files_by_ve[ve_id]:
            word_files.append((f, ve_id))
    
    return word_files


def get_output_path(word_path: Path, ve_id: str) -> Path:
    """Get the output DOCX path for a DOC file."""
    docx_filename = word_path.stem + ".docx"
    return DOCX_DIR / ve_id / docx_filename


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
    """Convert a single DOC file.
    
    Args:
        relative_path: Path relative to toprocess/, e.g., "IE3CN18525-VE5CN976/file.doc"
    """
    parts = Path(relative_path).parts
    if len(parts) < 2:
        logger.error(f"Invalid path format. Expected: IE3CN18525-VE5CN976/file.doc")
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
    
    output_path = get_output_path(word_path, ve_id)
    
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


def convert_all():
    """Convert all DOC files to DOCX."""
    logger.info("=" * 70)
    logger.info("DOC to DOCX Converter (Microsoft Word Version)")
    logger.info(f"Project: {IE_ID}")
    logger.info("=" * 70)
    
    ensure_directories()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    word_files = get_all_word_files()
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
    logger.info(f"  Output: {DOCX_DIR}")
    logger.info("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Convert DOC files to DOCX using Microsoft Word")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single DOC file (path relative to toprocess/)")
    args = parser.parse_args()
    
    if args.single:
        convert_single(args.single)
    else:
        convert_all()


if __name__ == "__main__":
    main()
