# Batch RTF to TEI XML Converter
RTF to to TEI XML converter with updated input and output file structure

### Directory Structure
#### Input Structure
```
/path/to/input/dir/
├── IE_ID_1/
│   └── sources/
│       └── VE_ID_1/
│           └── collection_name/
│               └── rtfs/
│                   └── volume_001/
│                       ├── file1.rtf
│                       └── file2.rtf

```

#### Output Structure
```
IE_ID_1_output/
├── archive/
│   └── VE_ID_1/
│       └── collection_name/
│           └── xml/
│               └── volume_001/
│                   └── UT{suffix}_{index}.xml

```

## Usage
```
# Process all collections found in the default input directory:

python updated_convert.py

# Specify Input Directory

python updated_convert.py --input-dir "/path/to/your/data"

# To process only a specific IE ID:

python updated_convert.py --ie-id IE1PD45495

# Adjust number of parallel workers (default: CPU count - 1)
python updated_convert.py --workers 4
```
