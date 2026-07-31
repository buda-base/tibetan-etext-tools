#!/usr/bin/env python3
"""
Step 3: Parser Validation Script

This script compares BasicRTF parser output with Microsoft Word's text extraction
to validate parser accuracy.

Usage:
    python 3_validate_parser.py --file VE1ER619/01_cover.rtf
    python 3_validate_parser.py --ve VE1ER619
    python 3_validate_parser.py --all
"""

import os
import sys
import time
import argparse
import logging
from pathlib import Path

script_dir = Path(__file__).parent
sys.path.insert(0, str(script_dir))

from config import RTF_DIR, VALIDATION_LOG, ensure_directories
from basic_rtf import BasicRTF

try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False
    print("ERROR: pywin32 is required. Install with: pip install pywin32")


def setup_logging():
    """Configure logging with file and console output."""
    ensure_directories()
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(VALIDATION_LOG, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()


def get_text_from_word(rtf_path: str) -> str:
    """Open RTF in Word and extract text directly."""
    if not WIN32COM_AVAILABLE:
        raise RuntimeError("pywin32 is required for Word text extraction")
    
    word = None
    doc = None
    try:
        logger.info(f"   Opening Word application...")
        word = win32com.client.Dispatch("Word.Application")
        word.Visible = False
        
        logger.info(f"   Opening document: {rtf_path}")
        doc = word.Documents.Open(os.path.abspath(rtf_path))
        
        file_size_mb = os.path.getsize(rtf_path) / (1024 * 1024)
        wait_time = max(2, int(file_size_mb / 2))
        logger.info(f"   Waiting {wait_time}s for document to load ({file_size_mb:.1f} MB)...")
        time.sleep(wait_time)
        
        logger.info(f"   Extracting text from document...")
        text = doc.Content.Text
        
        return text
        
    finally:
        if doc:
            try:
                doc.Close(SaveChanges=False)
            except:
                pass
        if word:
            try:
                word.Quit()
            except:
                pass


def get_text_from_parser(rtf_path: str) -> str:
    """Parse RTF with BasicRTF and concatenate all streams."""
    parser = BasicRTF()
    parser.parse_file(rtf_path, show_progress=False)
    
    parts = []
    for s in parser.get_streams():
        # Skip header, footer, and picture streams (like the conversion script does)
        stream_type = s.get('type', '')
        if stream_type in ('header', 'footer', 'pict'):
            continue
        
        if 'text' in s:
            parts.append(s['text'])
        elif stream_type == 'par_break':
            parts.append('\n')
        elif stream_type == 'cell_break':
            parts.append('\n\x07')
        elif stream_type == 'row_break':
            pass
    
    return ''.join(parts)


def normalize_for_comparison(text: str) -> str:
    """Normalize text for comparison."""
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    lines = [line.rstrip() for line in text.split('\n')]
    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return '\n'.join(lines)


def normalize_text_only(text: str) -> str:
    """Extract only the text content, ignoring cell markers."""
    text = text.replace('\x07', '')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    while '\n\n' in text:
        text = text.replace('\n\n', '\n')
    return text.strip()


def compare_texts(word_text: str, parser_text: str) -> bool:
    """Compare two texts and show differences."""
    word_norm = normalize_for_comparison(word_text)
    parser_norm = normalize_for_comparison(parser_text)
    
    word_text_only = normalize_text_only(word_text)
    parser_text_only = normalize_text_only(parser_text)
    text_only_match = word_text_only == parser_text_only
    
    if word_norm == parser_norm:
        logger.info("\n" + "=" * 60)
        logger.info("[OK] SUCCESS: Parser output matches Word output exactly!")
        logger.info("=" * 60)
        return True
    
    logger.info("\n" + "=" * 60)
    logger.info("[FAIL] MISMATCH DETECTED")
    logger.info("=" * 60)
    
    min_len = min(len(word_norm), len(parser_norm))
    first_diff = -1
    for i in range(min_len):
        if word_norm[i] != parser_norm[i]:
            first_diff = i
            break
    if first_diff == -1:
        first_diff = min_len
    
    context_start = max(0, first_diff - 40)
    context_end = min(max(len(word_norm), len(parser_norm)), first_diff + 40)
    
    logger.info(f"\nFirst difference at character position {first_diff}:")
    logger.info(f"  Word:   ...{repr(word_norm[context_start:min(context_end, len(word_norm))])}...")
    logger.info(f"  Parser: ...{repr(parser_norm[context_start:min(context_end, len(parser_norm))])}...")
    
    logger.info(f"\nLength comparison:")
    logger.info(f"  Word output:   {len(word_norm)} characters")
    logger.info(f"  Parser output: {len(parser_norm)} characters")
    
    logger.info("\n" + "-" * 60)
    logger.info("TEXT-ONLY COMPARISON (ignoring cell markers):")
    logger.info("-" * 60)
    if text_only_match:
        logger.info("[OK] Text content matches! (Differences are only cell markers)")
        return True
    else:
        logger.info("[FAIL] Text content differs even without cell markers")
        logger.info(f"  Word text-only:   {len(word_text_only)} characters")
        logger.info(f"  Parser text-only: {len(parser_text_only)} characters")
    
    return False


def save_outputs(word_text: str, parser_text: str, base_path: str):
    """Save both outputs to files for manual inspection."""
    word_file = base_path.replace('.rtf', '-word-output.txt')
    parser_file = base_path.replace('.rtf', '-parser-output.txt')
    
    with open(word_file, 'w', encoding='utf-8') as f:
        f.write(word_text)
    logger.info(f"   Saved Word output to: {word_file}")
    
    with open(parser_file, 'w', encoding='utf-8') as f:
        f.write(parser_text)
    logger.info(f"   Saved Parser output to: {parser_file}")


def validate_single_file(rtf_path: Path) -> bool:
    """Validate a single RTF file."""
    logger.info("=" * 60)
    logger.info("RTF Parser vs Microsoft Word Comparison Test")
    logger.info("=" * 60)
    logger.info(f"\nTesting: {rtf_path}")
    logger.info(f"File size: {os.path.getsize(rtf_path):,} bytes")
    
    logger.info("\n[1/3] Getting text from Microsoft Word...")
    try:
        word_text = get_text_from_word(str(rtf_path))
        logger.info(f"   [OK] Got {len(word_text):,} characters from Word")
    except Exception as e:
        logger.error(f"   [ERROR] Error getting Word output: {e}")
        return False
    
    logger.info("\n[2/3] Getting text from BasicRTF parser...")
    try:
        parser_text = get_text_from_parser(str(rtf_path))
        logger.info(f"   [OK] Got {len(parser_text):,} characters from parser")
    except Exception as e:
        logger.error(f"   [ERROR] Error getting parser output: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    logger.info("\n[3/3] Saving outputs for inspection...")
    save_outputs(word_text, parser_text, str(rtf_path))
    
    logger.info("\nComparing outputs...")
    success = compare_texts(word_text, parser_text)
    
    return success


def validate_ve_folder(ve_id: str) -> tuple:
    """Validate all RTF files in a VE folder."""
    ve_folder = RTF_DIR / ve_id
    
    if not ve_folder.exists():
        logger.error(f"VE folder not found: {ve_folder}")
        return (0, 0, 0)
    
    # Skip temp files (start with ~$) and other non-RTF files
    rtf_files = [f for f in ve_folder.glob("*.rtf") if not f.name.startswith('~$')]
    
    if not rtf_files:
        logger.warning(f"No RTF files found in {ve_folder}")
        return (0, 0, 0)
    
    logger.info(f"Validating {len(rtf_files)} files in {ve_id}")
    
    success_count = 0
    failed_count = 0
    
    for rtf_path in sorted(rtf_files):
        if validate_single_file(rtf_path):
            success_count += 1
        else:
            failed_count += 1
    
    return (success_count, failed_count, len(rtf_files))


def validate_all() -> tuple:
    """Validate all RTF files."""
    if not RTF_DIR.exists():
        logger.error(f"RTF directory not found: {RTF_DIR}")
        return (0, 0, 0)
    
    total_success = 0
    total_failed = 0
    total_files = 0
    
    ve_folders = [f for f in RTF_DIR.iterdir() if f.is_dir() and f.name.startswith("VE")]
    
    if not ve_folders:
        logger.warning("No VE folders found")
        return (0, 0, 0)
    
    logger.info(f"Found {len(ve_folders)} VE folders to validate")
    
    for ve_folder in sorted(ve_folders):
        success, failed, total = validate_ve_folder(ve_folder.name)
        total_success += success
        total_failed += failed
        total_files += total
    
    return (total_success, total_failed, total_files)


def main():
    parser = argparse.ArgumentParser(description="Validate BasicRTF parser output against Microsoft Word")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--file", "-f", metavar="PATH", help="Validate a single file (path relative to rtf/)")
    group.add_argument("--ve", "-v", metavar="VE_ID", help="Validate all files in a VE folder")
    group.add_argument("--all", "-a", action="store_true", help="Validate all files")
    args = parser.parse_args()
    
    if not WIN32COM_AVAILABLE:
        logger.error("Cannot proceed without pywin32. Install with: pip install pywin32")
        sys.exit(1)
    
    if args.file:
        rtf_path = RTF_DIR / args.file
        if not rtf_path.exists():
            logger.error(f"File not found: {rtf_path}")
            sys.exit(1)
        success = validate_single_file(rtf_path)
        sys.exit(0 if success else 1)
        
    elif args.ve:
        success, failed, total = validate_ve_folder(args.ve)
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Total files:  {total}")
        logger.info(f"  Passed:       {success}")
        logger.info(f"  Failed:       {failed}")
        sys.exit(0 if failed == 0 else 1)
        
    elif args.all:
        success, failed, total = validate_all()
        logger.info("\n" + "=" * 60)
        logger.info("VALIDATION SUMMARY")
        logger.info("=" * 60)
        logger.info(f"  Total files:  {total}")
        logger.info(f"  Passed:       {success}")
        logger.info(f"  Failed:       {failed}")
        sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()


