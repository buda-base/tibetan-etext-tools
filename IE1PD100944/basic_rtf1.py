import re

class BasicRTF:
    """
    A robust RTF parser that tracks the state stack (font, size) and 
    maps font IDs to names from the RTF font table.
    """
    def __init__(self):
        self.font_table = {}
        self.streams = []
        self._current_text_pos = 0

    def _extract_font_table(self, rtf_content):
        """Parses the {\fonttbl ...} section to map ID (\fN) to Font Names."""
        font_tbl_match = re.search(r'\{\\fonttbl(.*?)\}', rtf_content, re.DOTALL)
        if not font_tbl_match:
            return
        
        # Matches: \f45 ... Dedris-vowa; or \f0\fbidi ... Times New Roman;
        # This regex looks for the font index and the name ending in a semicolon
        raw_table = font_tbl_match.group(1)
        font_matches = re.findall(r'\\f(\d+)[^;]*?\s+([^;{}]+);', raw_table)
        
        for fid, fname in font_matches:
            # Clean up: remove RTF tags that might be inside the name
            clean_name = re.sub(r'\\[a-z0-9]+', '', fname).strip()
            self.font_table[fid] = clean_name

    def parse_file(self, file_path):
        """Reads and parses an RTF file into text streams."""
        with open(file_path, 'r', encoding='ascii', errors='ignore') as f:
            content = f.read()
        self.parse_string(content)

    def parse_string(self, rtf_content):
        """The main parsing engine logic."""
        self.streams = []
        self._current_text_pos = 0
        self._extract_font_table(rtf_content)

        # Initial State
        stack = []
        current_state = {
            "font_id": "0",
            "font_size": 24, # Default 12pt
            "type": "body"
        }

        # Tokenizer Regex:
        # 1. Control words: \wordN
        # 2. Hex characters: \'hh
        # 3. Braces: { }
        # 4. Plain text: characters
        pattern = re.compile(r"\\([a-z*]+)(-?\d+)? ?|\\\'([0-9a-fA-F]{2})|([{}])|([^{}\\\r\n]+)")

        # Temporary buffer for text with same properties to keep streams clean
        buffer_text = ""
        last_state_key = None

        def flush_buffer():
            nonlocal buffer_text
            if buffer_text:
                font_name = self.font_table.get(current_state["font_id"], f"Unknown-{current_state['font_id']}")
                
                # Check for special types in the stack (headers/footers/pict)
                stream_type = "body"
                for s in stack:
                    if s.get("type") in ["header", "footer", "pict"]:
                        stream_type = s["type"]
                        break

                start_pos = self._current_text_pos
                self._current_text_pos += len(buffer_text)
                
                self.streams.append({
                    "text": buffer_text,
                    "type": stream_type,
                    "start": start_pos,
                    "end": self._current_text_pos,
                    "font": {
                        "name": font_name,
                        "size": current_state["font_size"] / 2.0 # Convert half-pts to pts
                    }
                })
                buffer_text = ""

        for match in pattern.finditer(rtf_content):
            word, arg, hex_val, brace, text = match.groups()

            if brace == '{':
                stack.append(current_state.copy())
            elif brace == '}':
                if stack:
                    flush_buffer()
                    current_state = stack.pop()
            
            elif word:
                # Common RTF formatting tags
                if word == 'f':
                    flush_buffer()
                    current_state["font_id"] = arg
                elif word == 'fs':
                    flush_buffer()
                    current_state["font_size"] = int(arg) if arg else 24
                elif word in ['par', 'line']:
                    buffer_text += "\n"
                elif word in ['tab']:
                    buffer_text += "\t"
                # Type markers
                elif word in ['header', 'headerl', 'headerr', 'headerf']:
                    current_state["type"] = "header"
                elif word in ['footer', 'footerl', 'footerr', 'footerf']:
                    current_state["type"] = "footer"
                elif word == 'pict':
                    current_state["type"] = "pict"

            elif hex_val:
                # Convert \'hh to character
                char = bytes.fromhex(hex_val).decode('latin-1', errors='replace')
                buffer_text += char

            elif text:
                buffer_text += text

        flush_buffer()

    def get_streams(self):
        """Returns the parsed text segments."""
        return self.streams

    def get_full_text(self):
        """Helper to see the plain text output."""
        return "".join([s["text"] for s in self.streams if s["type"] == "body"])

if __name__ == "__main__":
    p = BasicRTF()
    p.parse_file("tibetan-etext-tools\IE1PD100944\KAMA-001.rtf")
    for s in p.get_streams()[:10]:
        print(f"Font: {s['font']['name']} | Size: {s['font']['size']} | Text: {s['text'][:30]!r}")