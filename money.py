"""Indian-style money formatting and amount-in-words, matching the existing documents."""
from decimal import Decimal, ROUND_HALF_UP


def r2(x) -> float:
    return float(Decimal(str(x or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def indian(x, decimals=2) -> str:
    """12345678.5 -> '1,23,45,678.50'"""
    x = r2(x)
    neg = x < 0
    s = f"{abs(x):.{decimals}f}"
    whole, _, frac = s.partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    out = whole + ("." + frac if decimals else "")
    return ("-" if neg else "") + out


def rs(x) -> str:
    """'Rs. 30,850.00' – the style used in permissions / POs."""
    return f"Rs. {indian(x)}"


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
         "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen",
         "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n):
    if n < 20:
        return _ONES[n]
    return (_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else "")).strip()


def _three(n):
    h, rest = divmod(n, 100)
    out = []
    if h:
        out.append(_ONES[h] + " Hundred")
    if rest:
        out.append(_two(rest))
    return " ".join(out)


def words(amount) -> str:
    """Whole-rupee amount in Indian words: 34273 -> 'Thirty Four Thousand Two Hundred Seventy Three only'"""
    n = int(Decimal(str(amount or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if n == 0:
        return "Zero only"
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(_three(crore) + " Crore")
    if lakh:
        parts.append(_two(lakh) + " Lakh")
    if thousand:
        parts.append(_two(thousand) + " Thousand")
    if n:
        parts.append(_three(n))
    return " ".join(parts) + " only"


def totals(items, discount=0, gst_override=None, other=0, inclusive=False, other_gst=0, round_off=0):
    """Subtotal / GST / other / grand total for one quotation.

    items: [{description, qty, rate, gst}] – rate excludes GST (unless inclusive=True).
    other: shipping / packing etc. before GST; other_gst: GST % charged on it.
    round_off: the vendor's rounding (e.g. -0.24), not taxed.
    Every part is rounded to paise first and the grand total is the sum of the rounded parts,
    so Total + GST + Other charges always equals Grand Total on the printed documents.
    """
    sub = 0.0
    gst_items = 0.0
    for it in items or []:
        line = r2(float(it.get("qty") or 0) * float(it.get("rate") or 0))
        sub += line
        if not inclusive:
            g = it.get("gst")
            gst_items += line * (18.0 if g in (None, "") else float(g)) / 100
    sub = r2(sub)
    discount = r2(discount or 0)
    if sub and discount and not inclusive:
        gst_items = gst_items * (sub - discount) / sub
    other = r2(other or 0)
    gst = r2(gst_items + other * float(other_gst or 0) / 100)
    if gst_override not in (None, ""):
        gst = r2(gst_override)
    other_total = r2(other + float(round_off or 0))
    grand = r2(sub - discount + gst + other_total)
    return {"subtotal": sub, "discount": discount, "gst": gst, "other": other_total,
            "shipping": other, "round_off": r2(round_off or 0), "grand": grand}
