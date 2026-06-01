"""
pdf2line.normalize — Enhanced Unicode/Tibetan normalization.

Uses the comprehensive corpus_normalization module which applies:
- Unicode NFC normalization
- Line break normalization
- Zero-width character removal
- Unicode space mapping to ASCII
- Control character removal (optional)
- Tibetan-specific space rules
- Tibetan Unicode normalization (character reordering, deprecated chars)
- Tsheg variant folding (U+0F0C -> U+0F0B)
- Double-shad expansion (U+0F0E -> U+0F0D U+0F0D)

Normalization is optional and applied per output line. Disable with the
``--no-normalize`` CLI flag.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Import normalize_corpus from the parent PDF_TXT directory
_parent = Path(__file__).parent.parent
if str(_parent) not in sys.path:
    sys.path.insert(0, str(_parent))

from corpus_normalization import normalize_corpus


def normalize_line(text: str) -> str:
    """
    Normalize an already-assembled pecha-page string.

    The input may be a single line OR a multi-line string (visual lines within
    a pecha page joined by ``\n``). Normalization is applied per visual line
    so that the line break structure is preserved — ``normalize_corpus``'s
    rule that collapses runs of newlines to one would otherwise be benign
    here, but applying per-line keeps the boundaries explicit and avoids any
    accidental swallowing of intentional separators.

    Uses ``normalize_corpus`` from the corpus_normalization module for
    comprehensive Unicode and Tibetan text normalization.
    """
    if not text:
        return text

    if "\n" not in text:
        return normalize_corpus(
            text, strip_control=True, collapse_internal_spaces=True
        )

    # Multi-line: normalize each visual line independently and rejoin.
    parts = text.split("\n")
    normalized = [
        normalize_corpus(p, strip_control=True, collapse_internal_spaces=True)
        for p in parts
    ]
    # Drop visual lines that became empty after normalization.
    normalized = [n for n in normalized if n]
    return "\n".join(normalized)
