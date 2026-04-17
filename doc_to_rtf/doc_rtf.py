import os
import time
import logging
from pathlib import Path
import win32com.client
from tqdm import tqdm
import threading
import argparse
r'''
REMOVE IMAGES FROM DOC FILES AND CONVERT TO RTF
NOTE : DIFFERENT FILE STRUCTURE

Input structure:  {IE_ID}/source/{IE_ID-VE_ID}/*.doc or *.docx
Output structure: {IE_ID}_output/toprocess/{IE_ID-VE_ID}/*.rtf

Single IE folder (base-dir = path to one IE_ID folder):
  python doc_to_rtf\doc_rtf.py --base-dir "D:\data\IE00KG02"

Bulk folder (process all IE_ID subfolders under the given path):
  python doc_to_rtf\doc_rtf.py --bulk-dir "D:\data"

With a specific volume (IE_ID-VE_ID) in single mode:
  python doc_to_rtf\doc_rtf.py --base-dir "D:\data\IE00KG02" --volume "IE00KG02-VE001"

With custom checkpoint and log:
  python doc_to_rtf\doc_rtf.py --base-dir "D:\data\IE00KG02" --checkpoint checkpoint.txt --log conversion.log
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

def doc_to_rtf_path(doc_path: Path, input_base: Path, output_base: Path) -> Path:
    """
    Map input path under input_base to output path under output_base.
    Input: {IE_ID}/source/{IE_ID-VE_ID}/file.doc -> Output: {IE_ID}_output/toprocess/{IE_ID-VE_ID}/file.rtf
    """
    try:
        rel = doc_path.relative_to(input_base)
    except ValueError:
        rel = Path(doc_path.name)
    parts = list(rel.parts)
    if parts and parts[0] == "source":
        parts[0] = "toprocess"
    return output_base / Path(*parts).with_suffix(".rtf")

def convert_with_word(word_app, doc_path: Path, output_path: Path, logger):
    """Convert a single .doc or .docx file to RTF using Microsoft Word"""
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

def collect_doc_files(input_base: Path, volume_filter: str | None) -> list[Path]:
    """
    Collect .doc and .docx files under input_base/toprocess/{IE_ID-VE_ID}/.
    If volume_filter is set (e.g. IE00KG02-VE001), only that subfolder is considered.
    """
    toprocess_dir = input_base / "toprocess"
    if not toprocess_dir.is_dir():
        return []
    doc_files = []
    for ext in ("*.doc", "*.docx"):
        for f in toprocess_dir.rglob(ext):
            if f.suffix.lower() not in (".doc", ".docx") or f.name.startswith("~") or f.name.startswith("._"):
                continue
            # Path is toprocess/{IE_ID-VE_ID}/file.doc(x)
            if volume_filter:
                try:
                    rel = f.relative_to(toprocess_dir)
                    # rel is like IE00KG02-VE001/file.doc
                    if rel.parts[0] != volume_filter:
                        continue
                except ValueError:
                    continue
            doc_files.append(f)
    return doc_files


def run_conversion_for_ie(
    input_base: Path,
    checkpoint_file: Path,
    log_file: Path,
    volume_filter: str | None,
    logger,
) -> tuple[int, int]:
    """
    Run conversion for one IE_ID folder. Returns (success_count, failed_count).
    input_base = path to {IE_ID}, e.g. D:/data/IE00KG02
    output_base = path to {IE_ID}_output, e.g. D:/data/IE00KG02_output
    """
    output_base = input_base.parent / f"{input_base.name}_output"
    output_base.mkdir(parents=True, exist_ok=True)

    checkpoints = load_checkpoints(checkpoint_file)
    doc_files = collect_doc_files(input_base, volume_filter)
    if not doc_files:
        logger.info(f"No .doc/.docx files under {input_base}/source/")
        return 0, 0

    to_convert = []
    for doc in doc_files:
        doc_path_str = str(doc)
        rtf_file = doc_to_rtf_path(doc, input_base, output_base)
        if doc_path_str not in checkpoints:
            if not rtf_file.exists() or rtf_file.stat().st_size == 0:
                to_convert.append(doc)
            else:
                save_checkpoint(checkpoint_file, doc_path_str)
                checkpoints.add(doc_path_str)

    if not to_convert:
        logger.info(f"All files already converted for {input_base.name}")
        return 0, 0

    logger.info("Starting Microsoft Word...")
    try:
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        word_app.Options.ConfirmConversions = False
        word_app.Options.DoNotPromptForConvert = True
        try:
            word_app.Options.SaveInterval = 0
        except Exception:
            pass
        try:
            word_app.Options.WarnBeforeSavingPrintingSendingMarkup = False
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Could not start Microsoft Word: {e}")
        return 0, len(to_convert)

    success_count = 0
    failed_count = 0
    try:
        for doc_file in tqdm(to_convert, desc=f"Converting {input_base.name}"):
            output_file = doc_to_rtf_path(doc_file, input_base, output_base)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            if convert_with_word(word_app, doc_file, output_file, logger):
                if output_file.exists() and output_file.stat().st_size > 0:
                    save_checkpoint(checkpoint_file, str(doc_file))
                    success_count += 1
                    logger.info(f"✓ {doc_file.relative_to(input_base)} -> {output_file.relative_to(output_base)}")
                else:
                    logger.error(f"✗ Output empty or missing: {doc_file.name}")
                    failed_count += 1
            else:
                failed_count += 1
            time.sleep(0.1)
    except KeyboardInterrupt:
        logger.info("Process interrupted by user.")
    finally:
        try:
            word_app.Quit()
        except Exception:
            pass
    return success_count, failed_count


def main():
    parser = argparse.ArgumentParser(
        description="Convert DOC/DOCX to RTF. Input: {IE_ID}/toprocess/{IE_ID-VE_ID}/*.doc(x). Output: {IE_ID}_output/toprocess/{IE_ID-VE_ID}/*.rtf"
    )
    parser.add_argument("--base-dir", "-b", type=str, default=None,
                        help="Single IE_ID folder (e.g. D:\\data\\IE00KG02). Ignored if --bulk-dir is set.")
    parser.add_argument("--bulk-dir", type=str, default=None,
                        help="Bulk folder: process every direct subdirectory as an IE_ID folder.")
    parser.add_argument("--volume", "-v", type=str, default=None,
                        help="Only process this volume subfolder (e.g. IE00KG02-VE001).")
    parser.add_argument("--checkpoint", "-c", type=str, default=None,
                        help="Checkpoint file path (default: checkpoint_rtf.txt in each IE base dir)")
    parser.add_argument("--log", "-l", type=str, default=None,
                        help="Log file path (default: conversion_log.txt in first IE base dir or bulk-dir)")
    args = parser.parse_args()

    if args.bulk_dir:
        bulk_dir = Path(args.bulk_dir)
        if not bulk_dir.is_dir():
            print(f"Bulk directory does not exist: {bulk_dir}")
            return
        ie_folders = [p for p in bulk_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        if not ie_folders:
            print(f"No subdirectories found under {bulk_dir}")
            return
        log_file = Path(args.log) if args.log else bulk_dir / "conversion_log.txt"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger = setup_logging(log_file)
        logger.info("DOC to RTF Converter (bulk mode)")
        logger.info(f"Bulk directory: {bulk_dir}, IE folders: {[p.name for p in ie_folders]}")
        total_ok, total_fail = 0, 0
        for ie_path in ie_folders:
            checkpoint_file = Path(args.checkpoint) if args.checkpoint else ie_path / "checkpoint_rtf.txt"
            logger.info("=" * 60)
            logger.info(f"Processing IE: {ie_path.name}")
            ok, fail = run_conversion_for_ie(ie_path, checkpoint_file, log_file, args.volume, logger)
            total_ok += ok
            total_fail += fail
        logger.info("=" * 70)
        logger.info("BULK CONVERSION COMPLETE")
        logger.info(f"  Total converted: {total_ok}, failed: {total_fail}")
        logger.info(f"  Output: each {ie_path.name}_output/toprocess/{{IE_ID-VE_ID}}/*.rtf")
        return

    # Single IE mode
    base_dir = Path(args.base_dir) if args.base_dir else Path.cwd()
    if not base_dir.is_dir():
        print(f"Base directory does not exist: {base_dir}")
        return
    checkpoint_file = Path(args.checkpoint) if args.checkpoint else base_dir / "checkpoint_rtf.txt"
    log_file = Path(args.log) if args.log else base_dir / "conversion_log.txt"
    base_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(log_file)
    logger.info("DOC to RTF Converter (single IE)")
    logger.info(f"Input base: {base_dir}")
    logger.info(f"Output base: {base_dir.parent / f'{base_dir.name}_output'}")
    success_count, failed_count = run_conversion_for_ie(base_dir, checkpoint_file, log_file, args.volume, logger)
    logger.info("=" * 70)
    logger.info("CONVERSION COMPLETE!")
    logger.info(f"  Converted: {success_count}, Failed: {failed_count}")
    logger.info(f"  Output: {base_dir.name}_output/toprocess/{{IE_ID-VE_ID}}/*.rtf")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
