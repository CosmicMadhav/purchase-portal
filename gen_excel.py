"""Advance Voucher, Advance Adjustment Voucher and Cash Voucher – filled into the original Excel
files through Excel itself (keeps the Nirma logo, tick boxes, borders and print setup)."""
import os
import shutil
from datetime import datetime

from convert import excel_to_pdf
from gen_word import parse_date, fy
from money import words, r2

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "doc_templates")


def _xl_date(d):
    """Excel serial number – avoids the COM timezone shift that turns 07-10 into 06-10."""
    from datetime import date as _date
    d = parse_date(d)
    return (_date(d.year, d.month, d.day) - _date(1899, 12, 30)).days


def _set_date(rng, d, fmt="dd-mm-yyyy"):
    rng.Value = _xl_date(d)
    rng.NumberFormat = fmt


def _one_page(ws):
    ps = ws.PageSetup
    ps.Zoom = False
    ps.FitToPagesWide = 1
    ps.FitToPagesTall = 1


def _ticks(ws):
    """The original uses Excel's new in-cell checkboxes, which older Excel builds print as '###'."""
    for a in ("A1", "A2"):
        c = ws.Range(a)
        c.Value = "☑"
        c.Font.Name = "Segoe UI Symbol"
        c.HorizontalAlignment = -4108


def _uniform_rows(ws, first, n, cols="A:I"):
    """Give every item row the formatting of the first one (template rows differ slightly)."""
    if n > 1:
        a, b = cols.split(":")
        ws.Range(f"{a}{first}:{b}{first}").Copy()
        ws.Range(f"{a}{first + 1}:{b}{first + n - 1}").PasteSpecial(-4122)
        ws.Application.CutCopyMode = False


def _fit_rows(ws, first, n_template, n_needed):
    """Template has n_template item rows starting at `first`; grow/shrink to n_needed (min 1)."""
    n_needed = max(1, n_needed)
    if n_needed > n_template:
        last = first + n_template - 1
        for _ in range(n_needed - n_template):
            ws.Rows(last).Insert()
    elif n_needed < n_template:
        ws.Range(f"{first + n_needed}:{first + n_template - 1}").EntireRow.Delete()
    return n_needed


def _budget_block(ws, row_provision, b):
    ws.Range(f"E{row_provision}").Value = r2(b.get("provision", 0))
    ws.Range(f"E{row_provision + 1}").Value = r2(b.get("utilized", 0))


# ------------------------------------------------------------------ advance request
def build_advance_voucher(adv, profile, budget, xlsx_out, pdf_out):
    """adv: {date, amount, items:[{description, qty, rate}], purpose}"""
    shutil.copyfile(os.path.join(TPL, "advance_voucher.xlsx"), xlsx_out)
    items = adv.get("items") or []
    amount = r2(adv.get("amount") or sum(float(i.get("qty") or 1) * float(i.get("rate") or 0) for i in items))

    def fill(wb, ws):
        _ticks(ws)
        _set_date(ws.Range("H6"), adv.get("date"))
        ws.Range("C8").Value = profile.get("payee", "")
        ws.Range("H8").Value = profile.get("contact", "")
        ws.Range("B9").Value = profile.get("payee_dept", "")
        ws.Range("G9").Value = amount
        ws.Range("B10").Value = words(amount)
        ws.Range("C11").Value = adv.get("purpose") or profile.get("advance_purpose", "")
        ws.Range("D22").Value = profile.get("project", "")
        ws.Range("D23").Value = profile.get("budget_code", "")
        ws.Range("E24").Value = r2(budget.get("provision", 0))
        ws.Range("E25").Value = r2(budget.get("utilized", 0))
        ws.Range("E26").Value = amount
        ws.Range("E27").Value = r2(budget.get("provision", 0) - budget.get("utilized", 0) - amount)
        ws.Range("E24:E27").NumberFormat = "#,##,##0"
        ws.Range("E29").Value = profile.get("advance_approver", "HOD,EC")
        n = _fit_rows(ws, 34, 10, len(items))
        _uniform_rows(ws, 34, n, "B:H")
        for i in range(n):
            r = 34 + i
            it = items[i] if i < len(items) else {}
            ws.Range(f"B{r}").Value = it.get("description", "")
            q = it.get("qty")
            rate = it.get("rate")
            ws.Range(f"F{r}").Value = q if q not in (None, "") else ""
            ws.Range(f"G{r}").Value = rate if (rate not in (None, "") and q not in (None, "")) else ""
            total = float(q or 1) * float(rate or 0) if it else ""
            ws.Range(f"H{r}").Value = total
        gt = 34 + n
        ws.Range(f"H{gt}").Formula = f"=SUM(H34:H{gt - 1})"
        _one_page(ws)

    return excel_to_pdf(xlsx_out, pdf_out, "Sheet1", fill)


# ------------------------------------------------------------------ advance adjustment
def build_advance_adjustment(adj, profile, budget, xlsx_out, pdf_out):
    """adj: {date, bills:[{biller, bill_no, bill_date, gst, items, amount}], remaining_adjustment}"""
    shutil.copyfile(os.path.join(TPL, "advance_adjustment.xlsx"), xlsx_out)
    bills = adj.get("bills") or []
    total = r2(sum(float(b.get("amount") or 0) for b in bills))

    def fill(wb, ws):
        _set_date(ws.Range("B2"), adj.get("date"))
        ws.Range("C4").Value = profile.get("payee", "")
        ws.Range("F4").Value = f"Contact: {profile.get('contact', '')}"
        ws.Range("A7").Value = adj.get("particular") or profile.get("adjust_particular", "")
        ws.Range("F7").Value = total
        ws.Range("B13").Value = words(round(total))
        ws.Range("B18").Value = profile.get("voucher_mentor", "")
        ws.Range("C18").Value = profile.get("voucher_hod", "")
        ws.Range("D21").Value = profile.get("project", "")
        ws.Range("D22").Value = profile.get("budget_code", "")
        ws.Range("E23").Value = r2(budget.get("provision", 0))
        ws.Range("E24").Value = r2(budget.get("utilized", 0))
        ws.Range("E25").Value = round(total)
        ws.Range("E26").Value = r2(adj.get("remaining_adjustment") or 0)
        ws.Range("C29").Value = f"Name of the Approving Authority : {profile.get('voucher_approver', '')}"
        code = fy(adj.get("date")).replace("-", "")[2:]  # 2026-27 -> 2627
        prefix = (profile.get("adjust_ref_prefix") or "NU/IT/{project}/{fy}/Advance Adjustment Voucher/") \
            .replace("{project}", profile.get("project", "")).replace("{fy}", code)
        ws.Range("A31").Formula = f'="{prefix}"&C4'
        # bills table: wipe old rows, then write ours with row 34's formatting
        n = max(1, len(bills))
        ws.Range("A34:G120").ClearContents()
        ws.Range("A35:G120").Borders.LineStyle = -4142
        ws.Range("A34:G34").Copy()
        ws.Range(f"A34:G{33 + n}").PasteSpecial(-4122)  # formats only
        for i, b in enumerate(bills):
            r = 34 + i
            ws.Range(f"A{r}").Value = i + 1
            ws.Range(f"B{r}").Value = b.get("biller", "")
            ws.Range(f"C{r}").NumberFormat = "@"
            ws.Range(f"C{r}").Value = str(b.get("bill_no", ""))
            if b.get("bill_date"):
                _set_date(ws.Range(f"D{r}"), b.get("bill_date"))
            ws.Range(f"E{r}").Value = r2(b.get("gst") or 0)
            ws.Range(f"F{r}").Value = b.get("items", "")
            ws.Range(f"G{r}").Value = r2(b.get("amount") or 0)
        ws.Range("G32").Formula = f"=SUM(G34:G{33 + n})"
        _one_page(ws)

    return excel_to_pdf(xlsx_out, pdf_out, "Sheet2", fill)


# ------------------------------------------------------------------ cash voucher (reimbursement)
def build_cash_voucher(cv, profile, budget, xlsx_out, pdf_out):
    """Reimbursement of a personal-fund purchase. No official template was provided, so this uses the
    Nirma 'Voucher for Advance' sheet (same header, logo and budget block) re-titled as a Cash Voucher.
    cv: {date, payee?, contact?, purpose, permission_ref, bills:[{biller, bill_no, bill_date, items, amount}]}"""
    shutil.copyfile(os.path.join(TPL, "advance_voucher.xlsx"), xlsx_out)
    bills = cv.get("bills") or []
    total = r2(sum(float(b.get("amount") or 0) for b in bills))

    def fill(wb, ws):
        ws.Range("D5").Value = "CASH VOUCHER"
        _ticks(ws)
        _set_date(ws.Range("H6"), cv.get("date"))
        ws.Range("C8").Value = cv.get("payee") or profile.get("payee", "")
        ws.Range("H8").Value = cv.get("contact") or profile.get("contact", "")
        ws.Range("B9").Value = profile.get("payee_dept", "")
        ws.Range("F9").Value = "Amount Rs."
        ws.Range("G9").Value = total
        ws.Range("B10").Value = words(round(total))
        ws.Range("A11").Value = "Being payment of"
        ws.Range("C11").Value = cv.get("purpose") or (
            f"Reimbursement of material purchased for {profile.get('project', '')} "
            f"({profile.get('grant', '')})")
        ws.Range("C11").ShrinkToFit = True
        ws.Range("A13").Value = "Purchase Permission Ref. / Date"
        ws.Range("G13").Value = cv.get("permission_ref", "")
        ws.Range("A14").Value = "Paid from personal funds; original bill(s) attached."
        ws.Range("A15:I15").ClearContents()
        ws.Range("D22").Value = profile.get("project", "")
        ws.Range("D23").Value = profile.get("budget_code", "")
        ws.Range("E24").Value = r2(budget.get("provision", 0))
        ws.Range("E25").Value = r2(budget.get("utilized", 0))
        ws.Range("E26").Value = total
        ws.Range("E27").Value = r2(budget.get("provision", 0) - budget.get("utilized", 0) - total)
        ws.Range("E24:E27").NumberFormat = "#,##,##0.00"
        ws.Range("E29").Value = cv.get("approver") or profile.get("advance_approver", "HOD,EC")
        ws.Range("A32").Value = "Details of bills attached"
        ws.Range("B33").Value = "Biller / Items"
        ws.Range("F33").Value = "Bill No."
        ws.Range("G33").Value = "Bill Date"
        ws.Range("H33").Value = "Amount"
        n = _fit_rows(ws, 34, 10, len(bills))
        _uniform_rows(ws, 34, n, "B:H")
        for i in range(n):
            r = 34 + i
            b = bills[i] if i < len(bills) else {}
            desc = b.get("biller", "")
            if b.get("items"):
                desc = f"{desc} – {b['items']}" if desc else b["items"]
            ws.Range(f"B{r}").Value = desc
            ws.Range(f"F{r}").NumberFormat = "@"
            ws.Range(f"F{r}").Value = str(b.get("bill_no", ""))
            if b.get("bill_date"):
                _set_date(ws.Range(f"G{r}"), b["bill_date"], "dd-mm-yy")
                ws.Range(f"G{r}").ShrinkToFit = True
            else:
                ws.Range(f"G{r}").Value = ""
            ws.Range(f"H{r}").Value = r2(b.get("amount") or 0) if b else ""
        gt = 34 + n
        ws.Range(f"H{gt}").Formula = f"=SUM(H34:H{gt - 1})"
        _one_page(ws)

    return excel_to_pdf(xlsx_out, pdf_out, "Sheet1", fill)
