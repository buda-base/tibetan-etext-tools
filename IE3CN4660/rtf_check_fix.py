#!/usr/bin/env python3
"""
RTF Command Issue Detection and Fix Script

This script scans converted XML files to detect RTF commands and spurious text.
If issues are found, it will ask if you want to fix them.

Usage:
    python rtf_check_fix.py [--input-dir rtf/] [--ie-id IE1KG4884] [--output report.txt] [--verbose]
    python rtf_check_fix.py --ie-id IE1KG4884 --workers 8
"""

import sys
import os
import re
import time
import argparse
import shutil
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from functools import partial
from typing import List, Tuple, Dict, Optional

# Per-file timeout (seconds); if a file takes longer, mark as timeout and skip (avoid stuck workers)
FILE_SCAN_TIMEOUT = 30
# Per-file timeout for fix phase (skip single file if it takes longer)
FILE_FIX_TIMEOUT = 60
# When waiting for next result, print spinner every N seconds
AS_COMPLETED_TIMEOUT = 2
# Give up after this many "still working" with no new result (stop burning CPU, skip remaining)
GIVE_UP_AFTER_STILL_WORKING = 5

# Unbuffer stdout so progress appears immediately
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(line_buffering=True)

# Single process + threads = same memory as convert; fewer workers = less CPU/heat (like convert)
DEFAULT_WORKERS = 4
# Spinner characters for "moving" progress while waiting
SPINNER = "|/-\\"

# Import detection patterns and functions from the detector module
try:
    from rtf_issue_detector import (
        TIBETAN_RANGE,
        DEDRIS_CORRUPTION_RE,
        find_rtf_commands,
        find_non_tibetan_lines,
        HI_HEAD_SHORT_DETECT_RE,
        SHAD
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
        clean_hi_wrappers,
        clean_dedris_corruption,
        clean_non_tibetan_lines,
        get_cleaner
    )
except ImportError:
    print("Error: Could not import from rtf_cleaner.py")
    print("Make sure rtf_cleaner.py is in the same directory")
    sys.exit(1)


def fix_xml_file(
    xml_path: Path,
    fix_from_source: bool = False,
    output_dir: Optional[Path] = None,
    rtf_dir: Optional[Path] = None,
) -> Dict:
    """
    Fix RTF issues in a single XML file.
    Writes fixed content directly back to the original file in archive/ folder.
    If fix_from_source is True and source RTF can be resolved, runs source-based correction.
    """
    result = {
        'file': str(xml_path),
        'rtf_commands_removed': 0,
        'spurious_text_removed': 0,
        'hi_wrappers_removed': 0,
        'dedris_corruption_fixes': 0,
        'source_correction_fixes': 0,
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
        
        cleaned_body, hi_wrappers_count = clean_hi_wrappers(cleaned_body)
        result['hi_wrappers_removed'] = hi_wrappers_count
        
        cleaned_body, corruption_count = clean_dedris_corruption(cleaned_body)
        result['dedris_corruption_fixes'] = corruption_count
        
        # Optional: source-based correction (re-convert runs with alternate fonts)
        if fix_from_source and output_dir is not None and rtf_dir is not None:
            try:
                from source_correction import (
                    get_src_path_from_xml,
                    resolve_source_path,
                    get_runs_from_rtf,
                    fix_corruption_from_source,
                )
                src_path_val = get_src_path_from_xml(content)
                if src_path_val:
                    source_path = resolve_source_path(xml_path, src_path_val, output_dir, rtf_dir)
                    if source_path and source_path.exists():
                        runs = get_runs_from_rtf(source_path)
                        if runs:
                            cleaned_body, src_count = fix_corruption_from_source(cleaned_body, runs)
                            result['source_correction_fixes'] = src_count
            except Exception:
                pass  # fall back to table-based only; source_correction_fixes stays 0
        
        cleaned_body, non_tibetan_count = clean_non_tibetan_lines(cleaned_body)
        result['non_tibetan_lines_removed'] = non_tibetan_count
        
        result['total_fixes'] = (
            rtf_count + spurious_count + hi_wrappers_count + corruption_count
            + result['source_correction_fixes'] + non_tibetan_count
        )
        
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
        
        # Also treat Dedris corruption and short heads as issues so they get fixed
        has_corruption = bool(DEDRIS_CORRUPTION_RE.search(body_text))
        has_short_head = any(SHAD not in m.group(1) for m in HI_HEAD_SHORT_DETECT_RE.finditer(body_text))
        
        result['has_issues'] = len(rtf_issues) > 0 or len(non_tibetan) > 0 or has_corruption or has_short_head
        
    except Exception as e:
        result['error'] = str(e)
        result['has_issues'] = True
    
    return result


def scan_collection(input_dir: Path, verbose: bool = False, ie_id_filter: str = None, workers: int = DEFAULT_WORKERS) -> Dict:
    """Scan all XML files in the input directory (parallel)."""
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
    
    total = len(xml_files)
    collection_info = f" for collection {ie_id_filter}" if ie_id_filter else ""
    print(f"Scanning {total} XML files with {workers} workers{collection_info}...", flush=True)
    print("  (one line per file as each completes - first results in a few seconds)", flush=True)
    
    file_results_ordered = [None] * total
    done = 0
    consecutive_still_working = 0
    # ThreadPoolExecutor = single process (same memory as convert), no 16x process overhead
    executor = ThreadPoolExecutor(max_workers=workers)
    try:
        future_to_item = {executor.submit(scan_xml_file, xml_file): (i, xml_file) for i, xml_file in enumerate(xml_files)}
        pending = set(future_to_item.keys())
        while pending:
            try:
                for future in as_completed(pending, timeout=AS_COMPLETED_TIMEOUT):
                    idx, xml_file = future_to_item[future]
                    pending.discard(future)
                    consecutive_still_working = 0  # got a result
                    try:
                        file_results_ordered[idx] = future.result(timeout=FILE_SCAN_TIMEOUT)
                    except FuturesTimeoutError:
                        file_results_ordered[idx] = {'file': str(xml_file), 'rtf_commands': [], 'non_tibetan_lines': [], 'has_issues': True, 'error': 'timeout'}
                    except Exception as e:
                        file_results_ordered[idx] = {'file': str(xml_file), 'rtf_commands': [], 'non_tibetan_lines': [], 'has_issues': True, 'error': str(e)}
                    done += 1
                    res = file_results_ordered[idx]
                    if res and res.get('error') == 'timeout':
                        print(f"  [{done}/{total}] {xml_file.name} - timeout (skipped)", flush=True)
                    elif res and res.get('error'):
                        print(f"  [{done}/{total}] {xml_file.name} - error: {str(res['error'])[:40]}...", flush=True)
                    elif res and res.get('has_issues'):
                        n_rtf = len(res.get('rtf_commands', []))
                        n_non = len(res.get('non_tibetan_lines', []))
                        print(f"  [{done}/{total}] {xml_file.name} - issues (rtf:{n_rtf} non-tib:{n_non})", flush=True)
                    else:
                        print(f"  [{done}/{total}] {xml_file.name} - ok", flush=True)
                    break
            except FuturesTimeoutError:
                consecutive_still_working += 1
                print(f"  ... still working ({done}/{total}) ...", flush=True)
                if consecutive_still_working >= GIVE_UP_AFTER_STILL_WORKING:
                    print(f"  Giving up after {GIVE_UP_AFTER_STILL_WORKING} timeouts with no progress; marking {len(pending)} files as skipped.", flush=True)
                    for f in pending:
                        idx, xml_file = future_to_item[f]
                        file_results_ordered[idx] = {'file': str(xml_file), 'rtf_commands': [], 'non_tibetan_lines': [], 'has_issues': True, 'error': 'skipped (no progress)'}
                    break
    finally:
        executor.shutdown(wait=False)
    
    results['file_results'] = file_results_ordered
    
    for file_result in results['file_results']:
        if file_result and file_result.get('has_issues'):
            results['files_with_issues'] += 1
            results['total_rtf_commands'] += len(file_result.get('rtf_commands', []))
            results['total_non_tibetan_lines'] += len(file_result.get('non_tibetan_lines', []))
            for issue in file_result.get('rtf_commands', []):
                issue_type = issue[1]
                results['issues_by_type'][issue_type] += 1
    
    return results


def fix_collection(
    input_dir: Path,
    ie_id_filter: str = None,
    verbose: bool = False,
    workers: int = DEFAULT_WORKERS,
    scan_results: Dict = None,
    fix_from_source: bool = False,
) -> Dict:
    """
    Fix RTF issues in all XML files with issues (parallel with per-file timeout and spinner).
    Writes fixed content directly back to archive/ folder.
    If scan_results is provided, skips re-scanning and uses it to get paths_to_fix.
    """
    results = {
        'total_files_fixed': 0,
        'total_rtf_commands_removed': 0,
        'total_spurious_text_removed': 0,
        'total_hi_wrappers_removed': 0,
        'total_dedris_corruption_fixes': 0,
        'total_source_correction_fixes': 0,
        'total_non_tibetan_lines_removed': 0,
        'total_fixes': 0,
        'errors': []
    }
    
    if scan_results is not None:
        paths_to_fix = [Path(fr['file']) for fr in scan_results['file_results'] if fr and fr.get('has_issues')]
    else:
        scan_results = scan_collection(input_dir, verbose=False, ie_id_filter=ie_id_filter, workers=workers)
        paths_to_fix = [Path(fr['file']) for fr in scan_results['file_results'] if fr and fr.get('has_issues')]
    if not paths_to_fix:
        return results
    
    # Resolve output_dir and rtf_dir for --fix-from-source (source RTF lookup)
    output_dir = input_dir
    rtf_dir = input_dir.parent
    fix_fn = partial(fix_xml_file, fix_from_source=fix_from_source, output_dir=output_dir, rtf_dir=rtf_dir)
    
    total_fix = len(paths_to_fix)
    print(f"\nFixing {total_fix} files with {workers} workers (per-file timeout {FILE_FIX_TIMEOUT}s)...")
    print("Fixed files will be written directly to archive/ folder\n")
    
    done_count = 0
    spinner_idx = 0
    # ProcessPoolExecutor: fix is CPU-bound (regex); threads are serialized by GIL and can appear stuck
    executor = ProcessPoolExecutor(max_workers=workers)
    try:
        future_to_path = {}
        future_to_submit_time = {}
        for p in paths_to_fix:
            f = executor.submit(fix_fn, p)
            future_to_path[f] = p
            future_to_submit_time[f] = time.monotonic()
        pending = set(future_to_path.keys())
        while pending:
            try:
                for future in as_completed(pending, timeout=AS_COMPLETED_TIMEOUT):
                    xml_path = future_to_path[future]
                    pending.discard(future)
                    done_count += 1
                    pct = round(100 * done_count / total_fix)
                    try:
                        fix_result = future.result(timeout=FILE_FIX_TIMEOUT)
                    except FuturesTimeoutError:
                        results['errors'].append(f"{xml_path.name}: timeout")
                        print(f"  [{done_count}/{total_fix}] ({pct}%) {xml_path.name} - skipped (timeout)", flush=True)
                        break
                    except Exception as e:
                        results['errors'].append(f"{xml_path.name}: {e}")
                        print(f"  [{done_count}/{total_fix}] ({pct}%) {xml_path.name} - exception: {str(e)[:40]}...", flush=True)
                        break
                    if fix_result.get('error'):
                        results['errors'].append(f"{xml_path.name}: {fix_result['error']}")
                        print(f"  [{done_count}/{total_fix}] ({pct}%) {xml_path.name} - error: {fix_result['error'][:40]}...", flush=True)
                    else:
                        results['total_files_fixed'] += 1
                        results['total_rtf_commands_removed'] += fix_result.get('rtf_commands_removed', 0)
                        results['total_spurious_text_removed'] += fix_result.get('spurious_text_removed', 0)
                        results['total_hi_wrappers_removed'] += fix_result.get('hi_wrappers_removed', 0)
                        results['total_dedris_corruption_fixes'] += fix_result.get('dedris_corruption_fixes', 0)
                        results['total_source_correction_fixes'] += fix_result.get('source_correction_fixes', 0)
                        results['total_non_tibetan_lines_removed'] += fix_result.get('non_tibetan_lines_removed', 0)
                        results['total_fixes'] += fix_result.get('total_fixes', 0)
                        n = fix_result.get('total_fixes', 0)
                        print(f"  [{done_count}/{total_fix}] ({pct}%) {xml_path.name} - done ({n} fixes)", flush=True)
                    break  # exit for-loop over as_completed, then while continues
            except FuturesTimeoutError:
                # No completion in time: check for per-file timeout, then show spinner
                now = time.monotonic()
                for f in list(pending):
                    if now - future_to_submit_time.get(f, now) > FILE_FIX_TIMEOUT:
                        f.cancel()
                        pending.discard(f)
                        xml_path = future_to_path[f]
                        done_count += 1
                        pct = round(100 * done_count / total_fix)
                        results['errors'].append(f"{xml_path.name}: timeout")
                        print(f"  [{done_count}/{total_fix}] ({pct}%) {xml_path.name} - skipped (timeout)", flush=True)
                pct = round(100 * done_count / total_fix)
                c = SPINNER[spinner_idx % len(SPINNER)]
                spinner_idx += 1
                print(f"\r  [{done_count}/{total_fix}] ({pct}%) fixing {c}    ", end="", flush=True)
    finally:
        executor.shutdown(wait=True)
    
    if done_count > 0 and spinner_idx > 0:
        print(flush=True)
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
        if not file_result or not file_result.get('has_issues'):
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
        help='Show extra detail in reports (per-file progress is always shown)'
    )
    parser.add_argument(
        '--no-fix',
        action='store_true',
        help='Only detect issues, do not prompt to fix'
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=DEFAULT_WORKERS,
        help=f'Number of parallel workers (default: {DEFAULT_WORKERS})'
    )
    parser.add_argument(
        '--fix-from-source',
        action='store_true',
        help='When fixing, also try to correct corruption using source RTF (resolve path, re-convert runs with alternate fonts)'
    )
    
    args = parser.parse_args()
    
    if not args.input_dir.exists():
        print(f"Error: Input directory not found: {args.input_dir}")
        sys.exit(1)
    
    # Scan files (parallel)
    results = scan_collection(args.input_dir, verbose=args.verbose, ie_id_filter=args.ie_id, workers=args.workers)
    
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
                verbose=args.verbose,
                workers=args.workers,
                scan_results=results,
                fix_from_source=args.fix_from_source,
            )
            
            print("\n" + "=" * 80)
            print("Fix Summary")
            print("=" * 80)
            print(f"Files fixed: {fix_results['total_files_fixed']}")
            print(f"RTF commands removed: {fix_results['total_rtf_commands_removed']}")
            print(f"Spurious text removed: {fix_results['total_spurious_text_removed']}")
            print(f"HI wrappers removed: {fix_results['total_hi_wrappers_removed']}")
            print(f"Dedris corruption fixes: {fix_results['total_dedris_corruption_fixes']}")
            print(f"Source correction fixes: {fix_results['total_source_correction_fixes']}")
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
