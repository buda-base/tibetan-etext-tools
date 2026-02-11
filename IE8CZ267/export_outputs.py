#!/usr/bin/env python3
"""
Export all output folders from RTF directory, removing '_output' suffix.

This script finds all {IE_ID}_output folders and copies them to an export
directory with the '_output' suffix removed.

Input structure:
    rtf/{IE_ID}/{IE_ID}_output/archive/{VE_ID}/*.xml
    rtf/{IE_ID}/{IE_ID}_output/sources/{VE_ID}/*.rtf

Output structure:
    export/{IE_ID}/archive/{VE_ID}/*.xml
    export/{IE_ID}/sources/{VE_ID}/*.rtf

Usage:
    # Export all outputs to default export directory
    python export_outputs.py
    
    # Export to custom directory
    python export_outputs.py --output-dir /path/to/export
    
    # Export specific collection
    python export_outputs.py --ie-id IE23636
    
    # Dry run (show what would be exported without copying)
    python export_outputs.py --dry-run
"""

import sys
import shutil
import logging
import argparse
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Ensure stdout is unbuffered
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

# Default directories
DEFAULT_INPUT_DIR = Path(__file__).parent.parent / "rtf"
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "export"


def find_output_folders(input_dir: Path) -> list:
    """
    Find all {IE_ID}_output folders in the input directory.
    
    Returns:
        List of (ie_id, output_folder_path) tuples
    """
    output_folders = []
    
    for ie_folder in input_dir.iterdir():
        if not ie_folder.is_dir():
            continue
        
        # Look for {IE_ID}_output folder
        output_folder = ie_folder / f"{ie_folder.name}_output"
        
        if output_folder.exists() and output_folder.is_dir():
            # Check if it has archive or sources subdirectories
            archive_dir = output_folder / "archive"
            sources_dir = output_folder / "sources"
            
            if archive_dir.exists() or sources_dir.exists():
                ie_id = ie_folder.name
                output_folders.append((ie_id, output_folder))
                logger.debug(f"Found output folder: {output_folder}")
    
    return sorted(output_folders, key=lambda x: x[0])


def count_files(directory: Path) -> dict:
    """Count XML and RTF files in a directory structure."""
    xml_count = len(list(directory.rglob("*.xml"))) if directory.exists() else 0
    rtf_count = len(list(directory.rglob("*.rtf"))) if directory.exists() else 0
    return {"xml": xml_count, "rtf": rtf_count}


def export_output(ie_id: str, source_output_dir: Path, dest_dir: Path, dry_run: bool = False) -> dict:
    """
    Export a single output folder to destination, removing '_output' suffix.
    
    Args:
        ie_id: The IE collection ID
        source_output_dir: Source {IE_ID}_output directory
        dest_dir: Destination directory (will create {IE_ID} subdirectory)
        dry_run: If True, only show what would be done without copying
        
    Returns:
        dict with export results
    """
    result = {
        "ie_id": ie_id,
        "success": False,
        "files_copied": 0,
        "errors": []
    }
    
    dest_collection_dir = dest_dir / ie_id
    
    try:
        # Count source files
        source_counts = count_files(source_output_dir)
        total_files = source_counts["xml"] + source_counts["rtf"]
        
        if total_files == 0:
            logger.warning(f"  {ie_id}: No files found in output folder, skipping")
            return result
        
        if dry_run:
            logger.info(f"  [DRY RUN] Would export {ie_id}:")
            logger.info(f"    Source: {source_output_dir}")
            logger.info(f"    Dest: {dest_collection_dir}")
            logger.info(f"    Files: {source_counts['xml']} XML, {source_counts['rtf']} RTF")
            result["success"] = True
            result["files_copied"] = total_files
            return result
        
        # Create destination directory
        dest_collection_dir.mkdir(parents=True, exist_ok=True)
        
        # Copy archive directory if it exists
        source_archive = source_output_dir / "archive"
        if source_archive.exists():
            dest_archive = dest_collection_dir / "archive"
            logger.info(f"  Copying archive: {source_archive} -> {dest_archive}")
            if dest_archive.exists():
                shutil.rmtree(dest_archive)
            shutil.copytree(source_archive, dest_archive)
            result["files_copied"] += source_counts["xml"]
        
        # Copy sources directory if it exists
        source_sources = source_output_dir / "sources"
        if source_sources.exists():
            dest_sources = dest_collection_dir / "sources"
            logger.info(f"  Copying sources: {source_sources} -> {dest_sources}")
            if dest_sources.exists():
                shutil.rmtree(dest_sources)
            shutil.copytree(source_sources, dest_sources)
            result["files_copied"] += source_counts["rtf"]
        
        result["success"] = True
        logger.info(f"  ✓ {ie_id}: Exported {result['files_copied']} files")
        
    except Exception as e:
        error_msg = f"Error exporting {ie_id}: {str(e)}"
        logger.error(f"  ✗ {error_msg}")
        result["errors"].append(error_msg)
    
    return result


def export_all_outputs(input_dir: Path, output_dir: Path, ie_filter: str = None, dry_run: bool = False):
    """
    Export all output folders from input directory to output directory.
    
    Args:
        input_dir: Directory containing IE collections with _output folders
        output_dir: Destination directory for exports
        ie_filter: Optional IE ID to filter to specific collection
        dry_run: If True, only show what would be done without copying
    """
    logger.info("=" * 70)
    logger.info("EXPORT OUTPUTS (Remove '_output' suffix)")
    logger.info("=" * 70)
    logger.info(f"Input directory: {input_dir}")
    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Mode: {'DRY RUN' if dry_run else 'EXPORT'}")
    
    if not input_dir.exists():
        logger.error(f"Input directory not found: {input_dir}")
        sys.exit(1)
    
    # Find all output folders
    output_folders = find_output_folders(input_dir)
    
    if ie_filter:
        output_folders = [(ie_id, path) for ie_id, path in output_folders if ie_id == ie_filter]
        if not output_folders:
            logger.error(f"Collection {ie_filter} not found or has no output folder")
            sys.exit(1)
    
    if not output_folders:
        logger.warning("No output folders found")
        return
    
    logger.info(f"Found {len(output_folders)} output folder(s) to export")
    logger.info("=" * 70)
    
    if not dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    total_files = 0
    
    for idx, (ie_id, source_output_dir) in enumerate(output_folders):
        logger.info(f"\n[{idx + 1}/{len(output_folders)}] Processing {ie_id}")
        
        result = export_output(ie_id, source_output_dir, output_dir, dry_run)
        results.append(result)
        total_files += result["files_copied"]
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    
    successful = [r for r in results if r["success"]]
    failed = [r for r in results if not r["success"]]
    
    for result in results:
        status = "✓" if result["success"] else "✗"
        logger.info(f"  {status} {result['ie_id']}: {result['files_copied']} files")
        if result["errors"]:
            for error in result["errors"]:
                logger.error(f"    - {error}")
    
    logger.info("-" * 70)
    logger.info(f"Total: {len(successful)} successful, {len(failed)} failed")
    logger.info(f"Total files exported: {total_files}")
    logger.info("=" * 70)
    
    if not dry_run:
        logger.info(f"\nExports saved to: {output_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Export all output folders, removing '_output' suffix"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Input directory containing IE collections (default: {DEFAULT_INPUT_DIR})"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for exports (default: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--ie-id",
        type=str,
        default=None,
        help="Export only this specific IE collection"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be exported without actually copying files"
    )
    
    args = parser.parse_args()
    
    export_all_outputs(args.input_dir, args.output_dir, args.ie_id, args.dry_run)


if __name__ == "__main__":
    main()

