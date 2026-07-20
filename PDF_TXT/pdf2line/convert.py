"""
pdf2line.convert - Orchestrate extraction -> assembly -> normalization -> file.

One .txt per PDF written flat into one output dir.

Output structure:
- Non-Tibetan boilerplate is one block at the top with single newlines.
- Visual line breaks within a pecha page are preserved as single newlines.
- Pecha pages are separated by a blank line (double newline).
"""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List

from .extract import extract_pages
from .assemble import split_into_pages
from .normalize import normalize_line

logger = logging.getLogger("pdf2line.convert")


@dataclass
class Result:
    pdf: str
    txt: str
    pages: int
    ok: bool
    error: str = ""
    seconds: float = 0.0


def convert_pdf(
    pdf_path: Path,
    out_dir: Path,
    *,
    backend: str = "hybrid",
    crop_top: float = 0.0,
    crop_bottom: float = 0.0,
    keep_page_numbers: bool = False,
    collect_boilerplate: bool = True,
    normalize: bool = False,
    overwrite: bool = False,
    two_up: bool = False,
    auto_two_up: bool = False,
    hybrid_min_tibetan_ratio: float = 0.20,
) -> Result:
    """
    Convert one PDF into one .txt.

    Visual line breaks within a pecha page are preserved and pecha pages are
    separated by a blank line (double newline).

    Parameters
    ----------
    two_up :
        Force split each PDF page into left and right halves before extraction
        (for scans where one PDF page contains two facing pecha pages).
    auto_two_up :
        Automatically detect two-up scans based on page aspect ratio
        (width > 1.5x height triggers the split).
    hybrid_min_tibetan_ratio :
        Threshold used by the hybrid backend to decide whether to retry with
        pytiblegenc (default 0.20).
    """
    start = time.time()
    out_path = out_dir / (pdf_path.stem + ".txt")

    if out_path.exists() and not overwrite:
        return Result(pdf_path.name, out_path.name, 0, True,
                      "skipped (exists; use --overwrite)", 0.0)

    try:
        pages = extract_pages(
            pdf_path,
            backend=backend,
            crop_top=crop_top,
            crop_bottom=crop_bottom,
            two_up=two_up,
            auto_two_up=auto_two_up,
            hybrid_min_tibetan_ratio=hybrid_min_tibetan_ratio,
        )
        lines = split_into_pages(
            pages,
            drop_page_numbers=not keep_page_numbers,
            collect_boilerplate=collect_boilerplate,
        )
        if normalize:
            lines = [normalize_line(l) for l in lines]

        out_dir.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")
        return Result(pdf_path.name, out_path.name, len(lines), True,
                      "", round(time.time() - start, 2))
    except Exception as exc:
        logger.error("FAILED %s: %s", pdf_path.name, exc)
        return Result(pdf_path.name, out_path.name, 0, False,
                      str(exc), round(time.time() - start, 2))


def discover_pdfs(input_dir: Path, recursive: bool) -> List[Path]:
    pattern = "**/*.pdf" if recursive else "*.pdf"
    return sorted(p for p in input_dir.glob(pattern) if p.is_file())


def convert_folder(
    input_dir: Path,
    out_dir: Path,
    *,
    recursive: bool = False,
    jobs: int = 1,
    write_summary: bool = True,
    **pdf_kwargs,
) -> List[Result]:
    """Convert every PDF under input_dir; flat output into out_dir."""
    pdfs = discover_pdfs(input_dir, recursive)
    if not pdfs:
        logger.warning("No PDFs found in %s (recursive=%s)", input_dir, recursive)
        return []

    logger.info("Found %d PDF(s) in %s", len(pdfs), input_dir)
    results: List[Result] = []

    if jobs and jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            futs = {ex.submit(convert_pdf, p, out_dir, **pdf_kwargs): p for p in pdfs}
            for fut in as_completed(futs):
                pdf_path = futs[fut]
                try:
                    r = fut.result()
                except Exception as exc:
                    # Worker crash: wrap as a failed Result so the batch continues.
                    r = Result(pdf_path.name, pdf_path.stem + ".txt", 0, False,
                               "worker crash: " + str(exc), 0.0)
                    logger.error("WORKER CRASH %s: %s", pdf_path.name, exc)
                results.append(r)
                _log(r)
    else:
        for p in pdfs:
            r = convert_pdf(p, out_dir, **pdf_kwargs)
            results.append(r)
            _log(r)

    results.sort(key=lambda r: r.pdf)
    ok = [r for r in results if r.ok and not r.error.startswith("skipped")]
    failed = [r for r in results if not r.ok]
    logger.info("DONE. %d ok, %d failed, %d pages.",
                len(ok), len(failed), sum(r.pages for r in ok))

    if write_summary and results:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "_summary.json").write_text(
            json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return results


def _log(r: Result) -> None:
    if r.error.startswith("skipped"):
        logger.info("  - %s (%s)", r.pdf, r.error)
    elif r.ok:
        logger.info("  OK %s -> %s (%d pages, %.2fs)", r.pdf, r.txt, r.pages, r.seconds)
    else:
        logger.info("  XX %s FAILED: %s", r.pdf, r.error)
