from pathlib import Path

IE_ID = "IE8LS75875"

BASE_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/6th_batch_conversion/archive_fitered_pdfs/process")
#BASE_DIR = Path(r"/Users/tenzinmonlam/Documents/dharmaduta/pdf_convert_5")
# IE3KG648 : --preserve-box 0.12 0.06 0.87 0.86
# IE3KG219 : --preserve-box 0.11 0.02 0.89 0.90
# IE3KG719 : --preserve-box 0.11 0.06 0.89 0.80
# IE3KG710 : 0.10 0.00 0.89 0.91
# IE3KG721 : 0.11 0.04 0.89 0.83
# IE2KG229147: 0.11 0.03 0.88 0.89
# Input PDFs: BASE_DIR / IE_ID / to_convert / VE_ID / *.pdf

SOURCES_DIR = BASE_DIR / IE_ID / "to_convert"
TOPROCESS_DIR = BASE_DIR / IE_ID / "toprocess"
OUTPUT_DIR = BASE_DIR / f"{IE_ID}_output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

LOG_DIR = BASE_DIR / "logs"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"

PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"
# ─── Header/footer redaction (physical) ───────────────────────────────
# 0.0 = none. Typical: 0.07–0.12. Override with --crop-top / --crop-bottom.
CROP_HEADER_FRACTION: float = 0.00  # e.g. 0.08  strips top 8 %
CROP_FOOTER_FRACTION: float = 0.00   # e.g. 0.07  strips bottom 7 %

def ensure_directories():
    for d in [
        OUTPUT_DIR,
        ARCHIVE_DIR,
        SOURCES_OUTPUT_DIR,
        LOG_DIR,
        CHECKPOINT_DIR,
    ]:
        d.mkdir(parents=True, exist_ok=True)


def extract_ve_id_from_folder(folder_name: str) -> str:
    if folder_name.startswith(f"{IE_ID}-"):
        return folder_name.replace(f"{IE_ID}-", "")
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    ve_suffix = ve_id[2:]
    return f"UT{ve_suffix}_{sequence:04d}"


def get_max_archive_sequence(ve_id: str) -> int:
    archive_ve = ARCHIVE_DIR / ve_id
    if not archive_ve.exists():
        return 0
    sequences = []
    for path in archive_ve.glob("UT*.xml"):
        parts = path.stem.split("_")
        if len(parts) >= 2:
            try:
                sequences.append(int(parts[-1]))
            except ValueError:
                pass
    return max(sequences, default=0)
