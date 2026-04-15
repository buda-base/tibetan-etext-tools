"""
IE3KG694: PDF in flat sources/ -> TEI XML (pytiblegenc).
VE ID(s) from toprocess/IE3KG694-VE* folder names.
"""

from pathlib import Path

IE_ID = "IE3KG694"

BASE_DIR = Path(r"D:\Work\OpenPecha\conversion\IE3KG694")

# Input PDFs (flat)
SOURCES_DIR = BASE_DIR / "IE3KG694" / "sources"

# VE discovery: folders IE3KG664-VE*
TOPROCESS_DIR = BASE_DIR / "IE3KG694" / "toprocess"

OUTPUT_DIR = BASE_DIR / "IE3KG694_output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

LOG_DIR = BASE_DIR / "logs"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"
PDF_TO_XML_LOG = LOG_DIR / "pdf_to_xml.log"
PDF_TO_XML_CHECKPOINT = CHECKPOINT_DIR / "pdf_to_xml_checkpoint.txt"

# Optional crop for pytiblegenc ``pdf_to_txt(..., region=...)``: [x, y, width, height].
# Floats in (0, 1) are page-relative (see pytiblegenc). None or [] = extract full page.
PDF_EXTRACT_REGION = [0.11, 0.03, 0.78, 0.82] # e.g. [0.13, 0.09, 0.76, 0.81]
# [0.11, 0.01, 0.78, 0.84] [0.11, 0.09, 0.78, 0.76] VE1ER1074
# [0.11, 0.10, 0.78, 0.75] VE1ER1075
# [0.11, 0.11, 0.78, 0.75] VE1ER1076
# [0.11, 0.11, 0.78, 0.75] VE1ER1077
# [0.11, 0.11, 0.78, 0.75] VE1ER1078
# [0.11, 0.11, 0.78, 0.75] VE1ER1079
# [0.11, 0.11, 0.78, 0.75] VE1ER1080
# [0.11, 0.11, 0.78, 0.75] VE1ER1081
# [0.11, 0.11, 0.78, 0.75] VE1ER1082
# [0.11, 0.11, 0.78, 0.75] VE1ER1083
# [0.11, 0.11, 0.78, 0.75] VE1ER1084
# [0.11, 0.11, 0.78, 0.75] VE1ER1085

# "pytiblegenc" — legacy Dedris conversion + pdfminer layout (default).
# "pymupdf" — PyMuPDF layout + ``<fs:N>`` + pytiblegenc ``convert_string`` per span (like pdfminer path).
# "tesseract" — PyMuPDF rasterize (same ``PDF_EXTRACT_REGION`` clip) + Tesseract OCR.
PDF_EXTRACT_BACKEND = "tesseract"

# Used when ``PDF_EXTRACT_BACKEND`` is ``"tesseract"`` (see ``tesseract_extractor``).
PDF_EXTRACT_TESS_DPI = 300.0
PDF_EXTRACT_TESS_LANG = "bod"
PDF_EXTRACT_TESS_CONFIG = ""  # optional extra Tesseract CLI flags, e.g. "--psm 6"


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
