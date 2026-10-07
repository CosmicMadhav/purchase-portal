"""Server API: saving, workflow locks, budget, security, scanning. PDF export is real (Word or LibreOffice)."""
import io
import os

import pytest

from conftest import quote
import extract
import store


def purchase(c, amount_rates=(5000, 6000, 7000), **kw):
    pid = store.all_("projects", "id ASC")[0]["id"]
    body = {"project_id": pid, "date": "2026-10-07", "title": "Test purchase", "route": "po", "selected": 0,
            "quotes": [dict(quote(v, [("Widget", 2, r)]), vendor={"name": v, "address": "Addr", "gst": g})
                       for v, r, g in zip(["ALPHA CO", "BETA CO", "GAMMA CO"], amount_rates,
                                          ["24AAAAA1111A1Z5", "24BBBBB2222B1Z5", "24CCCCC3333C1Z5"])]}
    body.update(kw)
    r = c.post("/api/purchases", json=body)
    assert r.status_code == 200
    return r.get_json()


def mark(c, table, id_, key, done=True):
    return c.post(f"/api/{table}/{id_}/stage", json={"key": key, "done": done})


# ---------------------------------------------------------------- saving and memory
def test_save_computes_amount_and_requirements(app_client):
    p = purchase(app_client)
    assert p["amount"] == 11800.0 and p["req"]["authority"] == "director" and p["req"]["audit"] is True


def test_vendors_and_items_are_remembered(app_client):
    purchase(app_client, title="Memory test")
    names = [v["name"] for v in app_client.get("/api/vendors").get_json()]
    assert "ALPHA CO" in names and "GAMMA CO" in names
    items = {i["description"]: i for i in app_client.get("/api/items").get_json()}
    assert items["Widget"]["rate"] == 5000 and items["Widget"]["vendor"] == "ALPHA CO"


def test_saved_vendor_fills_missing_address(app_client):
    app_client.post("/api/vendors", json={"name": "FILL ME LTD", "address": "Plot 1, Ahmedabad", "gst": "24ABCDE1234F1Z5"})
    pid = store.all_("projects", "id ASC")[0]["id"]
    p = app_client.post("/api/purchases", json={"project_id": pid, "date": "2026-10-07", "title": "t",
                        "quotes": [{"vendor": {"name": "Fill Me Ltd"}, "items": [{"description": "x", "qty": 1, "rate": 10}]}]}).get_json()
    v = p["quotes"][0]["vendor"]
    assert v["address"] == "Plot 1, Ahmedabad" and v["gst"] == "24ABCDE1234F1Z5"


def test_unknown_table_and_missing_record(app_client):
    assert app_client.get("/api/nothing").status_code == 404
    assert app_client.get("/api/purchases/999999").status_code == 404


# ---------------------------------------------------------------- generation and locks
def test_permission_needs_enough_quotations(app_client):
    p = purchase(app_client, amount_rates=(5000,))
    r = app_client.post(f"/api/generate/permission/{p['id']}", json={})
    assert r.status_code == 409 and "needs 3 quotations" in r.get_json()["error"]
    p["quote_waiver"] = True
    app_client.post("/api/purchases", json=p)
    assert app_client.post(f"/api/generate/permission/{p['id']}", json={}).status_code == 200


def test_full_po_flow_with_locks(app_client):
    p = purchase(app_client)
    pid = p["id"]
    assert app_client.post(f"/api/generate/po/{pid}", json={}).status_code == 409         # before permission
    r = app_client.post(f"/api/generate/permission/{pid}", json={})
    assert r.status_code == 200
    files = r.get_json()["docs"][0]["files"]
    assert all(os.path.exists(f) for f in files) and files[1].endswith(".pdf")
    assert mark(app_client, "purchases", pid, "audit").status_code == 409                 # before PO
    assert app_client.post(f"/api/generate/po/{pid}", json={}).status_code == 409         # not approved yet
    assert mark(app_client, "purchases", pid, "permission_approved").status_code == 200
    r = app_client.post(f"/api/generate/po/{pid}", json={})
    assert r.status_code == 200
    assert mark(app_client, "purchases", pid, "outward").status_code == 409               # audit pending
    for k in ("audit", "po_approved", "outward", "po_issued", "bill", "seal_nirvan", "submitted", "settled"):
        assert mark(app_client, "purchases", pid, k).status_code == 200, k
    assert mark(app_client, "purchases", pid, "settled", False).get_json()["stages"].get("settled") is None


def test_regenerating_replaces_the_file_and_is_never_cached(app_client):
    p = purchase(app_client)
    first = app_client.post(f"/api/generate/permission/{p['id']}", json={}).get_json()
    pdf = first["docs"][0]["files"][1]
    before = os.path.getmtime(pdf)
    p = first
    p["quotes"][0]["items"][0]["rate"] = 5100
    app_client.post("/api/purchases", json=p)
    second = app_client.post(f"/api/generate/permission/{p['id']}", json={}).get_json()
    assert len([d for d in second["docs"] if d["kind"] == "permission"]) == 1
    assert os.path.getmtime(pdf) >= before
    r = app_client.get("/api/file", query_string={"path": pdf})
    assert r.status_code == 200 and "no-store" in r.headers["Cache-Control"] and r.data[:4] == b"%PDF"
    assert "ETag" not in r.headers


def test_po_not_needed_up_to_3000(app_client):
    p = purchase(app_client, amount_rates=(1000,))
    mark(app_client, "purchases", p["id"], "quotes")
    mark(app_client, "purchases", p["id"], "permission_made")
    mark(app_client, "purchases", p["id"], "permission_approved")
    r = app_client.post(f"/api/generate/po/{p['id']}", json={})
    assert r.status_code == 409 and "not required" in r.get_json()["error"]


def test_rfq_letters_one_per_vendor(app_client):
    p = purchase(app_client)
    r = app_client.post(f"/api/generate/rfq/{p['id']}", json={}).get_json()
    files = [d for d in r["docs"] if d["kind"] == "rfq"][0]["files"]
    assert len(files) == 6 and sum(f.endswith(".pdf") for f in files) == 3


def test_advance_flow(app_client):
    pid = store.all_("projects", "id ASC")[0]["id"]
    a = app_client.post("/api/advances", json={"project_id": pid, "date": "2026-10-07", "title": "Adv",
                        "items": [{"description": "Bolts", "qty": 10, "rate": 50}]}).get_json()
    assert app_client.post(f"/api/generate/advance_voucher/{a['id']}", json={}).status_code == 200
    assert app_client.post(f"/api/generate/advance_adjustment/{a['id']}", json={}).status_code == 409
    assert mark(app_client, "advances", a["id"], "issued").status_code == 409            # approval first
    mark(app_client, "advances", a["id"], "approved")
    mark(app_client, "advances", a["id"], "issued")
    assert app_client.post(f"/api/generate/advance_adjustment/{a['id']}", json={}).status_code == 400   # no bills
    a = app_client.get(f"/api/advances/{a['id']}").get_json()
    a["bills"] = [{"biller": "Yogi", "bill_no": "G/1", "bill_date": "2026-10-05", "gst": 12, "items": "Bolts", "amount": 490}]
    app_client.post("/api/advances", json=a)
    r = app_client.post(f"/api/generate/advance_adjustment/{a['id']}", json={})
    assert r.status_code == 200 and r.get_json()["stages"]["adjustment_made"]


def test_cash_voucher_requires_approved_permission(app_client):
    pid = store.all_("projects", "id ASC")[0]["id"]
    p = purchase(app_client, amount_rates=(1000,), route="personal")
    c = app_client.post("/api/reimbursements", json={"project_id": pid, "date": "2026-10-07", "title": "CV",
                        "bills": [{"biller": "Hydro", "bill_no": "T/1", "bill_date": "2026-10-01", "amount": 1180}]}).get_json()
    assert app_client.post(f"/api/generate/cash_voucher/{c['id']}", json={}).status_code == 409   # nothing linked
    c["purchase_id"] = str(p["id"])
    app_client.post("/api/reimbursements", json=c)
    assert app_client.post(f"/api/generate/cash_voucher/{c['id']}", json={}).status_code == 409   # not approved
    for k in ("quotes", "permission_made", "permission_approved"):
        mark(app_client, "purchases", p["id"], k)
    assert app_client.post(f"/api/generate/cash_voucher/{c['id']}", json={}).status_code == 200
    c2 = app_client.post("/api/reimbursements", json={"project_id": pid, "date": "2026-10-07", "title": "Post facto",
                         "post_facto_ref": "VP approval 15-01-2026", "bills": [{"biller": "X", "amount": 10}]}).get_json()
    assert app_client.post(f"/api/generate/cash_voucher/{c2['id']}", json={}).status_code == 200


# ---------------------------------------------------------------- budget
def test_budget_counts_only_committed_spending(app_client):
    pid = store.all_("projects", "id ASC")[1]["id"]          # PrithviX: starts at zero
    store.save("projects", {**store.get("projects", pid), "provision": 100000, "opening_utilized": 6000})
    b0 = app_client.get(f"/api/budget/{pid}").get_json()
    assert b0["utilized"] == 6000 and b0["available"] == 94000
    p = app_client.post("/api/purchases", json={"project_id": pid, "date": "2026-10-07", "title": "Sub", "route": "card",
                        "quotes": [{"vendor": {"name": "Anthropic"}, "items": [{"description": "Claude", "qty": 1, "rate": 2000, "gst": 18}]}]}).get_json()
    assert app_client.get(f"/api/budget/{pid}").get_json()["utilized"] == 6000           # not approved yet
    for k in ("quotes", "permission_made", "permission_approved"):
        mark(app_client, "purchases", p["id"], k)
    assert app_client.get(f"/api/budget/{pid}").get_json()["utilized"] == 8360
    app_client.post("/api/ledger", json={"project_id": pid, "note": "Overhead", "name": "Overhead", "amount": 1000})
    assert app_client.get(f"/api/budget/{pid}").get_json()["available"] == 100000 - 9360


# ---------------------------------------------------------------- security
def test_api_keys_are_never_sent_back(app_client):
    app_client.post("/api/settings", json={"llm_key": "gsk_secret", "vision_key": "AIza_secret"})
    s = app_client.get("/api/settings").get_json()
    assert s["llm_key"] == "" and s["vision_key"] == "" and s["llm_key_set"] and s["vision_key_set"]
    app_client.post("/api/settings", json={"llm_key": "", "llm_model": "m"})             # blank keeps the key
    assert store.get_settings()["llm_key"] == "gsk_secret"
    store.set_settings({"llm_key": "", "vision_key": ""})


@pytest.mark.parametrize("path", [r"C:\Windows\win.ini", "/etc/passwd", "../app.py", "", "%s/../../app.py"])
def test_file_endpoint_only_serves_portal_files(app_client, path, tmpdir_root):
    if "%s" in path:
        path = path % os.environ["OUTPUT_DIR"]
    assert app_client.get("/api/file", query_string={"path": path}).status_code == 404


def test_login_when_password_set(monkeypatch):
    import app as portal
    monkeypatch.setattr(portal, "APP_PASSWORD", "pw123")
    with portal.app.test_client() as c:
        assert c.get("/api/purchases").status_code == 401
        assert c.get("/").status_code == 302
        assert b"Wrong password" in c.post("/login", data={"password": "nope"}).data
        assert c.post("/login", data={"password": "pw123"}).status_code == 302
        assert c.get("/api/purchases").status_code == 200


# ---------------------------------------------------------------- scanning (AI mocked)
def test_scan_maps_quote_without_fixing_gst(app_client, monkeypatch):
    fake = {"vendor": {"name": "Dazzle Robotics Pvt. Ltd.", "gst": "24AADCD2072M1ZP", "address": ""},
            "quote_no": "1103100", "quote_date": "2025-10-26",
            "items": [{"description": "Motor", "hsn": "8501", "qty": 4, "rate": 3912, "gst": 18}],
            "other": 0, "other_gst": 0, "round_off": 0, "gst_total": 2816.64, "grand_total": 18464.64,
            "payment": "PO", "delivery": "1 week"}
    monkeypatch.setattr(extract, "extract_text", lambda path, s: ("text", "pdf-text"))
    monkeypatch.setattr(extract, "llm_structure", lambda kind, text, s: fake)
    r = app_client.post("/api/scan", data={"kind": "quote", "file": (io.BytesIO(b"%PDF-1.4"), "q.pdf")},
                        content_type="multipart/form-data").get_json()
    q = r["quote"]
    assert r["vendor_match"]["name"] == "DAZZLE ROBOTICS PVT. LTD."               # matched by GSTIN
    assert q["vendor"]["address"].startswith("B1+B2+B3/5")                        # filled from saved vendor
    assert q["gst_override"] == "" and q["scanned_grand"] == 18464.64
    assert q["scanned_items"] == q["items"] and not any(k.startswith("_") for k in q["vendor"])


def test_scan_falls_back_when_ai_fails(app_client, monkeypatch):
    monkeypatch.setattr(extract, "extract_text", lambda path, s: ("QUOTATION\nGSTIN 24ACVPG3865E1ZF\nQuotation No: ATE-1-26\nDate: 3-OCT-2025\nTotal 22,900.00", "pdf-text"))
    def boom(*a):
        raise RuntimeError("rate limited")
    monkeypatch.setattr(extract, "llm_structure", boom)
    r = app_client.post("/api/scan", data={"kind": "quote", "file": (io.BytesIO(b"x"), "q.pdf")}, content_type="multipart/form-data").get_json()
    assert r["warning"] == "rate limited" and r["parser"] == "regex"
    assert r["quote"]["quote_no"] == "ATE-1-26" and r["quote"]["quote_date"] == "2025-10-03"
    assert r["vendor_match"]["name"] == "ALL TECH ELECTRONICS"


def test_vision_error_never_leaks_key(monkeypatch):
    class R:
        status_code = 403
        text = "nope"
        def json(self):
            return {"error": {"message": "billing disabled"}}
    monkeypatch.setattr(extract.requests, "post", lambda *a, **k: R())
    with pytest.raises(RuntimeError) as e:
        extract.vision_ocr(b"img", "AIzaSECRET")
    assert "AIzaSECRET" not in str(e.value) and "billing disabled" in str(e.value)


def test_post_facto_allows_fewer_quotes_and_waiver_and_backup(app_client):
    import zipfile
    p = purchase(app_client, amount_rates=(5000,), post_facto=True, justification="urgent")
    r = app_client.post(f"/api/generate/permission/{p['id']}", json={})
    assert r.status_code == 200 and "Post-facto Permission" in r.get_json()["docs"][0]["files"][0]
    pid = store.all_("projects", "id ASC")[0]["id"]
    c = app_client.post("/api/reimbursements", json={"project_id": pid, "date": "2026-10-07", "title": "W"}).get_json()
    assert app_client.post(f"/api/generate/waiver/{c['id']}", json={}).status_code == 400
    c["bills"] = [{"biller": "Hydro", "items": "Hub", "amount": 2950, "bill_no": "T/1", "bill_date": "2026-10-01"}]
    app_client.post("/api/reimbursements", json=c)
    r = app_client.post(f"/api/generate/waiver/{c['id']}", json={})
    assert r.status_code == 200 and r.get_json()["docs"][0]["kind"] == "waiver"
    z = app_client.get("/api/backup")
    assert z.status_code == 200 and z.mimetype == "application/zip"
    import io
    names = zipfile.ZipFile(io.BytesIO(z.data)).namelist()
    assert "data/portal.db" in names and any(n.endswith(".pdf") for n in names)


def test_regenerate_after_changes_keeps_only_the_new_document(app_client):
    """Madhav's case: generate, change details (even the subject), generate again."""
    import pymupdf
    p = purchase(app_client, title="Permission to purchase for Permission to Purchase Motor Drivers and Buck Converters")
    assert p["title"] == "Motor Drivers and Buck Converters"                     # duplicate wording removed
    first = app_client.post(f"/api/generate/permission/{p['id']}", json={}).get_json()
    old_pdf = first["docs"][0]["files"][1]
    folder = os.path.dirname(old_pdf)
    assert os.path.basename(folder) == f"Purchase {p['id']} - Motor Drivers and Buck Converters"
    assert os.path.basename(old_pdf) == "Purchase Permission.pdf"

    p = first
    p["title"] = "Motor drivers (revised)"
    p["quotes"][0]["items"][0]["rate"] = 4321
    app_client.post("/api/purchases", json=p)
    second = app_client.post(f"/api/generate/permission/{p['id']}", json={}).get_json()
    new_pdf = [d for d in second["docs"] if d["kind"] == "permission"][0]["files"][1]
    assert os.path.basename(os.path.dirname(new_pdf)) == f"Purchase {p['id']} - Motor drivers (revised)"
    assert not os.path.exists(folder)                                             # same folder, renamed
    assert len(os.listdir(os.path.dirname(new_pdf))) == 2                          # only the new docx + pdf
    text = "".join(pg.get_text() for pg in pymupdf.open(new_pdf))
    assert "Rs. 4,321.00" in text and "Motor drivers (revised)" in text
    assert len(new_pdf) < 200                                                     # far below Windows' 260 limit


def test_post_facto_switch_replaces_normal_permission(app_client):
    p = purchase(app_client)
    first = app_client.post(f"/api/generate/permission/{p['id']}", json={}).get_json()
    old = first["docs"][0]["files"]
    first["post_facto"] = True
    app_client.post("/api/purchases", json=first)
    second = app_client.post(f"/api/generate/permission/{p['id']}", json={}).get_json()
    assert not any(os.path.exists(f) for f in old)
    assert [os.path.basename(f) for f in second["docs"][0]["files"]] == ["Post-facto Permission.docx", "Post-facto Permission.pdf"]
