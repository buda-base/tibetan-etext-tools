# DOC/DOCX to RTF (`convert_doc_to_rtf.py`)

Converts DOC/DOCX to RTF (Word by default, or Google Drive API).

```bash
python convert_doc_to_rtf.py --ie-id IE3KG668
python convert_doc_to_rtf.py --ie-id IE3KG668 --method drive
python convert_doc_to_rtf.py --ie-id IE3KG668 --remove-original
```

Options: `--ie-id` (required), `--method {word,drive}`, `--input-dir`, `--remove-original`.

Dedris fonts are converted to Unicode in the RTF→XML step (`convert.py`), not during DOC→RTF.

---

# RTF to XML (`convert.py`)

**Test first file only** (no filename; recursively finds RTF and converts the first). Requires `--ie-id` or `--rtf-dir`:

```bash
python convert.py --ie-id IE3KG668 --test-first
python convert.py --rtf-dir ../rtf/IE3KG668 --test-first
```

**Single file or all:**

```bash
python convert.py --ie-id IE3KG668 --single yourfile.rtf
python convert.py --ie-id IE3KG668 --all
```

| Option | Description |
|--------|-------------|
| `--ie-id ID` | Collection ID; sets RTF dir to `rtf/{ID}`. |
| `--test-first`, `-t` | Convert first RTF found recursively. Needs `--ie-id` or `--rtf-dir`. |
| `--single FILE`, `-s` | Convert one file by name. |
| `--all`, `-a` | Convert all volumes. |
| `--rtf-dir DIR` | Override RTF folder. |
| `--output DIR`, `-o` | Output directory. |
| `--encoding`, | Encoding of the content text dedris/unicode(default). |

Output: `{output_dir}/archive/{VE_ID}/*.xml` and `.../sources/{VE_ID}/*.rtf`.

---

# RTF check/fix (`rtf_check_fix.py`)

```bash
python rtf_check_fix.py --ie-id IE3KG668
python rtf_check_fix.py --ie-id IE3KG668 --no-fix
python rtf_check_fix.py --ie-id IE3KG668 --output report.txt
```

Default input: `../rtf`. Fixes write to `archive/` (no backup). Add patterns in `rtf_issue_detector.py` (RTF_COMMAND_PATTERNS, SPURIOUS_PATTERNS).

---

# Export (`export_outputs.py`)

```bash
python export_outputs.py --ie-id IE3KG668
python export_outputs.py --ie-id IE3KG668 --output-dir /path/to/export
python export_outputs.py --dry-run
```

Reads from `rtf/{IE_ID}/{IE_ID}_output/`, writes to `export/{IE_ID}/` (no `_output` suffix).

---

# Quick start

1. DOC→RTF: `python convert_doc_to_rtf.py --ie-id IE3KG668`
2. RTF→XML: `python convert.py --ie-id IE3KG668 --test-first` or `--all`
3. Check RTF: `python rtf_check_fix.py --ie-id IE3KG668`
4. Export: `python export_outputs.py --ie-id IE3KG668`
