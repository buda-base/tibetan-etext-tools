#!/usr/bin/env python3
"""
Script to normalize Unicode in all txt files from W3KG218-etext0 folder.
First simplifies font size markup, then applies normalize_unicode function.
Saves results to W3KG218-step1_normalize/.
"""

import os
from pathlib import Path
from normalization import normalize_unicode
from step1_fs import simplify_font_sizes


def process_files():
    """Process all txt files in W3KG218-etext0 and save normalized versions."""
    
    # Define paths relative to script location
    script_dir = Path(__file__).parent.parent
    source_dir = script_dir / "W3KG218-step0"
    output_dir = script_dir / "W3KG218-step1_normalize"
    
    # Check if source directory exists
    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        return
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(exist_ok=True)
    
    # Counter for processed files
    processed_count = 0
    error_count = 0
    
    # Iterate through all subdirectories and txt files
    for txt_file in source_dir.rglob("*.txt"):
        try:
            # Calculate relative path from source_dir
            rel_path = txt_file.relative_to(source_dir)
            
            # Create corresponding output path
            output_file = output_dir / rel_path
            
            # Create parent directories if they don't exist
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Read input file
            with open(txt_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # First simplify font size markup
            simplified_content = simplify_font_sizes(content)
            
            # Then apply normalization
            normalized_content = normalize_unicode(simplified_content)
            
            # Write output file
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(normalized_content)
            
            processed_count += 1
            if processed_count % 100 == 0:
                print(f"Processed: {processed_count} files...")
            
        except Exception as e:
            error_count += 1
            print(f"Error processing {txt_file}: {e}")
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Processing complete!")
    print(f"Successfully processed: {processed_count} files")
    print(f"Errors: {error_count} files")
    print(f"Output directory: {output_dir}")
    print(f"{'='*60}")


if __name__ == "__main__":
    process_files()
