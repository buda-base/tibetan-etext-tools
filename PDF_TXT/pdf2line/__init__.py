"""
pdf2line — Convert PDFs to plain text, one page per line.

A standalone package that extracts text from PDFs (hybrid PyMuPDF + optional
pytiblegenc backend) and emits a UTF-8 ``.txt`` file per PDF where **each line
is one PDF page**: the page's content lines are joined into a single line, and
structural markers (page numbers, section labels, Latin boilerplate) are
dropped.

Public API
----------
    from pdf2line import extract_pdf_text, page_to_line, convert_pdf

See ``pdf2line.cli`` for the command-line entry point (``pdf2line ...``).
"""
import logging
logging.getLogger("pdf2line").addHandler(logging.NullHandler())

from .extract import extract_pdf_text, extract_pages
from .assemble import split_into_pages, is_page_number, is_boilerplate, has_tibetan
from .convert import convert_pdf, convert_folder

__all__ = [
    "extract_pdf_text",
    "extract_pages",
    "split_into_pages",
    "is_page_number",
    "is_boilerplate",
    "has_tibetan",
    "convert_pdf",
    "convert_folder",
]

__version__ = "0.1.0"
