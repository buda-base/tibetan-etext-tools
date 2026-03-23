import re

# AI generated code
# 


class BasicRTF:
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

        font_id = 0
        font_size = 24  # default RTF size (half-points)
        stack = []
        text = ""
        in_fonttable = False
        fonttbl_brace_level = 0
        fonttbl_data = ""
        in_colortbl = False
        colortbl_brace_level = 0
        colortbl_data = ""
        i = 0
        char_start = 0
        char_end = 0

        special_keywords = {
            r'\footnote': 'footnote',
            r'\header': 'header',
            r'\footer': 'footer',
            r'\pict': 'pict'
        }

        while i < len(data):
            c = data[i]
            # Font table detection
            if data[i:i+9] == r'{\fonttbl':
                in_fonttable = True
                fonttbl_brace_level = 1
                i += 9
                continue
            if in_fonttable:
                if data[i] == '{':
                    fonttbl_brace_level += 1
                elif data[i] == '}':
                    fonttbl_brace_level -= 1
                    if fonttbl_brace_level == 0:
                        in_fonttable = False
                        for m in re.finditer(r'{\\f(\d+)[^;]*;}', fonttbl_data):
                            fid = int(m.group(1))
                            name_match = re.search(r' ([^\\;]+);', m.group(0))
                            name = name_match.group(1).strip() if name_match else f"f{fid}"
                            self._font_map[fid] = {"id": fid, "name": name}
                            self._fonts.append({"id": fid, "name": name})
                        fonttbl_data = ""
                        i += 1
                        continue
                fonttbl_data += data[i]
                i += 1
                continue

            if data[i:i+9] == r'{\colortbl':
                in_colortbl = True
                colortbl_brace_level = 1
                i += 9
                continue
            if in_colortbl:
                if data[i] == '{':
                    colortbl_brace_level += 1
                elif data[i] == '}':
                    colortbl_brace_level -= 1
                    if colortbl_brace_level == 0:
                        in_colortbl = False
                        self._colors = []
                        color_entries = colortbl_data.split(';')
                        for entry in color_entries:
                            r = g = b = 0
                            m_r = re.search(r'\\red(\d+)', entry)
                            m_g = re.search(r'\\green(\d+)', entry)
                            m_b = re.search(r'\\blue(\d+)', entry)
                            if m_r: r = int(m_r.group(1))
                            if m_g: g = int(m_g.group(1))
                            if m_b: b = int(m_b.group(1))
                            if m_r or m_g or m_b:
                                self._colors.append({'red': r, 'green': g, 'blue': b})
                        colortbl_data = ""
                        i += 1
                        continue
                colortbl_data += data[i]
                i += 1
                continue

            special_type = None
            if c == '\\':
                for kw, typ in special_keywords.items():
                    if data.startswith(kw, i):
                        j = i + len(kw)
                        while j < len(data) and data[j] in ' \n\r\t':
                            j += 1
                        if j < len(data) and data[j] == '{':
                            block_start = j
                            brace_level = 1
                            k = j + 1
                            while k < len(data) and brace_level > 0:
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
                            i = j
                            special_type = typ
                            break
                if special_type:
                    continue

            if data[i] == '{' and i + 1 < len(data) and data[i+1] == '\\' and data[i+2] == '*':
                brace_level = 1
                j = i + 3
                while j < len(data) and brace_level > 0:
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
                    text = ""
                font_id, font_size = stack.pop()
                i += 1
                char_start = i
            elif c == '\\':
                m = re.match(r"\\u(-?\d+)(?:\\'[0-9a-fA-F]{2}|.)", data[i:])
                if m:
                    codepoint = int(m.group(1))
                    if codepoint < 0:
                        codepoint += 0x10000
                    try:
                        text += chr(codepoint)
                    except Exception:
                        text += '?'
                    i += len(m.group(0))
                    continue
                if data.startswith(r'\~', i):
                    text += '\u00A0'
                    i += 2
                    continue
                if data.startswith(r'\-', i):
                    i += 2
                    continue
                m = re.match(r"\\'([0-9a-fA-F]{2})", data[i:])
                if m:
                    text += bytes.fromhex(m.group(1)).decode('latin1')
                    i += len(m.group(0))
                    continue
                m = re.match(r'\\f(\d+)', data[i:])
                if m:
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
                        text = ""
                    font_id = int(m.group(1))
                    i += len(m.group(0))
                    char_start = i
                    continue
                m = re.match(r'\\fs(\d+)', data[i:])
                if m:
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
                        text = ""
                    font_size = int(m.group(1))
                    i += len(m.group(0))
                    char_start = i
                    continue
                m = re.match(r'\\par(?![a-zA-Z])', data[i:])
                if m:
                    text += '\n'
                    i += 4
                    continue
                m = re.match(r'\\[a-zA-Z0-9]+\s?', data[i:])
                if m:
                    i += len(m.group(0))
                    continue
                i += 1
            else:
                text += c
                i += 1
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

    def get_streams(self):
        return self._streams

    def get_fonts(self):
        return self._fonts

    def get_colors(self):
        return self._colors






