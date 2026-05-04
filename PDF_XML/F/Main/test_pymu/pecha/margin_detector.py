"""
margin_detector.py — Auto-detect the body preserve-rect for a PDF.

Samples up to ``SAMPLE_PAGES`` evenly-spaced pages (skipping the first and
last, which often carry title/colophon layouts), collects every text-block
bounding box, and identifies the main body column — the widest block that
repeats consistently across pages.

Return value
------------
``(x0, y0, x1, y1)`` as **fractions of the page dimensions** (0.0–1.0),
matching the format produced by https://buddhist.tools/pdf-cropper.
The rect is the area to **preserve**; everything outside is redacted.

Returns ``None`` if the PDF has no extractable text (scanned / image-only).

Typical usage
-------------
    from margin_detector import detect_margins

    # Auto-detect
    preserve = detect_margins(Path("my.pdf"))
    # → e.g. (0.12, 0.19, 0.88, 0.78)

    # Manual override from buddhist.tools — paste directly from the tool
    preserve = (0.12, 0.19, 0.88, 0.78)

Public API
----------
detect_margins(pdf_path, sample_pages=20, presence_threshold=0.75)
    -> tuple[float, float, float, float] | None
"""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ── tuneable constants ────────────────────────────────────────────────────────

# How many interior pages to sample (first + last page excluded).
SAMPLE_PAGES: int = 20

# A block x-span is considered the "body column" only when it appears on this
# fraction of sampled pages.  50% works well for pecha-format PDFs where the
# body text block width varies between recto/verso pages.
PRESENCE_THRESHOLD: float = 0.50

# Snap individual block edges to this grid (pts) before comparing across pages.
# Absorbs sub-pt rendering jitter without merging genuinely distinct columns.
SNAP_PT: float = 4.0

# Extra padding (in page-fraction units) added around the detected body rect
# so that ink at block edges is not accidentally clipped.
PADDING_FRAC: float = 0.005   # ~0.5 % of page dimension

# A block must be at least this fraction of page width to be a body-column
# candidate (excludes narrow margin columns like pecha folio labels).
MIN_BODY_WIDTH_FRAC: float = 0.30


# ── helpers ───────────────────────────────────────────────────────────────────

def _snap(value: float) -> float:
    return round(value / SNAP_PT) * SNAP_PT


def _sample_page_indices(total: int, n: int) -> list[int]:
    """Up to *n* evenly-spaced 0-based page indices, skipping first and last."""
    if total <= 2:
        return list(range(total))
    interior = list(range(1, total - 1))
    if len(interior) <= n:
        return interior
    step = len(interior) / n
    return [interior[round(i * step)] for i in range(n)]


# ── public API ────────────────────────────────────────────────────────────────

def detect_margins(
    pdf_path: Path,
    sample_pages: int = SAMPLE_PAGES,
    presence_threshold: float = PRESENCE_THRESHOLD,
) -> Optional[tuple]:
    """
    Analyse *pdf_path* and return the preserve-rect as
    ``(x0, y0, x1, y1)`` fractions of page width/height (0.0-1.0).

    The rect is the region to KEEP; everything outside is redacted.
    Fractions match the buddhist.tools/pdf-cropper coordinate format exactly,
    so a manual override can be pasted directly from that tool into config.py.

    Returns None when:
    - no extractable text blocks are found (scanned PDF), or
    - no block x-span appears on >= presence_threshold of sampled pages.

    Algorithm
    ---------
    1. Sample up to sample_pages evenly-spaced interior pages.
    2. For every text block, snap its x-edges to a SNAP_PT-pt grid and
       record which pages carry that (x0, x1) span.
    3. Discard spans narrower than MIN_BODY_WIDTH_FRAC of page width
       (eliminates pecha margin columns, folio labels, etc.).
    4. The body column is the x-span present on the most pages (ties broken
       by span width - wider wins).
    5. Collect the y-range of all body-column blocks -> bounding box.
    6. Add PADDING_FRAC on all sides; clamp to [0, 1].
    7. Normalise to page fractions and return.
    """
    try:
        import fitz  # type: ignore
    except ImportError:
        try:
            import pymupdf as fitz  # type: ignore
        except ImportError:
            logger.error("detect_margins: PyMuPDF is required. pip install pymupdf")
            return None

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        logger.error("detect_margins: cannot open %s: %s", pdf_path, exc)
        return None

    total_pages = len(doc)
    indices = _sample_page_indices(total_pages, sample_pages)
    n_sampled = len(indices)

    if n_sampled == 0:
        doc.close()
        return None

    ref_page = doc[indices[0]]
    page_w = ref_page.rect.width
    page_h = ref_page.rect.height

    # (snapped_x0, snapped_x1) -> set of page indices that contain that x-span
    x_span_pages: dict = defaultdict(set)
    # (snapped_x0, snapped_x1) -> list of (snapped_y0, snapped_y1) seen
    x_span_ybands: dict = defaultdict(list)

    total_blocks = 0
    min_body_w = page_w * MIN_BODY_WIDTH_FRAC

    for pi in indices:
        page = doc[pi]
        for block in page.get_text("rawdict").get("blocks", []):
            if block.get("type", 1) != 0:
                continue  # skip image blocks
            bx0, by0, bx1, by1 = block["bbox"]
            if (bx1 - bx0) < min_body_w:
                continue  # too narrow to be the body column
            sx0, sx1 = _snap(bx0), _snap(bx1)
            sy0, sy1 = _snap(by0), _snap(by1)
            x_span_pages[(sx0, sx1)].add(pi)
            x_span_ybands[(sx0, sx1)].append((sy0, sy1))
            total_blocks += 1

    doc.close()

    if total_blocks == 0:
        logger.warning(
            "detect_margins: no wide text blocks found in %s — "
            "cannot auto-detect margins (scanned PDF or unusual layout)",
            pdf_path.name,
        )
        return None

    threshold_count = presence_threshold * n_sampled

    qualifying = {
        span: pages
        for span, pages in x_span_pages.items()
        if len(pages) >= threshold_count
    }

    if not qualifying:
        logger.warning(
            "detect_margins: no body column found in %s "
            "(no x-span on >=%.0f%% of %d sampled pages) — skipping redaction",
            pdf_path.name, presence_threshold * 100, n_sampled,
        )
        return None

    # Body column = most-pages span; ties broken by width
    body_span = max(
        qualifying.keys(),
        key=lambda s: (len(qualifying[s]), s[1] - s[0]),
    )
    body_x0_snap, body_x1_snap = body_span

    # y-range: union of all body-column block y-bands
    ybands = x_span_ybands[body_span]
    body_y0_snap = min(y0 for y0, _ in ybands)
    body_y1_snap = max(y1 for _, y1 in ybands)

    # Convert to fractions, add padding, clamp to [0, 1]
    fx0 = max(0.0, body_x0_snap / page_w - PADDING_FRAC)
    fy0 = max(0.0, body_y0_snap / page_h - PADDING_FRAC)
    fx1 = min(1.0, body_x1_snap / page_w + PADDING_FRAC)
    fy1 = min(1.0, body_y1_snap / page_h + PADDING_FRAC)

    preserve = (round(fx0, 4), round(fy0, 4), round(fx1, 4), round(fy1, 4))

    logger.info(
        "detect_margins: %s — sampled %d/%d pages, "
        "body x-span=(%.1f, %.1f)pt on %d/%d pages -> "
        "preserve_rect=(%.4f, %.4f, %.4f, %.4f)  [fractions of %.0fx%.0f pt page]",
        pdf_path.name, n_sampled, total_pages,
        body_x0_snap, body_x1_snap,
        len(qualifying[body_span]), n_sampled,
        *preserve, page_w, page_h,
    )
    return preserve
