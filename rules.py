"""Purchase-value rules (approval matrix, quotations, PO, audit).

Defaults follow the procedure document plus the practical rule given by Madhav:
  * up to 3,000      -> HOD, no quotation comparison, no PO, no audit
  * 3,001 - 10,000   -> 3-party comparison; with that it stays in HOD's power; PO (Tally + normal), no audit
  * 10,001 - 50,000  -> Director, 3 quotations, PO + Internal Audit + Outward
  * above 50,000     -> Vice President, 3 quotations, PO + Internal Audit + Outward
All of it is editable from Settings, so nothing here is hard-wired.
"""

DEFAULT_SLABS = [
    {"upto": 3000, "label": "Up to Rs. 3,000", "authority": "hod", "quotes": 1,
     "po": False, "tally_po": False, "audit": False, "outward": False},
    {"upto": 10000, "label": "Rs. 3,001 - 10,000", "authority": "hod_statement", "quotes": 3,
     "po": True, "tally_po": True, "audit": False, "outward": False},
    {"upto": 50000, "label": "Rs. 10,001 - 50,000", "authority": "director", "quotes": 3,
     "po": True, "tally_po": False, "audit": True, "outward": True},
    {"upto": None, "label": "Above Rs. 50,000", "authority": "vp", "quotes": 3,
     "po": True, "tally_po": False, "audit": True, "outward": True},
]

AUTHORITY_NAMES = {
    "hod": "HOD",
    "hod_statement": "HOD (with comparison)",
    "director": "Director",
    "vp": "Vice President",
}

# Short name used on the PO audit page ("Name of Authority: VP dated ...")
AUTHORITY_SHORT = {"hod": "HOD", "hod_statement": "HOD", "director": "Director", "vp": "VP"}


def slab_for(amount, slabs=None):
    slabs = slabs or DEFAULT_SLABS
    for s in slabs:
        if s["upto"] is None or amount <= float(s["upto"]):
            return s
    return slabs[-1]


# Workflow stages. 'needs' lists the stages that must be done first.
STAGES = [
    {"key": "quotes", "label": "Quotations collected"},
    {"key": "permission_made", "label": "Purchase Permission prepared", "needs": ["quotes"]},
    {"key": "permission_approved", "label": "Permission approved", "needs": ["permission_made"]},
    {"key": "po_made", "label": "PO prepared", "needs": ["permission_approved"], "if": "po"},
    {"key": "tally_po", "label": "Tally PO prepared", "needs": ["permission_approved"], "if": "tally_po"},
    {"key": "audit", "label": "Internal Audit cleared", "needs": ["po_made"], "if": "audit"},
    {"key": "po_approved", "label": "PO approved", "needs": ["po_made"], "if": "po"},
    {"key": "outward", "label": "Outward done", "needs": ["audit", "po_approved"], "if": "outward"},
    {"key": "po_issued", "label": "PO given to vendor", "needs": ["po_approved", "outward"], "if": "po"},
    {"key": "bill", "label": "Vendor bill received", "needs": ["permission_approved"]},
    {"key": "seal_nirvan", "label": "Budget seal + Nirvan entry", "needs": ["bill"]},
    {"key": "submitted", "label": "Bill submitted to Accounts", "needs": ["seal_nirvan"]},
    {"key": "settled", "label": "Paid / settled", "needs": ["submitted"]},
]


def applicable_stages(slab):
    return [s for s in STAGES if not s.get("if") or slab.get(s["if"])]


def can_mark(stage_key, done: dict, slab) -> tuple[bool, str]:
    keys = {s["key"] for s in applicable_stages(slab)}
    stage = next((s for s in STAGES if s["key"] == stage_key), None)
    if not stage or stage_key not in keys:
        return False, "Stage not applicable for this purchase value"
    missing = [n for n in stage.get("needs", []) if n in keys and not done.get(n)]
    if missing:
        labels = [s["label"] for s in STAGES if s["key"] in missing]
        return False, "Pending first: " + ", ".join(labels)
    return True, ""


def requirements(amount, n_quotes, slabs=None, route="po"):
    s = slab_for(amount, slabs)
    out = dict(s)
    out["authority_name"] = AUTHORITY_NAMES.get(s["authority"], s["authority"])
    out["quotes_have"] = n_quotes
    out["quotes_ok"] = n_quotes >= int(s["quotes"])
    docs = ["Purchase Permission"]
    if s["quotes"] > 1:
        docs.append(f"{s['quotes']} quotations + comparative statement")
    if s["po"] and route == "po":
        docs.append("Purchase Order" + (" (Tally PO + normal PO)" if s.get("tally_po") else ""))
    if s["audit"] and route == "po":
        docs.append("Internal Audit page + Outward")
    if route == "advance":
        docs += ["Advance Voucher (request)", "Advance Adjustment Voucher after purchase"]
    if route == "personal":
        docs += ["Cash Voucher with original bill (reimbursement)"]
    docs += ["Vendor bill", "Budget seal + Nirvan entry"]
    out["documents"] = docs
    return out
