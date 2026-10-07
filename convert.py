"""PDF export.

Windows with MS Office: Word / Excel do the export (identical to a manual 'Save as PDF').
Anywhere else (the Docker image): LibreOffice headless.
"""
import os
import shutil
import subprocess
import tempfile
import threading

_lock = threading.Lock()

try:
    import pythoncom
    import win32com.client
    HAVE_OFFICE = os.name == "nt" and not os.environ.get("USE_LIBREOFFICE")
except ImportError:
    HAVE_OFFICE = False

WD_PDF = 17
WD_PAGE_OF_END = 3  # wdActiveEndPageNumber


# ------------------------------------------------------------------ public API
def docx_to_pdf(docx_path, pdf_path=None, smart_page_break=True):
    docx_path = os.path.abspath(docx_path)
    pdf_path = os.path.abspath(pdf_path or os.path.splitext(docx_path)[0] + ".pdf")
    with _lock:
        if HAVE_OFFICE:
            _word(docx_path, pdf_path, smart_page_break)
        else:
            _soffice(docx_path, pdf_path)
            if smart_page_break and _statement_overflowed(pdf_path):
                _drop_page_breaks(docx_path)
                _soffice(docx_path, pdf_path)
    return pdf_path


def xlsx_to_pdf(xlsx_path, pdf_path):
    xlsx_path, pdf_path = os.path.abspath(xlsx_path), os.path.abspath(pdf_path)
    with _lock:
        if HAVE_OFFICE:
            _excel(xlsx_path, pdf_path)
        else:
            _soffice(xlsx_path, pdf_path)
    return pdf_path


# ------------------------------------------------------------------ MS Office (Windows)
def _word(docx_path, pdf_path, smart_page_break):
    pythoncom.CoInitialize()
    word = None
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(docx_path, ReadOnly=False, AddToRecentFiles=False)
        if smart_page_break:
            _relax_page_breaks(doc)
        doc.SaveAs2(pdf_path, FileFormat=WD_PDF)
        doc.Close(False)
    finally:
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()


def _relax_page_breaks(doc):
    """The comparative statement starts on a new page. If page 1 already overflowed onto page 2,
    let the statement follow on that page instead of leaving page 2 almost empty."""
    changed = False
    paras = doc.Paragraphs
    for i in range(2, paras.Count + 1):
        para = paras(i)
        if para.Format.PageBreakBefore:
            if paras(i - 1).Range.Information(WD_PAGE_OF_END) >= 2:
                para.Format.PageBreakBefore = False
                changed = True
    if changed:
        doc.Save()


def _excel(xlsx_path, pdf_path):
    pythoncom.CoInitialize()
    xl = None
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        wb = xl.Workbooks.Open(xlsx_path)
        wb.Worksheets(1).ExportAsFixedFormat(0, pdf_path)
        wb.Close(False)
    finally:
        if xl is not None:
            xl.Quit()
        pythoncom.CoUninitialize()


# ------------------------------------------------------------------ LibreOffice (Docker / Linux)
def _soffice(src, pdf_path):
    exe = shutil.which("soffice") or shutil.which("libreoffice")
    if not exe:
        raise RuntimeError("Neither MS Office nor LibreOffice is available to make the PDF.")
    with tempfile.TemporaryDirectory() as tmp:
        profile = "file://" + os.path.join(tmp, "profile").replace("\\", "/")
        subprocess.run([exe, f"-env:UserInstallation={profile}", "--headless", "--convert-to", "pdf",
                        "--outdir", tmp, src], check=True, capture_output=True, timeout=180)
        produced = os.path.join(tmp, os.path.splitext(os.path.basename(src))[0] + ".pdf")
        shutil.move(produced, pdf_path)


def _statement_overflowed(pdf_path):
    """True when the (Comparative) Statement heading landed on page 3 or later, i.e. page 1 spilled
    over and the forced page break left a nearly empty page."""
    import pymupdf
    doc = pymupdf.open(pdf_path)
    for i, page in enumerate(doc):
        if "Statement" in page.get_text() and i >= 2:
            return True
    return False


def _drop_page_breaks(docx_path):
    from docx import Document
    from docx.oxml.ns import qn
    d = Document(docx_path)
    for el in list(d.element.body.iter(qn("w:pageBreakBefore"))):
        el.getparent().remove(el)
    d.save(docx_path)
