# tibetan-etext-tools

Tools for analyzing and converting different formats of Tibetan etexts

### Docx format

Different techniques can be used to extract the text from a docx file. Some requirements:
- identification of footnotes (should not be inline)
- no header or footer
- keeping paragraph and line breaks

- front, body, back
- homage, colophon, 
- sabche (up to h50)
- verse, prose
- citations
- interpretative decisions (paragraphs)
- markup in Word, the rest is not efficient
- abbreviations
- strikethrough
- XXX
- page & line + siglas

Some possible tools:
- `pandoc --wrap=preserve -s tests/docx/UT2KG5037-I2KG217533.docx -t tei -o ouput.xml`


### Checking output

- `xmllint --schema schema/tei_lite.xsd output.xml --noout`

- I3KG749, I3KG779, I3KG750, I3KG802 => refaire outline


I have a directory W3KG218 with subdirectories like W3KG218-I3KG692, W3KG218-I3KG693, etc. Each subdirectory contains PDFs that have 3 text pages per PDF page (3-ups, for printing), except a few that only have one text page per PDF page.

I have a csv file that represents a table of