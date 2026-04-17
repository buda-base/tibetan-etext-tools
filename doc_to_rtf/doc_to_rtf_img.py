import os
import time
import logging
from pathlib import Path
import win32com.client
from tqdm import tqdm
import threading
import argparse
'''
REMOVE IMAGES FROM DOC FILES AND CONVERT TO RTF

Simple command (using default settings):
python \doc_to_rtf\doc_to_rtf.py
With custom base directory for IE00KG02:
python \doc_to_rtf\doc_to_rtf.py --base-dir "D:\monlam_dharmaduta\convert3\IE00KG02\sources"
If you want to process a specific volume:
python \doc_to_rtf\doc_to_rtf.py --base-dir "D:\monlam_dharmaduta\convert3\IE00KG02\sources" --volume volume_001
With custom checkpoint and log files:
python \doc_to_rtf\doc_to_rtf.py --base-dir "D:\monlam_dharmaduta\convert3\IE00KG02\sources" --checkpoint checkpoint.txt --log conversion.log

'''
# Word Constants
wdFormatRTF = 6

# ============================================
# LOGGING SETUP
# ============================================
def setup_logging(log_file):
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

# Thread lock for checkpoint file
checkpoint_lock = threading.Lock()

def load_checkpoints(checkpoint_file):
    """Load previously converted files from checkpoint"""
    if checkpoint_file.exists():
        try:
            content = checkpoint_file.read_text(encoding='utf-8').strip()
            if content:
                return set(content.split("\n"))
        except Exception as e:
            print(f"Error reading checkpoint file: {e}")
    return set()

def save_checkpoint(checkpoint_file, file_path: str):
    """Save converted file to checkpoint"""
    with checkpoint_lock:
        with open(checkpoint_file, "a", encoding='utf-8') as f:
            f.write(f"{file_path}\n")

def doc_to_rtf_path(doc_path: Path, same_dir: bool = False) -> Path:
    """
    Return output RTF path.
    If same_dir is True, save in the same directory as the .doc file.
    Otherwise, return path with .rtf extension.
    """
    return doc_path.with_suffix(".rtf")

def convert_with_word(word_app, doc_path: Path, output_path: Path, logger):
    """Convert a single .doc file to RTF using Microsoft Word"""
    doc = None
    try:
        # Word needs absolute paths
        abs_doc_path = str(doc_path.absolute())
        abs_output_path = str(output_path.absolute())
        
        # Open the document with all dialog-suppressing parameters
        doc = word_app.Documents.Open(
            abs_doc_path,
            ConfirmConversions=False,   # Don't show file conversion dialog
            ReadOnly=False,             # Need write access to delete headers/footers
            AddToRecentFiles=False,     # Don't modify recent files list
            PasswordDocument="",        # No password
            PasswordTemplate="",        # No template password
            Revert=False,
            WritePasswordDocument="",
            WritePasswordTemplate="",
            Format=0,                   # wdOpenFormatAuto
            Visible=False,
            OpenAndRepair=False,
            NoEncodingDialog=True       # Don't show encoding dialog
        )
        
        # Remove headers and footers from all sections
        try:
            for section in doc.Sections:
                # Delete all header types (primary, first page, even pages)
                for header in section.Headers:
                    header.Range.Delete()
                # Delete all footer types (primary, first page, even pages)
                for footer in section.Footers:
                    footer.Range.Delete()
        except Exception as e:
            logger.warning(f"Could not remove headers/footers from {doc_path.name}: {e}")
        
        # Remove all images (InlineShapes and Shapes)
        try:
            # Remove InlineShapes (inline images)
            while doc.InlineShapes.Count > 0:
                doc.InlineShapes(1).Delete()
            
            # Remove Shapes (floating images, text boxes, etc.)
            while doc.Shapes.Count > 0:
                doc.Shapes(1).Delete()
        except Exception as e:
            logger.warning(f"Could not remove images from {doc_path.name}: {e}")
        
        # Save as RTF with dialog suppression
        try:
            doc.SaveAs2(
                abs_output_path,
                FileFormat=wdFormatRTF,
                AddToRecentFiles=False
            )
        except AttributeError:
            # Fallback for older Word versions
            doc.SaveAs(abs_output_path, FileFormat=wdFormatRTF)
        
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

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Convert DOC files to RTF format using Microsoft Word')
    parser.add_argument('--base-dir', '-b', type=str,
                        default=r"D:\monlam_dharmaduta\convert3\IE00KG02\IE00KG02\sources")
    parser.add_argument('--volume', '-v', type=str, default=None,
                        help='Specific volume to process (e.g., volume_001). If not specified, processes all volumes.')
    parser.add_argument('--checkpoint', '-c', type=str, default=None,
                        help='Checkpoint file path (default: checkpoint_rtf.txt in base dir)')
    parser.add_argument('--log', '-l', type=str, default=None,
                        help='Log file path (default: conversion_log.txt in base dir)')
    
    args = parser.parse_args()
    
    # Setup paths
    base_dir = Path(args.base_dir)
    
    # Set default checkpoint and log files if not provided
    checkpoint_file = Path(args.checkpoint) if args.checkpoint else base_dir / "checkpoint_rtf.txt"
    log_file = Path(args.log) if args.log else base_dir / "conversion_log.txt"
    
    # Create base directory if it doesn't exist
    base_dir.mkdir(parents=True, exist_ok=True)
    
    # Setup logging
    logger = setup_logging(log_file)
    
    logger.info("=" * 70)
    logger.info("DOC to RTF Converter (Microsoft Word Version)")
    logger.info("=" * 70)
    
    if not base_dir.is_dir():
        logger.error(f"Base directory does not exist: {base_dir}")
        return
    
    logger.info(f"Base directory: {base_dir}")
    logger.info(f"Checkpoint: {checkpoint_file}")
    logger.info(f"Log: {log_file}")
    
    # Load checkpoints
    checkpoints = load_checkpoints(checkpoint_file)
    logger.info(f"Existing checkpoint entries: {len(checkpoints)}")
    
    # Recursively find all DOC files in base directory and all subdirectories
    logger.info(f"Searching for .doc files recursively in {base_dir}...")
    doc_files = [
        f for f in base_dir.rglob("*.doc")
        if f.suffix.lower() == '.doc' and not f.name.startswith('~')
    ]
    
    # Group files by subdirectory for reporting
    subdirs = {}
    for doc_file in doc_files:
        rel_dir = doc_file.parent.relative_to(base_dir)
        subdir_name = str(rel_dir) if str(rel_dir) != '.' else 'base directory'
        if subdir_name not in subdirs:
            subdirs[subdir_name] = []
        subdirs[subdir_name].append(doc_file)
    
    # Log what was found
    if subdirs:
        logger.info(f"Found .doc files in {len(subdirs)} location(s):")
        for subdir_name, files in sorted(subdirs.items()):
            logger.info(f"  - {subdir_name}: {len(files)} files")
    
    logger.info(f"Total .doc files found: {len(doc_files)}")
    
    if not doc_files:
        logger.error(f"No .doc files found in {base_dir} or its subdirectories")
        return
    
    # Find files that need conversion
    to_convert = []
    for doc in doc_files:
        doc_path_str = str(doc)
        rtf_file = doc_to_rtf_path(doc)
        
        if doc_path_str not in checkpoints:
            # Even if it's not in checkpoint, check if valid RTF already exists
            if not rtf_file.exists() or rtf_file.stat().st_size == 0:
                to_convert.append(doc)
            else:
                # Add to checkpoint if it exists but wasn't recorded
                save_checkpoint(checkpoint_file, doc_path_str)
                checkpoints.add(doc_path_str)
    
    logger.info(f"Files to convert: {len(to_convert)}")
    
    if not to_convert:
        logger.info("All files already converted!")
        return

    # Initialize Word
    logger.info("Starting Microsoft Word...")
    try:
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0  # wdAlertsNone - suppress all alerts
        
        # Additional settings to suppress dialogs
        word_app.Options.ConfirmConversions = False
        word_app.Options.DoNotPromptForConvert = True
        
        # Disable AutoRecover popups
        try:
            word_app.Options.SaveInterval = 0
        except:
            pass
            
        # Try to disable Protected View warnings
        try:
            word_app.Options.WarnBeforeSavingPrintingSendingMarkup = False
        except:
            pass
            
        logger.info("Word initialized successfully")
    except Exception as e:
        logger.error(f"Could not start Microsoft Word: {e}")
        logger.error("Make sure Microsoft Word is installed on your system.")
        return

    success_count = 0
    failed_count = 0
    
    try:
        for doc_file in tqdm(to_convert, desc="Converting with Word"):
            output_file = doc_to_rtf_path(doc_file)
            
            if convert_with_word(word_app, doc_file, output_file, logger):
                # Verify output exists and is not empty
                if output_file.exists() and output_file.stat().st_size > 0:
                    save_checkpoint(checkpoint_file, str(doc_file))
                    success_count += 1
                    logger.info(f"✓ Converted: {doc_file.parent.name}/{doc_file.name} -> {output_file.name}")
                else:
                    logger.error(f"✗ Output file empty or missing: {doc_file.name}")
                    failed_count += 1
            else:
                failed_count += 1
            
            # Small delay to let Word stabilize between files
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
    logger.info(f"  Output: RTF files saved in same directories as .doc files")
    logger.info("=" * 70)

if __name__ == "__main__":
    main()
