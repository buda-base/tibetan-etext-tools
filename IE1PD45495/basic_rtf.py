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
_RE_FONT_ID = re.compile(r'\\f(\d+)\s?')

# Note: In RTF, a space after a control word terminates it and is NOT content.
# We use \s? to consume that terminating space.
_RE_AFONT = re.compile(r'\\af(\d+)\s?')
_RE_CHARSET = re.compile(r'\\(loch|hich|dbch)(?![a-zA-Z])\s?')
_RE_DIRCTX = re.compile(r'\\(ltrch|rtlch)(?![a-zA-Z])\s?')
_RE_FONT_SIZE = re.compile(r'\\fs(\d+)\s?')
_RE_PAR = re.compile(r'\\par(?![a-zA-Z])\s?')  # Match \par but not \pard, \paragraph etc.
_RE_LINE = re.compile(r'\\line(?![a-zA-Z])\s?')  # Forced line break inside a paragraph
_RE_CELL = re.compile(r'\\cell(?![a-zA-Z])\s?')  # Table cell end
_RE_ROW = re.compile(r'\\row(?![a-zA-Z])\s?')  # Table row end
# Control word pattern: \letters followed by optional negative number parameter
# Examples: \par, \f0, \fs36, \trleft-210, \tblind-102
_RE_CONTROL_WORD = re.compile(r'\\[a-zA-Z]+-?\d*\s?')
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
        # Strip RTF source newlines - these are just line wrapping in the RTF file,
        # not actual text content. Only \par creates paragraph breaks.
        text = text.replace('\r', '').replace('\n', '')
        
        # NOTE: We no longer strip leading spaces here because:
        # 1. The regex patterns already consume terminating spaces after control words
        # 2. Leading spaces in the remaining text are intentional content
        # The old logic was breaking content like " ," (space before comma)
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

        # RTF font selection can come from \fN and also from \afN (ANSI/script font).
        # Some documents (incl. this one) rely on \afN to select the active font for the text run.
        font_size = 24  # default RTF size (half-points)
        charset = 'loch'   # loch/hich/dbch
        dirctx = 'ltrch'   # ltrch/rtlch
        eff = {
            'ltrch': {'loch': 0, 'hich': 0, 'dbch': 0},
            'rtlch': {'loch': 0, 'hich': 0, 'dbch': 0},
        }
        def get_fid():
            return eff[dirctx][charset]
        stack = []
        text_parts = []  # Use list for O(1) appends
        i = 0
        char_start = 0
        char_end = 0

        def flush_text(end_pos: int):
            """Flush buffered text into a stream (if non-empty after cleaning)."""
            nonlocal text_parts, char_start
            if not text_parts:
                char_start = end_pos
                return
            text = self._clean_text(''.join(text_parts))
            if text:
                self._streams.append({
                    "text": text,
                    "font": {
                        "id": get_fid(),
                        "name": self._font_map.get(get_fid(), {}).get("name", ""),
                        "size": font_size // 2
                    },
                    "char_start": char_start,
                    "char_end": end_pos
                })
            text_parts = []
            char_start = end_pos

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
                                    "id": get_fid(),
                                    "name": self._font_map.get(get_fid(), {}).get("name", ""),
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
                stack.append((font_size, charset, dirctx, {k: v.copy() for k, v in eff.items()}))
                i += 1
            elif c == '}':
                if text_parts:
                    text = self._clean_text(''.join(text_parts))
                    if text:
                        char_end = i
                        self._streams.append({
                            "text": text,
                            "font": {
                                "id": get_fid(),
                                "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                "size": font_size // 2
                            },
                            "char_start": char_start,
                            "char_end": char_end
                        })
                    text_parts = []
                if stack:
                    font_size, charset, dirctx, eff_snapshot = stack.pop()
                    eff = {k: v.copy() for k, v in eff_snapshot.items()}
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
                # Handle \{, \} and \\ (escaped control symbols).
                # In some RTFs (incl. Word/LibreOffice "complex" output), immediate formatting controls
                # like \hich\afN can appear *right after* the control symbol. LibreOffice applies that
                # formatting to the emitted symbol; so we mimic that by looking ahead and consuming
                # any immediate font/charset switches before emitting the symbol.
                handled_escaped = False
                for sym, out_ch in ((r'\{', '{'), (r'\}', '}'), (r'\\', '\\')):
                    if data.startswith(sym, i):
                        j = i + 2
                        saw_format = False

                        # If formatting switches follow immediately, flush current run first so
                        # the escaped symbol starts a new run under the new formatting.
                        while True:
                            m = _RE_DIRCTX.match(data, j)
                            if m:
                                if not saw_format and text_parts:
                                    text = self._clean_text(''.join(text_parts))
                                    if text:
                                        char_end = i
                                        self._streams.append({
                                            "text": text,
                                            "font": {
                                                "id": get_fid(),
                                                "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                                "size": font_size // 2
                                            },
                                            "char_start": char_start,
                                            "char_end": char_end
                                        })
                                    text_parts = []
                                saw_format = True
                                dirctx = m.group(1)
                                j = m.end()
                                continue

                            m = _RE_CHARSET.match(data, j)
                            if m:
                                if not saw_format and text_parts:
                                    text = self._clean_text(''.join(text_parts))
                                    if text:
                                        char_end = i
                                        self._streams.append({
                                            "text": text,
                                            "font": {
                                                "id": get_fid(),
                                                "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                                "size": font_size // 2
                                            },
                                            "char_start": char_start,
                                            "char_end": char_end
                                        })
                                    text_parts = []
                                saw_format = True
                                charset = m.group(1)
                                j = m.end()
                                continue

                            m = _RE_AFONT.match(data, j)
                            if m:
                                if not saw_format and text_parts:
                                    text = self._clean_text(''.join(text_parts))
                                    if text:
                                        char_end = i
                                        self._streams.append({
                                            "text": text,
                                            "font": {
                                                "id": get_fid(),
                                                "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                                "size": font_size // 2
                                            },
                                            "char_start": char_start,
                                            "char_end": char_end
                                        })
                                    text_parts = []
                                saw_format = True
                                eff[dirctx][charset] = int(m.group(1))
                                j = m.end()
                                continue

                            m = _RE_FONT_ID.match(data, j)
                            if m:
                                if not saw_format and text_parts:
                                    text = self._clean_text(''.join(text_parts))
                                    if text:
                                        char_end = i
                                        self._streams.append({
                                            "text": text,
                                            "font": {
                                                "id": get_fid(),
                                                "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                                "size": font_size // 2
                                            },
                                            "char_start": char_start,
                                            "char_end": char_end
                                        })
                                    text_parts = []
                                saw_format = True
                                eff[dirctx][charset] = int(m.group(1))
                                j = m.end()
                                continue

                            m = _RE_FONT_SIZE.match(data, j)
                            if m:
                                if not saw_format and text_parts:
                                    text = self._clean_text(''.join(text_parts))
                                    if text:
                                        char_end = i
                                        self._streams.append({
                                            "text": text,
                                            "font": {
                                                "id": get_fid(),
                                                "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                                "size": font_size // 2
                                            },
                                            "char_start": char_start,
                                            "char_end": char_end
                                        })
                                    text_parts = []
                                saw_format = True
                                font_size = int(m.group(1))
                                j = m.end()
                                continue

                            break


                        if saw_format:
                            char_start = i  # new run starts at the escaped symbol

                        text_parts.append(out_ch)
                        i = j
                        handled_escaped = True
                        break  # Break out of the for loop; we'll continue the while loop below
                
                # If we handled an escaped symbol, continue the main while loop
                # (don't fall through to other handlers or the i += 1 at the end)
                if handled_escaped:
                    continue
                    
                # Handle \'hh (hex character)
                m = _RE_HEX_CHAR.match(data, i)
                if m:
                    text_parts.append(bytes.fromhex(m.group(1)).decode('latin1'))
                    i = m.end()
                    continue
                # Direction context (Word often emits {\rtlch ... \ltrch ...} blocks)
                m = _RE_DIRCTX.match(data, i)
                if m:
                    if text_parts:
                        text = self._clean_text(''.join(text_parts))
                        if text:
                            char_end = i
                            self._streams.append({
                                "text": text,
                                "font": {
                                    "id": get_fid(),
                                    "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                    "size": font_size // 2
                                },
                                "char_start": char_start,
                                "char_end": char_end
                            })
                        text_parts = []
                    dirctx = m.group(1)
                    i = m.end()
                    char_start = i
                    continue

                # Charset selection (low/high/DBCS)
                m = _RE_CHARSET.match(data, i)
                if m:
                    if text_parts:
                        text = self._clean_text(''.join(text_parts))
                        if text:
                            char_end = i
                            self._streams.append({
                                "text": text,
                                "font": {
                                    "id": get_fid(),
                                    "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                    "size": font_size // 2
                                },
                                "char_start": char_start,
                                "char_end": char_end
                            })
                        text_parts = []
                    charset = m.group(1)
                    i = m.end()
                    char_start = i
                    continue

                # ANSI/script font (often the one that matters for text runs)
                m = _RE_AFONT.match(data, i)
                if m:
                    if text_parts:
                        text = self._clean_text(''.join(text_parts))
                        if text:
                            char_end = i
                            self._streams.append({
                                "text": text,
                                "font": {
                                    "id": get_fid(),
                                    "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                    "size": font_size // 2
                                },
                                "char_start": char_start,
                                "char_end": char_end
                            })
                        text_parts = []
                    eff[dirctx][charset] = int(m.group(1))
                    i = m.end()
                    char_start = i
                    continue

                # Font ID (fallback; treat as current effective font)
                m = _RE_FONT_ID.match(data, i)
                if m:
                    if text_parts:
                        text = self._clean_text(''.join(text_parts))
                        if text:
                            char_end = i
                            self._streams.append({
                                "text": text,
                                "font": {
                                    "id": get_fid(),
                                    "name": self._font_map.get(get_fid(), {}).get("name", ""),
                                    "size": font_size // 2
                                },
                                "char_start": char_start,
                                "char_end": char_end
                            })
                        text_parts = []
                    eff[dirctx][charset] = int(m.group(1))
                    i = m.end()
                    char_start = i
                    continue
                # Font size
                m = _RE_FONT_SIZE.match(data, i)
                if m:
                    if text_parts:
                        text = self._clean_text(''.join(text_parts))
                        if text:
                            char_end = i
                            self._streams.append({
                                "text": text,
                                "font": {
                                    "id": get_fid(),
                                    "name": self._font_map.get(get_fid(), {}).get("name", ""),
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
                    # RTF paragraph break: end the current paragraph structurally.
                    # Do NOT store as a literal newline in a text run; that tends to get
                    # dropped/reshuffled when groups close.
                    flush_text(i)
                    self._streams.append({
                        "type": "par_break",
                        "char_start": i,
                        "char_end": m.end()
                    })
                    i = m.end()
                    char_start = i
                    continue

                # Forced line break inside a paragraph
                m = _RE_LINE.match(data, i)
                if m:
                    flush_text(i)
                    self._streams.append({
                        "type": "line_break",
                        "char_start": i,
                        "char_end": m.end()
                    })
                    i = m.end()
                    char_start = i
                    continue
                
                # Table cell end - treat like a newline (Word shows as \x07)
                m = _RE_CELL.match(data, i)
                if m:
                    flush_text(i)
                    self._streams.append({
                        "type": "cell_break",
                        "char_start": i,
                        "char_end": m.end()
                    })
                    i = m.end()
                    char_start = i
                    continue
                
                # Table row end - treat like a paragraph break
                m = _RE_ROW.match(data, i)
                if m:
                    flush_text(i)
                    self._streams.append({
                        "type": "row_break",
                        "char_start": i,
                        "char_end": m.end()
                    })
                    i = m.end()
                    char_start = i
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
            if text:
                char_end = i
                self._streams.append({
                    "text": text,
                    "font": {
                        "id": get_fid(),
                        "name": self._font_map.get(get_fid(), {}).get("name", ""),
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
