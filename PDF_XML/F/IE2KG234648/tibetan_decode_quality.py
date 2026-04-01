"""
Phase 2 gating (per project spec): detect PDF text extraction that maps Tibetan glyphs to
wrong Unicode (e.g. Latin-1), so we can retry with embedded-font cmap decoding.

Operates on the string returned by pytiblegenc (optionally split by page-break markers).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

# Minimum "letter-like" characters before applying strict ratios (skip nearly empty chunks).
MIN_SIGNIFICANT_CHARS: int = 40
# For body Tibetan, expect a noticeable share in U+0F00–U+0FFF.
MIN_TIBETAN_RATIO: float = 0.10
# Suspicious if many letter-like chars look like Latin / Latin-extended filler (legacy ToUnicode).
MAX_LATIN_EXTENDED_LETTER_RATIO: float = 0.28
# Non–U+0F00 codepoints at U+0080+ among letter-like glyphs (garbage ToUnicode to Latin-1 / symbols).
MIN_HIGH_BYTE_NON_TIBETAN_RATIO: float = 0.20
# CJK-dominant pages: do not treat as "failed Tibetan decode".
MIN_CJK_RATIO_TO_SKIP_GATE: float = 0.35

_TIBETAN_RE = re.compile(r"[\u0f00-\u0fff]")
# Latin-1 supplement + Latin Extended-A/B (common wrong mappings for Tibetan PDFs)
_LATIN_EXTENDED_LETTER_RE = re.compile(
    r"[\u00c0-\u024f\u1e00-\u1eff]"
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_FS_MARKUP_RE = re.compile(r"<fs:\d+>")


def _high_byte_non_tibetan_letter(c: str) -> bool:
    o = ord(c)
    if 0x0F00 <= o <= 0x0FFF:
        return False
    return o >= 0x80


@dataclass
class DecodeQualityReport:
    """Metrics for one sample (whole doc or one page)."""

    significant_chars: int
    tibetan_chars: int
    tibetan_ratio: float
    latin_extended_letters: int
    latin_extended_ratio: float
    cjk_chars: int
    cjk_ratio: float
    passes_gate: bool
    reason: str


def strip_extraction_markup(text: str, page_break_marker: Optional[str] = None) -> str:
    """Remove pytiblegenc font-size tags and optional page-break lines."""
    s = _FS_MARKUP_RE.sub("", text)
    if page_break_marker:
        s = re.sub(
            re.escape(page_break_marker),
            "\n",
            s,
        )
    return s


def _letter_like_or_tibetan(c: str) -> bool:
    if not c:
        return False
    o = ord(c)
    if 0x0F00 <= o <= 0x0FFF:
        return True
    if c.isalpha():
        return True
    if _LATIN_EXTENDED_LETTER_RE.fullmatch(c):
        return True
    return False


def _assess_clean_sample(clean: str) -> DecodeQualityReport:
    sig = [c for c in clean if _letter_like_or_tibetan(c)]
    n = len(sig)
    if n < MIN_SIGNIFICANT_CHARS:
        return DecodeQualityReport(
            significant_chars=n,
            tibetan_chars=0,
            tibetan_ratio=0.0,
            latin_extended_letters=0,
            latin_extended_ratio=0.0,
            cjk_chars=0,
            cjk_ratio=0.0,
            passes_gate=True,
            reason="too_few_significant_chars",
        )

    tibetan = sum(1 for c in sig if _TIBETAN_RE.match(c))
    lat_ext = sum(1 for c in sig if _LATIN_EXTENDED_LETTER_RE.match(c))
    non_ws = sum(1 for c in clean if not c.isspace())
    cjk_count = sum(1 for c in clean if _CJK_RE.match(c))
    sig_set = len(sig)
    t_ratio = tibetan / sig_set
    l_ratio = lat_ext / sig_set
    cjk_ratio = cjk_count / max(1, non_ws)
    high_byte_non_tib = sum(1 for c in sig if _high_byte_non_tibetan_letter(c))
    hb_ratio = high_byte_non_tib / sig_set

    if cjk_ratio >= MIN_CJK_RATIO_TO_SKIP_GATE:
        return DecodeQualityReport(
            significant_chars=sig_set,
            tibetan_chars=tibetan,
            tibetan_ratio=t_ratio,
            latin_extended_letters=lat_ext,
            latin_extended_ratio=l_ratio,
            cjk_chars=cjk_count,
            cjk_ratio=cjk_ratio,
            passes_gate=True,
            reason="mostly_cjk_skipped",
        )

    fails = t_ratio < MIN_TIBETAN_RATIO and (
        l_ratio >= MAX_LATIN_EXTENDED_LETTER_RATIO
        or hb_ratio >= MIN_HIGH_BYTE_NON_TIBETAN_RATIO
    )
    if not fails:
        reason = "ok"
    else:
        reason = "low_tibetan_high_latin_ext"
    return DecodeQualityReport(
        significant_chars=sig_set,
        tibetan_chars=tibetan,
        tibetan_ratio=t_ratio,
        latin_extended_letters=lat_ext,
        latin_extended_ratio=l_ratio,
        cjk_chars=cjk_count,
        cjk_ratio=cjk_ratio,
        passes_gate=not fails,
        reason=reason,
    )


def assess_decode_quality(
    text: str,
    *,
    page_break_marker: Optional[str] = None,
) -> DecodeQualityReport:
    """
    If *page_break_marker* appears in *text*, evaluate each page and fail the gate if any
    substantial page fails (TOC-only pages with few chars are ignored).
    Otherwise evaluate the whole string once.
    """
    if page_break_marker and page_break_marker in text:
        parts = re.split(
            rf"\n{re.escape(page_break_marker)}\n",
            text,
        )
        reports: List[DecodeQualityReport] = []
        for part in parts:
            clean = strip_extraction_markup(part, page_break_marker=None)
            reports.append(_assess_clean_sample(clean))
        substantial = [r for r in reports if r.reason != "too_few_significant_chars"]
        if not substantial:
            return next((r for r in reports if r.reason == "too_few_significant_chars"), reports[0])
        failed = [r for r in substantial if not r.passes_gate]
        if failed:
            worst = min(failed, key=lambda r: r.tibetan_ratio)
            return DecodeQualityReport(
                significant_chars=sum(r.significant_chars for r in substantial),
                tibetan_chars=sum(r.tibetan_chars for r in substantial),
                tibetan_ratio=worst.tibetan_ratio,
                latin_extended_letters=worst.latin_extended_letters,
                latin_extended_ratio=worst.latin_extended_ratio,
                cjk_chars=sum(r.cjk_chars for r in substantial),
                cjk_ratio=max(r.cjk_ratio for r in substantial),
                passes_gate=False,
                reason=f"page_failed:{worst.reason}",
            )
        return DecodeQualityReport(
            significant_chars=sum(r.significant_chars for r in substantial),
            tibetan_chars=sum(r.tibetan_chars for r in substantial),
            tibetan_ratio=(
                sum(r.tibetan_chars for r in substantial)
                / max(1, sum(r.significant_chars for r in substantial))
            ),
            latin_extended_letters=0,
            latin_extended_ratio=0.0,
            cjk_chars=sum(r.cjk_chars for r in substantial),
            cjk_ratio=max(r.cjk_ratio for r in substantial),
            passes_gate=True,
            reason="all_pages_ok",
        )

    clean = strip_extraction_markup(text, page_break_marker=None)
    return _assess_clean_sample(clean)


def format_report_log(report: DecodeQualityReport) -> str:
    return (
        f"tibetan_ratio={report.tibetan_ratio:.3f} "
        f"latin_extended_ratio={report.latin_extended_ratio:.3f} "
        f"significant={report.significant_chars} "
        f"passes={report.passes_gate} "
        f"({report.reason})"
    )
