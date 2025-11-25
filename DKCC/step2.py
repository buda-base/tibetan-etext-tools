#!/usr/bin/env python3
"""
Script to apply font size markup to files based on classification.
Reads font_size_classification.csv and applies <large> and <small> tags.
Processes files from W3KG218-step1_normalize to W3KG218-step2_fsmarkup.
"""

import re
import csv
from pathlib import Path
from collections import defaultdict


def load_classifications(csv_file='DKCC/font_size_classification.csv'):
    """
    Load font size classifications from CSV.
    
    Returns:
        dict: profile -> {font_size -> classification}
    """
    classifications = defaultdict(dict)
    
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            profile = row['profile']
            font_size = int(row['font_size'])
            classification = row['classification']
            classifications[profile][font_size] = classification
    
    return classifications


def get_font_profile(text):
    """
    Extract font sizes from text to determine profile.
    
    Returns:
        tuple: sorted tuple of font sizes
    """
    pattern = r'<fs:(\d+)>'
    matches = re.findall(pattern, text)
    return tuple(sorted(set(int(fs) for fs in matches)))


def find_profile_match(font_sizes, classifications):
    """
    Find matching profile for given font sizes.
    
    Returns:
        dict: {font_size -> classification} or None
    """
    # Try exact match first
    for profile, profile_classifications in classifications.items():
        profile_sizes = tuple(sorted(profile_classifications.keys()))
        if profile_sizes == font_sizes:
            return profile_classifications
    
    # If no exact match, return None (file will be skipped)
    return None


def append_missing_profiles(missing_profiles, csv_file='DKCC/font_size_classification.csv'):
    """
    Append missing profiles to the CSV file with pre-computed classifications.
    
    Args:
        missing_profiles: list of tuples (font_sizes, sample_text)
        csv_file: path to CSV file
        
    Returns:
        int: first profile number added
    """
    # Import here to avoid circular dependency
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from font_size_profiles import classify_font_sizes
    
    # Find the highest existing profile number
    max_profile_num = 0
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            profile = row['profile']
            if profile.startswith('profile'):
                num = int(profile.replace('profile', ''))
                max_profile_num = max(max_profile_num, num)
    
    first_new_profile = max_profile_num + 1
    
    # Append new profiles
    with open(csv_file, 'a', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        
        for i, (font_sizes, sample_text) in enumerate(missing_profiles, start=first_new_profile):
            profile_name = f'profile{i}'
            
            # Use classification heuristics
            classifications = classify_font_sizes(sample_text)
            
            for fs in sorted(font_sizes):
                if fs in classifications:
                    cls, confident, pct = classifications[fs]
                    confidence = '' if confident else '?'
                    writer.writerow([profile_name, fs, cls, confidence, f'{pct:.1f}', 'AUTO-ADDED'])
                else:
                    # Shouldn't happen, but handle gracefully
                    writer.writerow([profile_name, fs, '?', '?', '0.0', 'AUTO-ADDED: ERROR'])
    
    return first_new_profile


def apply_markup(text, size_classifications):
    """
    Apply <large> and <small> markup based on classifications.
    
    Args:
        text: Input text with <fs:xx> tags
        size_classifications: dict of {font_size -> classification}
        
    Returns:
        Text with <large>/<small> tags and <fs:xx> removed
    """
    
    # Replace <fs:xx> with temporary markers
    def replace_fs(match):
        fs = int(match.group(1))
        classification = size_classifications.get(fs, 'regular')
        
        if classification == 'large':
            return '<LARGE_START>'
        elif classification == 'small':
            return '<SMALL_START>'
        else:
            return '<REGULAR_START>'
    
    # Replace all <fs:xx> tags
    text = re.sub(r'<fs:(\d+)>', replace_fs, text)
    
    # Convert markers to actual tags with proper closing
    # Track current state
    result = []
    current_state = 'regular'
    
    # Split by markers
    parts = re.split(r'(<(?:LARGE|SMALL|REGULAR)_START>)', text)
    
    for part in parts:
        if part == '<LARGE_START>':
            if current_state == 'small':
                result.append('</small>')
            elif current_state == 'large':
                pass  # Already in large, don't close/reopen
            else:
                pass  # Coming from regular
            
            if current_state != 'large':
                result.append('<large>')
                current_state = 'large'
        
        elif part == '<SMALL_START>':
            if current_state == 'large':
                result.append('</large>')
            elif current_state == 'small':
                pass  # Already in small, don't close/reopen
            else:
                pass  # Coming from regular
            
            if current_state != 'small':
                result.append('<small>')
                current_state = 'small'
        
        elif part == '<REGULAR_START>':
            if current_state == 'large':
                result.append('</large>')
            elif current_state == 'small':
                result.append('</small>')
            current_state = 'regular'
        
        else:
            # Regular content
            result.append(part)
    
    # Close any open tags at the end
    if current_state == 'large':
        result.append('</large>')
    elif current_state == 'small':
        result.append('</small>')
    
    text = ''.join(result)
    
    # Normalize whitespace/boundaries around tags
    # Move opening tags AFTER spaces: <tag>space -> space<tag>
    text = re.sub(r'(<(?:large|small)>)(\s)', r'\2\1', text)
    
    # Move closing tags BEFORE spaces: space</tag> -> </tag>space
    text = re.sub(r'(\s)(</(?:large|small)>)', r'\2\1', text)
    
    # For ZZZZ (page breaks): move tags and close/reopen tags that span them
    # First move tags adjacent to ZZZZ
    text = re.sub(r'(<(?:large|small)>)(ZZZZ)', r'\2\1', text)
    text = re.sub(r'(ZZZZ)(</(?:large|small)>)', r'\2\1', text)
    
    # Then close and reopen tags that span ZZZZ boundaries
    parts = re.split(r'(ZZZZ)', text)
    result = []
    current_tag = None
    
    for part in parts:
        if part == 'ZZZZ':
            # Close tag before ZZZZ
            if current_tag:
                result.append(f'</{current_tag}>')
            result.append(part)
            # Reopen tag after ZZZZ
            if current_tag:
                result.append(f'<{current_tag}>')
        else:
            # Track tag state in this part
            i = 0
            while i < len(part):
                if part[i:i+7] == '<large>':
                    current_tag = 'large'
                    result.append('<large>')
                    i += 7
                elif part[i:i+7] == '<small>':
                    current_tag = 'small'
                    result.append('<small>')
                    i += 7
                elif part[i:i+8] == '</large>':
                    if current_tag == 'large':
                        current_tag = None
                    result.append('</large>')
                    i += 8
                elif part[i:i+8] == '</small>':
                    if current_tag == 'small':
                        current_tag = None
                    result.append('</small>')
                    i += 8
                else:
                    result.append(part[i])
                    i += 1
    
    text = ''.join(result)
    
    # Remove empty tags
    text = re.sub(r'<large></large>', '', text)
    text = re.sub(r'<small></small>', '', text)
    
    return text


def process_files(input_dir='../W3KG218-step1_normalize', 
                  output_dir='../W3KG218-step2_fsmarkup',
                  csv_file='font_size_classification.csv'):
    """Process all files and apply markup."""
    
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    
    if not input_path.exists():
        print(f"Error: Input directory not found: {input_dir}")
        return
    
    # Load classifications
    print("Loading font size classifications...")
    classifications = load_classifications(csv_file)
    print(f"Loaded {len(classifications)} profiles")
    
    # Create output directory
    output_path.mkdir(exist_ok=True)
    
    # First pass: scan for missing profiles
    txt_files = list(input_path.rglob('*.txt'))
    print(f"\nScanning {len(txt_files)} files for missing profiles...")
    
    missing_profiles = {}  # font_sizes -> sample_text
    
    for txt_file in txt_files:
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                text = f.read()
            
            font_sizes = get_font_profile(text)
            if not font_sizes:
                continue
            
            size_classifications = find_profile_match(font_sizes, classifications)
            if size_classifications is None and font_sizes not in missing_profiles:
                missing_profiles[font_sizes] = text
        
        except Exception as e:
            pass
    
    # Append missing profiles if any
    if missing_profiles:
        print(f"\nFound {len(missing_profiles)} missing profiles")
        first_new = append_missing_profiles(list(missing_profiles.items()), csv_file)
        print(f"Appended profiles starting at profile{first_new}")
        
        # Reload classifications
        classifications = load_classifications(csv_file)
        print(f"Reloaded classifications: {len(classifications)} profiles")
    
    # Second pass: process all files
    print(f"\nProcessing {len(txt_files)} files...")
    
    processed = 0
    skipped = 0
    errors = 0
    
    for txt_file in txt_files:
        try:
            # Read file
            with open(txt_file, 'r', encoding='utf-8') as f:
                text = f.read()
            
            # Get font profile
            font_sizes = get_font_profile(text)
            
            if not font_sizes:
                # No font sizes in file, just copy as is
                rel_path = txt_file.relative_to(input_path)
                output_file = output_path / rel_path
                output_file.parent.mkdir(parents=True, exist_ok=True)
                
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(text)
                
                processed += 1
                continue
            
            # Find matching profile
            size_classifications = find_profile_match(font_sizes, classifications)
            
            if size_classifications is None:
                print(f"Warning: No profile match for {txt_file.name} with sizes {font_sizes}")
                skipped += 1
                continue
            
            # Apply markup
            marked_text = apply_markup(text, size_classifications)
            
            # Write output
            rel_path = txt_file.relative_to(input_path)
            output_file = output_path / rel_path
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(marked_text)
            
            processed += 1
            
            if processed % 100 == 0:
                print(f"Processed {processed} files...")
        
        except Exception as e:
            print(f"Error processing {txt_file}: {e}")
            errors += 1
    
    # Summary
    print(f"\n{'='*60}")
    print(f"Processing complete!")
    print(f"Processed: {processed} files")
    print(f"Skipped: {skipped} files (no profile match)")
    print(f"Errors: {errors} files")
    print(f"Output directory: {output_path}")
    print(f"{'='*60}")


if __name__ == "__main__":
    process_files()
