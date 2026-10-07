import random

import pytest

from money import indian, rs, words, totals, r2
from rules import slab_for, requirements, can_mark, applicable_stages, DEFAULT_SLABS


# ---------------------------------------------------------------- formatting
@pytest.mark.parametrize("x,out", [
    (0, "0.00"), (5, "5.00"), (999, "999.00"), (1000, "1,000.00"), (30850, "30,850.00"),
    (300000, "3,00,000.00"), (1234567.891, "12,34,567.89"), (10000000, "1,00,00,000.00"), (-2050.5, "-2,050.50"),
])
def test_indian_grouping(x, out):
    assert indian(x) == out


def test_rs_prefix():
    assert rs(36403) == "Rs. 36,403.00"


@pytest.mark.parametrize("n,out", [
    (0, "Zero only"), (1, "One only"), (19, "Nineteen only"), (20000, "Twenty Thousand only"),
    (34273, "Thirty Four Thousand Two Hundred Seventy Three only"),
    (300000, "Three Lakh only"), (1000001, "Ten Lakh One only"), (12500000, "One Crore Twenty Five Lakh only"),
    (7599.6, "Seven Thousand Six Hundred only"),
])
def test_words(n, out):
    assert words(n) == out


# ---------------------------------------------------------------- totals against real past documents
REAL = [
    ("Jetson", [(1, 24950), (1, 1400), (1, 4500)], 0, 0, 0, 0, 36403.00),
    ("Motors", [(4, 3912)], 0, 0, 0, 0, 18464.64),
    ("Lidar", [(1, 23321)], 0, 0, 0, 0, 27518.78),
    ("Printer with discount", [(1, 40000), (1, 3000), (100, 5)], 3500, 0, 0, 0, 47200.00),
    ("Battery rounded", [(1, 38395)], 0, 0, 0, -0.10, 45306.00),
    ("Soil sensor rounded", [(1, 30508)], 0, 0, 0, 0.56, 36000.00),
    ("Camera", [(1, 15500), (1, 4350)], 0, 0, 0, 0, 23423.00),
    ("Dazzle motors", [(2, 3548), (4, 268)], 0, 0, 0, -0.24, 9638.00),
    ("Prayog with taxed shipping", [(2, 3924)], 0, 180, 18, -0.04, 9473.00),
]


@pytest.mark.parametrize("name,items,disc,ship,sg,ro,expect", REAL, ids=[r[0] for r in REAL])
def test_matches_real_documents(name, items, disc, ship, sg, ro, expect):
    t = totals([{"qty": q, "rate": r, "gst": 18} for q, r in items], disc, None, ship, other_gst=sg, round_off=ro)
    assert t["grand"] == pytest.approx(expect, abs=0.005)


def test_parts_always_add_up():
    random.seed(1)
    for _ in range(3000):
        items = [{"qty": random.choice([1, 2, 3, 7, 100, 0.5]), "rate": round(random.uniform(0, 50000), random.choice([0, 2, 3])),
                  "gst": random.choice([0, 5, 12, 18, 28, "", None])} for _ in range(random.randint(0, 6))]
        t = totals(items, random.choice([0, 0, 123.45]), random.choice([None, None, "", 99.99]),
                   random.choice([0, 180, 211.86]), other_gst=random.choice([0, 18]), round_off=random.choice([0, -0.24, 0.4]))
        assert t["grand"] == r2(t["subtotal"] - t["discount"] + t["gst"] + t["other"])
        for k in ("subtotal", "gst", "other", "grand"):
            assert t[k] == r2(t[k])


def test_blank_gst_means_18_percent_and_zero_is_zero():
    assert totals([{"qty": 1, "rate": 100, "gst": ""}])["gst"] == 18
    assert totals([{"qty": 1, "rate": 100, "gst": None}])["gst"] == 18
    assert totals([{"qty": 1, "rate": 100, "gst": 0}])["gst"] == 0


def test_override_is_used_only_when_given():
    assert totals([{"qty": 1, "rate": 100}], gst_override="")["gst"] == 18
    assert totals([{"qty": 1, "rate": 100}], gst_override=5)["gst"] == 5


def test_empty_and_garbage_inputs():
    assert totals([])["grand"] == 0
    assert totals(None)["grand"] == 0
    assert totals([{"qty": "", "rate": ""}])["grand"] == 0


# ---------------------------------------------------------------- slabs
@pytest.mark.parametrize("amount,auth,quotes,po,audit", [
    (0, "hod", 1, False, False), (2999.99, "hod", 1, False, False), (3000, "hod", 1, False, False),
    (3000.01, "hod_statement", 3, True, False), (10000, "hod_statement", 3, True, False),
    (10000.01, "director", 3, True, True), (50000, "director", 3, True, True),
    (50000.01, "vp", 3, True, True), (5_00_000, "vp", 3, True, True),
])
def test_slab_boundaries(amount, auth, quotes, po, audit):
    s = slab_for(amount, DEFAULT_SLABS)
    assert (s["authority"], s["quotes"], s["po"], s["audit"]) == (auth, quotes, po, audit)


def test_requirements_documents_by_route():
    assert "Cash Voucher" in " ".join(requirements(2000, 1, route="personal")["documents"])
    assert "Advance Voucher" in " ".join(requirements(2000, 1, route="advance")["documents"])
    r = requirements(20000, 2)
    assert not r["quotes_ok"] and r["quotes"] == 3
    assert any("Audit" in d for d in r["documents"])


# ---------------------------------------------------------------- workflow gating
def test_gating_order_for_audit_slab():
    slab = slab_for(20000)
    done = {}
    order = [s["key"] for s in applicable_stages(slab)]
    assert "tally_po" not in order          # Tally PO only for 3k-10k
    assert can_mark("po_made", done, slab)[0] is False
    assert can_mark("outward", done, slab)[0] is False
    for key in ["quotes", "permission_made", "permission_approved", "po_made", "audit", "po_approved", "outward", "po_issued",
                "bill", "seal_nirvan", "submitted", "settled"]:
        ok, why = can_mark(key, done, slab)
        assert ok, f"{key}: {why}"
        done[key] = "x"


def test_stage_not_applicable_below_3000():
    slab = slab_for(1500)
    ok, why = can_mark("po_made", {"permission_approved": "x"}, slab)
    assert not ok and "not applicable" in why
    ok, _ = can_mark("bill", {"permission_approved": "x"}, slab)
    assert ok


def test_every_stage_requires_its_predecessors():
    for amount in (1000, 5000, 20000, 80000):
        slab = slab_for(amount)
        keys = {s["key"] for s in applicable_stages(slab)}
        for s in applicable_stages(slab):
            needs = [n for n in s.get("needs", []) if n in keys]
            if needs:
                assert can_mark(s["key"], {}, slab)[0] is False
