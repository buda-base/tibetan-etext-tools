import re
import sys

# AI generated code
# 
# Two RTF format parsers:
# 1. Simple format - Dedris fonts without {\*\panose} (KAMA-001 style)
# 2. Complex format - ALL fonts have {\*\panose} (KAMA-003 style)

# Pre-compiled regex patterns for performance
_RE_UNICODE = re.compile(r'\\u(-?\d+)\??')
_RE_HEX_CHAR = re.compile(r"\\'([0-9a-fA-F]{2})")
_RE_FONT_ID = re.compile(r'\\f(\d+)')
_RE_FONT_SIZE = re.compile(r'\\fs(\d+)')
_RE_PAR = re.compile(r'\\par(?![a-zA-Z])')  # Match \par but not \pard, \paragraph etc.
_RE_CONTROL_WORD = re.compile(r'\\[a-zA-Z0-9]+\s?')
_RE_FONTTBL_ENTRY = re.compile(r'{\\f(\d+)[^{}]*(?:{[^{}]*}[^{}]*)*;}')
_RE_COLOR_RED = re.compile(r'\\red(\d+)')
_RE_COLOR_GREEN = re.compile(r'\\green(\d+)')
_RE_COLOR_BLUE = re.compile(r'\\blue(\d+)')


def detect_rtf_format(file_path: str) -> str:
    """
    Detect RTF format by checking if Dedris fonts have {\*\panose}.
    
    Args:
        file_path: Path to RTF file
        
    Returns:
        'complex' if Dedris fonts have panose, 'simple' otherwise
    """
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        header = f.read(100000)  # Read enough to get font table
    
    # Look for Dedris fonts with panose - indicates complex format
    # Pattern: Dedris font name followed by ; with panose before it
    if re.search(r'\\panose[^}]*\}Dedris', header):
        return 'complex'
    return 'simple'


def _strip_nested_groups(text: str) -> str:
    """
    Remove nested {...} groups from text (groups inside the outer braces).
    Used to strip {\*\panose ...} and {\*\falt ...} from font entries.
    
    Input like: {\f0\froman{\*\panose 123}Times New Roman;}
    Output: {\f0\fromanTimes New Roman;}
    """
    result = []
    level = 0
    i = 0
    # Skip the first character if it's an opening brace (outer brace)
    first_brace_skipped = False
    
    while i < len(text):
        c = text[i]
        if c == '{':
            if not first_brace_skipped:
                # Keep the first opening brace
                result.append(c)
                first_brace_skipped = True
            else:
                level += 1
        elif c == '}':
            if level > 0:
                level -= 1
            else:
                # Keep the final closing brace
                result.append(c)
        elif level == 0:
            result.append(c)
        i += 1
    return ''.join(result)


def _parse_font_table_simple(fonttbl_data: str) -> list:
    """
    Parse font table for simple RTF format.
    
    Simple Dedris fonts: {\f3\fnil\fcharset0 Dedris-a;}
    System fonts may have panose: {\f0\froman...\fprq2{\*\panose...}Times New Roman;}
    """
    fonts = []
    
    # Find each font entry
    brace_level = 0
    entry_start = -1
    
    for i, c in enumerate(fonttbl_data):
        if c == '{':
            if brace_level == 0:
                entry_start = i
            brace_level += 1
        elif c == '}':
            brace_level -= 1
            if brace_level == 0 and entry_start >= 0:
                entry = fonttbl_data[entry_start:i+1]
                
                # Extract font ID
                m = re.match(r'\{\\f(\d+)', entry)
                if m:
                    fid = int(m.group(1))
                    
                    # Strip nested groups (like {\*\panose...})
                    cleaned = _strip_nested_groups(entry)
                    
                    # Remove control words
                    cleaned = re.sub(r'\\[a-zA-Z]+\-?\d*\s?', '', cleaned)
                    
                    # Remove braces
                    cleaned = cleaned.replace('{', '').replace('}', '')
                    
                    # Get text before ;
                    if ';' in cleaned:
                        name = cleaned.split(';')[0].strip()
                    else:
                        name = cleaned.strip()
                    
                    if name:
                        fonts.append({"id": fid, "name": name})
                
                entry_start = -1
    
    return fonts


def _parse_font_table_complex(fonttbl_data: str) -> list:
    """
    Parse font table for complex RTF format.
    
    All fonts have panose: {\f45\fbidi \froman...\fprq2{\*\panose...}Dedris-vowa;}
    May also have {\*\falt ...} groups.
    """
    fonts = []
    
    # Find each font entry
    brace_level = 0
    entry_start = -1
    
    for i, c in enumerate(fonttbl_data):
        if c == '{':
            if brace_level == 0:
                entry_start = i
            brace_level += 1
        elif c == '}':
            brace_level -= 1
            if brace_level == 0 and entry_start >= 0:
                entry = fonttbl_data[entry_start:i+1]
                
                # Extract font ID (may have \flomajor etc prefix)
                m = re.search(r'\\f(\d+)', entry)
                if m:
                    fid = int(m.group(1))
                    
                    # Strip all nested groups ({\*\panose...}, {\*\falt...})
                    cleaned = _strip_nested_groups(entry)
                    
                    # Remove control words
                    cleaned = re.sub(r'\\[a-zA-Z]+\-?\d*\s?', '', cleaned)
                    
                    # Remove braces
                    cleaned = cleaned.replace('{', '').replace('}', '')
                    
                    # Get text before ;
                    if ';' in cleaned:
                        name = cleaned.split(';')[0].strip()
                    else:
                        name = cleaned.strip()
                    
                    if name:
                        fonts.append({"id": fid, "name": name})
                
                entry_start = -1
    
    return fonts


class BasicRTF:
    def __init__(self):
        self._fonts = []
        self._font_map = {}
        self._streams = []
        self._raw_data = ""
        self._colors = []
        self._show_progress = False
        self._format = None

    def _clean_text(self, text):
        """Clean text for storage, stripping RTF artifacts."""
        # For complex RTF format, strip leading single space (RTF artifact)
        # This fixes broken Tibetan like "མའ ི" -> "མའི"
        if self._format == 'complex' and text.startswith(' ') and not text.startswith('  '):
            text = text[1:]
        return text

    def _report_progress(self, current, total, message=""):
        """Report parsing progress to stderr."""
        if not self._show_progress:
            return
        percent = (current / total * 100) if total > 0 else 0
        bar_len = 40
        filled = int(bar_len * current / total) if total > 0 else 0
        bar = '█' * filled + '░' * (bar_len - filled)
        sys.stderr.write(f'\r  Parsing: [{bar}] {percent:5.1f}% {message}')
        sys.stderr.flush()
        if current >= total:
            sys.stderr.write('\n')

    def parse_file(self, file_path, show_progress=True):
        """
        Parse an RTF file, auto-detecting format.
        
        Args:
            file_path: Path to the RTF file
            show_progress: Whether to show progress bar (default: True)
        """
        self._fonts = []
        self._font_map = {}
        self._streams = []
        self._raw_data = ""
        self._show_progress = show_progress
        
        # Detect format
        self._format = detect_rtf_format(file_path)
        if show_progress:
            sys.stderr.write(f'  RTF format: {self._format}\n')
        
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            data = f.read()
        self._raw_data = data
        data_len = len(data)

        # Parse font table first with format-specific parser
        self._parse_font_table(data)

        font_id = 0
        font_size = 24  # default RTF size (half-points)
        stack = []
        text_parts = []  # Use list for O(1) appends
        i = 0
        char_start = 0
        char_end = 0

        special_keywords = {
            r'\footnote': 'footnote',
            r'\header': 'header',
            r'\footer': 'footer',
            r'\pict': 'pict'
        }

        # Skip these sections entirely
        skip_sections = [
            r'{\fonttbl', r'{\colortbl', r'{\stylesheet', r'{\info',
            r'{\listtable', r'{\listoverridetable', r'{\*\generator',
            r'{\*\rsidtbl', r'{\*\pgptbl', r'{\mmathPr',
            r'{\footer', r'{\header'  # Skip header/footer blocks
        ]

        # Progress tracking
        progress_interval = max(1, data_len // 100)  # Update every 1%
        last_progress = 0

        while i < data_len:
            # Report progress periodically
            if i - last_progress >= progress_interval:
                self._report_progress(i, data_len)
                last_progress = i
            
            c = data[i]
            
            # Skip known metadata sections
            skip = False
            for section in skip_sections:
                if data.startswith(section, i):
                    brace_level = 1
                    i += len(section)
                    while i < data_len and brace_level > 0:
                        if data[i] == '{':
                            brace_level += 1
                        elif data[i] == '}':
                            brace_level -= 1
                        i += 1
                    skip = True
                    break
            if skip:
                continue

            # Detect special blocks
            special_type = None
            if c == '\\':
                for kw, typ in special_keywords.items():
                    if data.startswith(kw, i):
                        # Check that keyword is complete (not followed by alphanumeric)
                        # e.g., \header should not match \headery
                        end_pos = i + len(kw)
                        if end_pos < data_len and data[end_pos].isalnum():
                            continue  # Not a complete keyword match
                        
                        # Find the opening brace for this block
                        j = end_pos
                        while j < data_len and data[j] in ' \n\r\t':
                            j += 1
                        if j < data_len and data[j] == '{':
                            # Start of special block
                            brace_level = 1
                            k = j + 1
                            while k < data_len and brace_level > 0:
                                if data[k] == '{':
                                    brace_level += 1
                                elif data[k] == '}':
                                    brace_level -= 1
                                k += 1
                            block_end = k
                            block_text = data[j+1:block_end-1]
                            self._streams.append({
                                "text": block_text,
                                "font": {
                                    "id": font_id,
                                    "name": self._font_map.get(font_id, {}).get("name", ""),
                                    "size": font_size // 2
                                },
                                "char_start": j,
                                "char_end": block_end,
                                "type": typ
                            })
                            i = block_end
                            special_type = typ
                            break
                        else:
                            # Not a group, just skip the keyword
                            i = j
                            special_type = typ
                            break
                if special_type:
                    continue

            # Handle groups starting with \* (ignore group)
            if c == '{' and i + 2 < data_len and data[i+1] == '\\' and data[i+2] == '*':
                # Find the end of this group (handle nested braces)
                brace_level = 1
                j = i + 3
                while j < data_len and brace_level > 0:
                    if data[j] == '{':
                        brace_level += 1
                    elif data[j] == '}':
                        brace_level -= 1
                    j += 1
                i = j
                continue

            if c == '{':
                stack.append((font_id, font_size))
                i += 1
            elif c == '}':
                if text_parts:
                    text = self._clean_text(''.join(text_parts))
                    if text.strip():
                        char_end = i
                        self._streams.append({
                            "text": text,
                            "font": {
                                "id": font_id,
                                "name": self._font_map.get(font_id, {}).get("name", ""),
                                "size": font_size // 2
                            },
                            "char_start": char_start,
                            "char_end": char_end
                        })
                    text_parts = []
                if stack:
                    font_id, font_size = stack.pop()
                i += 1
                char_start = i
            elif c == '\\':
                # Handle \uN? unicode characters - use match with position
                m = _RE_UNICODE.match(data, i)
                if m:
                    codepoint = int(m.group(1))
                    # RTF \uN is always a 16-bit signed integer
                    if codepoint < 0:
                        codepoint += 0x10000
                    try:
                        text_parts.append(chr(codepoint))
                    except Exception:
                        text_parts.append('?')
                    i = m.end()
                    continue
                # Handle \~ (non-breakable space)
                if data.startswith(r'\~', i):
                    text_parts.append('\u00A0')
                    i += 2
                    continue
                # Ignore \- (optional hyphen)
                if data.startswith(r'\-', i):
                    i += 2
                    continue
                # Handle \{ and \} (escaped braces - literal { and } in text)
                # IMPORTANT for Dedris fonts where } = སྔ (char 125)
                if data.startswith(r'\{', i):
                    text_parts.append('{')
                    i += 2
                    continue
                if data.startswith(r'\}', i):
                    text_parts.append('}')
                    i += 2
                    continue
                # Handle \\ (escaped backslash)
                if data.startswith(r'\\', i):
                    text_parts.append('\\')
                    i += 2
                    continue
                # Handle \'hh (hex character)
                m = _RE_HEX_CHAR.match(data, i)
                if m:
                    text_parts.append(bytes.fromhex(m.group(1)).decode('latin1'))
                    i = m.end()
                    continue
                # Font ID
                m = _RE_FONT_ID.match(data, i)
                if m:
                    if text_parts:
                        text = self._clean_text(''.join(text_parts))
                        if text.strip():
                            char_end = i
                            self._streams.append({
                                "text": text,
                                "font": {
                                    "id": font_id,
                                    "name": self._font_map.get(font_id, {}).get("name", ""),
                                    "size": font_size // 2
                                },
                                "char_start": char_start,
                                "char_end": char_end
                            })
                        text_parts = []
                    font_id = int(m.group(1))
                    i = m.end()
                    char_start = i
                    continue
                # Font size
                m = _RE_FONT_SIZE.match(data, i)
                if m:
                    if text_parts:
                        text = self._clean_text(''.join(text_parts))
                        if text.strip():
                            char_end = i
                            self._streams.append({
                                "text": text,
                                "font": {
                                    "id": font_id,
                                    "name": self._font_map.get(font_id, {}).get("name", ""),
                                    "size": font_size // 2
                                },
                                "char_start": char_start,
                                "char_end": char_end
                            })
                        text_parts = []
                    font_size = int(m.group(1))
                    i = m.end()
                    char_start = i
                    continue
                # Paragraph
                m = _RE_PAR.match(data, i)
                if m:
                    text_parts.append('\n')
                    i = m.end()
                    continue
                # Other control words - skip
                m = _RE_CONTROL_WORD.match(data, i)
                if m:
                    i = m.end()
                    continue
                i += 1
            else:
                text_parts.append(c)
                i += 1
        
        # Final text
        if text_parts:
            text = self._clean_text(''.join(text_parts))
            if text.strip():
                char_end = i
                self._streams.append({
                    "text": text,
                    "font": {
                        "id": font_id,
                        "name": self._font_map.get(font_id, {}).get("name", ""),
                        "size": font_size // 2
                    },
                    "char_start": char_start,
                    "char_end": char_end
                })
        
        # Final progress report
        self._report_progress(data_len, data_len, f"Done! {len(self._streams)} streams")

    def _parse_font_table(self, data: str):
        """Parse font table using format-specific parser."""
        # Find font table
        start = data.find(r'{\fonttbl')
        if start == -1:
            return
        
        # Find end of font table
        brace_level = 1
        i = start + 9
        while i < len(data) and brace_level > 0:
            if data[i] == '{':
                brace_level += 1
            elif data[i] == '}':
                brace_level -= 1
            i += 1
        
        fonttbl_data = data[start+9:i-1]
        
        # Use appropriate parser based on format
        if self._format == 'complex':
            fonts = _parse_font_table_complex(fonttbl_data)
        else:
            fonts = _parse_font_table_simple(fonttbl_data)
        
        self._fonts = fonts
        self._font_map = {f["id"]: f for f in fonts}

    def get_format(self) -> str:
        """Get detected RTF format ('simple' or 'complex')."""
        return self._format

    def get_streams(self):
        return self._streams

    def get_fonts(self):
        return self._fonts

    def get_colors(self):
        return self._colors

    def print_debug(self):
        for idx, s in enumerate(self._streams):
            raw = self._raw_data[s["char_start"]:s["char_end"]]
            print(f"Stream {idx}:")
            print("  Raw:", repr(raw))
            print("  Parsed:", s)
            print()
        if hasattr(self, "_colors") and self._colors:
            print("Color Table:")
            for idx, c in enumerate(self._colors):
                print(f"  {idx}: {c}")
