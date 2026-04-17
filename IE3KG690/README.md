# IE3KG690 PDF to TEI XML Converter

Convert Tibetan PDF files to TEI XML format 

## Usage

```bash
python pdf_to_xml.py <input_folder> <output_folder>
```

### Example

```bash
python pdf_to_xml.py /path/to/IE3KG690 /path/to/IE3KG690_output
```

## Input Structure

```
IE3KG690/
└── toprocess/
    ├── VE1ER574/
    │   └── TI1471-01-001.pdf
    ├── VE1ER575/
    │   └── TI1472-01-001.pdf
    └── ...
```

## Output Structure

```
IE3KG690_output/
├── archive/
│   ├── VE1ER574/
│   │   └── UT1ER574_0001.xml
│   └── ...
└── sources/
     ├── VE1ER574/
     │   └── TI1471-01-001.pdf
     ├── VE1ER575/
     │   └── TI1472-01-001.pdf
     └── ...
```

## Processing Pipeline

1. **PDF Extraction** - Extract text with font size tracking using py-tiblegenc
2. **Normalization** - Apply Unicode normalization
3. **Font Classification** - Auto-classify font sizes as regular/small/large
4. **TEI Conversion** - Generate TEI XML with proper structure

## Requirements

```bash
pip install pytiblegenc natsort
```

## Features

- Automatic font size classification
- Unicode normalization for Tibetan text
- Removes duplicate page breaks
- Preserves folder structure in output
