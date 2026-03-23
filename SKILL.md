# BDRC Etext Conversion Skill

This skill guides the conversion of Tibetan etext documents (DOC, DOCX, RTF, PDF) to TEI XML format for the Buddhist Digital Resource Center (BDRC).

## When to Use This Skill

Activate this skill when:

- User mentions a new IE project ID (e.g., "IE3XXX", "IE1KG14", "IE3CN4059")
- User asks to convert DOC/DOCX/RTF/PDF files to XML
- User mentions "toprocess", "sources", or "volume" folders
- User encounters font encoding issues (garbled Tibetan text)
- User needs to set up a new conversion pipeline

## General Workflow

1. Download input zip from `files_to_process/` folder (Google Drive)
2. Extract to local workspace: `C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\{IE_ID}\`
3. Analyze input structure (see Step 1)
4. Create/copy appropriate scripts to `tibetan-etext-tools/{IE_ID}/`
5. Run conversion pipeline
6. Validate output XML
7. Zip output and upload to `files_processed/` folder

## Step 1: Analyze Input Structure

### Folder Structure Patterns

**Pattern A: Files inside VE folders**
```
{IE_ID}/
├── {IE_ID}/
│   └── toprocess/
│       ├── {IE_ID}-VE{xxx}/
│       │   ├── file1.doc
│       │   └── file2.doc
│       └── {IE_ID}-VE{yyy}/
│           └── files...
```

**Pattern B: Flat sources folder (VE from toprocess folder names)**
```
{IE_ID}/
├── {IE_ID}/
│   ├── sources/
│   │   ├── file1.rtf
│   │   ├── file2.rtf
│   │   └── ...
│   └── toprocess/
│       └── {IE_ID}-VE{xxx}/  (empty, just for VE ID)
```

**Pattern C: Nested subfolders**
```
{IE_ID}/
├── {IE_ID}/
│   └── toprocess/
│       └── {IE_ID}-VE{xxx}/
│           └── subfolder.doc/  (folder named with .doc!)
│               ├── 1-24.doc
│               └── 25-48.doc
```

### Analysis Commands

```python
# List toprocess structure
from pathlib import Path
toprocess = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\{IE_ID}\{IE_ID}\toprocess")
for folder in toprocess.iterdir():
    print(f"{folder.name}: {list(folder.glob('*'))[:5]}")

# Check file extensions
extensions = set()
for f in toprocess.rglob("*"):
    if f.is_file():
        extensions.add(f.suffix.lower())
print(f"File types: {extensions}")
```

## Step 2: Select Conversion Pipeline

### Decision Tree

1. **What file extension?**
   - `.doc` -> Go to step 2
   - `.docx` -> Use DOCX to XML pipeline
   - `.rtf` -> Use RTF to XML pipeline
   - `.pdf` -> Use PDF to XML pipeline

2. **For .doc files, check font type:**
   - Open in Word, check font names
   - Dedris/legacy fonts -> DOC to PDF to XML (pytiblegenc)
   - Unicode fonts -> DOC to DOCX to XML

3. **For RTF/PDF, check font type:**
   - TibetanChogyal/TibetanClassic -> Use `is_legacy_tibetan_font()` 
   - Dedris -> Use pytiblegenc `convert_string()`
   - Unicode -> Pass through directly

### Pipeline Reference Table

| Input Pattern | Pipeline | Reference Project | Key Scripts |
|---------------|----------|-------------------|-------------|
| DOC in VE folders (Unicode) | DOC->DOCX->XML | IE2PD17467 | `1_convert_doc_to_docx.py`, `2_convert_docx_to_xml.py` |
| DOC in VE folders (Dedris) | DOC->PDF->XML | IE3CN4059, IE3CN26475 | `1_convert_doc_to_pdf.py`, `2_convert_pdf_to_xml.py` |
| DOC nested subfolders | DOC->PDF->XML | IE3CN4059 | Same as above, with recursive file search |
| RTF flat (TibetanChogyal) | RTF->XML | IE3KG235 | `convert_rtf_to_xml.py` |
| PDF flat (Dedris) | PDF->XML | IE3KG664, IE1KG14 | `convert_pdf_to_xml.py` |
| DOCX in VE folders | DOCX->XML | IE3CN5624, IE3KG184 | `convert_docx_to_xml.py` |
| DOC (fallback) | DOC->RTF->XML | IE3CN8070 | `1_convert_doc_to_rtf.py`, `2_convert_rtf_to_xml.py` |

## Step 3: Generate Project Scripts

### Config.py Template

Create `tibetan-etext-tools/{IE_ID}/config.py`:

```python
"""
Shared Configuration for {IE_ID} Conversion Pipeline

{DESCRIPTION}
"""

from pathlib import Path

# =============================================================================
# Project Configuration
# =============================================================================

IE_ID = "{IE_ID}"

BASE_DIR = Path(r"C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\{IE_ID}")

# Input: Adjust based on input structure
TOPROCESS_DIR = BASE_DIR / "{IE_ID}" / "toprocess"
SOURCES_DIR = BASE_DIR / "{IE_ID}" / "sources"  # For flat input pattern

# Intermediate (if needed)
# DOCX_DIR = BASE_DIR / "{IE_ID}" / "docx"
# PDF_DIR = BASE_DIR / "{IE_ID}" / "pdf"
# RTF_DIR = BASE_DIR / "{IE_ID}" / "rtf"

# Output (always same structure)
OUTPUT_DIR = BASE_DIR / "{IE_ID}_OUTPUT"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
SOURCES_OUTPUT_DIR = OUTPUT_DIR / "sources"

# Logging and checkpoints
LOG_DIR = BASE_DIR / "logs"
CHECKPOINT_DIR = BASE_DIR / "checkpoints"

# =============================================================================
# Helper Functions
# =============================================================================

def ensure_directories():
    """Create all necessary directories if they don't exist."""
    for d in [OUTPUT_DIR, ARCHIVE_DIR, SOURCES_OUTPUT_DIR, LOG_DIR, CHECKPOINT_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def extract_ve_id_from_folder(folder_name: str) -> str:
    """Extract VE ID from folder name like '{IE_ID}-VE{xxx}' -> 'VE{xxx}'."""
    if folder_name.startswith(f"{IE_ID}-"):
        return folder_name.replace(f"{IE_ID}-", "")
    return None


def get_ut_id(ve_id: str, sequence: int = 1) -> str:
    """Generate UT ID from VE ID and sequence, e.g. VE1ER489, 1 -> UT1ER489_0001."""
    ve_suffix = ve_id[2:]  # Remove 'VE' prefix
    return f"UT{ve_suffix}_{sequence:04d}"


def get_max_archive_sequence(ve_id: str) -> int:
    """Return max sequence already in archive/{ve_id}/ (UT*.xml). Returns 0 if none."""
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
```

### Copy Required Modules

Copy these shared modules from a reference project:

- `normalization.py` - Unicode normalization
- `tibetan_text_fixes.py` - Tibetan-specific text fixes
- `tei_generator.py` - TEI XML generation
- `dedris_converter.py` - Legacy font conversion (update for new fonts if needed)
- `basic_rtf.py` - RTF parsing (if using RTF pipeline)
- `basic_docx.py` - DOCX parsing (if using DOCX pipeline)

## Step 4: Font Detection and Handling

### Legacy Font Detection

The `dedris_converter.py` module handles legacy Tibetan fonts:

```python
def is_legacy_tibetan_font(font_name: str) -> bool:
    """Check if font is a legacy Tibetan font requiring conversion."""
    if not font_name:
        return False
    lower_name = font_name.lower()
    return lower_name.startswith((
        'dedris', 'ededris',
        'tibetanchogyal', 'tibetanchogyalskt',
        'tibetanclassic', 'tibetanclassicskt',
    ))
```

### Adding New Font Support

If you encounter a new legacy font not in the list:

1. Check if `pytiblegenc` supports it:
```python
from pytiblegenc import convert_string
stats = {"handled_fonts": {}, "unhandled_fonts": {}, "unknown_characters": {}, 
         "diffs_with_utfc": {}, "error_characters": 0}
result = convert_string("test text", "NewFontName", stats)
print(f"Handled: {stats['handled_fonts']}")
print(f"Unhandled: {stats['unhandled_fonts']}")
```

2. If supported, add to `is_legacy_tibetan_font()`:
```python
return lower_name.startswith((
    'dedris', 'ededris',
    'tibetanchogyal', 'tibetanchogyalskt',
    'tibetanclassic', 'tibetanclassicskt',
    'newfontname',  # Add new font prefix here
))
```

## Step 5: Run Conversion

### Execution Commands

```bash
# Navigate to script directory
cd "C:\Users\GANGA GYATSO\OneDrive\Documents\IE1PD100944\tibetan-etext-tools\{IE_ID}"

# For multi-step pipelines:
python 1_convert_doc_to_pdf.py    # Step 1
python 2_convert_pdf_to_xml.py    # Step 2

# For single-step pipelines:
python convert_rtf_to_xml.py
python convert_docx_to_xml.py
python convert_pdf_to_xml.py

# With options:
python convert_rtf_to_xml.py --ve VE3KG205  # Process single volume
python convert_pdf_to_xml.py --single file.pdf  # Process single file
```

### Checkpointing

Scripts use checkpoint files to resume interrupted conversions:

- Checkpoint location: `{IE_ID}/checkpoints/`
- To restart from scratch, delete checkpoint files
- Each successfully converted file is recorded in checkpoint

## Step 6: Validate Output

### Expected Output Structure

```
{IE_ID}_OUTPUT/
├── archive/
│   └── {VE_ID}/
│       ├── UT{VE_suffix}_0001.xml
│       ├── UT{VE_suffix}_0002.xml
│       └── ...
└── sources/
    └── {VE_ID}/
        └── (copies of original input files)
```

### TEI XML Structure

Each output XML should have:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader>
  <fileDesc>
    <titleStmt><title>...</title></titleStmt>
    <publicationStmt>...</publicationStmt>
    <sourceDesc>
      <bibl>
        <idno type="src_path">sources/{VE_ID}/{filename}</idno>
        <idno type="src_sha256">...</idno>
        <idno type="bdrc_ie">http://purl.bdrc.io/resource/{IE_ID}</idno>
        <idno type="bdrc_ve">http://purl.bdrc.io/resource/{VE_ID}</idno>
        <idno type="bdrc_ut">http://purl.bdrc.io/resource/{UT_ID}</idno>
      </bibl>
    </sourceDesc>
  </fileDesc>
</teiHeader>
<text>
<body xml:lang="bo">
<p><pb/>
<lb/>Tibetan text here...
</p>
</body>
</text>
</TEI>
```

### Validation Checklist

- [ ] XML is well-formed (no parsing errors)
- [ ] Tibetan text is Unicode (not garbled legacy encoding)
- [ ] `<lb/>` tags have text content (no empty lb lines)
- [ ] VE/UT IDs match folder structure
- [ ] SHA256 hash matches source file
- [ ] All input files have corresponding output XML

## Troubleshooting

### Issue: Garbled Text in Output

**Symptoms**: Output XML contains characters like `ÉÊ ÊÅþ/` instead of Tibetan

**Cause**: Font not recognized as legacy font

**Solution**:
1. Check font name in source file (open in Word/RTF viewer)
2. Add font prefix to `is_legacy_tibetan_font()` in `dedris_converter.py`
3. Verify pytiblegenc supports the font (see Step 4)

### Issue: Empty `<lb/>` Tags

**Symptoms**: XML has lines with just `<lb/>` and no text

**Cause**: `post_process_body()` adds `<lb/>` to every line

**Solution**: Add filtering after `post_process_body()`:
```python
tei_body = post_process_body(tei_body)

# Remove empty <lb/> lines
lines = tei_body.split('\n')
filtered_lines = []
for line in lines:
    stripped = line.strip()
    content_only = re.sub(r'<lb/>', '', stripped).strip()
    if content_only == '':
        continue
    filtered_lines.append(line)
tei_body = '\n'.join(filtered_lines)
```

### Issue: Files Not Found

**Symptoms**: Script reports no files found

**Cause**: Folder structure doesn't match config expectations

**Solution**:
1. Print actual folder structure: `list(TOPROCESS_DIR.rglob("*"))`
2. Adjust file discovery logic (e.g., use `rglob()` for nested folders)
3. Check if files are in `sources/` instead of `toprocess/`

### Issue: Wrong Volume Mapping

**Symptoms**: Files assigned to wrong VE ID

**Cause**: Volume extraction logic doesn't match folder naming

**Solution**:
1. Check `extract_ve_id_from_folder()` pattern
2. For flat sources, verify VE folders exist in toprocess
3. For multiple VEs, check file assignment logic in `assign_files_to_ve()`

### Issue: Word COM Automation Fails

**Symptoms**: DOC to PDF/DOCX conversion fails with COM error

**Cause**: Microsoft Word not installed or COM not accessible

**Solution**:
1. Ensure Microsoft Word is installed
2. Close any open Word instances
3. Run script as administrator if needed
4. Check pywin32 is installed: `pip install pywin32`

## Reference Projects

### DOC to DOCX to XML (Unicode fonts)
- **IE2PD17467**: `tibetan-etext-tools/IE2PD17467/`
- Files: `config.py`, `1_convert_doc_to_docx.py`, `2_convert_docx_to_xml.py`

### DOC to PDF to XML (Dedris fonts)
- **IE3CN4059**: `tibetan-etext-tools/IE3CN4059/` (nested folders)
- **IE3CN26475**: `tibetan-etext-tools/IE3CN26475/`
- Files: `config.py`, `1_convert_doc_to_pdf.py`, `2_convert_pdf_to_xml.py`

### RTF to XML (TibetanChogyal/Classic fonts)
- **IE3KG235**: `tibetan-etext-tools/IE3KG235/`
- Files: `config.py`, `convert_rtf_to_xml.py`, `dedris_converter.py`, `basic_rtf.py`

### PDF to XML (direct)
- **IE3KG664**: `tibetan-etext-tools/IE3KG664/` (flat sources)
- **IE1KG14**: `tibetan-etext-tools/IE1KG14/` (complex with regions)
- Files: `config.py`, `convert_pdf_to_xml.py`

### DOCX to XML (direct)
- **IE3CN5624**: `tibetan-etext-tools/IE3CN5624/`
- **IE3KG184**: `tibetan-etext-tools/IE3KG184/`
- Files: `config.py`, `convert_docx_to_xml.py`

### Multiple Pipeline Options
- **IE3CN8070**: `tibetan-etext-tools/IE3CN8070/`
- Supports: DOC->DOCX->XML, DOC->RTF->XML, DOC->PDF->XML
- Files: All conversion scripts available

## External Resources

- **Output specification**: https://github.com/buda-base/ao_etexts/blob/main/doc/README.md
- **Validation tool**: https://github.com/buda-base/ao_etexts
- **pytiblegenc**: `pip install -U git+https://github.com/buda-base/py-tiblegenc.git`
- **Conversion log spreadsheet**: (Internal Google Sheets)
- **Files to process**: (Internal Google Drive `files_to_process/` folder)
- **Discord support**: #bdrc-etext-corpus-wg channel, "Conversion" thread
