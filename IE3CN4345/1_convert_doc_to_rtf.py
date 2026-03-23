#!/usr/bin/env python3
"""
Step 1: DOC to RTF Converter using Microsoft Word COM Automation

This script converts DOC files to RTF format using Microsoft Word.
It processes all DOC files in the sources/{VE_ID}/ folders and outputs
RTF files to rtf/{VE_ID}/ preserving the folder structure.

Usage:
    python 1_convert_doc_to_rtf.py           # Convert all DOC files
    python 1_convert_doc_to_rtf.py --single VE1ER619/file.doc  # Convert single file
"""

import os
import sys
import time
import logging
import argparse
import threading
from pathlib import Path

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from config import (
    SOURCE_DIR, RTF_DIR, DOC_TO_RTF_LOG, DOC_TO_RTF_CHECKPOINT,
    WD_FORMAT_RTF, ensure_directories
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
            logging.FileHandler(DOC_TO_RTF_LOG, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()
checkpoint_lock = threading.Lock()


def load_checkpoints() -> set:
    """Load previously converted files from checkpoint."""
    if DOC_TO_RTF_CHECKPOINT.exists():
        try:
            content = DOC_TO_RTF_CHECKPOINT.read_text(encoding='utf-8').strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            logger.error(f"Error reading checkpoint file: {e}")
    return set()


def save_checkpoint(file_path: str):
    """Save a converted file to checkpoint."""
    with checkpoint_lock:
        DOC_TO_RTF_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
        with open(DOC_TO_RTF_CHECKPOINT, "a", encoding='utf-8') as f:
            f.write(f"{file_path}\n")


def get_all_doc_files() -> list:
    """Get all DOC files from sources/{VE_ID}/ folders."""
    doc_files = []
    
    if not SOURCE_DIR.exists():
        logger.error(f"Source directory not found: {SOURCE_DIR}")
        return []
    
    for ve_folder in SOURCE_DIR.iterdir():
        if ve_folder.is_dir() and ve_folder.name.startswith("VE"):
            ve_id = ve_folder.name
            for doc_file in ve_folder.glob("*.doc"):
                if not doc_file.name.startswith('~'):
                    doc_files.append((doc_file, ve_id))
    
    doc_files.sort(key=lambda x: (x[1], x[0].name))
    return doc_files


def get_output_path(doc_path: Path, ve_id: str) -> Path:
    """Get the output RTF path for a DOC file."""
    rtf_filename = doc_path.stem + ".rtf"
    return RTF_DIR / ve_id / rtf_filename


def convert_with_word(word_app, doc_path: Path, output_path: Path) -> bool:
    """Convert a single DOC file to RTF using Microsoft Word."""
    doc = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        abs_doc_path = str(doc_path.absolute())
        abs_output_path = str(output_path.absolute())
        
        doc = word_app.Documents.Open(
            abs_doc_path,
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
            doc.SaveAs2(abs_output_path, FileFormat=WD_FORMAT_RTF, AddToRecentFiles=False)
        except AttributeError:
            doc.SaveAs(abs_output_path, FileFormat=WD_FORMAT_RTF)
        
        return True
        
    except Exception as e:
        logger.error(f"Word conversion failed for {doc_path.name}: {e}")
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
    doc_path = SOURCE_DIR / relative_path
    
    if not doc_path.exists():
        logger.error(f"File not found: {doc_path}")
        return
    
    ve_id = doc_path.parent.name
    if not ve_id.startswith("VE"):
        logger.error(f"Could not determine VE ID from path: {relative_path}")
        return
    
    output_path = get_output_path(doc_path, ve_id)
    
    word_app = initialize_word()
    if not word_app:
        return
    
    try:
        logger.info(f"Converting: {doc_path.name}")
        logger.info(f"  VE ID: {ve_id}")
        logger.info(f"  Output: {output_path}")
        
        if convert_with_word(word_app, doc_path, output_path):
            if output_path.exists() and output_path.stat().st_size > 0:
                save_checkpoint(str(doc_path))
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
    """Convert all DOC files to RTF."""
    logger.info("=" * 70)
    logger.info("DOC to RTF Converter (Microsoft Word Version)")
    logger.info("=" * 70)
    
    ensure_directories()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    doc_files = get_all_doc_files()
    logger.info(f"Total DOC files found: {len(doc_files)}")
    
    if not doc_files:
        logger.warning("No DOC files found in source directory")
        return
    
    to_convert = []
    for doc_path, ve_id in doc_files:
        doc_path_str = str(doc_path)
        output_path = get_output_path(doc_path, ve_id)
        
        if doc_path_str not in checkpoints:
            if not output_path.exists() or output_path.stat().st_size == 0:
                to_convert.append((doc_path, ve_id))
            else:
                save_checkpoint(doc_path_str)
                checkpoints.add(doc_path_str)
    
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
        
        for doc_path, ve_id in iterator:
            output_path = get_output_path(doc_path, ve_id)
            
            if not TQDM_AVAILABLE:
                logger.info(f"Converting: {doc_path.name}")
            
            if convert_with_word(word_app, doc_path, output_path):
                if output_path.exists() and output_path.stat().st_size > 0:
                    save_checkpoint(str(doc_path))
                    success_count += 1
                else:
                    logger.error(f"Output file empty or missing: {doc_path.name}")
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
    logger.info(f"  Output: {RTF_DIR}")
    logger.info("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Convert DOC files to RTF using Microsoft Word")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single file (path relative to sources/)")
    args = parser.parse_args()
    
    if args.single:
        convert_single(args.single)
    else:
        convert_all()


if __name__ == "__main__":
    main()


