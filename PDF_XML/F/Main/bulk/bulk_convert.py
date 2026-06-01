#!/usr/bin/env python3
"""
bulk_convert.py — batch PDF→TEI conversion for many BUDA IE worksets.

Drop-in replacement for the older ``bulk_multi_ie.py``.  Walks every direct
child of ROOT named ``IE...`` and runs ``convert_pdf_to_xml.py`` once per
workset, each in its own subprocess with isolated env vars, logs, and
checkpoints.

What it adds over the old script
--------------------------------
* **Auto-detects** the input subfolder per IE (``sources/`` or ``to_convert/``)
  so the same root can mix the Unicode-PDF and legacy-font pipelines.
* **Resume**: tracks completed IEs in ``<ROOT>/checkpoints/_bulk_state.json``
  and skips them on re-run unless ``--force`` (or ``--force-ie``) is passed.
* **Progress bar** + rolling ETA across worksets (live, on stderr).
* **Per-IE manifest** (``--manifest manifest.yaml`` / ``.json``): override
  crop fractions, preserve-box, FONT_DIR, and any pass-through flags per IE.
* **Dry-run**: reports pipeline auto-detect, PDF counts, and skip-vs-run
  status for every IE without converting anything.
* **Summary report**: prints to stdout and writes
  ``<ROOT>/logs/_bulk_summary.{txt,json}`` with per-IE status, duration,
  PDF count, output path, and the tail of any error.

Layout assumed::

    ROOT/
      IE1KG25273/sources/*.pdf         OR  IE1KG25273/to_convert/<VE>/*.pdf
      IE2KG209991/sources/*.pdf        OR  IE2KG209991/to_convert/<VE>/*.pdf
      ...
      # auto-created:
      IE1KG25273_output/, IE2KG209991_output/, ...
      checkpoints/<IE_ID>/, logs/<IE_ID>/
      checkpoints/_bulk_state.json     # bulk-driver resume state
      logs/_bulk_summary.{txt,json}    # last run's report

Examples
--------
::

    # Dry-run: see what would happen, no conversions
    python bulk_convert.py -r /path/to/parent --dry-run

    # Full bulk run, default parallelism
    python bulk_convert.py -r /path/to/parent

    # 4 workers, only two specific IEs
    python bulk_convert.py -r /path/to/parent -j 4 --ie IE1KG25273 --ie IE2KG209991

    # With a manifest of per-IE overrides
    python bulk_convert.py -r /path/to/parent --manifest overrides.yaml

    # Force re-run a previously completed IE
    python bulk_convert.py -r /path/to/parent --force-ie IE1KG25273

    # Pass extra flags through to convert_pdf_to_xml.py
    python bulk_convert.py -r /path/to/parent -- --no-font-tags --no-phantom-space
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from multiprocessing import Pool
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
_CONVERT = _SCRIPT_DIR / "convert_pdf_to_xml.py"

# BUDA-style image group folders: IE + digits/letters (e.g. IE1KG25273).
_IE_NAME_RE = re.compile(r"^IE[A-Z0-9]+$", re.IGNORECASE)

# Names we'll probe (in order) for the input subfolder containing PDFs.
_INPUT_SUBDIR_CANDIDATES = ("sources", "to_convert")


# ─── Manifest types ───────────────────────────────────────────────────────


@dataclass
class IEOverrides:
    """Per-IE overrides loaded from the manifest file."""

    crop_top: Optional[float] = None
    crop_bottom: Optional[float] = None
    preserve_box: Optional[Sequence[float]] = None  # [x0, y0, x1, y1]
    font_dir: Optional[str] = None
    no_font_tags: bool = False
    no_normalization: bool = False
    no_extraction_dedup: bool = False
    no_phantom_space: bool = False
    extra_args: list[str] = field(default_factory=list)

    def to_cli_args(self) -> list[str]:
        """Render this override into convert_pdf_to_xml.py CLI flags."""
        args: list[str] = []
        if self.crop_top is not None:
            args += ["--crop-top", str(self.crop_top)]
        if self.crop_bottom is not None:
            args += ["--crop-bottom", str(self.crop_bottom)]
        if self.preserve_box is not None:
            pb = list(self.preserve_box)
            if len(pb) != 4:
                raise ValueError(f"preserve_box must have 4 floats, got {pb!r}")
            args += ["--preserve-box", *[str(x) for x in pb]]
        if self.no_font_tags:
            args.append("--no-font-tags")
        if self.no_normalization:
            args.append("--no-normalization")
        if self.no_extraction_dedup:
            args.append("--no-extraction-dedup")
        if self.no_phantom_space:
            args.append("--no-phantom-space")
        if self.extra_args:
            args.extend(self.extra_args)
        return args


def _coerce_override(d: dict[str, Any]) -> IEOverrides:
    """Accept lenient key spellings (hyphen or underscore) from manifest."""
    norm = {k.replace("-", "_"): v for k, v in d.items()}
    valid_keys = {f.name for f in IEOverrides.__dataclass_fields__.values()}
    unknown = set(norm) - valid_keys
    if unknown:
        raise ValueError(f"Unknown manifest key(s): {sorted(unknown)}")
    return IEOverrides(**norm)


def load_manifest(path: Path) -> dict[str, IEOverrides]:
    """Load per-IE overrides from a YAML or JSON file.

    Top-level shape::

        defaults:           # optional, applied to every IE first
          crop_top: 0.05
        IE1KG25273:
          crop_top: 0.10
          preserve_box: [0.11, 0.09, 0.89, 0.82]
        IE2KG999:
          no_font_tags: true
    """
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ImportError as e:
            raise SystemExit(
                f"Manifest {path} is YAML but PyYAML is not installed. "
                "Install it (pip install pyyaml) or use a .json manifest."
            ) from e
        data = yaml.safe_load(raw) or {}
    else:
        data = json.loads(raw)

    if not isinstance(data, dict):
        raise ValueError(f"Manifest root must be a mapping, got {type(data).__name__}")

    defaults_dict = data.pop("defaults", None) or {}
    defaults = _coerce_override(defaults_dict) if defaults_dict else IEOverrides()

    out: dict[str, IEOverrides] = {}
    for ie_id, override_dict in data.items():
        if override_dict is None:
            override_dict = {}
        if not isinstance(override_dict, dict):
            raise ValueError(f"Manifest entry for {ie_id} must be a mapping")
        # Start from defaults, then layer IE-specific values.
        merged_dict = {**asdict(defaults), **override_dict}
        out[ie_id] = _coerce_override(merged_dict)
    # Defaults applies to IEs not listed too — record under sentinel "*".
    if defaults_dict:
        out.setdefault("*", defaults)
    return out


# ─── Workset discovery and pipeline detection ─────────────────────────────


@dataclass
class Workset:
    """One discoverable IE folder under ROOT."""

    ie_id: str
    path: Path
    input_subdir: str          # "sources" or "to_convert"
    pipeline: str              # "unicode" or "legacy" (best guess)
    pdf_count: int
    output_dir: Path


def _detect_input_subdir(ie_dir: Path) -> Optional[str]:
    """Return ``sources`` or ``to_convert`` (whichever has PDFs), or None."""
    for name in _INPUT_SUBDIR_CANDIDATES:
        sub = ie_dir / name
        if not sub.is_dir():
            continue
        # Recurse one level deep — most layouts are sub/VE_ID/*.pdf, but
        # some are flat sub/*.pdf.  rglob is fine since IE input folders
        # are small.
        try:
            for pdf in sub.rglob("*.pdf"):
                if pdf.is_file():
                    return name
        except OSError:
            continue
    return None


def _count_pdfs(input_dir: Path) -> int:
    return sum(1 for p in input_dir.rglob("*.pdf") if p.is_file())


# Font-name fragments that strongly indicate the legacy-font pipeline.
# These are PDFs where pytiblegenc's byte-table decoding is required.
_LEGACY_FONT_HINTS = (
    "TB-Youtso",
    "TCRC",
    "TibetanMachine",
    "Bod-Yig",
    "Chogyal",
    "Esukhia",
    "Sambhota",
    "Qomolangma",
    "DDC-",
    "Jomolhari",
)
# Font-name fragments that indicate the modern Unicode pipeline.
_UNICODE_FONT_HINTS = (
    "Monlam",
    "Microsoft Himalaya",
    "Noto",
    "Tibetan Machine Uni",
)


def _detect_pipeline(input_dir: Path) -> str:
    """Best-effort pipeline pick by sniffing fonts in the first PDF found.

    Returns ``"legacy"`` when any legacy font hint matches and no unicode
    hint dominates, else ``"unicode"``.  Falls back to ``"unicode"`` when
    PyMuPDF is unavailable or no font names can be read — that pipeline is
    safe for both kinds of input (it just won't apply pytiblegenc tables).
    """
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        try:
            import fitz  # type: ignore  # noqa: F401
        except ImportError:
            return "unicode"

    # Pick the first PDF deterministically (sorted), since that's what the
    # converter will hit first too.
    pdfs = sorted(input_dir.rglob("*.pdf"))
    if not pdfs:
        return "unicode"

    try:
        doc = fitz.open(str(pdfs[0]))
    except Exception:
        return "unicode"

    seen_fonts: set[str] = set()
    try:
        # Only inspect the first few pages — fonts are declared early.
        for page in doc[:3] if hasattr(doc, "__getitem__") else doc:
            try:
                for f in page.get_fonts(full=True):
                    # f = (xref, ext, type, basefont, name, encoding)
                    basefont = f[3] if len(f) > 3 else ""
                    if basefont:
                        # Strip PDF subset prefix "ABCDEF+"
                        clean = basefont.split("+", 1)[-1] if "+" in basefont else basefont
                        seen_fonts.add(clean)
            except Exception:
                continue
    finally:
        doc.close()

    has_legacy = any(any(h.lower() in f.lower() for h in _LEGACY_FONT_HINTS) for f in seen_fonts)
    has_unicode = any(any(h.lower() in f.lower() for h in _UNICODE_FONT_HINTS) for f in seen_fonts)

    if has_legacy and not has_unicode:
        return "legacy"
    if has_legacy and has_unicode:
        # Mixed — pick legacy since it's the more aggressive decoder and
        # falls through to PyMuPDF's native chars for non-legacy fonts.
        return "legacy"
    return "unicode"


def discover_worksets(
    root: Path,
    only: Optional[Sequence[str]] = None,
) -> list[Workset]:
    """Walk ROOT, return one Workset per IE folder with discoverable PDFs."""
    root = root.resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Not a directory: {root}")

    want_cf = {x.strip().casefold() for x in only} if only else None
    out: list[Workset] = []

    for child in sorted(root.iterdir(), key=lambda p: p.name.casefold()):
        if not child.is_dir():
            continue
        if not _IE_NAME_RE.match(child.name):
            continue
        if want_cf is not None and child.name.casefold() not in want_cf:
            continue

        subdir_name = _detect_input_subdir(child)
        if subdir_name is None:
            continue  # silently skip IEs with no recognizable input folder

        input_dir = child / subdir_name
        pdf_count = _count_pdfs(input_dir)
        if pdf_count == 0:
            continue

        pipeline = _detect_pipeline(input_dir)
        out.append(
            Workset(
                ie_id=child.name,
                path=child,
                input_subdir=subdir_name,
                pipeline=pipeline,
                pdf_count=pdf_count,
                output_dir=root / f"{child.name}_output",
            )
        )

    return out


# ─── Bulk state (resume) ──────────────────────────────────────────────────


def _state_path(root: Path) -> Path:
    return root / "checkpoints" / "_bulk_state.json"


def load_bulk_state(root: Path) -> dict[str, dict[str, Any]]:
    """Read the bulk-driver state file.  Missing/corrupt → empty dict."""
    p = _state_path(root)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_bulk_state(root: Path, state: dict[str, dict[str, Any]]) -> None:
    p = _state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _is_ie_already_complete(ws: Workset, state: dict[str, dict[str, Any]]) -> bool:
    """An IE is considered complete when the bulk state marks it 'ok' AND
    its output archive directory has at least one .xml file (defence against
    stale state from an output dir that was deleted)."""
    rec = state.get(ws.ie_id)
    if not rec or rec.get("status") != "ok":
        return False
    archive_dir = ws.output_dir / "archive"
    if not archive_dir.is_dir():
        return False
    for _ in archive_dir.rglob("*.xml"):
        return True
    return False


# ─── Subprocess execution ─────────────────────────────────────────────────


def _build_subprocess_env(
    root_s: str,
    ws: Workset,
    override: Optional[IEOverrides],
) -> dict[str, str]:
    env = os.environ.copy()
    env["PDF_BULK_BASE_DIR"] = root_s
    env["PDF_BULK_IE_ID"] = ws.ie_id
    env["PDF_BULK_INPUT_SUBDIR"] = ws.input_subdir
    if override and override.font_dir is not None:
        # Empty string explicitly clears FONT_DIR.
        env["PDF_BULK_FONT_DIR"] = override.font_dir
    return env


def _run_one(payload: tuple[str, Workset, list[str], Optional[IEOverrides]]) -> dict[str, Any]:
    """Run conversion for one IE; module-level for Pool pickling."""
    root_s, ws, forward_args, override = payload

    cli_args = list(forward_args)
    if override:
        cli_args = override.to_cli_args() + cli_args

    cmd = [sys.executable, str(_CONVERT), *cli_args]
    env = _build_subprocess_env(root_s, ws, override)

    start = time.monotonic()
    proc = subprocess.run(
        cmd,
        env=env,
        cwd=str(_SCRIPT_DIR),
        capture_output=True,
        text=True,
    )
    duration = time.monotonic() - start

    # Compose a useful tail: last lines of stdout, plus stderr if it failed.
    tail = ""
    if proc.stdout:
        lines = proc.stdout.strip().splitlines()
        tail = "\n".join(lines[-30:]) if len(lines) > 30 else proc.stdout.strip()
    if proc.returncode != 0 and proc.stderr:
        err = proc.stderr.strip()
        tail = (tail + "\n--- stderr ---\n" + err) if tail else err

    rc = proc.returncode if proc.returncode is not None else -1
    return {
        "ie_id": ws.ie_id,
        "pipeline": ws.pipeline,
        "input_subdir": ws.input_subdir,
        "pdf_count": ws.pdf_count,
        "output_dir": str(ws.output_dir),
        "returncode": rc,
        "status": "ok" if rc == 0 else "failed",
        "duration_s": round(duration, 2),
        "tail": tail,
    }


# ─── Progress bar ─────────────────────────────────────────────────────────


def _fmt_eta(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # NaN guard
        return "--:--"
    td = timedelta(seconds=int(seconds))
    return str(td)


def _emit_progress(
    completed: int,
    total: int,
    ie_id: str,
    status: str,
    durations: list[float],
) -> None:
    """Render a single-line progress bar to stderr.  No external dep."""
    width = 30
    pct = completed / total if total else 1.0
    filled = int(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    if durations:
        avg = sum(durations) / len(durations)
        remaining = (total - completed) * avg
        eta = _fmt_eta(remaining)
    else:
        eta = "--:--"

    msg = (
        f"\r[{bar}] {completed}/{total} ({pct * 100:5.1f}%) "
        f"ETA {eta} | last: {ie_id} {status}"
    )
    # Pad to overwrite any longer previous line.
    sys.stderr.write(msg.ljust(110))
    sys.stderr.flush()


# ─── Summary report ───────────────────────────────────────────────────────


def _write_summary(root: Path, results: list[dict[str, Any]], started_at: datetime) -> tuple[Path, Path]:
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    json_path = log_dir / "_bulk_summary.json"
    txt_path = log_dir / "_bulk_summary.txt"

    finished_at = datetime.now()
    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    failed = total - ok
    total_duration = sum(r["duration_s"] for r in results)
    total_pdfs = sum(r["pdf_count"] for r in results)

    summary_obj = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "wall_clock_s": round((finished_at - started_at).total_seconds(), 2),
        "worksets_total": total,
        "worksets_ok": ok,
        "worksets_failed": failed,
        "pdfs_total": total_pdfs,
        "cpu_seconds_total": round(total_duration, 2),
        "results": sorted(results, key=lambda r: r["ie_id"]),
    }
    json_path.write_text(json.dumps(summary_obj, indent=2), encoding="utf-8")

    # Human-readable text report.
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"Bulk conversion summary  ({started_at:%Y-%m-%d %H:%M:%S} → {finished_at:%H:%M:%S})")
    lines.append("=" * 72)
    lines.append(f"Worksets:  {ok} ok / {failed} failed / {total} total")
    lines.append(f"PDFs:      {total_pdfs}")
    lines.append(f"Wall:      {_fmt_eta(summary_obj['wall_clock_s'])}")
    lines.append(f"CPU sum:   {_fmt_eta(total_duration)}")
    lines.append("")
    lines.append(f"{'IE_ID':<20}  {'PIPE':<8}  {'STATUS':<8}  {'PDFs':>5}  {'DUR':>9}  OUTPUT")
    lines.append("-" * 72)
    for r in sorted(results, key=lambda r: r["ie_id"]):
        lines.append(
            f"{r['ie_id']:<20}  {r['pipeline']:<8}  {r['status']:<8}  "
            f"{r['pdf_count']:>5}  {r['duration_s']:>8.1f}s  {r['output_dir']}"
        )
    if failed:
        lines.append("")
        lines.append("Failures (tail of output):")
        lines.append("-" * 72)
        for r in results:
            if r["status"] == "ok":
                continue
            lines.append(f"\n## {r['ie_id']}  (exit {r['returncode']})")
            lines.append(r["tail"] or "(no output)")
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return json_path, txt_path


# ─── Main ─────────────────────────────────────────────────────────────────


def _print_dry_run(
    worksets: list[Workset],
    state: dict[str, dict[str, Any]],
    overrides_by_ie: dict[str, IEOverrides],
    force_set: set[str],
    force_all: bool,
) -> None:
    print(f"{'IE_ID':<20}  {'PIPE':<8}  {'SUBDIR':<11}  {'PDFs':>5}  {'STATUS':<10}  NOTES")
    print("-" * 80)
    for ws in worksets:
        already = (
            _is_ie_already_complete(ws, state)
            and not force_all
            and ws.ie_id not in force_set
        )
        status = "skip" if already else "run"
        notes_parts: list[str] = []
        if "*" in overrides_by_ie or ws.ie_id in overrides_by_ie:
            notes_parts.append("manifest override")
        if ws.ie_id in force_set:
            notes_parts.append("forced")
        notes = ", ".join(notes_parts) if notes_parts else ""
        print(
            f"{ws.ie_id:<20}  {ws.pipeline:<8}  {ws.input_subdir:<11}  "
            f"{ws.pdf_count:>5}  {status:<10}  {notes}"
        )
    runnable = sum(
        1
        for ws in worksets
        if force_all or ws.ie_id in force_set or not _is_ie_already_complete(ws, state)
    )
    print(f"\nTotal: {len(worksets)} worksets discovered, "
          f"{runnable} would run, {len(worksets) - runnable} would skip.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-run PDF→TEI for every IE*/ folder under a parent directory. "
            "Auto-detects sources/ vs to_convert/ per IE and which extraction "
            "pipeline (unicode vs legacy-font) applies. Forward extras after -- "
            "to convert_pdf_to_xml.py."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python bulk_convert.py -r /path/to/parent --dry-run\n"
            "  python bulk_convert.py -r /path/to/parent -j 4\n"
            "  python bulk_convert.py -r /path/to/parent --manifest overrides.yaml\n"
            "  python bulk_convert.py -r /path/to/parent --force-ie IE1KG25273\n"
            "  python bulk_convert.py -r /path/to/parent -- --no-font-tags\n"
        ),
    )
    parser.add_argument(
        "-r", "--root",
        type=Path,
        required=True,
        help="Parent directory containing IE…/ worksets",
    )
    parser.add_argument(
        "-j", "--jobs",
        type=int,
        default=None,
        metavar="N",
        help="Parallel worker processes (default: min(CPU count, 8))",
    )
    parser.add_argument(
        "--ie",
        action="append",
        dest="ie_only",
        metavar="IE_ID",
        help="Process only this folder name (repeatable; default: all IEs found)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        metavar="PATH",
        help="YAML or JSON file of per-IE overrides (see README §Manifest)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run every IE, ignoring the bulk resume state",
    )
    parser.add_argument(
        "--force-ie",
        action="append",
        dest="force_ies",
        metavar="IE_ID",
        default=[],
        help="Re-run only this IE even if previously completed (repeatable)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would run; do not convert anything",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Suppress the live progress bar (useful for CI / log capture)",
    )
    parser.add_argument(
        "--quiet-children",
        action="store_true",
        help="Don't dump each child's stdout tail to stderr while running "
             "(reduces interleaving; summary still captures it)",
    )
    args, forward = parser.parse_known_args()

    # Strip an optional explicit "--" boundary before forwarding.
    if "--" in forward:
        idx = forward.index("--")
        forward = forward[idx + 1:]

    if not _CONVERT.is_file():
        print(f"Missing converter script: {_CONVERT}", file=sys.stderr)
        return 2

    # 1. Discover worksets.
    try:
        worksets = discover_worksets(args.root, args.ie_only)
    except NotADirectoryError as e:
        print(e, file=sys.stderr)
        return 2

    if not worksets:
        print(
            f"No IE worksets under {args.root.resolve()}\n"
            f"  Expected: direct child folders matching IE… that contain "
            f"either sources/ or to_convert/ with at least one .pdf inside.",
            file=sys.stderr,
        )
        return 1

    # 2. Load manifest and resume state.
    overrides_by_ie: dict[str, IEOverrides] = {}
    if args.manifest:
        if not args.manifest.is_file():
            print(f"Manifest not found: {args.manifest}", file=sys.stderr)
            return 2
        try:
            overrides_by_ie = load_manifest(args.manifest)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"Manifest parse error: {e}", file=sys.stderr)
            return 2

    state = load_bulk_state(args.root)
    force_set = set(args.force_ies)

    root_s = str(args.root.resolve())
    print(f"Root:           {root_s}")
    print(f"Worksets found: {len(worksets)}")
    print(f"Resume state:   {len(state)} previous entry(ies)")
    if overrides_by_ie:
        explicit = [k for k in overrides_by_ie if k != "*"]
        print(f"Manifest:       {args.manifest}  ({len(explicit)} IE override(s)"
              f"{', with defaults' if '*' in overrides_by_ie else ''})")
    print()

    # 3. Dry-run? Print table and exit.
    if args.dry_run:
        _print_dry_run(worksets, state, overrides_by_ie, force_set, args.force)
        return 0

    # 4. Filter out already-complete worksets (unless forced).
    to_run: list[Workset] = []
    skipped: list[Workset] = []
    for ws in worksets:
        if not args.force and ws.ie_id not in force_set and _is_ie_already_complete(ws, state):
            skipped.append(ws)
        else:
            to_run.append(ws)

    if skipped:
        names = ", ".join(ws.ie_id for ws in skipped[:5])
        more = f", +{len(skipped) - 5} more" if len(skipped) > 5 else ""
        print(f"Skipping (already complete): {names}{more}  "
              f"— pass --force or --force-ie to re-run")
        print()

    if not to_run:
        print("Nothing to do.  Use --force to re-run completed worksets.")
        return 0

    # 5. Build payloads.
    default_override = overrides_by_ie.get("*")

    def _resolve_override(ie_id: str) -> Optional[IEOverrides]:
        # An explicit IE entry already had defaults merged in by load_manifest.
        if ie_id in overrides_by_ie:
            return overrides_by_ie[ie_id]
        return default_override

    payloads = [
        (root_s, ws, list(forward), _resolve_override(ws.ie_id))
        for ws in to_run
    ]

    # 6. Run.
    ncpu = os.cpu_count() or 1
    jobs = max(1, args.jobs if args.jobs is not None else min(ncpu, 8))
    print(f"Running {len(to_run)} workset(s) with {jobs} parallel worker(s)…")
    print()

    show_progress = (not args.no_progress) and sys.stderr.isatty()
    started_at = datetime.now()
    results: list[dict[str, Any]] = []
    durations: list[float] = []

    def _on_result(r: dict[str, Any]) -> None:
        results.append(r)
        durations.append(r["duration_s"])
        # Update persistent state immediately so a Ctrl-C doesn't lose progress.
        state[r["ie_id"]] = {
            "status": r["status"],
            "returncode": r["returncode"],
            "duration_s": r["duration_s"],
            "pdf_count": r["pdf_count"],
            "pipeline": r["pipeline"],
            "input_subdir": r["input_subdir"],
            "output_dir": r["output_dir"],
            "completed_at": datetime.now().isoformat(timespec="seconds"),
        }
        save_bulk_state(args.root, state)

        if show_progress:
            _emit_progress(len(results), len(to_run), r["ie_id"], r["status"], durations)

        if not args.quiet_children:
            # One blank line above so it lands cleanly under the progress bar.
            sys.stderr.write("\n")
            print(f"\n========== {r['ie_id']} ({r['pipeline']}, exit {r['returncode']}, {r['duration_s']:.1f}s) ==========")
            if r["tail"]:
                print(r["tail"])

    try:
        if jobs == 1:
            for pl in payloads:
                _on_result(_run_one(pl))
        else:
            with Pool(processes=jobs) as pool:
                for r in pool.imap_unordered(_run_one, payloads):
                    _on_result(r)
    except KeyboardInterrupt:
        print("\n\nInterrupted.  Partial state saved; rerun to resume.", file=sys.stderr)
        # Still try to write a summary for whatever finished.

    if show_progress:
        sys.stderr.write("\n")
        sys.stderr.flush()

    # 7. Summary report.
    json_path, txt_path = _write_summary(args.root, results, started_at)

    failures = [r for r in results if r["status"] != "ok"]
    print("\n" + "=" * 72)
    if failures:
        print(f"Finished with {len(failures)} failure(s): "
              f"{', '.join(r['ie_id'] for r in failures)}")
    else:
        print(f"All {len(results)} workset(s) completed successfully.")
    print(f"Summary:        {txt_path}")
    print(f"Summary (JSON): {json_path}")
    print(f"Bulk state:     {_state_path(args.root)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
