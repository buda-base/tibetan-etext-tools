#!/usr/bin/env python3
"""
Step 1: DOC to RTF Converter using Microsoft Word COM Automation

This script converts DOC files to RTF format using Microsoft Word.
It processes all DOC files in the toprocess/{IE_ID}-{VE_ID}/{subfolder}/ folders
and outputs RTF files to rtf/{VE_ID}/ preserving the folder structure.

Note: DOCX files are handled separately by 1_convert_docx_to_xml.py (direct conversion to XML).

Usage:
    python 1_convert_doc_to_rtf.py           # Convert all DOC files
    python 1_convert_doc_to_rtf.py --limit 4 # Convert only first 4 files per volume
    python 1_convert_doc_to_rtf.py --single IE2PD17465-VE5CN239/1/file.doc  # Convert single file
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
    IE_ID, TOPROCESS_DIR, RTF_DIR, DOC_TO_RTF_LOG, DOC_TO_RTF_CHECKPOINT,
    WD_FORMAT_RTF, ensure_directories, extract_ve_id_from_folder
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


def get_all_word_files(limit: int = None) -> list:
    """Get all DOC files from toprocess/{IE_ID}-{VE_ID}/{subfolder}/ folders.
    
    Args:
        limit: If specified, only return the first N files from each volume
    
    Note: DOCX files are handled separately by 1_convert_docx_to_xml.py
    """
    if not TOPROCESS_DIR.exists():
        logger.error(f"toprocess directory not found: {TOPROCESS_DIR}")
        return []
    
    files_by_ve = {}
    
    for ve_folder in TOPROCESS_DIR.iterdir():
        if ve_folder.is_dir():
            ve_id = extract_ve_id_from_folder(ve_folder.name)
            if ve_id:
                ve_files = []
                for subfolder in ve_folder.iterdir():
                    if subfolder.is_dir():
                        doc_files = list(subfolder.glob("*.doc"))
                        
                        for doc_file in doc_files:
                            if not doc_file.name.startswith('~'):
                                ve_files.append(doc_file)
                
                if ve_files:
                    files_by_ve[ve_id] = natsorted(ve_files, key=lambda p: p.name)
    
    word_files = []
    for ve_id in natsorted(files_by_ve.keys()):
        ve_files = files_by_ve[ve_id]
        
        if limit:
            ve_files = ve_files[:limit]
        
        for f in ve_files:
            word_files.append((f, ve_id))
    
    return word_files


def get_output_path(word_path: Path, ve_id: str) -> Path:
    """Get the output RTF path for a DOC file."""
    rtf_filename = word_path.stem + ".rtf"
    return RTF_DIR / ve_id / rtf_filename


def convert_with_word(word_app, word_path: Path, output_path: Path) -> bool:
    """Convert a single DOC file to RTF using Microsoft Word."""
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
            doc.SaveAs2(abs_output_path, FileFormat=WD_FORMAT_RTF, AddToRecentFiles=False)
        except AttributeError:
            doc.SaveAs(abs_output_path, FileFormat=WD_FORMAT_RTF)
        
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
    # Parse relative path: IE2PD17465-VE5CN239/1/file.doc
    parts = Path(relative_path).parts
    if len(parts) < 3:
        logger.error(f"Invalid path format. Expected: IE2PD17465-VE5CN239/1/file.doc")
        return
    
    folder_name = parts[0]
    filename = parts[-1]
    
    ve_id = extract_ve_id_from_folder(folder_name)
    if not ve_id:
        logger.error(f"Could not extract VE ID from folder name: {folder_name}")
        return
    
    # Reconstruct path to find the file
    word_path = TOPROCESS_DIR / folder_name / parts[1] / filename
    
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


def convert_all(limit: int = None):
    """Convert all DOC files to RTF.
    
    Args:
        limit: If specified, only convert the first N files from each volume
    
    Note: DOCX files are handled separately by 1_convert_docx_to_xml.py
    """
    logger.info("=" * 70)
    logger.info("DOC to RTF Converter (Microsoft Word Version)")
    logger.info(f"Project: {IE_ID}")
    if limit:
        logger.info(f"Limit: First {limit} files per volume")
    logger.info("Note: DOCX files are handled by 1_convert_docx_to_xml.py")
    logger.info("=" * 70)
    
    ensure_directories()
    
    checkpoints = load_checkpoints()
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    word_files = get_all_word_files(limit=limit)
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
    logger.info(f"  Output: {RTF_DIR}")
    logger.info("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Convert DOC files to RTF using Microsoft Word (DOCX files handled by 1_convert_docx_to_xml.py)")
    parser.add_argument("--single", "-s", metavar="PATH", help="Convert a single DOC file (path relative to toprocess/, e.g., IE2PD17465-VE5CN239/1/file.doc)")
    parser.add_argument("--limit", "-l", type=int, metavar="N", help="Convert only the first N files from each volume")
    args = parser.parse_args()
    
    if args.single:
        convert_single(args.single)
    else:
        convert_all(limit=args.limit)


if __name__ == "__main__":
    main()

