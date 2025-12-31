import re

# AI generated code - HIGHLY OPTIMIZED VERSION
# Key optimizations:
# 1. Pre-compiled regex patterns at class level
# 2. Position-based matching with .match(data, i) instead of slicing
# 3. List-based string building instead of string concatenation
# 4. Avoid regex for simple pattern checks (use direct string comparison)
# 5. Inline hex conversion for \'XX patterns (most common in Dedris)


class BasicRTF:
    # Pre-compile patterns at class level
    _RE_UNICODE = re.compile(r'\\u(-?\d+)\??')
    _RE_FONT = re.compile(r'\\f(\d+)')
    _RE_FONTSIZE = re.compile(r'\\fs(\d+)')
    _RE_KEYWORD = re.compile(r'\\[a-zA-Z]+[0-9]*\s?')
    _RE_FONTTBL_ENTRY = re.compile(r'{\\f(\d+)[^;]*;}')
    _RE_FONTNAME = re.compile(r' ([^\\;]+);')
    _RE_RED = re.compile(r'\\red(\d+)')
    _RE_GREEN = re.compile(r'\\green(\d+)')
    _RE_BLUE = re.compile(r'\\blue(\d+)')
    
    # Precompute hex lookup table for \'XX patterns (0-9, a-f, A-F)
    _HEX_CHARS = set('0123456789abcdefABCDEF')
    _HEX_VALUES = {
        '0': 0, '1': 1, '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9,
        'a': 10, 'b': 11, 'c': 12, 'd': 13, 'e': 14, 'f': 15,
        'A': 10, 'B': 11, 'C': 12, 'D': 13, 'E': 14, 'F': 15
    }

    def __init__(self):
        self._fonts = []
        self._font_map = {}
        self._streams = []
        self._raw_data = ""
        self._colors = []

    def parse_file(self, file_path):
        self._fonts = []
        self._font_map = {}
        self._streams = []
        self._raw_data = ""
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            data = f.read()
        self._raw_data = data
        data_len = len(data)

        font_id = 0
        font_size = 24
        stack = []
        text_parts = []
        in_fonttable = False
        fonttbl_brace_level = 0
        fonttbl_parts = []
        in_colortbl = False
        colortbl_brace_level = 0
        colortbl_parts = []
        in_stylesheet = False
        stylesheet_brace_level = 0
        i = 0
        char_start = 0

        # Cache frequently used values
        hex_chars = self._HEX_CHARS
        hex_values = self._HEX_VALUES
        re_unicode = self._RE_UNICODE
        re_font = self._RE_FONT
        re_fontsize = self._RE_FONTSIZE
        re_keyword = self._RE_KEYWORD
        font_map = self._font_map
        streams = self._streams

        while i < data_len:
            c = data[i]

            # Font table detection
            if c == '{' and data[i:i+9] == '{\\fonttbl':
                in_fonttable = True
                fonttbl_brace_level = 1
                i += 9
                continue
            if in_fonttable:
                if c == '{':
                    fonttbl_brace_level += 1
                elif c == '}':
                    fonttbl_brace_level -= 1
                    if fonttbl_brace_level == 0:
                        in_fonttable = False
                        fonttbl_data = ''.join(fonttbl_parts)
                        for m in self._RE_FONTTBL_ENTRY.finditer(fonttbl_data):
                            fid = int(m.group(1))
                            name_match = self._RE_FONTNAME.search(m.group(0))
                            name = name_match.group(1).strip() if name_match else f"f{fid}"
                            font_map[fid] = {"id": fid, "name": name}
                            self._fonts.append({"id": fid, "name": name})
                        fonttbl_parts = []
                        i += 1
                        continue
                fonttbl_parts.append(c)
                i += 1
                continue

            # Color table detection
            if c == '{' and data[i:i+9] == '{\\colortbl':
                in_colortbl = True
                colortbl_brace_level = 1
                i += 9
                continue
            if in_colortbl:
                if c == '{':
                    colortbl_brace_level += 1
                elif c == '}':
                    colortbl_brace_level -= 1
                    if colortbl_brace_level == 0:
                        in_colortbl = False
                        colortbl_data = ''.join(colortbl_parts)
                        self._colors = []
                        for entry in colortbl_data.split(';'):
                            r = g = b = 0
                            m_r = self._RE_RED.search(entry)
                            m_g = self._RE_GREEN.search(entry)
                            m_b = self._RE_BLUE.search(entry)
                            if m_r: r = int(m_r.group(1))
                            if m_g: g = int(m_g.group(1))
                            if m_b: b = int(m_b.group(1))
                            if m_r or m_g or m_b:
                                self._colors.append({'red': r, 'green': g, 'blue': b})
                        colortbl_parts = []
                        i += 1
                        continue
                colortbl_parts.append(c)
                i += 1
                continue

            # Stylesheet detection - skip style definitions (contains "Normal", "heading 1", etc.)
            if c == '{' and data[i:i+12] == '{\\stylesheet':
                in_stylesheet = True
                stylesheet_brace_level = 1
                i += 12
                continue
            if in_stylesheet:
                if c == '{':
                    stylesheet_brace_level += 1
                elif c == '}':
                    stylesheet_brace_level -= 1
                    if stylesheet_brace_level == 0:
                        in_stylesheet = False
                        i += 1
                        continue
                i += 1
                continue

            # Handle groups starting with \* (ignore group) - check early
            if c == '{' and i + 2 < data_len and data[i+1] == '\\' and data[i+2] == '*':
                brace_level = 1
                j = i + 3
                while j < data_len and brace_level > 0:
                    ch = data[j]
                    if ch == '{':
                        brace_level += 1
                    elif ch == '}':
                        brace_level -= 1
                    j += 1
                i = j
                continue

            if c == '{':
                stack.append((font_id, font_size))
                i += 1
            elif c == '}':
                if text_parts:
                    text = ''.join(text_parts)
                    if text.strip():
                        streams.append({
                            "text": text,
                            "font": {
                                "id": font_id,
                                "name": font_map.get(font_id, {}).get("name", ""),
                                "size": font_size // 2
                            },
                            "char_start": char_start,
                            "char_end": i
                        })
                    text_parts = []
                if stack:
                    font_id, font_size = stack.pop()
                i += 1
                char_start = i
            elif c == '\\':
                next_i = i + 1
                if next_i >= data_len:
                    i += 1
                    continue
                    
                nc = data[next_i]
                
                # Fast path: \'XX hex character (most common in Dedris RTF)
                if nc == "'" and next_i + 2 < data_len:
                    h1 = data[next_i + 1]
                    h2 = data[next_i + 2]
                    if h1 in hex_chars and h2 in hex_chars:
                        byte_val = hex_values[h1] * 16 + hex_values[h2]
                        text_parts.append(chr(byte_val))
                        i = next_i + 3
                        continue

                # Fast path: \~ non-breakable space
                if nc == '~':
                    text_parts.append('\u00A0')
                    i = next_i + 1
                    continue

                # Fast path: \- optional hyphen (skip)
                if nc == '-':
                    i = next_i + 1
                    continue

                # Fast path: \par paragraph
                if nc == 'p' and data[next_i:next_i+3] == 'par' and (next_i + 3 >= data_len or not data[next_i+3].isalpha()):
                    text_parts.append('\n')
                    i = next_i + 3
                    # Skip optional space after \par
                    if i < data_len and data[i] == ' ':
                        i += 1
                    continue

                # Handle \uN? unicode characters
                if nc == 'u' and next_i + 1 < data_len and (data[next_i+1].isdigit() or data[next_i+1] == '-'):
                    m = re_unicode.match(data, i)
                    if m:
                        codepoint = int(m.group(1))
                        if codepoint < 0:
                            codepoint += 0x10000
                        try:
                            text_parts.append(chr(codepoint))
                        except Exception:
                            text_parts.append('?')
                        i = m.end()
                        continue

                # Handle \fN (font change)
                if nc == 'f' and next_i + 1 < data_len and data[next_i+1].isdigit():
                    m = re_font.match(data, i)
                    if m:
                        if text_parts:
                            text = ''.join(text_parts)
                            if text.strip():
                                streams.append({
                                    "text": text,
                                    "font": {
                                        "id": font_id,
                                        "name": font_map.get(font_id, {}).get("name", ""),
                                        "size": font_size // 2
                                    },
                                    "char_start": char_start,
                                    "char_end": i
                                })
                            text_parts = []
                        font_id = int(m.group(1))
                        i = m.end()
                        char_start = i
                        continue

                # Handle \fsN (font size)
                if nc == 'f' and next_i + 1 < data_len and data[next_i+1] == 's':
                    m = re_fontsize.match(data, i)
                    if m:
                        if text_parts:
                            text = ''.join(text_parts)
                            if text.strip():
                                streams.append({
                                    "text": text,
                                    "font": {
                                        "id": font_id,
                                        "name": font_map.get(font_id, {}).get("name", ""),
                                        "size": font_size // 2
                                    },
                                    "char_start": char_start,
                                    "char_end": i
                                })
                            text_parts = []
                        font_size = int(m.group(1))
                        i = m.end()
                        char_start = i
                        continue

                # Handle other keywords
                if nc.isalpha():
                    m = re_keyword.match(data, i)
                    if m:
                        i = m.end()
                        continue

                i += 1
            else:
                text_parts.append(c)
                i += 1

        # Handle remaining text
        if text_parts:
            text = ''.join(text_parts)
            if text.strip():
                streams.append({
                    "text": text,
                    "font": {
                        "id": font_id,
                        "name": font_map.get(font_id, {}).get("name", ""),
                        "size": font_size // 2
                    },
                    "char_start": char_start,
                    "char_end": data_len
                })

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
