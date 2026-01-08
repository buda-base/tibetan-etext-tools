#!/usr/bin/env python3
"""
RTF Command Issue Detection Script

This script scans converted XML files to detect RTF commands and spurious text
that should be removed from the output.

Usage:
    python check_rtf_issues.py [--input-dir rtf/] [--output report.txt] [--verbose]
"""

import sys
import re
import argparse
from pathlib import Path
from collections import defaultdict
from typing import List, Tuple, Dict

# RTF command patterns to detect
RTF_COMMAND_PATTERNS = [
    # Page number commands
    (r'PAGE\s+\*\s+MERGEFORMAT\s+\d+', 'PAGE * MERGEFORMAT'),
    (r'NUMPAGES\s+\*\s+MERGEFORMAT', 'NUMPAGES * MERGEFORMAT'),
    (r'PAGE\s+OF\s+NUMPAGES', 'PAGE OF NUMPAGES'),
    
    # Date/time commands
    (r'DATE\s+\*\s+MERGEFORMAT', 'DATE * MERGEFORMAT'),
    (r'TIME\s+\*\s+MERGEFORMAT', 'TIME * MERGEFORMAT'),
    
    # Reference commands
    (r'REF\s+\w+\s+\*\s+MERGEFORMAT', 'REF * MERGEFORMAT'),
    
    # Other common RTF field codes
    (r'SEQ\s+\w+', 'SEQ field'),
    (r'STYLEREF\s+\d+', 'STYLEREF'),
    (r'TOC\s+\\', 'TOC field'),
    
    # General MERGEFORMAT pattern
    (r'\w+\s+\*\s+MERGEFORMAT', 'MERGEFORMAT field'),
]

# Spurious text patterns
# Spurious text patterns
SPURIOUS_PATTERNS = [
    (r'Got these', 'Spurious "Got these" text'),
    # Semicolon patterns - one, two, or three
    (r'<lb/>\s*;', '<lb/> followed by single semicolon'),
    (r'<lb/>\s*;;', '<lb/> followed by two semicolons'),
    (r'<lb/>\s*;;;', '<lb/> followed by three semicolons'),
    (r'<lb/>\s*;{4,}', '<lb/> followed by four or more semicolons'),
    # Standalone semicolons (not part of Tibetan text)
    (r'(?<![\u0F00-\u0FFF])\s*;\s*(?![\u0F00-\u0FFF])', 'Standalone semicolon'),
    # <lb/> followed by single letter (like 'p', 'r', etc.)
    (r'<lb/>\s*([a-zA-Z])(?:\s|$)', '<lb/> followed by single letter'),
    # Multiple line breaks with semicolons
    (r'<lb/>\s*<lb/>\s*;+', 'Multiple line breaks with semicolons'),
    # <lb/> followed by non-Tibetan text
    (r'<lb/>\s*([A-Za-z]{2,})(?:\s|$)', '<lb/> followed by ASCII text'),
]

# Non-Tibetan text patterns (lines with no Tibetan characters)
TIBETAN_RANGE = r'[\u0F00-\u0FFF]'
NON_TIBETAN_PATTERN = re.compile(rf'^[^{TIBETAN_RANGE}\s<>&;]*$', re.MULTILINE)


def find_rtf_commands(text: str, file_path: Path) -> List[Tuple[int, str, str, str]]:
    """Find RTF command patterns in text."""
    issues = []
    lines = text.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Check RTF command patterns
        for pattern, description in RTF_COMMAND_PATTERNS:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                # Get context (surrounding text, max 50 chars each side)
                start = max(0, match.start() - 20)
                end = min(len(line), match.end() + 20)
                context = line[start:end].strip()
                
                issues.append((
                    line_num,
                    description,
                    match.group(0),
                    context  # Add context
                ))
        
        # Check spurious patterns
        for pattern, description in SPURIOUS_PATTERNS:
            matches = re.finditer(pattern, line, re.IGNORECASE)
            for match in matches:
                # Get context
                start = max(0, match.start() - 20)
                end = min(len(line), match.end() + 20)
                context = line[start:end].strip()
                
                issues.append((
                    line_num,
                    description,
                    match.group(0),
                    context  # Add context
                ))
    
    return issues


def find_non_tibetan_lines(text: str, file_path: Path) -> List[Tuple[int, str]]:
    """Find lines that contain no Tibetan characters (potential RTF artifacts)."""
    issues = []
    lines = text.split('\n')
    
    for line_num, line in enumerate(lines, 1):
        # Skip XML tags and empty lines
        if not line.strip() or line.strip().startswith('<'):
            continue
        
        # Check if line has any Tibetan characters
        if not re.search(TIBETAN_RANGE, line):
            # Check if it's not just whitespace or XML
            stripped = line.strip()
            if stripped and not stripped.startswith('<') and not stripped.endswith('>'):
                # Check if it contains ASCII text (potential RTF command)
                if re.search(r'[A-Za-z]{3,}', stripped):
                    issues.append((
                        line_num,
                        stripped[:50]  # First 50 chars
                    ))
    
    return issues


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
        
        # Extract body content (between <body> and </body>)
        body_match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL)
        if not body_match:
            return result
        
        body_text = body_match.group(1)
        
        # Find RTF commands (now returns 4-tuples with context)
        rtf_issues = find_rtf_commands(body_text, xml_path)
        result['rtf_commands'] = rtf_issues
        
        # Find non-Tibetan lines
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
    
    # Find all XML files in archive directories
    xml_files = list(input_dir.glob("**/archive/**/*.xml"))
    
    if not xml_files:
        # Fallback: find all XML files and filter for archive directories
        all_xml = list(input_dir.rglob("*.xml"))
        xml_files = [f for f in all_xml if "archive" in f.parts]
    
    # Filter by IE_ID if specified
    if ie_id_filter:
        # Filter files to only include those from the specified collection
        # Path structure: rtf/{IE_ID}/{IE_ID}_output/archive/...
        filtered_files = []
        for xml_file in xml_files:
            # Check if the file path contains the IE_ID
            parts = xml_file.parts
            # Find the IE_ID in the path (should be in the path before _output)
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
            
            # Count by type
            for _, issue_type, _ in file_result['rtf_commands']:
                results['issues_by_type'][issue_type] += 1
    
    return results


def print_report(results: Dict, output_file: Path = None):
    """Print or save a detailed report."""
    output_lines = []
    
    # Summary
    output_lines.append("=" * 80)
    output_lines.append("RTF Command Issue Detection Report")
    output_lines.append("=" * 80)
    output_lines.append("")
    output_lines.append(f"Total XML files scanned: {results['total_files']}")
    output_lines.append(f"Files with issues: {results['files_with_issues']}")
    output_lines.append(f"Total RTF commands found: {results['total_rtf_commands']}")
    output_lines.append(f"Total non-Tibetan lines: {results['total_non_tibetan_lines']}")
    output_lines.append("")
    
    # Issues by type
    if results['issues_by_type']:
        output_lines.append("Issues by Type:")
        output_lines.append("-" * 80)
        for issue_type, count in sorted(results['issues_by_type'].items(), key=lambda x: -x[1]):
            output_lines.append(f"  {issue_type}: {count}")
        output_lines.append("")
    
    # Detailed file results
    output_lines.append("=" * 80)
    output_lines.append("Detailed Results")
    output_lines.append("=" * 80)
    output_lines.append("")
    
    for file_result in results['file_results']:
        if not file_result['has_issues']:
            continue
        
        output_lines.append(f"\nFile: {file_result['file']}")
        output_lines.append("-" * 80)
        
         # RTF commands
        if file_result['rtf_commands']:
            output_lines.append("RTF Commands Found:")
            for issue in file_result['rtf_commands']:
                if len(issue) == 4:  # Has context
                    line_num, issue_type, match, context = issue
                    output_lines.append(f"  Line {line_num}: {issue_type}")
                    output_lines.append(f"    Match: {match}")
                    output_lines.append(f"    Context: ...{context}...")
                else:  # Old format without context
                    line_num, issue_type, match = issue
                    output_lines.append(f"  Line {line_num}: {issue_type}")
                    output_lines.append(f"    Match: {match}")
        
        # Non-Tibetan lines
        if file_result['has_issues']:
            results['files_with_issues'] += 1
            results['total_rtf_commands'] += len(file_result['rtf_commands'])
            results['total_non_tibetan_lines'] += len(file_result['non_tibetan_lines'])
                    
            # Count by type
            for issue in file_result['rtf_commands']:
                issue_type = issue[1]  # Second element is the issue type
                results['issues_by_type'][issue_type] += 1
        
        if 'error' in file_result:
            output_lines.append(f"  ERROR: {file_result['error']}")
    
    report_text = "\n".join(output_lines)
    
    # Print to console
    print(report_text)
    
    # Save to file if specified
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(report_text)
        print(f"\nReport saved to: {output_file}")


def main():
    parser = argparse.ArgumentParser(
        description='Detect RTF command issues in converted XML files'
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
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        print(f"Error: Input directory not found: {args.input_dir}")
        sys.exit(1)
    
    # Scan files
    results = scan_collection(args.input_dir, verbose=args.verbose, ie_id_filter=args.ie_id)
    
    # Print report
    print_report(results, args.output)
    
    # Exit code based on findings
    if results['files_with_issues'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()