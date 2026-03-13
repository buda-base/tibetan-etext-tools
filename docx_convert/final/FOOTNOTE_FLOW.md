# Footnote Processing Flow

## Complete Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. DOCX File Input                                              │
│    - Main document text with footnote references (¹, ², etc.)   │
│    - word/footnotes.xml with footnote definitions               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 2. BasicDOCX Parser (basic_docx.py)                             │
│    ┌───────────────────────────────────────────────────────┐   │
│    │ _parse_footnotes()                                     │   │
│    │ - Reads word/footnotes.xml                            │   │
│    │ - Extracts text for each footnote ID                  │   │
│    │ - Cleans: strips whitespace, removes leading numbers  │   │
│    │ - Stores in self._footnotes dict                      │   │
│    └───────────────────────────────────────────────────────┘   │
│    ┌───────────────────────────────────────────────────────┐   │
│    │ _parse_document()                                      │   │
│    │ - Reads word/document.xml                             │   │
│    │ - Detects <w:footnoteReference> elements              │   │
│    │ - Inserts FOOTNOTE_MARKER at exact position           │   │
│    │ - Marks stream with is_footnote_marker=True           │   │
│    └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 3. Stream Processing (convert.py)                               │
│    - Normalize footnote text: normalize_unicode()               │
│    - Skip normalization for footnote markers (preserve marker)  │
│    - Normalize all other text streams                           │
│    - Pass normalized_footnotes to build_tei_body()              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 4. TEI Body Building (tei_generator.py)                         │
│    ┌───────────────────────────────────────────────────────┐   │
│    │ build_tei_body()                                       │   │
│    │ - Iterate through converted_streams                    │   │
│    │ - When is_footnote_marker=True:                        │   │
│    │   • Get footnote_text from normalized_footnotes        │   │
│    │   • Escape XML: escape_xml(footnote_text)             │   │
│    │   • Format: <note n="{id}" place="foot">{text}</note> │   │
│    │   • Append inline (NO extra whitespace)               │   │
│    │ - For regular text:                                    │   │
│    │   • Apply font classification (<hi> tags)             │   │
│    │   • Escape XML and append                             │   │
│    └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 5. Post-Processing (tei_generator.py)                           │
│    ┌───────────────────────────────────────────────────────┐   │
│    │ post_process_body()                                    │   │
│    │ - Replace \n with \n<lb/>                             │   │
│    │ - Remove spaces around <lb/> tags                     │   │
│    │ - Remove spaces around <note> tags                    │   │
│    │ - Clean empty <hi> tags                               │   │
│    │ - Merge consecutive <hi> tags across line breaks      │   │
│    └───────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ 6. TEI XML Generation (tei_generator.py)                        │
│    - Wrap in <p xml:space="preserve">                           │
│    - Add TEI header with metadata                               │
│    - Write to output file                                       │
└─────────────────────────────────────────────────────────────────┘
```

## Example Transformation

### Step 1: DOCX Input
```
Word Document:
  "Main text¹ continues here."
  
  Footnote 1: "This is the note."
```

### Step 2: After BasicDOCX Parsing
```python
streams = [
    {"text": "Main text", "font": {...}},
    {"text": "\x00FOOTNOTE_1\x00", "is_footnote_marker": True, "footnote_id": "1"},
    {"text": " continues here.", "font": {...}}
]

footnotes = {
    "1": "This is the note."
}
```

### Step 3: After Normalization
```python
normalized_footnotes = {
    "1": "This is the note."  # Unicode normalized
}

converted_streams = [
    {"text": "Main text", "font_size": 12},
    {"text": "\x00FOOTNOTE_1\x00", "is_footnote_marker": True, "footnote_id": "1"},
    {"text": " continues here.", "font_size": 12}
]
```

### Step 4: After build_tei_body()
```
Main text<note n="1" place="foot">This is the note.</note> continues here.
```

### Step 5: After post_process_body()
```
Main text<note n="1" place="foot">This is the note.</note> continues here.
```
(No changes - note tags are preserved without extra whitespace)

### Step 6: Final TEI XML
```xml
<p xml:space="preserve">Main text<note n="1" place="foot">This is the note.</note> continues here.</p>
```

## Key Design Decisions

### 1. Marker-Based Approach
Using a special marker (`\x00FOOTNOTE_{id}\x00`) allows us to:
- Track exact position of footnote references
- Preserve position through normalization (by skipping marker normalization)
- Replace with formatted `<note>` tags at the right stage

### 2. Inline Insertion
Footnotes are inserted inline (not at end of document) because:
- BDRC TEI guidelines specify inline placement
- Maintains reading flow
- Preserves exact reference location

### 3. Text Cleaning
Footnote text is cleaned to:
- Remove leading footnote numbers (Word adds these automatically)
- Strip extra whitespace
- Normalize Unicode (same as main text)
- Join multiple paragraphs with spaces

### 4. Whitespace Control
Strict whitespace control ensures:
- No spaces before `<note>` tag
- No spaces after `</note>` tag
- `xml:space="preserve"` maintains exact spacing
- Post-processing removes any accidental spaces

## Edge Cases Handled

1. **Missing footnotes.xml**: Script continues without errors
2. **Footnote reference without definition**: Silently skipped
3. **Multiple paragraphs in footnote**: Joined with spaces
4. **Special footnote types**: Separators and continuation separators are skipped
5. **XML special characters**: Escaped in both main text and footnotes
6. **Control characters in markers**: Markers skip normalization to preserve structure
