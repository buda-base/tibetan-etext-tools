#!/usr/bin/env python3
"""
Find Dedris corruption patterns and short heads in converted TEI XML files.

Scans XML under archive/ (or --input-dir), detects:
- ་.་ (tsheg + full stop + tsheg)
- Comma before Tibetan: ,ོ ,གས ,ི ,ན etc.
- Curly braces { } in body text
- Isolated . between Tibetan characters
- Short heads: <hi rend="head"> with single char or 1-2 chars without shad

Output: report (corruption_audit.txt) and optionally CSV.
"""

import re
import argparse
import csv
from pathlib import Path
from collections import defaultdict

# Tibetan tsheg and full stop
TSEG = '\u0F0B'  # ་
SHAD = '\u0F0D'  # །
# Tibetan block for "between Tibetan" patterns (inner part of [...])
TIBETAN_INNER = r'\u0F00-\u0FFF'

# Corruption patterns: (name, regex_pattern)
CORRUPTION_PATTERNS = [
    ('tsheg_dot_tsheg', re.compile(r'་\.་')),
    ('comma_o', re.compile(r',ོ')),
    ('comma_tibetan', re.compile(r',[' + TIBETAN_INNER + r']')),  # , followed by any Tibetan
    ('curly_brace', re.compile(r'[{}]')),
    # Isolated full stop between Tibetan (single . surrounded by Tibetan or tsheg)
    ('isolated_dot', re.compile(r'(?:[' + TIBETAN_INNER + r']|་)\.(?:[' + TIBETAN_INNER + r']|་)')),
    # Dot as Dedris: . followed by Tibetan vowel (e.g. .ེ .ོ)
    ('dot_vowel', re.compile(r'\.[\u0F71-\u0F84]')),
    # Tibetan followed by dot (e.g. འ. མེ.)
    ('tibetan_dot', re.compile(r'[' + TIBETAN_INNER + r']\.')),
    # Digit 0 + tsheg in Tibetan context
    ('zero_tsheg', re.compile(r'0་')),
    # Digit 0 between Tibetan (e.g. གཅིག་0་)
    ('tibetan_zero', re.compile(r'[' + TIBETAN_INNER + r']0')),
]

# Short head: <hi rend="head">content</hi> where content is 1-2 chars (or dash) and no shad
HI_HEAD_RE = re.compile(r'<hi\s+rend=["\']head["\']\s*>([^<]{1,2})</hi>')
SHAD_CHAR = '\u0F0D'


def extract_body(content: str) -> str:
    """Extract body content between <body...> and </body>."""
    match = re.search(r'<body[^>]*>(.*?)</body>', content, re.DOTALL)
    return match.group(1) if match else ''


def find_corruptions_in_text(text: str) -> list:
    """Return list of (pattern_name, match_text, start_pos) for body text."""
    findings = []
    for name, pattern in CORRUPTION_PATTERNS:
        for m in pattern.finditer(text):
            findings.append((name, m.group(0), m.start()))
    return findings


def find_short_heads_in_text(text: str) -> list:
    """Return list of (match_full, content) for short head tags (1-2 char, no shad)."""
    findings = []
    for m in HI_HEAD_RE.finditer(text):
        content = m.group(1)
        if SHAD_CHAR not in content:  # no shad = not a real heading
            findings.append((m.group(0), content))
    return findings


def scan_file(xml_path: Path) -> tuple:
    """
    Scan one XML file. Returns (corruption_list, short_head_list).
    corruption_list: [(pattern_name, match_text, context_snippet)]
    short_head_list: [(full_tag, content)]
    """
    try:
        content = xml_path.read_text(encoding='utf-8')
    except Exception as e:
        return ([('_error', str(e), '')], [])
    body = extract_body(content)
    if not body:
        return ([], [])

    corruptions = []
    for name, match_text, pos in find_corruptions_in_text(body):
        start = max(0, pos - 25)
        end = min(len(body), pos + len(match_text) + 25)
        context = body[start:end].replace('\n', ' ')
        corruptions.append((name, match_text, context))

    short_heads = find_short_heads_in_text(body)
    return (corruptions, short_heads)


def main():
    parser = argparse.ArgumentParser(description='Find Dedris corruptions and short heads in TEI XML.')
    parser.add_argument('--input-dir', type=Path, default=None,
                        help='Root directory containing archive/ with XML files (e.g. rtf/IE1KG4884/IE1KG4884_output)')
    parser.add_argument('--output', '-o', type=Path, default=Path('corruption_audit.txt'),
                        help='Output report path')
    parser.add_argument('--csv', type=Path, default=None, help='Optional CSV output (file, pattern, context)')
    parser.add_argument('--short-heads', action='store_true', default=True, help='Include short head detection')
    parser.add_argument('--no-short-heads', action='store_false', dest='short_heads')
    args = parser.parse_args()

    if args.input_dir is None:
        script_dir = Path(__file__).parent
        args.input_dir = script_dir.parent / 'rtf' / 'IE1KG4884' / 'IE1KG4884_output'
    archive = args.input_dir / 'archive'
    if not archive.exists():
        archive = args.input_dir
    xml_files = list(archive.rglob('*.xml'))

    by_file = defaultdict(lambda: {'corruptions': [], 'short_heads': []})
    for xml_path in sorted(xml_files):
        rel = xml_path.relative_to(args.input_dir) if args.input_dir in xml_path.parents else xml_path.name
        corruptions, short_heads = scan_file(xml_path)
        if corruptions:
            by_file[str(rel)]['corruptions'] = corruptions
        if args.short_heads and short_heads:
            by_file[str(rel)]['short_heads'] = short_heads

    # Report
    lines = [
        'Dedris corruption and short head audit',
        '======================================',
        f'Scanned {len(xml_files)} XML files under {archive}',
        f'Files with issues: {len(by_file)}',
        '',
    ]
    for rel in sorted(by_file.keys()):
        data = by_file[rel]
        lines.append(f'\n--- {rel} ---')
        if data['corruptions']:
            lines.append('Corruptions:')
            for name, match_text, context in data['corruptions']:
                if name == '_error':
                    lines.append(f'  Error: {match_text}')
                else:
                    lines.append(f'  [{name}] "{match_text}" -> {context[:60]}...')
        if data['short_heads']:
            lines.append('Short heads:')
            for full_tag, content in data['short_heads']:
                lines.append(f'  {full_tag!r} (content: {content!r})')

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Wrote {args.output}')

    if args.csv:
        rows = []
        for rel in sorted(by_file.keys()):
            data = by_file[rel]
            for name, match_text, context in data['corruptions']:
                if name != '_error':
                    rows.append((rel, name, match_text, context[:200]))
            for full_tag, content in data['short_heads']:
                rows.append((rel, 'short_head', content, full_tag))
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, 'w', encoding='utf-8', newline='') as f:
            w = csv.writer(f)
            w.writerow(['file', 'pattern', 'match_or_content', 'context'])
            w.writerows(rows)
        print(f'Wrote {args.csv}')


if __name__ == '__main__':
    main()
