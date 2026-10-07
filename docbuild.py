"""Rebuilds a document from an existing .docx by cloning its own paragraphs and tables.

Every paragraph/table we emit is a deep copy of one already in the template, so fonts,
spacing, borders and widths stay exactly as in Madhav's original files – only the text
changes.
"""
import copy
from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.table import Table
from docx.text.paragraph import Paragraph


class DocBuilder:
    def __init__(self, template_path):
        self.doc = Document(template_path)
        self.body = self.doc.element.body
        self.protos = [el for el in self.body.iterchildren() if el.tag != qn("w:sectPr")]
        for el in self.protos:
            self.body.remove(el)
        self.sect = self.body.find(qn("w:sectPr"))

    # --- emitting -------------------------------------------------------------
    def _append(self, el):
        if self.sect is not None:
            self.sect.addprevious(el)
        else:
            self.body.append(el)

    def proto(self, idx):
        return self.protos[idx]

    def p(self, idx, text=None, page_break_before=False, align=None):
        """Clone template paragraph #idx. text may be a str or a list of (text, bold) runs."""
        el = copy.deepcopy(self.protos[idx])
        self._append(el)
        para = Paragraph(el, self.doc._body)
        if text is not None:
            set_text(para, text)
        if page_break_before:
            pPr = el.get_or_add_pPr()
            b = OxmlElement("w:pageBreakBefore")
            pPr.insert(0, b)
        if align is not None:
            para.alignment = align
        return para

    def table(self, idx):
        el = copy.deepcopy(self.protos[idx])
        self._append(el)
        return Table(el, self.doc._body)

    def save(self, path):
        self.doc.save(path)


# --- text helpers ---------------------------------------------------------------
def _first_rpr(p_el):
    r = p_el.find(qn("w:r"))
    if r is not None and r.find(qn("w:rPr")) is not None:
        return copy.deepcopy(r.find(qn("w:rPr")))
    ppr = p_el.find(qn("w:pPr"))
    if ppr is not None and ppr.find(qn("w:rPr")) is not None:
        rpr = copy.deepcopy(ppr.find(qn("w:rPr")))
        rpr.tag = qn("w:rPr")
        return rpr
    return None


def _set_bold(rpr, bold):
    for tag in ("w:b", "w:bCs"):
        old = rpr.find(qn(tag))
        if old is not None:
            rpr.remove(old)
    if bold:
        # w:b must come early in rPr – after rFonts if present
        b = OxmlElement("w:b")
        fonts = rpr.find(qn("w:rFonts"))
        style = rpr.find(qn("w:rStyle"))
        anchor = fonts if fonts is not None else style
        if anchor is not None:
            anchor.addnext(b)
        else:
            rpr.insert(0, b)


def _strip_underline(rpr):
    u = rpr.find(qn("w:u"))
    if u is not None:
        rpr.remove(u)


def set_text(para, text, keep_underline=False):
    """Replace all runs in a paragraph, keeping the first run's formatting.

    text: str, or list of (str, bold) / (str, bold, underline) tuples. '\n' becomes a line break,
    '\t' a tab.
    """
    p_el = para._p
    base = _first_rpr(p_el)
    for child in list(p_el):
        if child.tag in (qn("w:r"), qn("w:hyperlink"), qn("w:proofErr"), qn("w:bookmarkStart"),
                         qn("w:bookmarkEnd"), qn("w:smartTag"), qn("w:ins"), qn("w:del")):
            p_el.remove(child)
    segs = [(text, None)] if isinstance(text, str) else text
    for seg in segs:
        s, bold = seg[0], seg[1]
        underline = seg[2] if len(seg) > 2 else None
        r = OxmlElement("w:r")
        rpr = copy.deepcopy(base) if base is not None else OxmlElement("w:rPr")
        if bold is not None:
            _set_bold(rpr, bold)
        if underline is False:
            _strip_underline(rpr)
        if underline:
            u = OxmlElement("w:u")
            u.set(qn("w:val"), "single")
            rpr.append(u)
        if len(rpr):
            r.append(rpr)
        lines = str(s).split("\n")
        for li, line in enumerate(lines):
            if li:
                r.append(OxmlElement("w:br"))
            chunks = line.split("\t")
            for ci, chunk in enumerate(chunks):
                if ci:
                    r.append(OxmlElement("w:tab"))
                if chunk:
                    t = OxmlElement("w:t")
                    t.set(qn("xml:space"), "preserve")
                    t.text = chunk
                    r.append(t)
        p_el.append(r)


def set_cell(cell, text, bold=None):
    paras = cell.paragraphs
    for extra in paras[1:]:
        extra._p.getparent().remove(extra._p)
    if isinstance(text, str) and bold is not None:
        text = [(text, bold)]
    set_text(paras[0], text)


# --- table helpers ------------------------------------------------------------------
def unique_cells(row):
    """Cells of a row with horizontally merged duplicates removed (python-docx repeats them)."""
    out = []
    seen = set()
    for tc in row._tr.findall(qn("w:tc")):
        if id(tc) in seen:
            continue
        seen.add(id(tc))
        from docx.table import _Cell
        out.append(_Cell(tc, row.table))
    return out


def clone_row_after(table, src_row, after_row=None):
    new_tr = copy.deepcopy(src_row._tr)
    (after_row or src_row)._tr.addnext(new_tr)
    from docx.table import _Row
    return _Row(new_tr, table)


def remove_row(row):
    row._tr.getparent().remove(row._tr)


def find_row(table, label_startswith):
    for row in table.rows:
        cells = unique_cells(row)
        if cells and cells[0].text.strip().lower().startswith(label_startswith.lower()):
            return row
    return None


def set_columns(table, n_total):
    """Force a simple grid table to n_total columns (cloning the last column or dropping extras).
    The first column keeps its width; the remaining width is shared equally."""
    tbl = table._tbl
    grid = tbl.tblGrid
    cols = grid.findall(qn("w:gridCol"))
    widths = [int(c.get(qn("w:w")) or 0) for c in cols]
    total_w = sum(widths) or 9000
    first_w = widths[0] if widths else 2000
    while len(cols) > n_total:
        grid.remove(cols[-1])
        cols = cols[:-1]
    while len(cols) < n_total:
        nc = copy.deepcopy(cols[-1])
        cols[-1].addnext(nc)
        cols.append(nc)
    rest = (total_w - first_w) // max(1, n_total - 1)
    for i, c in enumerate(cols):
        c.set(qn("w:w"), str(first_w if i == 0 else rest))
    for tr in tbl.findall(qn("w:tr")):
        tcs = tr.findall(qn("w:tc"))
        while len(tcs) > n_total:
            tr.remove(tcs[-1])
            tcs = tcs[:-1]
        while len(tcs) < n_total:
            nc = copy.deepcopy(tcs[-1])
            tcs[-1].addnext(nc)
            tcs.append(nc)
        for i, tc in enumerate(tcs):
            tcPr = tc.get_or_add_tcPr()
            w = tcPr.find(qn("w:tcW"))
            if w is None:
                w = OxmlElement("w:tcW")
                tcPr.insert(0, w)
            w.set(qn("w:w"), str(first_w if i == 0 else rest))
            w.set(qn("w:type"), "dxa")
            span = tcPr.find(qn("w:gridSpan"))
            if span is not None:
                tcPr.remove(span)
