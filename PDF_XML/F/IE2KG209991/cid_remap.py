import json
import re

class CIDRemapper:
    def __init__(self, map_path="qomolangma_cid_map.json"):
        self.cid_map = self._load_map(map_path)
        # Fallback to catch literal (cid:NNN) strings if emitted by other extractors
        self.cid_pattern = re.compile(r'\(cid:\s*(\d+)\)', re.IGNORECASE)

    def _load_map(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw_map = json.load(f)
                # Force all keys to be standard string integers to avoid padding issues
                clean_map = {}
                for k, v in raw_map.items():
                    try:
                        clean_map[str(int(k))] = v
                    except ValueError:
                        pass
                return clean_map
        except FileNotFoundError:
            print(f"Warning: CID map not found at {path}. No remapping will occur.")
            return {}

    def _replace_cid_string(self, match):
        """Replaces literal (cid:123) string matches."""
        cid_str = str(int(match.group(1)))
        return self.cid_map.get(cid_str, match.group(0))

    def _replace_pua_chars(self, text):
        """Translates PyMuPDF's U+F000 Private Use Area characters back to Unicode."""
        result = []
        for char in text:
            code = ord(char)
            # Check if the character falls in the PyMuPDF PUA offset range
            if 0xF000 <= code <= 0xF2FF:
                # Subtract the 0xF000 offset to get the raw CID
                cid_str = str(code - 0xF000)
                if cid_str in self.cid_map:
                    result.append(self.cid_map[cid_str])
                else:
                    result.append(char)
            else:
                result.append(char)
        return "".join(result)

    def remap_text(self, text):
        """Processes raw text and replaces all known CID tokens and PUA characters."""
        if not self.cid_map or not text:
            return text
            
        # 1. Remap PyMuPDF PUA characters (U+F000 offset)
        text = self._replace_pua_chars(text)
        
        # 2. Remap literal (cid:NNN) tokens as a fallback
        text = self.cid_pattern.sub(self._replace_cid_string, text)
        
        return text