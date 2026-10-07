"""Purchase Permission, Purchase Order and Request-for-Quotation (.docx) generators."""
import os
from datetime import date, datetime

from docbuild import (DocBuilder, set_cell, set_columns, unique_cells, clone_row_after,
                      remove_row, find_row)
from money import rs, totals, indian
from rules import slab_for, AUTHORITY_SHORT

HERE = os.path.dirname(os.path.abspath(__file__))
TPL = os.path.join(HERE, "doc_templates")


# ---------------------------------------------------------------- helpers
def parse_date(d):
    if isinstance(d, (date, datetime)):
        return d
    if not d:
        return date.today()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(d, fmt).date()
        except ValueError:
            pass
    return date.today()


def dmy(d, sep="-"):
    d = parse_date(d)
    return f"{d.day:02d}{sep}{d.month:02d}{sep}{d.year}"


def fy(d):
    d = parse_date(d)
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{(y + 1) % 100:02d}"


def ref_line(profile, d):
    return (profile.get("ref_prefix") or "").replace("{fy}", fy(d))


def qty_str(q):
    q = float(q or 0)
    return str(int(q)) if q == int(q) else str(q)


def quote_totals(q, inclusive=False):
    return totals(q.get("items"), q.get("discount"), q.get("gst_override"), q.get("other"),
                  inclusive=inclusive)


def selected_quote(p):
    qs = p.get("quotes") or []
    if not qs:
        return {"vendor": {}, "items": p.get("items") or []}
    i = int(p.get("selected") or 0)
    return qs[i if i < len(qs) else 0]


def subject_lines(p, items):
    """Returns (first line, [extra lines]) the way the existing letters are written."""
    title = (p.get("title") or "").strip()
    prefix = (p.get("subject_prefix") or "").strip()
    if len(items) > 1 and p.get("list_items_in_subject", True):
        head = title or "Components"
        return head, [it["description"] for it in items]
    return title or (items[0]["description"] if items else ""), []


def fill_item_table(table, rows, summary, header=None):
    """rows: list of 5-tuples; summary: list of (label, value)."""
    trs = list(table.rows)
    if header:
        for cell, txt in zip(unique_cells(trs[0]), header):
            if txt is not None:
                set_cell(cell, txt)
    first_sum = next(i for i, r in enumerate(trs) if i > 0 and len(unique_cells(r)) == 2)
    item_proto = trs[1]
    sum_proto = trs[first_sum]
    anchor = trs[0]
    for vals in rows:
        nr = clone_row_after(table, item_proto, anchor)
        for cell, v in zip(unique_cells(nr), vals):
            set_cell(cell, str(v))
        anchor = nr
    for label, value in summary:
        nr = clone_row_after(table, sum_proto, anchor)
        c = unique_cells(nr)
        set_cell(c[0], label)
        set_cell(c[1], value)
        anchor = nr
    for r in trs[1:]:
        remove_row(r)


def fill_comparative(table, quotes, inclusive=False):
    """Supplier columns: selected quote first, then the rest (as in the existing statements)."""
    n = len(quotes)
    set_columns(table, n + 1)
    trs = list(table.rows)
    proto_bold = trs[0]          # Supplier name row (values bold)
    proto_item = trs[1]          # Item row
    proto_plain = find_row(table, "Total")
    proto_grand = find_row(table, "Grand")
    n_items = max(len(q.get("items") or []) for q in quotes) if quotes else 1
    anchor = trs[-1]

    def add(proto, label, vals):
        nonlocal anchor
        nr = clone_row_after(table, proto, anchor)
        cells = unique_cells(nr)
        set_cell(cells[0], label)
        for c, v in zip(cells[1:], vals):
            set_cell(c, v)
        anchor = nr

    tots = [quote_totals(q, inclusive) for q in quotes]
    add(proto_bold, "Supplier name", [(q.get("vendor") or {}).get("name", "") for q in quotes])
    for i in range(n_items):
        label = "Item" if n_items == 1 else f"Item {i + 1}"
        vals = []
        for q in quotes:
            its = q.get("items") or []
            vals.append(its[i].get("description", "") if i < len(its) else "")
        add(proto_item, label, vals)
    add(proto_plain, "Total", [rs(t["subtotal"] - t["discount"]) for t in tots])
    add(proto_plain, "GST", [rs(t["gst"]) for t in tots])
    add(proto_plain, "Other charges", [rs(t["other"]) for t in tots])
    add(proto_plain, "Payment condition", [q.get("payment") or "" for q in quotes])
    add(proto_plain, "Delivery time", [q.get("delivery") or "" for q in quotes])
    add(proto_grand, "Grand Total", [rs(t["grand"]) for t in tots])
    for r in trs:
        remove_row(r)


def _approval_block(b, profile, authority, idx):
    """Emit the Through/To lines. idx = dict of proto indices for this template."""
    hod = profile.get("hod", "HoD- EC (N.P Gajjar)")
    ar = profile.get("ar", "Asst. Registrar, SoT-NU")
    director = profile.get("director", "Director, SoT NU")
    gap = " " * 67
    if authority in ("hod", "hod_statement"):
        b.p(idx["blank"])
        b.p(idx["to"], "To")
        b.p(idx["blank"])
        b.p(idx["line"], hod)
        return
    b.p(idx["blank"])
    b.p(idx["to"], "Through ")
    b.p(idx["blank"])
    b.p(idx["blank"])
    b.p(idx["line"], f"{hod}{gap}{ar}")
    b.p(idx["blank"])
    b.p(idx["blank"])
    if authority == "vp":
        b.p(idx["line"], f"{director}\t\t\t\t\t             {profile.get('exec_registrar', 'Exec. Registrar, NU')}")
        b.p(idx["blank"])
        b.p(idx["blank"])
        b.p(idx["to"], "To")
        b.p(idx["line"], profile.get("vp", "Vice President, NU"))
    else:
        b.p(idx["line"], director)


# ---------------------------------------------------------------- permission
def build_permission(p, profile, out_path, slabs=None):
    if profile.get("letter_style") == "incubation":
        return build_permission_incubation(p, profile, out_path)

    q = selected_quote(p)
    items = q.get("items") or []
    quotes = p.get("quotes") or []
    sel = int(p.get("selected") or 0)
    ordered = ([quotes[sel]] + [x for i, x in enumerate(quotes) if i != sel]) if quotes else []
    t0 = quote_totals(q)
    slab = slab_for(t0["grand"], slabs)
    authority = p.get("authority_override") or slab["authority"]
    small = authority == "hod" and len(quotes) <= 1   # the "PP 3000" format
    vendor = q.get("vendor") or {}
    d = p.get("date")
    first, extra = subject_lines(p, items)
    subject = "Subject: " + ((p.get("subject_prefix") or "").strip() + " " if p.get("subject_prefix") else "") \
        + f"Permission to purchase for {first}"
    following = (f"Following items are required to be procured for {profile.get('project', '')} "
                 f"({profile.get('grant', '')}).")
    request = p.get("request_text") or (
        "It is kindly requested to grant the permission to purchase the above-mentioned items as per the "
        "terms and conditions mentioned above. The account section may please be directed to do the needful.")

    if small:
        b = DocBuilder(os.path.join(TPL, "permission_hod.docx"))
        I = dict(ref=0, date=1, blank=2, plain=3, subject=5, following=6, table=7, terms_head=8,
                 term=9, term_bold=12, request=13, sign=16, title=17, to=19, line=21)
        incl = totals(items, q.get("discount"), q.get("gst_override"), q.get("other"))
        rows = []
        for n, it in enumerate(items, 1):
            g = float(it.get("gst") if it.get("gst") not in (None, "") else 18)
            rate_inc = float(it.get("rate") or 0) * (1 + g / 100)
            rows.append((f"{n}.", it.get("description", ""), rs(rate_inc), qty_str(it.get("qty")),
                         rs(rate_inc * float(it.get("qty") or 0))))
        grand = incl["grand"]
        summary = [("Total (₹)", rs(grand - incl["other"])), ("Other charges", rs(incl["other"])),
                   ("Grand Total(approx)", rs(grand))]
    else:
        b = DocBuilder(os.path.join(TPL, "permission_main.docx"))
        I = dict(ref=0, date=1, blank=2, plain=3, subject=5, subj_line=6, following=9, table=10,
                 terms_head=11, term=12, term_bold=17, request=18, sign=21, title=22, to=24, line=27,
                 stmt_head=36, stmt_blank=37, stmt_table=38, recommend=41, sign2=45)
        rows = [(str(n), it.get("description", ""), rs(it.get("rate")), qty_str(it.get("qty")),
                 rs(float(it.get("rate") or 0) * float(it.get("qty") or 0))) for n, it in enumerate(items, 1)]
        grand = t0["grand"]
        summary = [("Total (₹)", rs(t0["subtotal"]))]
        if t0["discount"]:
            summary.append(("Discount", rs(t0["discount"])))
        summary += [("GST", rs(t0["gst"])), ("Other charges", rs(t0["other"])), ("Grand Total", rs(grand))]

    b.p(I["ref"], ref_line(profile, d))
    b.p(I["date"], f"Date: {dmy(d)}")
    b.p(I["blank"])
    b.p(I["plain"], "Submitted")
    b.p(I["blank"])
    b.p(I["subject"], subject)
    for line in extra:
        b.p(I.get("subj_line", I["subject"]), line)
    b.p(I["following"], following)
    fill_item_table(b.table(I["table"]), rows, summary)

    b.p(I["terms_head"], "Other terms and conditions:")
    terms = [("Extra cost ", "Nil"), ("Total cost of purchase", f"₹ {indian(grand)}")]
    if vendor.get("name") and not (small and not p.get("show_supplier_small")):
        terms.append(("Supplier Details", vendor["name"]))
    pay = p.get("payment_condition") or q.get("payment")
    if not small and pay:
        terms.append(("Payment condition", pay))
    dl = p.get("delivery_time") or (q.get("delivery") if not small else "After receiving payment")
    if dl:
        terms.append(("Expected delivery time", dl))
    for n, (k, v) in enumerate(terms, 1):
        b.p(I["term"], f"{n}.      {k}: {v}")
    b.p(I["term_bold"], [(f"{len(terms) + 1}.      Budget head: ", False), (profile.get("budget_code", ""), True)])
    b.p(I["request"], request)
    for extra_para in (p.get("extra_paragraphs") or []):
        b.p(I["request"], extra_para)
    b.p(I["blank"])
    b.p(I["blank"])
    b.p(I["sign"], profile.get("mentor_name", ""))
    b.p(I["title"], profile.get("mentor_title", ""))
    _approval_block(b, profile, authority, I)

    if not small:
        single = len(ordered) <= 1
        b.p(I["stmt_head"], " Statement" if single else "Comparative Statement", page_break_before=True)
        b.p(I["stmt_blank"])
        fill_comparative(b.table(I["stmt_table"]), ordered or [q])
        b.p(I["stmt_blank"])
        b.p(I["stmt_blank"])
        verb = "requested" if single else "recommended"
        b.p(I["recommend"], [(f"It is {verb} to purchase the item from ", False),
                             (vendor.get("name", "").rstrip(".") + ".", True)])
        b.p(I["blank"])
        b.p(I["blank"])
        b.p(I["sign2"], profile.get("mentor_name", ""))
        b.p(I["sign2"], profile.get("mentor_title", ""))
    b.save(out_path)
    return out_path


def build_permission_incubation(p, profile, out_path):
    """PrithviX / incubation-cell letter (Claude / Supabase style)."""
    q = selected_quote(p)
    items = q.get("items") or []
    t = quote_totals(q)
    cur = p.get("currency_symbol") or "₹"
    b = DocBuilder(os.path.join(TPL, "permission_incubation.docx"))
    b.p(0, f"Date: {dmy(p.get('date'))}")
    b.p(1)
    b.p(2, "Submitted")
    b.p(3)
    first, extra = subject_lines(p, items)
    b.p(4, f"Subject: Permission to purchase for {first}")
    b.p(5)
    for para in (profile.get("intro_paragraphs") or []):
        b.p(6, para)
    b.p(8)
    rows = [(f"{n}.", it.get("description", ""), f"{cur} {indian(it.get('rate'))}",
             it.get("period") or qty_str(it.get("qty")),
             f"{cur} {indian(float(it.get('rate') or 0) * float(it.get('qty') or 1))}")
            for n, it in enumerate(items, 1)]
    fill_item_table(b.table(9), rows, [("Total", f"{cur} {indian(t['subtotal'])}"),
                                      ("TAX", f"{cur} {indian(t['gst'])}" if t["gst"] else "0"),
                                      ("Other charges", f"{cur} {indian(t['other'])}"),
                                      ("Grand Total(approx)", f"{cur} {indian(t['grand'])}")],
                    header=[None, None, f"Price ({cur})", "Period", None])
    b.p(10, "Other terms and conditions:")
    b.p(11, "1.      Extra cost : Nil")
    b.p(12, f"2.      Total cost of purchase: {cur}{indian(t['grand'])}")
    b.p(13, p.get("request_text") or (
        "It is kindly requested to grant the permission to purchase the above-mentioned items so we can "
        "increase the efficiency of the team. The account section may please be directed to do the needful."))
    b.p(14)
    b.p(15)
    b.p(17, profile.get("mentor_name", ""))
    b.p(18, profile.get("mentor_title", ""))
    b.p(19)
    b.p(22, "Through")
    b.p(23, profile.get("through", ""))
    b.p(24)
    b.p(27, "To,")
    b.p(28, profile.get("to", ""))
    b.save(out_path)
    return out_path


# ---------------------------------------------------------------- purchase order
def build_po(p, profile, out_path, budget=None, slabs=None):
    q = selected_quote(p)
    items = q.get("items") or []
    vendor = q.get("vendor") or {}
    t = quote_totals(q)
    slab = slab_for(t["grand"], slabs)
    authority = p.get("authority_override") or slab["authority"]
    with_audit = p.get("po_audit_page") if p.get("po_audit_page") is not None else slab["audit"]
    d = p.get("po_date") or p.get("date")
    b = DocBuilder(os.path.join(TPL, "po.docx"))
    b.p(0, ref_line(profile, d))
    b.p(1, f"Date: {dmy(d)}")
    b.p(2)
    b.p(3, "To")
    b.p(4, (vendor.get("name") or "").upper())
    for line in (vendor.get("address") or "").splitlines():
        if line.strip():
            b.p(5, line.strip())
    if vendor.get("gst"):
        b.p(7, f"GST: {vendor['gst']}")
    b.p(9)
    first, extra = subject_lines(p, items)
    if extra:
        b.p(10, "Subject: Purchase Order for ")
        for line in extra:
            b.p(11, line)
    else:
        b.p(10, f"Subject: Purchase Order for {first}")
    b.p(9)
    if q.get("quote_no") or q.get("quote_date"):
        ref = "Your Quotation Reference: " + (q.get("quote_no") or "").strip()
        if q.get("quote_date"):
            ref = ref.rstrip() + f" dated {dmy(q['quote_date'], '/')}"
        b.p(13, ref)
        b.p(9)
    b.p(14, "Dear sir,")
    b.p(15, "We are pleased to place an order of the following items")
    rows = [(str(n), it.get("description", ""), rs(it.get("rate")), qty_str(it.get("qty")),
             rs(float(it.get("rate") or 0) * float(it.get("qty") or 0))) for n, it in enumerate(items, 1)]
    summary = [("Total (₹)", rs(t["subtotal"]))]
    if t["discount"]:
        summary.append(("Discount", rs(t["discount"])))
    summary += [("GST", rs(t["gst"])), ("Other charges", rs(t["other"])), ("Grand Total", rs(t["grand"]))]
    fill_item_table(b.table(16), rows, summary)
    b.p(17, "Other terms and conditions:  ")
    b.p(18)
    b.p(19, f"2. Payment: {p.get('po_payment') or q.get('payment') or 'PO – After 15 days of Delivery'}")
    b.p(20, f"3. Delivery: {p.get('po_delivery') or q.get('delivery') or 'within a week after receiving a PO'} "
            f"\n4. Warranty: As per manufacturer")
    for i in (21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31):
        b.p(i)
    if with_audit:
        b.p(32)  # keeps the page break
        b.p(33)
        b.p(34)
        b.p(35)
        b.p(36, ref_line(profile, d))
        b.p(37, f"Date: {dmy(p.get('audit_date') or d)}")
        b.p(38)
        b.p(39, f"Name of the Institute: {profile.get('institute', 'Institute of Technology')}.")
        b.p(40)
        b.p(41, [("Budget Year ", False, False), (fy(d), False, True), ("   Budget Code:  ", False, False),
                 (profile.get("budget_code", ""), True, False), ("    Budget Head: ", False, False),
                 ((profile.get("budget_head_po") or "") + "                 ", False, True)])
        b.p(42)
        tbl = b.table(43)
        bud = budget or {}
        util_date = dmy(bud.get("as_of") or d)
        hdr = unique_cells(tbl.rows[0])
        set_cell(hdr[3], f"Budget Utilized up to Date : _{util_date}\nRs.")
        c = unique_cells(tbl.rows[1])
        set_cell(c[1], profile.get("department", "GA"))
        set_cell(c[2], indian(bud.get("provision", 0), 0) if float(bud.get("provision", 0)).is_integer() else indian(bud.get("provision", 0)))
        set_cell(c[3], indian(bud.get("utilized", 0)))
        set_cell(c[4], indian(bud.get("available", 0)))
        set_cell(c[5], indian(t["grand"]))
        for i in (44, 45, 46):
            b.p(i)
        b.p(47, f"Name of Authority: {profile.get('dop_authority') or 'VP'} dated  __________  Item No. ________")
        for i in range(48, 61):
            b.p(i)
    else:
        b.p(32, "(2) Account Section (Nirma University),(3) O/C to concern authority")  # drops page break
    b.save(out_path)
    return out_path


# ---------------------------------------------------------------- request for quotation
def build_rfq(p, profile, vendor, out_path):
    """Letter asking a vendor for their quotation – sent to each of the 3 parties."""
    items = selected_quote(p).get("items") or p.get("items") or []
    d = p.get("rfq_date") or date.today().isoformat()
    b = DocBuilder(os.path.join(TPL, "po.docx"))
    b.p(0, ref_line(profile, d))
    b.p(1, f"Date: {dmy(d)}")
    b.p(2)
    b.p(3, "To")
    b.p(4, (vendor.get("name") or "").upper())
    for line in (vendor.get("address") or "").splitlines():
        if line.strip():
            b.p(5, line.strip())
    b.p(9)
    first, _ = subject_lines(p, items)
    b.p(10, f"Subject: Request for quotation for {first}")
    b.p(9)
    b.p(14, "Dear sir,")
    b.p(18, "We request you to kindly submit your best quotation for the following items required for "
            f"{profile.get('project', '')} ({profile.get('grant', '')}).")
    rows = [(str(n), it.get("description", ""), "", qty_str(it.get("qty")), "") for n, it in enumerate(items, 1)]
    fill_item_table(b.table(16), rows, [])
    b.p(17, "Please mention in your quotation:")
    lines = ["1. Unit rate, GST % and HSN code for each item",
             "2. Other / shipping charges, if any",
             "3. Payment terms and delivery period",
             "4. Validity of the quotation",
             "5. Bill to: Nirma University, Ahmedabad (GST 24AAATT6829N1ZY)"]
    for line in lines:
        b.p(18, line)
    b.p(25)
    b.p(26, "Thanking You")
    b.p(27)
    b.p(28, profile.get("mentor_name", ""))
    b.p(28, profile.get("mentor_title", ""))
    b.p(29, f"{profile.get('institute', 'Institute of Technology')}, Nirma University, S G Highway, Ahmedabad")
    b.save(out_path)
    return out_path
