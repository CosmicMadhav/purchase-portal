"""Purchase Portal – local web app for Nirma purchase paperwork.

Run:  python app.py   then open http://127.0.0.1:5050
"""
import os
import re
import traceback
from datetime import date

from flask import Flask, jsonify, request, send_file, send_from_directory, abort

import store
from rules import requirements, slab_for, applicable_stages, can_mark, STAGES, AUTHORITY_NAMES
from money import totals, r2
from gen_word import build_permission, build_po, build_rfq, build_waiver, selected_quote, quote_totals, dmy
from gen_excel import build_advance_voucher, build_advance_adjustment, build_cash_voucher
from convert import docx_to_pdf
import extract

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(HERE, "data", "uploads")
app = Flask(__name__, static_folder="static", static_url_path="/static")
store.init()

CRUD = {"projects", "vendors", "items", "purchases", "advances", "reimbursements", "ledger"}
SECRET_KEYS = ("llm_key", "vision_key")


def err(msg, code=400):
    return jsonify({"error": msg}), code


@app.errorhandler(Exception)
def on_error(e):
    if hasattr(e, "code") and isinstance(getattr(e, "code"), int) and e.code < 500:
        return err(str(e), e.code)
    traceback.print_exc()
    return err(f"{type(e).__name__}: {e}", 500)


# ------------------------------------------------------------------ optional login (set APP_PASSWORD)
APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(24)


@app.before_request
def require_login():
    from flask import session, redirect
    if not APP_PASSWORD or session.get("ok") or request.path in ("/login",):
        return None
    if request.path.startswith("/api/"):
        return err("Login required", 401)
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    from flask import session, redirect
    bad = ""
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["ok"] = True
            session.permanent = True
            return redirect("/")
        bad = "<p style='color:#a3262a'>Wrong password</p>"
    return (f"<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'><title>Purchase Portal</title>"
            f"<body style='font:15px Segoe UI,sans-serif;display:grid;place-items:center;height:100vh;background:#f4f5f2;margin:0'>"
            f"<form method=post style='background:#fff;padding:28px;border-radius:10px;border:1px solid #dfe3dd;width:300px'>"
            f"<h2 style='margin-top:0'>Purchase Portal</h2>{bad}<input type=password name=password autofocus placeholder=Password "
            f"style='width:100%;padding:9px;border:1px solid #dfe3dd;border-radius:6px;box-sizing:border-box'>"
            f"<button style='margin-top:12px;width:100%;padding:9px;background:#2f6b45;color:#fff;border:0;border-radius:6px'>"
            f"Open</button></form>")


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ------------------------------------------------------------------ settings
@app.get("/api/settings")
def get_settings():
    s = store.get_settings()
    for k in SECRET_KEYS:
        s[k + "_set"] = bool(s.get(k))
        s[k] = ""
    s["can_open_folder"] = hasattr(os, "startfile")
    s["output_base"] = os.path.abspath(output_base())
    s["output_fixed"] = bool(os.environ.get("OUTPUT_DIR"))
    s["authority_names"] = AUTHORITY_NAMES
    s["stages"] = STAGES
    return jsonify(s)


@app.post("/api/settings")
def post_settings():
    d = request.json or {}
    for k in SECRET_KEYS:
        if not d.get(k):
            d.pop(k, None)          # empty field = keep the stored key
        if d.get(k + "_clear"):
            d[k] = ""
        d.pop(k + "_set", None)
        d.pop(k + "_clear", None)
    d.pop("authority_names", None)
    d.pop("can_open_folder", None)
    d.pop("output_base", None)
    d.pop("output_fixed", None)
    d.pop("stages", None)
    store.set_settings(d)
    return get_settings()


# ------------------------------------------------------------------ CRUD
@app.get("/api/<table>")
def list_(table):
    if table not in CRUD:
        abort(404)
    return jsonify(store.all_(table, "id ASC" if table in ("projects",) else "id DESC"))


@app.get("/api/<table>/<int:id_>")
def get_(table, id_):
    if table not in CRUD:
        abort(404)
    rec = store.get(table, id_)
    return jsonify(rec) if rec else err("Not found", 404)


@app.post("/api/<table>")
def save_(table):
    if table not in CRUD:
        abort(404)
    d = request.json or {}
    if table == "purchases":
        d = enrich_purchase(d)
        # remember vendors/items from every quotation
        for q in d.get("quotes") or []:
            v = store.remember_vendor(q.get("vendor") or {})
            if v:
                q["vendor"]["id"] = v["id"]
                for k in ("address", "gst", "phone", "email"):   # fill gaps from the saved vendor
                    if not q["vendor"].get(k) and v.get(k):
                        q["vendor"][k] = v[k]
        sel = selected_quote(d)
        store.remember_items(sel.get("items"), (sel.get("vendor") or {}).get("name"), d.get("date"))
    return jsonify(store.save(table, d))


@app.delete("/api/<table>/<int:id_>")
def del_(table, id_):
    if table not in CRUD:
        abort(404)
    store.delete(table, id_)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ rules / budget
def enrich_purchase(p):
    s = store.get_settings()
    p["title"] = clean_title(p.get("title"))
    q = selected_quote(p)
    t = quote_totals(q)
    p["amount"] = t["grand"]
    p["totals"] = t
    req = requirements(t["grand"], len(p.get("quotes") or []), s["slabs"], p.get("route") or "po")
    p["req"] = req
    return p


@app.post("/api/rules")
def rules_():
    d = request.json or {}
    s = store.get_settings()
    q = selected_quote(d)
    t = quote_totals(q)
    req = requirements(t["grand"], len(d.get("quotes") or []), s["slabs"], d.get("route") or "po")
    req["totals"] = t
    req["stages"] = applicable_stages(req)
    req["all_totals"] = [quote_totals(x) for x in d.get("quotes") or []]
    return jsonify(req)


def budget_for(project_id, exclude=None):
    """Opening utilisation + everything committed in the portal. exclude=(table, id) leaves one record out
    (the audit page shows the utilisation *before* the PO in question)."""
    proj = store.get("projects", project_id) or {}
    entries = []
    for p in store.all_("purchases", "id ASC"):
        if str(p.get("project_id")) != str(project_id) or exclude == ("purchases", p["id"]):
            continue
        if (p.get("route") or "po") in ("po", "card") and (p.get("stages") or {}).get("permission_approved"):
            entries.append({"date": p.get("date"), "what": p.get("title"), "amount": r2(p.get("amount")),
                            "ref": f"purchases/{p['id']}"})
    for a in store.all_("advances", "id ASC"):
        if str(a.get("project_id")) != str(project_id) or exclude == ("advances", a["id"]):
            continue
        if (a.get("stages") or {}).get("adjustment_made"):
            amt = sum(float(b.get("amount") or 0) for b in a.get("bills") or [])
            entries.append({"date": a.get("adjust_date"), "what": f"Advance adjustment – {a.get('title', '')}",
                            "amount": r2(amt), "ref": f"advances/{a['id']}"})
    for c in store.all_("reimbursements", "id ASC"):
        if str(c.get("project_id")) != str(project_id) or exclude == ("reimbursements", c["id"]):
            continue
        if (c.get("stages") or {}).get("voucher_made"):
            amt = sum(float(b.get("amount") or 0) for b in c.get("bills") or [])
            entries.append({"date": c.get("date"), "what": f"Cash voucher – {c.get('title', '')}",
                            "amount": r2(amt), "ref": f"reimbursements/{c['id']}"})
    for l in store.all_("ledger", "id ASC"):
        if str(l.get("project_id")) == str(project_id):
            entries.append({"date": l.get("date"), "what": l.get("note"), "amount": r2(l.get("amount")),
                            "ref": f"ledger/{l['id']}"})
    provision = float(proj.get("provision") or 0)
    opening = float(proj.get("opening_utilized") or 0)
    utilized = r2(opening + sum(e["amount"] for e in entries))
    return {"provision": provision, "opening": opening, "opening_as_of": proj.get("opening_as_of"),
            "entries": entries, "utilized": utilized, "available": r2(provision - utilized),
            "as_of": date.today().isoformat()}


@app.get("/api/budget/<int:project_id>")
def budget(project_id):
    return jsonify(budget_for(project_id))


# ------------------------------------------------------------------ workflow stages
ADV_STAGES = [
    {"key": "voucher_made", "label": "Advance Voucher prepared"},
    {"key": "approved", "label": "Advance approved", "needs": ["voucher_made"]},
    {"key": "issued", "label": "Advance amount received", "needs": ["approved"]},
    {"key": "adjustment_made", "label": "Adjustment Voucher prepared", "needs": ["issued"]},
    {"key": "adjustment_approved", "label": "Adjustment approved", "needs": ["adjustment_made"]},
    {"key": "to_accounts", "label": "Sent to Accounts Section", "needs": ["adjustment_approved"]},
    {"key": "settled", "label": "Advance settled", "needs": ["to_accounts"]},
]
CV_STAGES = [
    {"key": "voucher_made", "label": "Cash Voucher prepared"},
    {"key": "submitted", "label": "Submitted with original bills", "needs": ["voucher_made"]},
    {"key": "verified", "label": "Verified / approved", "needs": ["submitted"]},
    {"key": "reimbursed", "label": "Amount reimbursed", "needs": ["verified"]},
]


def _simple_can_mark(stages, key, done):
    st = next((s for s in stages if s["key"] == key), None)
    if not st:
        return False, "Unknown stage"
    missing = [n for n in st.get("needs", []) if not done.get(n)]
    if missing:
        return False, "Pending first: " + ", ".join(s["label"] for s in stages if s["key"] in missing)
    return True, ""


@app.get("/api/stages/<table>")
def stage_defs(table):
    return jsonify({"advances": ADV_STAGES, "reimbursements": CV_STAGES}.get(table, STAGES))


@app.post("/api/<table>/<int:id_>/stage")
def mark_stage(table, id_):
    d = request.json or {}
    rec = store.get(table, id_)
    if not rec:
        return err("Not found", 404)
    done = rec.setdefault("stages", {})
    key, val = d.get("key"), bool(d.get("done"))
    if val:
        if table == "purchases":
            slab = slab_for(float(rec.get("amount") or 0), store.get_settings()["slabs"])
            ok, why = can_mark(key, done, slab)
        else:
            ok, why = _simple_can_mark(ADV_STAGES if table == "advances" else CV_STAGES, key, done)
        if not ok:
            return err(why, 409)
        done[key] = d.get("date") or date.today().isoformat()
    else:
        done.pop(key, None)
    return jsonify(store.save(table, rec))


# ------------------------------------------------------------------ files
def output_base():
    return os.environ.get("OUTPUT_DIR") or store.get_settings().get("output_dir") or os.path.join(HERE, "data", "output")


def short(text, n):
    """Safe for Windows file names, cut at a word boundary, no trailing dot/space."""
    t = " ".join(re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", text or "").split())
    if len(t) > n:
        t = t[:n].rsplit(" ", 1)[0] if " " in t[:n] else t[:n]
    return t.rstrip(" .") or "Untitled"


def clean_title(title):
    """'Permission to purchase for Permission to Purchase X' -> 'X'."""
    return re.sub(r"^\s*(subject\s*:\s*)?((permission\s+to\s+purchase|purchase\s+order)(\s+for)?\s*[:\-]?\s*)+",
                  "", title or "", flags=re.I).strip()


def record_dir(project, label, rec):
    """One fixed folder per record, e.g. 'Purchase 2 - Electronics Components'. If the title changes,
    the same folder is renamed, so old and new copies never sit in different places."""
    proj_dir = os.path.join(output_base(), short(project.get("name") or "Project", 40))
    os.makedirs(proj_dir, exist_ok=True)
    prefix = f"{label} {rec['id']} - "
    name = prefix + short(clean_title(rec.get("title")) or label, 45)
    path = os.path.join(proj_dir, name)
    for existing in os.listdir(proj_dir):
        if existing.startswith(prefix) and existing != name:
            try:
                os.rename(os.path.join(proj_dir, existing), path)
            except OSError:
                path = os.path.join(proj_dir, existing)
            break
    os.makedirs(path, exist_ok=True)
    return path


def fname(*parts):
    return short(" - ".join(p for p in parts if p), 70)


def file_entry(kind, *paths):
    return {"kind": kind, "files": [p for p in paths if p], "made": store.now()}


@app.get("/api/file")
def get_file():
    path = os.path.abspath(request.args.get("path", ""))
    base = os.path.abspath(output_base())
    allowed = [base, os.path.abspath(UPLOADS), os.path.abspath(os.path.join(HERE, "data", "output"))]
    if not any(path.startswith(a + os.sep) for a in allowed) or not os.path.exists(path):
        abort(404)
    resp = send_file(path, as_attachment=request.args.get("dl") == "1", conditional=False, etag=False,
                     last_modified=None, max_age=0)
    resp.headers["Cache-Control"] = "no-store, max-age=0"   # always the latest regenerated file
    return resp


@app.post("/api/open-folder")
def open_folder():
    path = os.path.abspath((request.json or {}).get("path", ""))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if os.path.isdir(path) and hasattr(os, "startfile"):
        os.startfile(path)
    return jsonify({"ok": True})


# ------------------------------------------------------------------ generation
def _project(rec):
    proj = store.get("projects", int(rec.get("project_id") or 0))
    if not proj:
        raise ValueError("Choose a project first")
    return proj


def _push_doc(table, rec, entry):
    """Record the new files and delete the previous version's files, so only the latest exists."""
    rec = store.get(table, rec["id"])
    base = os.path.abspath(output_base())
    for old in [x for x in rec.get("docs") or [] if x["kind"] == entry["kind"]]:
        for f in old.get("files", []):
            if f not in entry["files"] and os.path.abspath(f).startswith(base + os.sep) and os.path.exists(f):
                try:
                    os.remove(f)
                except OSError:
                    pass
    docs = [x for x in rec.get("docs") or [] if x["kind"] != entry["kind"]]
    docs.append(entry)
    rec["docs"] = docs
    return rec


@app.post("/api/generate/<kind>/<int:id_>")
def generate(kind, id_):
    s = store.get_settings()
    body = request.json or {}

    if kind in ("permission", "po", "rfq"):
        p = store.get("purchases", id_)
        if not p:
            return err("Save the purchase first", 404)
        proj = _project(p)
        t = quote_totals(selected_quote(p))
        slab = slab_for(t["grand"], s["slabs"])
        nq = len(p.get("quotes") or [])
        folder = record_dir(proj, "Purchase", p)
        stages = p.setdefault("stages", {})

        if kind == "permission":
            if (proj.get("letter_style") != "incubation" and nq < int(slab["quotes"]) and not p.get("quote_waiver")
                    and not p.get("post_facto")):
                return err(f"This amount (Rs. {t['grand']:,.2f}) needs {slab['quotes']} quotations – "
                           f"you have {nq}. Add the quotations (or tick 'single source / waiver' if that "
                           f"applies).", 409)
            label = "Post-facto Permission" if p.get("post_facto") else "Purchase Permission"
            path = build_permission(p, proj, os.path.join(folder, label + ".docx"), s["slabs"])
            pdf = docx_to_pdf(path)
            p = _push_doc("purchases", p, file_entry("permission", path, pdf))
            p.setdefault("stages", {})
            p["stages"].setdefault("quotes", date.today().isoformat())
            p["stages"].setdefault("permission_made", date.today().isoformat())
            return jsonify(store.save("purchases", p))

        if kind == "po":
            if not slab["po"] and not body.get("force"):
                return err("A Purchase Order is not required up to Rs. 3,000.", 409)
            if not stages.get("permission_approved"):
                return err("Purchase Permission is not approved yet – the PO cannot be created. "
                           "Mark 'Permission approved' once it is signed.", 409)
            budget = budget_for(int(p["project_id"]), exclude=("purchases", p["id"]))
            path = build_po(p, proj, os.path.join(folder, "Purchase Order.docx"),
                            budget, s["slabs"])
            pdf = docx_to_pdf(path, smart_page_break=False)
            p = _push_doc("purchases", p, file_entry("po", path, pdf))
            p["stages"].setdefault("po_made", date.today().isoformat())
            return jsonify(store.save("purchases", p))

        if kind == "rfq":
            files = []
            for q in p.get("quotes") or []:
                v = q.get("vendor") or {}
                if not v.get("name"):
                    continue
                path = build_rfq(p, proj, v, os.path.join(folder, fname("Quotation Request", short(v["name"], 35)) + ".docx"))
                files += [path, docx_to_pdf(path, smart_page_break=False)]
            if not files:
                return err("Add the vendors (in the quotation cards) to send requests to.", 400)
            p = _push_doc("purchases", p, file_entry("rfq", *files))
            return jsonify(store.save("purchases", p))

    if kind in ("advance_voucher", "advance_adjustment"):
        a = store.get("advances", id_)
        if not a:
            return err("Save the advance first", 404)
        proj = _project(a)
        folder = record_dir(proj, "Advance", a)
        if kind == "advance_voucher":
            budget = budget_for(int(a["project_id"]), exclude=("advances", a["id"]))
            base = os.path.join(folder, "Advance Voucher")
            build_advance_voucher(a, proj, budget, base + ".xlsx", base + ".pdf")
            a = _push_doc("advances", a, file_entry("advance_voucher", base + ".xlsx", base + ".pdf"))
            a.setdefault("stages", {}).setdefault("voucher_made", date.today().isoformat())
            return jsonify(store.save("advances", a))
        if not (a.get("stages") or {}).get("issued"):
            return err("Mark 'Advance amount received' first – an adjustment can only be made against an "
                       "issued advance.", 409)
        if not a.get("bills"):
            return err("Add the bills spent from this advance.", 400)
        budget = budget_for(int(a["project_id"]), exclude=("advances", a["id"]))
        adj = dict(a, date=a.get("adjust_date") or date.today().isoformat())
        base = os.path.join(folder, "Advance Adjustment Voucher")
        build_advance_adjustment(adj, proj, budget, base + ".xlsx", base + ".pdf")
        a = _push_doc("advances", a, file_entry("advance_adjustment", base + ".xlsx", base + ".pdf"))
        a["stages"].setdefault("adjustment_made", date.today().isoformat())
        a.setdefault("adjust_date", adj["date"])
        return jsonify(store.save("advances", a))

    if kind == "cash_voucher":
        c = store.get("reimbursements", id_)
        if not c:
            return err("Save the reimbursement first", 404)
        proj = _project(c)
        perm_ref = c.get("post_facto_ref") or ""
        if c.get("purchase_id"):
            p = store.get("purchases", int(c["purchase_id"]))
            if not p or not (p.get("stages") or {}).get("permission_approved"):
                return err("The linked Purchase Permission is not approved yet. Personal payment does not "
                           "replace prior approval.", 409)
            perm_ref = f"Permission dated {dmy(p.get('date'))} – {p.get('title', '')}"
        if not perm_ref:
            return err("Link the approved Purchase Permission (or enter the post-facto approval reference).", 409)
        if not c.get("bills"):
            return err("Add the original bill(s).", 400)
        budget = budget_for(int(c["project_id"]), exclude=("reimbursements", c["id"]))
        folder = record_dir(proj, "Reimbursement", c)
        base = os.path.join(folder, "Cash Voucher")
        build_cash_voucher(dict(c, permission_ref=perm_ref), proj, budget, base + ".xlsx", base + ".pdf")
        c = _push_doc("reimbursements", c, file_entry("cash_voucher", base + ".xlsx", base + ".pdf"))
        c.setdefault("stages", {}).setdefault("voucher_made", date.today().isoformat())
        return jsonify(store.save("reimbursements", c))

    if kind == "waiver":
        c = store.get("reimbursements", id_)
        if not c:
            return err("Save the reimbursement first", 404)
        if not c.get("bills"):
            return err("Add the bills the waiver is for.", 400)
        proj = _project(c)
        folder = record_dir(proj, "Reimbursement", c)
        path = build_waiver(c, proj, os.path.join(folder, "Waiver.docx"))
        pdf = docx_to_pdf(path, smart_page_break=False)
        c = _push_doc("reimbursements", c, file_entry("waiver", path, pdf))
        return jsonify(store.save("reimbursements", c))

    return err("Unknown document type", 404)


# ------------------------------------------------------------------ backup
@app.get("/api/backup")
def backup():
    """One zip with the database (incl. keys), private details and every generated document."""
    import io
    import sqlite3
    import tempfile
    import zipfile
    buf = io.BytesIO()
    with tempfile.TemporaryDirectory() as tmp:
        snap = os.path.join(tmp, "portal.db")
        src = sqlite3.connect(store.DB)
        dst = sqlite3.connect(snap)
        src.backup(dst)          # consistent copy even while the portal is running
        dst.close()
        src.close()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(snap, "data/portal.db")
            priv = os.path.join(os.path.dirname(store.DB), "private_seed.json")
            if os.path.exists(priv):
                z.write(priv, "data/private_seed.json")
            base = output_base()
            for root, _, files in os.walk(base):
                for f in files:
                    full = os.path.join(root, f)
                    z.write(full, os.path.join("data", "output", os.path.relpath(full, base)))
    buf.seek(0)
    from datetime import datetime
    return send_file(buf, mimetype="application/zip", as_attachment=True,
                     download_name=f"purchase-portal-backup-{datetime.now():%Y-%m-%d}.zip")


# ------------------------------------------------------------------ scanning
@app.post("/api/scan")
def scan():
    f = request.files.get("file")
    kind = request.form.get("kind", "quote")
    if not f:
        return err("No file")
    os.makedirs(UPLOADS, exist_ok=True)
    name = re.sub(r"[^\w.\- ]+", "_", f.filename or "upload")
    path = os.path.join(UPLOADS, f"{store.now().replace(':', '')}_{name}")
    f.save(path)
    res = extract.scan(path, kind, store.get_settings())
    res["file"] = path
    if kind == "quote":
        d = res["data"]
        v = d.get("vendor") or {}
        match = store.find_vendor(v.get("name"), v.get("gst"))
        if match:
            match = {k: val for k, val in match.items() if not k.startswith("_")}
        res["vendor_match"] = match
        items = []
        for it in d.get("items") or []:
            items.append({"description": it.get("description", ""), "hsn": it.get("hsn", ""),
                          "qty": it.get("qty") or 1, "rate": it.get("rate") or 0,
                          "gst": it.get("gst") if it.get("gst") not in (None, "") else 18})
        res["quote"] = {
            "vendor": {**(match or {}), **{k: v2 for k, v2 in v.items() if v2}} if match else v,
            "quote_no": d.get("quote_no", ""), "quote_date": d.get("quote_date", ""),
            "items": items, "scanned_items": [dict(i) for i in items],
            "discount": d.get("discount") or 0, "other": d.get("other") or 0,
            "other_gst": d.get("other_gst") or 0, "round_off": d.get("round_off") or 0,
            "gst_override": "", "scanned_grand": d.get("grand_total") or "",
            "scanned_gst": d.get("gst_total") or "", "payment": d.get("payment", ""),
            "delivery": d.get("delivery", ""), "file": path,
        }
        if match:
            res["quote"]["vendor"]["name"] = match["name"]
    return jsonify(res)


def _open_browser_when_ready(url):
    import socket, time, webbrowser
    for _ in range(60):
        try:
            socket.create_connection(("127.0.0.1", int(url.rsplit(":", 1)[1])), timeout=0.5).close()
            webbrowser.open(url)
            return
        except OSError:
            time.sleep(0.5)


if __name__ == "__main__":
    import socket, threading, webbrowser
    port = int(os.environ.get("PORT", 5050))
    url = f"http://127.0.0.1:{port}"
    try:  # already running (double-clicked twice)? just open the page
        socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
        webbrowser.open(url)
        raise SystemExit
    except OSError:
        pass
    if not os.environ.get("NO_BROWSER"):
        threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True).start()
    print(f"Purchase Portal running on {url}  (keep this window open; close it to stop)")
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=port, debug=False, threaded=True)
