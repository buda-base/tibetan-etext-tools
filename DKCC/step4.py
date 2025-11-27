#!/usr/bin/env python3
"""
Script to organize files into the final IE3KG218 directory structure.

Creates:
  IE3KG218/
    archive/
      VE1ER12/   (contains XML files from W3KG218-step3_tei/IE3KG218-VE1ER12/)
      VE1ER13/
      ...
    sources/
      W3KG218-I3KG780/   (contains PDF files from W3KG218/W3KG218-I3KG780/)
      ...

This script copies files without regenerating them.
"""

import shutil
from pathlib import Path
from natsort import natsorted


def copy_archive_files(tei_dir, archive_dir):
    """
    Copy TEI XML files from W3KG218-step3_tei to IE3KG218/archive.
    
    Strips the 'IE3KG218-' prefix from folder names.
    E.g., W3KG218-step3_tei/IE3KG218-VE1ER12/ -> IE3KG218/archive/VE1ER12/
    
    Args:
        tei_dir: Path to W3KG218-step3_tei directory
        archive_dir: Path to IE3KG218/archive directory
    
    Returns:
        Tuple of (files_copied, folders_processed)
    """
    files_copied = 0
    folders_processed = 0
    
    # Get all subdirectories in tei_dir
    folders = natsorted([d for d in tei_dir.iterdir() if d.is_dir()])
    
    for folder in folders:
        folder_name = folder.name
        
        # Strip 'IE3KG218-' prefix if present
        if folder_name.startswith('IE3KG218-'):
            ve_name = folder_name[9:]  # Remove 'IE3KG218-' prefix
        else:
            ve_name = folder_name
        
        # Create destination folder
        dest_folder = archive_dir / ve_name
        dest_folder.mkdir(parents=True, exist_ok=True)
        
        # Copy all XML files
        xml_files = list(folder.glob('*.xml'))
        for xml_file in xml_files:
            dest_file = dest_folder / xml_file.name
            shutil.copy2(xml_file, dest_file)
            files_copied += 1
        
        folders_processed += 1
        print(f"  Copied {len(xml_files)} files to archive/{ve_name}/")
    
    return files_copied, folders_processed


def copy_source_files(pdf_dir, sources_dir):
    """
    Copy PDF source files from W3KG218 to IE3KG218/sources.
    
    Maintains the original folder structure.
    E.g., W3KG218/W3KG218-I3KG780/4-1-0.pdf -> IE3KG218/sources/W3KG218-I3KG780/4-1-0.pdf
    
    Args:
        pdf_dir: Path to W3KG218 directory
        sources_dir: Path to IE3KG218/sources directory
    
    Returns:
        Tuple of (files_copied, folders_processed)
    """
    files_copied = 0
    folders_processed = 0
    
    # Get all subdirectories in pdf_dir
    folders = natsorted([d for d in pdf_dir.iterdir() if d.is_dir()])
    
    for folder in folders:
        folder_name = folder.name
        
        # Create destination folder with same name
        dest_folder = sources_dir / folder_name
        dest_folder.mkdir(parents=True, exist_ok=True)
        
        # Copy all PDF files
        pdf_files = list(folder.glob('*.pdf'))
        for pdf_file in pdf_files:
            dest_file = dest_folder / pdf_file.name
            shutil.copy2(pdf_file, dest_file)
            files_copied += 1
        
        folders_processed += 1
        print(f"  Copied {len(pdf_files)} files to sources/{folder_name}/")
    
    return files_copied, folders_processed


def organize_files(tei_dir='W3KG218-step3_tei',
                   pdf_dir='W3KG218',
                   output_dir='IE3KG218'):
    """
    Organize files into the final IE3KG218 directory structure.
    
    Args:
        tei_dir: Path to W3KG218-step3_tei directory (default 'W3KG218-step3_tei')
        pdf_dir: Path to W3KG218 directory with PDF sources (default 'W3KG218')
        output_dir: Path to output directory (default 'IE3KG218')
    """
    tei_path = Path(tei_dir)
    pdf_path = Path(pdf_dir)
    output_path = Path(output_dir)
    
    # Validate input directories
    if not tei_path.exists():
        print(f"Error: TEI directory not found: {tei_dir}")
        return
    
    if not pdf_path.exists():
        print(f"Error: PDF directory not found: {pdf_dir}")
        return
    
    # Create output directory structure
    archive_path = output_path / 'archive'
    sources_path = output_path / 'sources'
    
    archive_path.mkdir(parents=True, exist_ok=True)
    sources_path.mkdir(parents=True, exist_ok=True)
    
    print(f"{'='*60}")
    print(f"Organizing files into {output_dir}/")
    print(f"{'='*60}")
    
    # Copy archive files (TEI XML)
    print(f"\nCopying TEI XML files from {tei_dir} to {output_dir}/archive/...")
    archive_files, archive_folders = copy_archive_files(tei_path, archive_path)
    
    # Copy source files (PDFs)
    print(f"\nCopying PDF source files from {pdf_dir} to {output_dir}/sources/...")
    source_files, source_folders = copy_source_files(pdf_path, sources_path)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Organization complete!")
    print(f"{'='*60}")
    print(f"\nArchive (TEI XML files):")
    print(f"  Folders processed: {archive_folders}")
    print(f"  Files copied: {archive_files}")
    print(f"\nSources (PDF files):")
    print(f"  Folders processed: {source_folders}")
    print(f"  Files copied: {source_files}")
    print(f"\nOutput directory: {output_path.absolute()}")
    print(f"  archive/  - {archive_folders} VE folders with {archive_files} XML files")
    print(f"  sources/  - {source_folders} folders with {source_files} PDF files")
    print(f"{'='*60}")


if __name__ == "__main__":
    organize_files()

