#!/usr/bin/env python3
"""
Analyze font size profiles across all files in W3KG218-step1_normalize.
Groups files by their font size profiles and creates test samples.
Automatically classifies font sizes using heuristics.
"""

import re
import random
import shutil
from pathlib import Path
from collections import Counter, defaultdict


def extract_font_sizes(text):
    """Extract all unique font sizes from text."""
    pattern = r'<fs:(\d+)>'
    matches = re.findall(pattern, text)
    return tuple(sorted(set(int(fs) for fs in matches)))


def classify_font_sizes(text):
    """
    Classify font sizes in text into large, regular, and small categories.
    Only classifies sizes as 'large' on the first page (before second 'ZZZZ').
    
    Returns:
        dict: Mapping of font_size -> (classification, confidence, percentage)
    """
    
    # Split text at SECOND ZZZZ to separate first page from rest
    zzzz_positions = [m.start() for m in re.finditer('ZZZZ', text)]
    if len(zzzz_positions) >= 2:
        first_page = text[:zzzz_positions[1]]
    else:
        first_page = text
    
    # Extract all font sizes and their character counts
    pattern = r'<fs:(\d+)>([^<]*)'
    
    # Count characters for each font size on first page
    first_page_matches = re.findall(pattern, first_page)
    first_page_sizes = set()
    for fs, content in first_page_matches:
        char_count = len([c for c in content if ord(c) > 3840])
        if char_count > 0:
            first_page_sizes.add(int(fs))
    
    # Count characters for each font size in entire text
    all_matches = re.findall(pattern, text)
    if not all_matches:
        return {}
    
    size_counts = Counter()
    for fs, content in all_matches:
        char_count = len([c for c in content if ord(c) > 3840])
        if char_count > 0:
            size_counts[int(fs)] += char_count
    
    if not size_counts:
        return {}
    
    sizes = sorted(size_counts.keys())
    total_chars = sum(size_counts.values())
    size_percentages = {fs: (count / total_chars * 100) for fs, count in size_counts.items()}
    
    classifications = {}
    
    if len(sizes) == 1:
        classifications[sizes[0]] = ('regular', True, size_percentages[sizes[0]])
    
    elif len(sizes) == 2:
        fs1, fs2 = sizes
        pct1, pct2 = size_percentages[fs1], size_percentages[fs2]
        
        if pct1 > pct2:
            if fs2 > fs1:
                classifications[fs1] = ('regular', True, pct1)
                if fs2 in first_page_sizes:
                    classifications[fs2] = ('large', pct2 <= 15, pct2)
                else:
                    classifications[fs2] = ('regular', False, pct2)
            else:
                classifications[fs1] = ('regular', True, pct1)
                classifications[fs2] = ('small', True, pct2)
        else:
            if fs1 > fs2:
                classifications[fs2] = ('regular', True, pct2)
                if fs1 in first_page_sizes:
                    classifications[fs1] = ('large', pct1 <= 15, pct1)
                else:
                    classifications[fs1] = ('regular', False, pct1)
            else:
                classifications[fs2] = ('regular', True, pct2)
                classifications[fs1] = ('small', True, pct1)
    
    else:
        # Three or more sizes
        body_text_range = [fs for fs in sizes if 18 <= fs <= 26]
        
        if body_text_range:
            most_common_fs = max(body_text_range, key=lambda fs: size_counts[fs])
        else:
            most_common_fs = max(size_counts.items(), key=lambda x: x[1])[0]
        
        classifications[most_common_fs] = ('regular', True, size_percentages[most_common_fs])
        
        for fs in sizes:
            if fs == most_common_fs:
                continue
            
            pct = size_percentages[fs]
            
            if fs > most_common_fs:
                if fs in first_page_sizes:
                    classifications[fs] = ('large', pct <= 15, pct)
                else:
                    classifications[fs] = ('regular', False, pct)
            else:
                classifications[fs] = ('small', True, pct)
    
    # Post-processing: Ensure sizes with significant ratios can't both be regular
    regular_sizes = [fs for fs, (cls, _, _) in classifications.items() if cls == 'regular']
    
    if len(regular_sizes) > 1:
        regular_sizes_sorted = sorted(regular_sizes)
        for i in range(len(regular_sizes_sorted) - 1):
            smaller = regular_sizes_sorted[i]
            larger = regular_sizes_sorted[i + 1]
            ratio = larger / smaller
            
            if ratio >= 1.25:
                if size_counts[larger] >= size_counts[smaller]:
                    classifications[smaller] = ('small', True, size_percentages[smaller])
    
    # Validation: Ensure at least one size is classified as "regular"
    regular_sizes = [fs for fs, (cls, _, _) in classifications.items() if cls == 'regular']
    if not regular_sizes:
        candidates = [fs for fs in sizes if 20 <= fs <= 26]
        if candidates:
            best_regular = max(candidates, key=lambda fs: size_counts[fs])
        else:
            best_regular = max(size_counts.items(), key=lambda x: x[1])[0]
        
        old_class = classifications[best_regular][0]
        classifications[best_regular] = ('regular', True, size_percentages[best_regular])
    
    return classifications


def analyze_profiles(input_dir='../W3KG218-step1_normalize'):
    """
    Analyze all files and group them by font size profile.
    
    Returns:
        dict: profile_tuple -> (list of file paths, sample_text, classifications)
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        print(f"Error: Input directory not found: {input_dir}")
        return {}
    
    # Collect all txt files
    txt_files = list(input_path.rglob('*.txt'))
    print(f"Found {len(txt_files)} txt files to analyze")
    
    # Group files by profile
    profiles = defaultdict(list)
    profile_data = {}
    
    for txt_file in txt_files:
        try:
            with open(txt_file, 'r', encoding='utf-8') as f:
                text = f.read()
            
            font_sizes = extract_font_sizes(text)
            if font_sizes:  # Only add if there are font sizes
                profiles[font_sizes].append(txt_file)
                
                # Store sample text and classification for first file of each profile
                if font_sizes not in profile_data:
                    classifications = classify_font_sizes(text)
                    profile_data[font_sizes] = (text, classifications)
        
        except Exception as e:
            print(f"Error processing {txt_file}: {e}")
            continue
    
    # Combine profiles and profile_data
    result = {}
    for font_sizes, files in profiles.items():
        sample_text, classifications = profile_data[font_sizes]
        result[font_sizes] = (files, sample_text, classifications)
    
    return result


def create_test_samples(profiles, output_dir='DKCC/tests/font_profiles', samples_per_profile=2):
    """
    Create test samples for each profile.
    
    Args:
        profiles: dict of profile_tuple -> (list of file paths, sample_text, classifications)
        output_dir: where to save test samples
        samples_per_profile: number of random samples to take per profile
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Sort profiles by number of files (most common first)
    sorted_profiles = sorted(profiles.items(), key=lambda x: len(x[1][0]), reverse=True)
    
    print(f"\nFound {len(sorted_profiles)} unique font size profiles")
    print("="*60)
    
    profile_info = []
    
    for profile_idx, (font_sizes, (files, sample_text, classifications)) in enumerate(sorted_profiles, 1):
        profile_name = f"profile{profile_idx}"
        num_files = len(files)
        
        # Show classification summary
        cls_summary = []
        for fs in font_sizes:
            if fs in classifications:
                cls, confident, pct = classifications[fs]
                conf_mark = '' if confident else '?'
                cls_summary.append(f"{fs}:{cls}{conf_mark}")
        
        print(f"{profile_name}: {' '.join(cls_summary)} ({num_files} files)")
        
        # Take random samples
        num_samples = min(samples_per_profile, num_files)
        sample_files = random.sample(files, num_samples)
        
        for sample_idx, sample_file in enumerate(sample_files, 1):
            # Copy file to test directory
            output_file = output_path / f"{profile_name}_{sample_idx}.txt"
            shutil.copy2(sample_file, output_file)
            if sample_idx == 1:  # Only print first sample
                print(f"  Sample: {sample_file.name}")
        
        profile_info.append((profile_name, font_sizes, num_files, classifications))
    
    print("="*60)
    
    return profile_info


def generate_classification_csv(profile_info, output_file='DKCC/font_size_classification.csv'):
    """
    Generate a CSV with automatic classifications.
    
    Args:
        profile_info: list of (profile_name, font_sizes, num_files, classifications)
        output_file: path to output CSV file
    """
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("profile,font_size,classification,confidence,percentage,notes\n")
        
        for profile_name, font_sizes, num_files, classifications in profile_info:
            for fs in font_sizes:
                if fs in classifications:
                    cls, confident, pct = classifications[fs]
                    confidence_str = '' if confident else '?'
                    f.write(f"{profile_name},{fs},{cls},{confidence_str},{pct:.1f},\n")
                else:
                    # Shouldn't happen, but handle gracefully
                    f.write(f"{profile_name},{fs},?,?,0.0,ERROR: not classified\n")
    
    print(f"\nGenerated classification CSV: {output_file}")
    print("Review and edit classifications as needed (especially those marked with '?')")


if __name__ == "__main__":
    import sys
    
    # Set random seed for reproducibility
    random.seed(42)
    
    # Analyze profiles
    print("Analyzing font size profiles...")
    profiles = analyze_profiles()
    
    if not profiles:
        print("No profiles found")
        sys.exit(1)
    
    # Create test samples
    profile_info = create_test_samples(profiles)
    
    # Generate classification CSV with automatic classifications
    generate_classification_csv(profile_info)
    
    print("\nDone! Next steps:")
    print("1. Review files in DKCC/tests/font_profiles/")
    print("2. Review DKCC/font_size_classification.csv")
    print("3. Edit classifications marked with '?' or that seem incorrect")
    print("4. Pay special attention to profiles with uncertain classifications")
