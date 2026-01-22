#!/usr/bin/env python3
"""
RTF Command Issue Detection and Fix Script

This script scans converted XML files to detect RTF commands and spurious text.
If issues are found, it will ask if you want to fix them.

Usage:
    python check_rtf_issues.py [--input-dir rtf/] [--ie-id IE23636] [--output report.txt] [--verbose]
"""

import sys
import re
import argparse
import shutil
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict

# Import detection patterns and functions from the detector module
try:
    from rtf_issue_detector import (
        TIBETAN_RANGE,
        find_rtf_commands,
        find_non_tibetan_lines
    )
except ImportError:
    print("Error: Could not import from rtf_issue_detector.py")
    print("Make sure rtf_issue_detector.py is in the same directory")
    sys.exit(1)

# Import cleaning functions from the cleaner module
try:
    from rtf_cleaner import (
        clean_rtf_commands,
        clean_spurious_text,
        clean_non_tibetan_lines,
        get_cleaner
    )
except ImportError:
    print("Error: Could not import from rtf_cleaner.py")
    print("Make sure rtf_cleaner.py is in the same directory")
    sys.exit(1)


def fix_xml_file(xml_path: Path) -> Dict:
    """
    Fix RTF issues in a single XML file.
    Writes fixed content directly back to the original file in archive/ folder.
    """
    result = {
        'file': str(xml_path),
        'rtf_commands_removed': 0,
        'spurious_text_removed': 0,
        'non_tibetan_lines_removed': 0,
        'total_fixes': 0,
        'error': None
    }
    
    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        body_match = re.search(r'(<body[^>]*>)(.*?)(</body>)', content, re.DOTALL)
        if not body_match:
            return result
        
        header = body_match.group(1)
        body_text = body_match.group(2)
        footer = body_match.group(3)
        
        # Use the cleaner module to fix all issues
        cleaned_body, rtf_count = clean_rtf_commands(body_text)
        result['rtf_commands_removed'] = rtf_count
        
        cleaned_body, spurious_count = clean_spurious_text(cleaned_body)
        result['spurious_text_removed'] = spurious_count
        
        cleaned_body, non_tibetan_count = clean_non_tibetan_lines(cleaned_body)
        result['non_tibetan_lines_removed'] = non_tibetan_count
        
        result['total_fixes'] = rtf_count + spurious_count + non_tibetan_count
        
        if result['total_fixes'] == 0:
            return result
        
        # Reconstruct and write fixed content directly back to original file
        cleaned_content = content[:body_match.start()] + header + cleaned_body + footer + content[body_match.end():]
        
        with open(xml_path, 'w', encoding='utf-8') as f:
            f.write(cleaned_content)
        
    except Exception as e:
        result['error'] = str(e)
    
    return result


def scan_xml_file(xml_path: Path) -> Dict:
    """Scan a single XML file for RTF issues."""
    result = {
        'file': str(xml_path),
        'rtf_commands': [],
        'non_tibetan_lines': [],
        'has_issues': False
    }
    
    try:
        with open(xml_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL)
        if not body_match:
            return result
        
        body_text = body_match.group(1)
        
        rtf_issues = find_rtf_commands(body_text, xml_path)
        result['rtf_commands'] = rtf_issues
        
        non_tibetan = find_non_tibetan_lines(body_text, xml_path)
        result['non_tibetan_lines'] = non_tibetan
        
        result['has_issues'] = len(rtf_issues) > 0 or len(non_tibetan) > 0
        
    except Exception as e:
        result['error'] = str(e)
        result['has_issues'] = True
    
    return result


def scan_collection(input_dir: Path, verbose: bool = False, ie_id_filter: str = None) -> Dict:
    """Scan all XML files in the input directory."""
    results = {
        'total_files': 0,
        'files_with_issues': 0,
        'total_rtf_commands': 0,
        'total_non_tibetan_lines': 0,
        'issues_by_type': defaultdict(int),
        'file_results': [],
        'skipped_collections': []
    }
    
    xml_files = list(input_dir.glob("**/archive/**/*.xml"))
    
    if not xml_files:
        all_xml = list(input_dir.rglob("*.xml"))
        xml_files = [f for f in all_xml if "archive" in f.parts]
    
    if ie_id_filter:
        filtered_files = []
        for xml_file in xml_files:
            parts = xml_file.parts
            for i, part in enumerate(parts):
                if part == ie_id_filter and i + 1 < len(parts) and parts[i + 1] == f"{ie_id_filter}_output":
                    filtered_files.append(xml_file)
                    break
        xml_files = filtered_files
        
        if not xml_files:
            print(f"Error: No XML files found for collection {ie_id_filter}")
            print(f"  Expected path: {input_dir}/{ie_id_filter}/{ie_id_filter}_output/archive/")
            return results
    
    results['total_files'] = len(xml_files)
    
    if verbose:
        collection_info = f" for collection {ie_id_filter}" if ie_id_filter else ""
        print(f"Scanning {len(xml_files)} XML files{collection_info}...")
    
    for xml_file in xml_files:
        if verbose:
            print(f"  Checking: {xml_file.name}")
        
        file_result = scan_xml_file(xml_file)
        results['file_results'].append(file_result)
        
        if file_result['has_issues']:
            results['files_with_issues'] += 1
            results['total_rtf_commands'] += len(file_result['rtf_commands'])
            results['total_non_tibetan_lines'] += len(file_result['non_tibetan_lines'])
            
            for issue in file_result['rtf_commands']:
                issue_type = issue[1]
                results['issues_by_type'][issue_type] += 1
    
    return results


def fix_collection(input_dir: Path, ie_id_filter: str = None, verbose: bool = False) -> Dict:
    """
    Fix RTF issues in all XML files with issues.
    Writes fixed content directly back to archive/ folder.
    """
    results = {
        'total_files_fixed': 0,
        'total_rtf_commands_removed': 0,
        'total_spurious_text_removed': 0,
        'total_non_tibetan_lines_removed': 0,
        'total_fixes': 0,
        'errors': []
    }
    
    # First scan to find files with issues
    scan_results = scan_collection(input_dir, verbose=False, ie_id_filter=ie_id_filter)
    
    if verbose:
        print(f"\nFixing {scan_results['files_with_issues']} files with issues...")
        print("Fixed files will be written directly to archive/ folder")
    
    for file_result in scan_results['file_results']:
        if not file_result['has_issues']:
            continue
        
        xml_path = Path(file_result['file'])
        if verbose:
            print(f"  Fixing: {xml_path.name}")
        
        fix_result = fix_xml_file(xml_path)
        
        if fix_result['error']:
            results['errors'].append(f"{xml_path.name}: {fix_result['error']}")
        else:
            results['total_files_fixed'] += 1
            results['total_rtf_commands_removed'] += fix_result['rtf_commands_removed']
            results['total_spurious_text_removed'] += fix_result['spurious_text_removed']
            results['total_non_tibetan_lines_removed'] += fix_result['non_tibetan_lines_removed']
            results['total_fixes'] += fix_result['total_fixes']
    
    return results


def print_report(results: Dict, output_file: Path = None):
    """Print or save a detailed report."""
    output_lines = []
    
    output_lines.append("=" * 80)
    output_lines.append("RTF Command Issue Detection Report")
    output_lines.append("=" * 80)
    output_lines.append("")
    output_lines.append(f"Total XML files scanned: {results['total_files']}")
    output_lines.append(f"Files with issues: {results['files_with_issues']}")
    output_lines.append(f"Total RTF commands found: {results['total_rtf_commands']}")
    output_lines.append(f"Total non-Tibetan lines: {results['total_non_tibetan_lines']}")
    output_lines.append("")
    
    if results['issues_by_type']:
        output_lines.append("Issues by Type:")
        output_lines.append("-" * 80)
        for issue_type, count in sorted(results['issues_by_type'].items(), key=lambda x: -x[1]):
            output_lines.append(f"  {issue_type}: {count}")
        output_lines.append("")
    
    output_lines.append("=" * 80)
    output_lines.append("Detailed Results")
    output_lines.append("=" * 80)
    output_lines.append("")
    
    for file_result in results['file_results']:
        if not file_result['has_issues']:
            continue
        
        output_lines.append(f"\nFile: {file_result['file']}")
        output_lines.append("-" * 80)
        
        if file_result['rtf_commands']:
            output_lines.append("RTF Commands Found:")
            for issue in file_result['rtf_commands']:
                if len(issue) == 4:
                    line_num, issue_type, match, context = issue
                    output_lines.append(f"  Line {line_num}: {issue_type}")
                    output_lines.append(f"    Match: {match}")
                    output_lines.append(f"    Context: ...{context}...")
                else:
                    line_num, issue_type, match = issue
                    output_lines.append(f"  Line {line_num}: {issue_type}")
                    output_lines.append(f"    Match: {match}")
        
        if file_result['non_tibetan_lines']:
            output_lines.append("Non-Tibetan Lines Found:")
            for line_num, content in file_result['non_tibetan_lines']:
                output_lines.append(f"  Line {line_num}: {content}")
        
        if 'error' in file_result:
            output_lines.append(f"  ERROR: {file_result['error']}")
    
    report_text = "\n".join(output_lines)
    print(report_text)
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"\nReport saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Detect and fix RTF command issues in converted XML files'
    )
    parser.add_argument(
        '--input-dir',
        type=Path,
        default=Path(__file__).parent.parent / "rtf",
        help='Input directory containing XML files (default: ../rtf)'
    )
    parser.add_argument(
        '--ie-id',
        type=str,
        help='Specific collection ID to check (e.g., IE23636). If not specified, checks all collections.'
    )
    parser.add_argument(
        '--output',
        type=Path,
        help='Output file for detailed report (optional)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Show progress while scanning'
    )
    parser.add_argument(
        '--no-fix',
        action='store_true',
        help='Only detect issues, do not prompt to fix'
    )
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        print(f"Error: Input directory not found: {args.input_dir}")
        sys.exit(1)
    
    # Scan files
    results = scan_collection(args.input_dir, verbose=args.verbose, ie_id_filter=args.ie_id)
    
    # Print report
    print_report(results, args.output)
    
    # Check if there are issues
    if results['files_with_issues'] == 0:
        print("\n" + "=" * 80)
        print("✓ Good to go! No RTF issues found.")
        print("=" * 80)
        sys.exit(0)
    
    # Ask if user wants to fix issues
    if not args.no_fix:
        print("\n" + "=" * 80)
        print(f"Found issues in {results['files_with_issues']} files.")
        print("=" * 80)
        
        response = input("\nDo you want to fix these issues? (y/n): ").strip().lower()
        
        if response == 'y':
            print("\nFixed files will be written directly to archive/ folder")
            print("(Original files will be replaced with fixed versions)")
            
            fix_results = fix_collection(
                args.input_dir,
                ie_id_filter=args.ie_id,
                verbose=args.verbose
            )
            
            print("\n" + "=" * 80)
            print("Fix Summary")
            print("=" * 80)
            print(f"Files fixed: {fix_results['total_files_fixed']}")
            print(f"RTF commands removed: {fix_results['total_rtf_commands_removed']}")
            print(f"Spurious text removed: {fix_results['total_spurious_text_removed']}")
            print(f"Non-Tibetan lines removed: {fix_results['total_non_tibetan_lines_removed']}")
            print(f"Total fixes: {fix_results['total_fixes']}")
            print(f"\nFixed files written to: archive/")
            
            if fix_results['errors']:
                print(f"\nErrors: {len(fix_results['errors'])}")
                for error in fix_results['errors'][:5]:
                    print(f"  - {error}")
            
            print("=" * 80)
        else:
            print("\nIssues not fixed. Run again with --no-fix to skip this prompt.")
    
    sys.exit(1 if results['files_with_issues'] > 0 else 0)


if __name__ == '__main__':
    main()
