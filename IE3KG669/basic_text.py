"""
Plain text parser for TEI conversion pipeline.

Produces a list of "streams" compatible with the same format as BasicRTF.get_streams(),
so convert_txt_to_tei() can reuse the same downstream logic (font size classification,
normalization, TEI body building). Each line of the file becomes one text stream with
a default font; no paragraph/line break types are emitted (newlines are in the text).
"""


class BasicText:
    """
    Parse a plain text file into streams compatible with BasicRTF output.
    
    Each line becomes one stream: {"text": line_content (with \\n), "font": {"name": "", "size": 12}}.
    """

    def __init__(self):
        self._streams = []

    def parse_file(self, file_path, encoding="utf-8"):
        """
        Read a text file and build streams (one per line).
        
        Args:
            file_path: Path to the .txt file (or str)
            encoding: File encoding (default utf-8)
        """
        self._streams = []
        with open(file_path, encoding=encoding, errors="ignore") as f:
            for line in f:
                # Preserve trailing newline so line breaks are in the content
                text = line if line.endswith("\n") else line + "\n"
                self._streams.append({
                    "text": text,
                    "font": {"name": "", "size": 12},
                })

    def get_streams(self):
        """Return the list of streams (same shape as BasicRTF.get_streams())."""
        return self._streams
