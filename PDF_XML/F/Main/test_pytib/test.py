import fitz

pdf_path = '/Users/tenzinmonlam/Downloads/F/unzip/convert/IE4CZ369288/sources/VE1ER1172/TI904-01-001.pdf'
doc = fitz.open(pdf_path)

for i, page in enumerate(doc):
    for b in page.get_fonts(full=True):
        print(f'Page {i+1}: {b}')
    if i >= 2:  # Note: i >= 2 means it will run for pages 0, 1, and 2 (Pages 1-3).
        break