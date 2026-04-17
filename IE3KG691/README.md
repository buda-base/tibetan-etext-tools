# IE3KG691 PDF to TEI XML Converter

Convert Tibetan PDF files to TEI XML format 

## Usage

```bash
python pdf_to_xml.py <input_folder> <output_folder>
```

### Example

```bash
python pdf_to_xml.py /path/to/IE3KG691 /path/to/IE3KG691_output
```

## Input Structure

```
IE3KG691/
└── toprocess/
    ├── VE1ER566/
    │   └── TI1441-01-001.pdf
    ├── VE1ER567/
    │   └── TI1442-01-001.pdf
    └── ...
```

## Output Structure

```
IE3KG691_output/
├── archive/
│   ├── VE1ER566/
│   │   └── UT1ER566_0001.xml
│   └── ...
└── sources/
    ├── VE1ER566/
    │   └── TI1441-01-001.pdf
    └── ...
```

## Processing Pipeline

1. **PDF Extraction** - Extract text with font size tracking using py-tiblegenc
2. **Normalization** - Apply Unicode normalization and fix character substitutions (μ → ག)
3. **Font Classification** - Auto-classify font sizes as regular/small/large
4. **TEI Conversion** - Generate TEI XML with proper structure

## Requirements

```bash
pip install pytiblegenc natsort
```

## Features

- Automatic font size classification
- Unicode normalization for Tibetan text
- Character substitution fixes (common PDF extraction errors)
- Removes duplicate page breaks
- Preserves folder structure in output
