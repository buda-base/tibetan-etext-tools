import time
import logging
import shutil
from pathlib import Path
import win32com.client
from tqdm import tqdm
import threading
import argparse

r'''
CONVERT .DOC FILES TO .DOCX FORMAT (content and layout preserved)

Input structure:  {IE_ID}/toprocess/{IE_ID-VE_ID}/*.doc
Output structure: {IE_ID}_output/toprocess/{IE_ID-VE_ID}/*.doc  (copy)
                  {IE_ID}_output/toprocess/{IE_ID-VE_ID}/*.docx (converted)

Single IE folder (base-dir = path to one IE_ID folder):
  python doc_to_docx\convert.py --base-dir "D:\data\IE2DB4568"

Bulk folder (process all IE_ID subfolders under the given path):
  python doc_to_docx\convert.py --bulk-dir "D:\data"

With a specific subfolder ({IE_ID-VE_ID}) in single mode:
  python doc_to_docx\convert.py --base-dir "D:\data\IE2DB4568" --volume "IE2DB4568-VE001"

With custom checkpoint and log:
  python doc_to_docx\convert.py --base-dir "D:\data\IE2DB4568" --checkpoint checkpoint.txt --log conversion.log
'''

# Word save-format constant for .docx (wdFormatDocumentDefault)
WD_FORMAT_DOCX = 16

# ============================================
# LOGGING SETUP
# ============================================
def setup_logging(log_file: Path) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    return logging.getLogger(__name__)


# ============================================
# CHECKPOINT HELPERS
# ============================================
_checkpoint_lock = threading.Lock()


def load_checkpoints(checkpoint_file: Path) -> set:
    if checkpoint_file.exists():
        try:
            content = checkpoint_file.read_text(encoding='utf-8').strip()
            if content:
                return set(content.split('\n'))
        except Exception as e:
            print(f"Error reading checkpoint file: {e}")
    return set()


def save_checkpoint(checkpoint_file: Path, file_path: str) -> None:
    with _checkpoint_lock:
        with open(checkpoint_file, 'a', encoding='utf-8') as f:
            f.write(f"{file_path}\n")


# ============================================
# PATH MAPPING
# ============================================
def map_output_path(doc_path: Path, input_base: Path, output_base: Path, suffix: str) -> Path:
    """
    Map an input path to the corresponding output path.
      Input:  {IE_ID}/toprocess/{IE_ID-VE_ID}/file.doc
      Output: {IE_ID}_output/toprocess/{IE_ID-VE_ID}/file{suffix}
    """
    try:
        rel = doc_path.relative_to(input_base)
    except ValueError:
        rel = Path(doc_path.name)
    return output_base / Path(*rel.parts).with_suffix(suffix)


# ============================================
# FILE COLLECTION
# ============================================
def collect_doc_files(input_base: Path, volume_filter: str | None) -> list[Path]:
    """
    Collect only .doc files (not .docx) under input_base/toprocess/{IE_ID-VE_ID}/.
    Skips Word lock files (~$...) and macOS resource forks (._...).
    """
    toprocess_dir = input_base / 'toprocess'
    if not toprocess_dir.is_dir():
        return []

    doc_files = []
    for f in toprocess_dir.rglob('*.doc'):
        # Skip already-docx, lock files, resource forks
        if f.suffix.lower() != '.doc':
            continue
        if f.name.startswith('~') or f.name.startswith('._'):
            continue
        if volume_filter:
            try:
                rel = f.relative_to(toprocess_dir)
                if rel.parts[0] != volume_filter:
                    continue
            except ValueError:
                continue
        doc_files.append(f)

    doc_files.sort()
    return doc_files


# ============================================
# SINGLE FILE CONVERSION
# ============================================
def convert_doc_to_docx(word_app, src: Path, dst: Path, logger: logging.Logger) -> bool:
    """
    Open src (.doc) with Word, save as dst (.docx) without any content changes.
    Returns True on success, False on failure.
    """
    doc = None
    try:
        doc = word_app.Documents.Open(
            str(src.resolve()),
            ConfirmConversions=False,
            ReadOnly=True,
            AddToRecentFiles=False,
            PasswordDocument='',
            PasswordTemplate='',
            Revert=False,
            WritePasswordDocument='',
            WritePasswordTemplate='',
            Format=0,
            Visible=False,
            OpenAndRepair=True,
            NoEncodingDialog=True,
        )

        try:
            doc.SaveAs2(
                str(dst.resolve()),
                FileFormat=WD_FORMAT_DOCX,
                AddToRecentFiles=False,
            )
        except AttributeError:
            # Older Word versions may not have SaveAs2
            doc.SaveAs(str(dst.resolve()), FileFormat=WD_FORMAT_DOCX)

        return True

    except Exception as e:
        logger.error(f"Word conversion failed for {src.name}: {e}")
        return False
    finally:
        if doc is not None:
            try:
                doc.Close(SaveChanges=False)
            except Exception:
                pass


# ============================================
# IE-LEVEL CONVERSION RUNNER
# ============================================
def run_conversion_for_ie(
    input_base: Path,
    checkpoint_file: Path,
    log_file: Path,
    volume_filter: str | None,
    logger: logging.Logger,
) -> tuple[int, int]:
    """
    Convert all .doc files under input_base to .docx in the output folder.
    Also copies the original .doc to the output folder.
    Returns (success_count, failed_count).
    """
    output_base = input_base.parent / f"{input_base.name}_output"
    output_base.mkdir(parents=True, exist_ok=True)

    checkpoints = load_checkpoints(checkpoint_file)
    doc_files = collect_doc_files(input_base, volume_filter)

    if not doc_files:
        logger.info(f"No .doc files found under {input_base}/toprocess/")
        return 0, 0

    to_convert = []
    for doc in doc_files:
        doc_path_str = str(doc)
        docx_out = map_output_path(doc, input_base, output_base, '.docx')
        if doc_path_str not in checkpoints:
            if not docx_out.exists() or docx_out.stat().st_size == 0:
                to_convert.append(doc)
            else:
                # Already done from a previous run — record in checkpoint
                save_checkpoint(checkpoint_file, doc_path_str)
                checkpoints.add(doc_path_str)

    if not to_convert:
        logger.info(f"All files already converted for {input_base.name}")
        return 0, 0

    logger.info(f"Files to convert: {len(to_convert)}")
    logger.info("Starting Microsoft Word...")

    try:
        word_app = win32com.client.Dispatch('Word.Application')
        word_app.Visible = False
        word_app.DisplayAlerts = 0
        word_app.Options.ConfirmConversions = False
        try:
            word_app.Options.DoNotPromptForConvert = True
        except Exception:
            pass
        try:
            word_app.Options.SaveInterval = 0
        except Exception:
            pass
    except Exception as e:
        logger.error(f"Could not start Microsoft Word: {e}")
        return 0, len(to_convert)

    success_count = 0
    failed_count = 0

    try:
        for doc_file in tqdm(to_convert, desc=f"Converting {input_base.name}"):
            docx_out = map_output_path(doc_file, input_base, output_base, '.docx')
            doc_copy = map_output_path(doc_file, input_base, output_base, '.doc')

            docx_out.parent.mkdir(parents=True, exist_ok=True)

            if convert_doc_to_docx(word_app, doc_file, docx_out, logger):
                if docx_out.exists() and docx_out.stat().st_size > 0:
                    # Copy original .doc to output alongside .docx
                    try:
                        shutil.copy2(doc_file, doc_copy)
                    except Exception as e:
                        logger.warning(f"Could not copy .doc to output: {e}")

                    save_checkpoint(checkpoint_file, str(doc_file))
                    success_count += 1
                    logger.info(
                        f"OK  {doc_file.relative_to(input_base)}"
                        f" -> {docx_out.relative_to(output_base)}"
                    )
                else:
                    logger.error(f"FAIL  Output empty or missing: {doc_file.name}")
                    failed_count += 1
            else:
                failed_count += 1

            time.sleep(0.05)

    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        try:
            word_app.Quit()
        except Exception:
            pass

    return success_count, failed_count


# ============================================
# MAIN
# ============================================
def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert .doc files to .docx (content preserved). "
            "Input: {IE_ID}/toprocess/{IE_ID-VE_ID}/*.doc  "
            "Output: {IE_ID}_output/toprocess/{IE_ID-VE_ID}/*.doc and *.docx"
        )
    )
    parser.add_argument(
        '--base-dir', '-b', type=str, default=None,
        help='Single IE_ID folder (e.g. D:\\data\\IE2DB4568). Ignored if --bulk-dir is set.',
    )
    parser.add_argument(
        '--bulk-dir', type=str, default=None,
        help='Bulk folder: process every direct subdirectory as an IE_ID folder.',
    )
    parser.add_argument(
        '--volume', '-v', type=str, default=None,
        help='Only process this subfolder under toprocess (e.g. IE2DB4568-VE001).',
    )
    parser.add_argument(
        '--checkpoint', '-c', type=str, default=None,
        help='Checkpoint file path (default: checkpoint_docx.txt in each IE base dir).',
    )
    parser.add_argument(
        '--log', '-l', type=str, default=None,
        help='Log file path (default: conversion_log_docx.txt in IE base dir or bulk-dir).',
    )
    args = parser.parse_args()

    # ---- BULK MODE ----
    if args.bulk_dir:
        bulk_dir = Path(args.bulk_dir)
        if not bulk_dir.is_dir():
            print(f"Bulk directory does not exist: {bulk_dir}")
            return

        ie_folders = sorted(
            p for p in bulk_dir.iterdir()
            if p.is_dir() and not p.name.startswith('.')
        )
        if not ie_folders:
            print(f"No subdirectories found under {bulk_dir}")
            return

        log_file = Path(args.log) if args.log else bulk_dir / 'conversion_log_docx.txt'
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logger = setup_logging(log_file)
        logger.info("DOC -> DOCX Converter (bulk mode)")
        logger.info(f"Bulk directory : {bulk_dir}")
        logger.info(f"IE folders     : {[p.name for p in ie_folders]}")

        total_ok, total_fail = 0, 0
        last_ie = ie_folders[-1]
        for ie_path in ie_folders:
            checkpoint_file = (
                Path(args.checkpoint) if args.checkpoint
                else ie_path / 'checkpoint_docx.txt'
            )
            logger.info('=' * 60)
            logger.info(f"Processing IE: {ie_path.name}")
            ok, fail = run_conversion_for_ie(ie_path, checkpoint_file, log_file, args.volume, logger)
            total_ok += ok
            total_fail += fail

        logger.info('=' * 70)
        logger.info("BULK CONVERSION COMPLETE")
        logger.info(f"  Total converted : {total_ok}")
        logger.info(f"  Total failed    : {total_fail}")
        logger.info(f"  Output pattern  : {{IE_ID}}_output/toprocess/{{IE_ID-VE_ID}}/*.doc and *.docx")
        return

    # ---- SINGLE IE MODE ----
    base_dir = Path(args.base_dir) if args.base_dir else Path.cwd()
    if not base_dir.is_dir():
        print(f"Base directory does not exist: {base_dir}")
        return

    checkpoint_file = (
        Path(args.checkpoint) if args.checkpoint
        else base_dir / 'checkpoint_docx.txt'
    )
    log_file = (
        Path(args.log) if args.log
        else base_dir / 'conversion_log_docx.txt'
    )
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging(log_file)
    logger.info("DOC -> DOCX Converter (single IE mode)")
    logger.info(f"Input base  : {base_dir}")
    logger.info(f"Output base : {base_dir.parent / f'{base_dir.name}_output'}")

    ok, fail = run_conversion_for_ie(base_dir, checkpoint_file, log_file, args.volume, logger)

    logger.info('=' * 70)
    logger.info("CONVERSION COMPLETE")
    logger.info(f"  Converted : {ok}")
    logger.info(f"  Failed    : {fail}")
    logger.info(f"  Output    : {base_dir.name}_output/toprocess/{{IE_ID-VE_ID}}/*.doc and *.docx")
    logger.info('=' * 70)


if __name__ == '__main__':
    main()
