# Example of difficult cases

#### JKW-KABAB-vol7-p6.pdf (text outside the page)

This PDF has just one line of text on the page, but when extracting text automatically (through `pdftotext`, etc.) several pages are extracted in addition to the line of text. This is due to a lot of invisible text being present outside of the visible area of the page. PDF has many values for the dimensions of pages, but in order to extract the text from this PDF properly, the value `CropBox` should be taken. Most text extractors will use `MediaBox` instead. 

Solution:

Text extraction should use `CropBox` instead of `MediaBox`. An example of a fix is https://github.com/buda-base/py-tiblegenc/commit/8f907aa0d662881519cba2e245b563befff82246

#### noToUnicode.pdf

This PDF is not using a Tibetan legacy encoding but is still impossible to extract automatically. 

The reason is relatively complex. The PDF does not embed the original Unicode font but instead several subsets in the form of small (255 characters) non-Unicode fonts. You can view the different embedded subset fonts using `mutool extract noToUnicode.pdf`, which will create TTF font files (that can be opened using Fontforge). These subset fonts can have a corresponding `/ToUnicode` character map (`cmap`) in the PDF, mapping each character of the subset font to a Unicode sequence. Unfortunately this is not mandatory. This PDF is an example of real-life PDF that does not have a `/ToUnicode` mapping. Thus, when extracting text, the output will be the character point in the non-Unicode embedded fonts (`D`, `N`, etc.) instead of the original Unicode characters.

Solutions:

1. Since the embedded font can be extracted, it is feasible to create a (relatively complex) system that would run an OCR on an image created with the font and create a mapping that could be used when extracting text.

2. the embedded fonts seem to embed the glyph name of the original Unicode font (like `/tsh_u` for `ཚུ`), so it would be possible to create mappings from glyph name to original character for the main Unicode fonts. It would probably be possible to do it automatically through fontforge scripts. The main issue is that different versions of the font may use different glyph names, and it is not guaranteed that embedded fonts will use the original glyph names.