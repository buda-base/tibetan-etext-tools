#!/usr/bin/env python3
"""
File Sorter Script
Traverses all folders and organizes files into an output directory 
based on their extensions.
"""

import os
import shutil
from pathlib import Path
from collections import defaultdict


def organize_files_by_extension(source_dir=None, output_dir=None, operation="copy"):
    """
    Traverse all folders recursively and organize files into an output directory
    based on their extensions.
    
    Args:
        source_dir (str): Path to the source directory to scan.
        output_dir (str): Path to the output directory where organized files will be stored.
        operation (str): "copy" to copy files, "move" to move files.
    """
    
    # Use current directory if not specified
    if source_dir is None:
        source_dir = os.getcwd()
    
    source_path = Path(source_dir)
    
    # Validate source directory exists
    if not source_path.is_dir():
        print(f"Error: '{source_dir}' is not a valid directory.")
        return
    
    # Create output directory if not specified
    if output_dir is None:
        output_dir = source_path / "ORGANIZED_FILES"
    
    output_path = Path(output_dir)
    
    # Create output directory
    try:
        output_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"Error creating output directory: {e}")
        return
    
    print(f"Source directory: {source_path}")
    print(f"Output directory: {output_path}")
    print(f"Operation mode: {operation.upper()}\n")
    print("Scanning all folders and files...\n")
    
    # Dictionary to store file extensions and their full paths
    file_stats = defaultdict(list)
    
    # Traverse all folders recursively
    try:
        for file_path in source_path.rglob("*"):
            # Only process files, skip directories
            if file_path.is_file():
                # Skip files in the output directory
                if output_path in file_path.parents or output_path == file_path.parent:
                    continue
                
                # Get file extension (without the dot)
                extension = file_path.suffix.lstrip('.').lower()
                
                # Handle files without extensions
                if not extension:
                    extension = "no_extension"
                
                file_stats[extension].append(file_path)
        
        if not file_stats:
            print("No files found in the directory structure.")
            return
        
        # Create folders and organize files
        print("Organizing files...\n")
        total_processed = 0
        
        for extension, files in sorted(file_stats.items()):
            # Create folder name based on extension
            folder_name = extension.upper()
            extension_folder = output_path / folder_name
            
            # Create extension folder if it doesn't exist
            extension_folder.mkdir(exist_ok=True)
            print(f"Created folder: {folder_name}/ ({len(files)} file(s))")
            
            # Copy or move files to the extension folder
            for file_path in files:
                try:
                    dest_path = extension_folder / file_path.name
                    
                    # Handle duplicate filenames
                    counter = 1
                    original_stem = file_path.stem
                    while dest_path.exists():
                        new_name = f"{original_stem}_{counter}{file_path.suffix}"
                        dest_path = extension_folder / new_name
                        counter += 1
                    
                    # Copy or move the file
                    if operation.lower() == "move":
                        shutil.move(str(file_path), str(dest_path))
                    else:  # Default to copy
                        shutil.copy2(str(file_path), str(dest_path))
                    
                    total_processed += 1
                    
                    # Show relative path for better readability
                    try:
                        relative_source = file_path.relative_to(source_path)
                    except ValueError:
                        relative_source = file_path
                    
                    print(f"  {operation.upper()}: {relative_source} → {folder_name}/")
                
                except Exception as e:
                    print(f"  Error processing {file_path.name}: {e}")
        
        # Print summary
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        print(f"Total files organized: {total_processed}")
        print(f"Total extension folders created: {len(file_stats)}\n")
        
        print("Extension breakdown:")
        for extension in sorted(file_stats.keys()):
            count = len(file_stats[extension])
            print(f"  ✓ {extension.upper()}: {count} file(s)")
        
        print(f"\nOutput location: {output_path}")
        print("\nFiles have been successfully organized!")
    
    except PermissionError as e:
        print(f"Error: Permission denied - {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    import sys
    
    print("╔════════════════════════════════════════════════════╗")
    print("║   FILE SORTER BY EXTENSION (CENTRALIZED OUTPUT)    ║")
    print("╚════════════════════════════════════════════════════╝\n")
    
    # Get directory from command line argument or use current directory
    if len(sys.argv) > 1:
        source_directory = sys.argv[1]
    else:
        source_directory = os.getcwd()
    
    # Get custom output directory if provided
    output_directory = None
    if len(sys.argv) > 2:
        output_directory = sys.argv[2]
    
    print(f"Source directory: {source_directory}\n")
    
    if output_directory:
        print(f"Output directory: {output_directory}\n")
    else:
        print(f"Output directory: {source_directory}/ORGANIZED_FILES\n")
    
    # Ask user for operation mode
    print("Choose operation mode:")
    print("  1. COPY files (keep originals)")
    print("  2. MOVE files (remove from source)")
    
    operation_choice = input("\nEnter your choice (1 or 2): ").strip()
    
    if operation_choice == "2":
        operation_mode = "move"
        confirm = input("\n⚠️  WARNING: This will MOVE files from source. Continue? (yes/no): ").strip().lower()
        if confirm != "yes":
            print("Operation cancelled.")
            sys.exit(0)
    else:
        operation_mode = "copy"
    
    # Execute the organization
    organize_files_by_extension(source_directory, output_directory, operation_mode)