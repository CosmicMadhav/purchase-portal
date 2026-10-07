"""PDF export through the installed Microsoft Word / Excel, so PDFs look exactly like a manual export."""
import os
import threading

import pythoncom
import win32com.client

_lock = threading.Lock()

WD_PDF = 17
WD_PAGE_OF_END = 3  # wdActiveEndPageNumber


def docx_to_pdf(docx_path, pdf_path=None, smart_page_break=True):
    docx_path = os.path.abspath(docx_path)
    pdf_path = os.path.abspath(pdf_path or os.path.splitext(docx_path)[0] + ".pdf")
    with _lock:
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
    return pdf_path


def _relax_page_breaks(doc):
    """The comparative statement starts on a new page. If page 1 already overflowed onto page 2,
    let the statement follow on that page instead of leaving page 2 almost empty."""
    changed = False
    paras = doc.Paragraphs
    for i in range(2, paras.Count + 1):
        para = paras(i)
        if para.Format.PageBreakBefore:
            prev = paras(i - 1)
            if prev.Range.Information(WD_PAGE_OF_END) >= 2:
                para.Format.PageBreakBefore = False
                changed = True
    if changed:
        doc.Save()


def excel_to_pdf(xlsx_path, pdf_path, sheet_name=None, fill=None):
    """Open an .xlsx, optionally run fill(workbook) to write values, save it, export one sheet to PDF."""
    xlsx_path = os.path.abspath(xlsx_path)
    pdf_path = os.path.abspath(pdf_path)
    with _lock:
        pythoncom.CoInitialize()
        xl = None
        try:
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            wb = xl.Workbooks.Open(xlsx_path)
            ws = wb.Worksheets(sheet_name) if sheet_name else wb.Worksheets(1)
            if fill:
                fill(wb, ws)
            wb.Save()
            ws.ExportAsFixedFormat(0, pdf_path)
            wb.Close(False)
        finally:
            if xl is not None:
                xl.Quit()
            pythoncom.CoUninitialize()
    return pdf_path
