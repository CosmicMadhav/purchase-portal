"""Real PDF export (Word/Excel on Windows, LibreOffice in Docker): read the PDFs back and check them."""
import pymupdf
import pytest

from conftest import quote
from convert import docx_to_pdf
from gen_word import build_permission, build_po, quote_totals
from gen_excel import build_advance_voucher, build_advance_adjustment, build_cash_voucher

BUDGET = {"provision": 300000, "utilized": 259572.10, "available": 40427.90}


def pdf_text(path):
    d = pymupdf.open(path)
    return len(d), "\n".join(p.get_text() for p in d)


def test_permission_pdf(tmp_path, profile):
    qs = [quote("ALPHA", [("Jetson", 1, 24950), ("Case", 1, 1400), ("SSD", 1, 4500)]),
          quote("BETA", [("Jetson", 1, 27500), ("Case", 1, 1800), ("SSD", 1, 4750)]),
          quote("GAMMA", [("Jetson", 1, 28000), ("Case", 1, 1600), ("SSD", 1, 5000)])]
    out = build_permission({"date": "2026-10-07", "title": "Electronics Components", "quotes": qs}, profile, str(tmp_path / "p.docx"))
    pages, t = pdf_text(docx_to_pdf(out))
    assert pages == 2
    assert "Rs. 36,403.00" in t and "Rs. 40,179.00" in t and "Rs. 40,828.00" in t
    assert "Comparative Statement" in pymupdf.open(out.replace(".docx", ".pdf"))[1].get_text()


def test_long_permission_does_not_leave_blank_page(tmp_path, profile):
    q = quote("ALPHA", [(f"Component number {i} with a fairly long description", 1, 100 + i) for i in range(14)])
    qs = [q, quote("BETA", [("x", 1, 9000)]), quote("GAMMA", [("y", 1, 9000)])]
    out = build_permission({"date": "2026-10-07", "title": "Many parts", "quotes": qs, "list_items_in_subject": False},
                           profile, str(tmp_path / "long.docx"))
    pdf = docx_to_pdf(out)
    d = pymupdf.open(pdf)
    for page in d:
        assert len(page.get_text().strip()) > 40, "a nearly empty page was produced"


def test_po_pdf(tmp_path, profile):
    q = quote("DAZZLE ROBOTICS PVT. LTD.", [("Motor", 4, 3912)])
    out = build_po({"date": "2026-10-07", "title": "Motor", "quotes": [q]}, profile, str(tmp_path / "po.docx"), BUDGET)
    pages, t = pdf_text(docx_to_pdf(out, smart_page_break=False))
    assert pages == 2 and "Rs. 18,464.64" in t and "Internal Auditor" in t


@pytest.mark.parametrize("n", [3, 18])
def test_advance_voucher_pdf_is_one_page(tmp_path, profile, n):
    items = [{"description": f"Item {i}", "qty": 1, "rate": 100} for i in range(n)]
    pdf = build_advance_voucher({"date": "2026-10-07", "items": items}, profile, BUDGET, str(tmp_path / "a.xlsx"), str(tmp_path / "a.pdf"))
    pages, t = pdf_text(pdf)
    assert pages == 1 and "###" not in t and "07-10-2026" in t and "06-11-2026" in t
    assert ("Three Hundred only" if n == 3 else "One Thousand Eight Hundred only") in t


def test_adjustment_and_cash_pdf(tmp_path, profile):
    bills = [{"biller": "HYDRO SPRAY TECH", "bill_no": "T/29", "bill_date": "2026-06-30", "gst": 450, "items": "Wheel Hub", "amount": 2950},
             {"biller": "YOGI ENTERPRISES", "bill_no": "G/0906", "bill_date": "2026-07-03", "gst": 442.36, "items": "Chain", "amount": 2900}]
    pdf = build_advance_adjustment({"date": "2026-10-07", "bills": bills}, profile, BUDGET, str(tmp_path / "j.xlsx"), str(tmp_path / "j.pdf"))
    pages, t = pdf_text(pdf)
    assert pages == 1 and "5,850.00" in t and "Five Thousand Eight Hundred Fifty only" in t and "30-06-2026" in t and "###" not in t
    pdf = build_cash_voucher({"date": "2026-10-07", "bills": bills, "permission_ref": "Permission dated 27-06-2026"},
                             profile, BUDGET, str(tmp_path / "c.xlsx"), str(tmp_path / "c.pdf"))
    pages, t = pdf_text(pdf)
    assert pages == 1 and "CASH VOUCHER" in t and "5850" in t.replace(",", "") and "###" not in t
