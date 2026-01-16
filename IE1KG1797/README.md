# Batch RTF Processing Tools

## 1. RTF to XML Conversion (`convert.py`)

### Basic Usage

The simplest ways to run `convert.py`:

```bash
# Basic: Process all collections in the default location
python convert.py

# Process a specific collection (most common use case)
python convert.py --ie-id IE1KG1797

# Adjust number of parallel workers (for faster processing)
python convert.py --ie-id IE1KG1797 --workers 4

# Use a custom input directory
python convert.py --input-dir /path/to/rtf

# Combine options: custom directory + specific collection + workers
python convert.py --input-dir /path/to/rtf --ie-id IE1KG1797 --workers 8
```

### Input Directory Setup

**Default location (line 68):**
```python
INPUT_DIR = Path(__file__).parent.parent / "rtf"
```

**To change:** Edit line 68 in `convert.py` or use `--input-dir` flag.

### Input Structure

**Standard structure:**
```
rtf/
└── {IE_ID}/
    └── toprocess/
        └── {IE_ID}-{VE_ID}/
            └── *.rtf
```

**Non-standard structures:** The script can also recursively find RTF/DOC files in any folder structure. When files are found in non-standard locations, you'll be prompted to confirm before processing. Use `--yes` to skip prompts.

### Command-Line Options

```bash
# Process all collections
python convert.py

# Process specific collection
python convert.py --ie-id IE1KG1797

# Custom input directory
python convert.py --input-dir /path/to/rtf

# Adjust number of parallel workers (default: CPU count - 1)
python convert.py --workers 4

# Skip confirmation prompts for non-standard structures
python convert.py --yes

# Combine multiple options
python convert.py --ie-id IE1KG797 --workers 4 --input-dir /path/to/rtf --yes
```

### Output

- **XML files**: `rtf/{IE_ID}/{IE_ID}_output/archive/{VE_ID}/*.xml`
- **Source RTF copies**: `rtf/{IE_ID}/{IE_ID}_output/sources/{VE_ID}/*.rtf`

**Note:** 
- Collections with existing output are automatically skipped.
- Supports both `.rtf` and `.doc` files (case-insensitive).
- Automatically finds files recursively even in non-standard folder structures.

---

## 2. RTF Issue Detection and Fix (`rtf_check_fix.py`)

### Input Directory Setup

**Default location (line 382):**
```python
default=Path(__file__).parent.parent / "rtf"
```

**To change:** Edit line 382 in `rtf_check_fix.py` or use `--input-dir` flag.

### Usage

```bash
# Check all collections (prompts to fix if issues found)
python rtf_check_fix.py

# Check specific collection
python rtf_check_fix.py --ie-id IE1KG1797

# Check only (no fixing)
python rtf_check_fix.py --ie-id IE1KG1797 --no-fix

# Save report
python rtf_check_fix.py --ie-id IE1KG1796 --output report.txt
```

### Output

- **Fixed files**: Written directly to `archive/` folder (replaces originals)
- **Report file**: If `--output` specified

**Note:** Original files in `archive/` are replaced with fixed versions. No backups are created.

---

## 3. Export Outputs (`export_outputs.py`)

### Basic Usage

Export all output folders, removing the `_output` suffix from folder names:

```bash
# Export all outputs to default export directory
python export_outputs.py

# Export specific collection
python export_outputs.py --ie-id IE1KG1797

# Export to custom directory
python export_outputs.py --output-dir /path/to/export

# Dry run (see what would be exported without copying)
python export_outputs.py --dry-run

# Combine options
python export_outputs.py --ie-id IE1KG1797 --output-dir /path/to/export
```

### Input Directory Setup

**Default input location:**
```python
DEFAULT_INPUT_DIR = Path(__file__).parent.parent / "rtf"
```

**Default output location:**
```python
DEFAULT_OUTPUT_DIR = Path(__file__).parent.parent / "export"
```

**To change:** Use `--input-dir` and `--output-dir` flags.

### Input Structure

The script looks for output folders in:
```
rtf/{IE_ID}/{IE_ID}_output/archive/{VE_ID}/*.xml
rtf/{IE_ID}/{IE_ID}_output/sources/{VE_ID}/*.rtf
```

### Output Structure

Exported files are saved to:
```
export/{IE_ID}/archive/{VE_ID}/*.xml
export/{IE_ID}/sources/{VE_ID}/*.rtf
```

**Note:** The `_output` suffix is removed from the folder name in the export.

### Command-Line Options

```bash
# Export all outputs
python export_outputs.py

# Export specific collection
python export_outputs.py --ie-id IE1KG797

# Custom input directory
python export_outputs.py --input-dir /path/to/rtf

# Custom output directory
python export_outputs.py --output-dir /path/to/export

# Dry run (preview without copying)
python export_outputs.py --dry-run

# Combine options
python3 export_outputs.py --ie-id IEKG1797 --output-dir /path/to/export
```

---

## Quick Start

1. **Convert RTF to XML:**
   ```bash
   cd batch_process_rtf
   python convert.py --ie-id IE1KF1797
   ```

2. **Check and fix issues:**
   ```bash
   python rtf_check_fix.py --ie-id IE1KF1797
   ```

3. **Verify:**
   ```bash
   python rtf_check_fix.py --ie-id IE1KG1797 --no-fix
   ```

4. **Export outputs:**
   ```bash
   python export_outputs.py --ie-id IE1KG1797
   ```
