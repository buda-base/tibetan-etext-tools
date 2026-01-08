# Batch RTF Processing Tools

## 1. RTF to XML Conversion (`convert.py`)

### Input Directory Setup

**Default location (line 68):**
```python
INPUT_DIR = Path(__file__).parent.parent / "rtf"
```

**To change:** Edit line 68 in `convert.py` or use `--input-dir` flag.

### Input Structure

```
rtf/
└── {IE_ID}/
    └── toprocess/
        └── {IE_ID}-{VE_ID}/
            └── *.rtf
```

### Usage

```bash
# Process all collections
python convert.py

# Process specific collection
python convert.py --ie-id IE23636

# Custom input directory
python convert.py --input-dir /path/to/rtf
```

### Output

- **XML files**: `rtf/{IE_ID}/{IE_ID}_output/archive/{VE_ID}/*.xml`
- **Source RTF copies**: `rtf/{IE_ID}/{IE_ID}_output/sources/{VE_ID}/*.rtf`

**Note:** Collections with existing output are automatically skipped.

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
python rtf_check_fix.py --ie-id IE23636

# Check only (no fixing)
python rtf_check_fix.py --ie-id IE23636 --no-fix

# Save report
python rtf_check_fix.py --ie-id IE23636 --output report.txt
```

### Output

- **Fixed files**: Written directly to `archive/` folder (replaces originals)
- **Report file**: If `--output` specified

**Note:** Original files in `archive/` are replaced with fixed versions. No backups are created.

---

## Quick Start

1. **Convert RTF to XML:**
   ```bash
   cd batch_process_rtf
   python convert.py --ie-id IE23636
   ```

2. **Check and fix issues:**
   ```bash
   python rtf_check_fix.py --ie-id IE23636
   ```

3. **Verify:**
   ```bash
   python rtf_check_fix.py --ie-id IE23636 --no-fix
   ```
