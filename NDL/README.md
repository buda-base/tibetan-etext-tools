# NDL Text to TEI XML Converter

This script converts Tibetan text files from the Nitartha Digital Library (NDL) format into TEI XML format and generates CSV outlines of the document structure.

## Overview

The `convert_ndl.py` script processes text files with hierarchical divisions (marked with `#div1`, `#div2`, etc.) and converts them into:
1. TEI XML files with proper structure and metadata
2. CSV files outlining the document structure with volume, text, and chapter information

## Input Structure

The script expects input files in the following directory structure:

```
{input_folder}/
  {ie_lname}/
    toprocess/
      {ie_lname}-{ve_lname}/
        {file_id}.txt
```

Where:
- `{ie_lname}`: Instance/Edition name (e.g., `IE001`)
- `{ve_lname}`: Volume/Edition name (e.g., `VE001`)
- `{file_id}`: File identifier

## Input File Format

Text files should contain metadata at the top followed by content with hierarchical divisions:

```
Title = སེང་ཆེན་ནོར་བུ་དགྲ་འདུལ་གྱི་སྐུ་ཚེའི་སྟོད་ཀྱི་རྣམ་ཐར་ཉི་མའི་དཀྱིལ་འཁོར་སྐལ་ལྡན་ཡིད་ཀྱི་མུན་སེལ། 
Text_type = གླེགས་བམ། སྟོད་ཆ༽ 
Author = རིག་འཛིན་བཟང་པོ།
Publisher = Nitartha international
Id = GSP001

#div1 མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས།
༄༅། མཛད་པ་པོའི་རྣམ་ཐར་མདོར་བསྡུས། 
སྒྲུང་བ་རིག་འཛིན་བཟང་པོའམ་ཁྱི་ཤུལ་རིག་བཟང་ནི། ...

#div1 འཁྲུང་གླིང་།
#div2 ཀླུ་མོ་ཡ་དཀར་མཛེས་ལྡན་འགག་ཡུལ་དུ་ཕེབས་པའི་སྐོར།
༄༅།  སེང་ཆེན་ནོར་བུ་དགྲ་འདུལ་གྱི་སྐུ་ཚེའི་སྟོད་ཀྱི་རྣམ་ཐར་ཉི་མའི་དཀྱིལ་འཁོར་སྐལ་ལྡན་ཡིད་ཀྱི་མུན་སེལ་བཞུགས་སོ། །
 ༈ ཨེ་མ་ཧོཿ...
```

## Output Structure

The script generates the following output structure:

```
{output_folder}/
  {ie_lname}/
    sources/
      {ve_lname}/
        {file_id}.txt       # Copy of original text file
    archive/
      {ve_lname}/
        {ut_lname}.xml      # TEI XML file
    {ie_lname}.csv         # Structure outline CSV
```

Where `{ut_lname}` follows the pattern: `UT{ve_lname}[2:]_0001`

## TEI XML Output

The XML output follows the TEI (Text Encoding Initiative) standard with:
- TEI header containing title, publication info, and source metadata
- BDRC resource identifiers (IE, VE, UT)
- SHA256 hash of the source file
- Hierarchical document structure with milestones and divisions
- Language attribute set to Tibetan (`xml:lang="bo"`)

## CSV Output

The CSV file provides a structural outline with the following columns:
- RID, Position (×4), part type, label, titles, work, notes, colophon, authorshipStatement, identifiers, etext start, etext end, img grp start, img grp end

Part types:
- `V`: Volume (only when multiple volumes exist)
- `T`: Text (div1 level)
- `C`: Chapter (div2 level)

## Usage

```bash
python convert_ndl.py <input_folder> <output_folder> <ie_lname>
```

### Example

```bash
python convert_ndl.py ./input ./output IE001
```

This will process all volumes under `./input/IE001/toprocess/` and generate output in `./output/IE001/`.

## Features

- Automatic parsing of hierarchical divisions (div1, div2, div3+)
- TEI XML generation with proper namespace and structure
- SHA256 hash calculation for source file verification
- Multi-volume support with automatic volume numbering
- CSV outline generation for navigation and indexing
- Unicode normalization support (placeholder for future implementation)

## Requirements

- Python 3.6+
- Standard library only (no external dependencies)

## Notes

- The script assumes VE folders are processed in alphabetical order for volume numbering
- Divisions deeper than div2 are included in the XML but not in the CSV outline
- The `normalize_unicode()` function is currently a stub and can be implemented as needed
