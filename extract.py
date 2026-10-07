"""Read a quotation / proforma / bill (PDF or photo) and pull out structured details.

1. Text: digital PDFs are read directly (PyMuPDF). Scanned PDFs and photos go to Google Vision OCR.
2. Structure: the text is sent to an LLM (xAI Grok, or Groq – both OpenAI-compatible) which returns JSON.
   Without an LLM key a simple regex fallback fills what it can (GSTIN, number, date, totals).
Everything extracted is shown in the form for checking before it is saved.
"""
import base64
import json
import re

import pymupdf
import requests

VISION_URL = "https://vision.googleapis.com/v1/images:annotate"
PROVIDERS = {
    "xai": "https://api.x.ai/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}
DEFAULT_MODELS = {"xai": "grok-4", "groq": "openai/gpt-oss-120b"}


# ------------------------------------------------------------------ text
def vision_ocr(image_bytes, key):
    body = {"requests": [{"image": {"content": base64.b64encode(image_bytes).decode()},
                          "features": [{"type": "DOCUMENT_TEXT_DETECTION"}]}]}
    r = requests.post(VISION_URL, params={"key": key}, json=body, timeout=60)
    if r.status_code >= 400:   # report Google's reason, never the URL (it contains the key)
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"Google Vision error {r.status_code}: {msg}")
    resp = r.json()["responses"][0]
    if "error" in resp:
        raise RuntimeError(resp["error"].get("message", "Vision error"))
    return resp.get("fullTextAnnotation", {}).get("text", "")


def extract_text(path, settings):
    key = settings.get("vision_key")
    low = path.lower()
    if low.endswith(".pdf"):
        doc = pymupdf.open(path)
        pages = []
        method = "pdf-text"
        for page in doc:
            t = page.get_text()
            if len(t.strip()) < 40:          # scanned page
                if not key:
                    raise RuntimeError("This PDF is scanned. Add the Google Vision API key in Settings to read it.")
                t = vision_ocr(page.get_pixmap(dpi=200).tobytes("png"), key)
                method = "vision-ocr"
            pages.append(t)
        return "\n\n".join(pages), method
    if not key:
        raise RuntimeError("Reading photos needs the Google Vision API key (Settings).")
    with open(path, "rb") as f:
        return vision_ocr(f.read(), key), "vision-ocr"


# ------------------------------------------------------------------ structure
QUOTE_SCHEMA = """{
  "vendor": {"name": "", "address": "multi-line postal address", "gst": "GSTIN", "phone": "", "email": ""},
  "quote_no": "quotation / proforma / order number",
  "quote_date": "YYYY-MM-DD",
  "items": [{"description": "", "hsn": "", "qty": 0, "rate": 0, "gst": 18}],
  "discount": 0,
  "other": 0,
  "other_gst": 0,
  "round_off": 0,
  "gst_total": 0,
  "grand_total": 0,
  "payment": "payment terms, short",
  "delivery": "delivery period, short",
  "validity": ""
}"""

BILL_SCHEMA = """{
  "biller": "seller name", "gst_no": "seller GSTIN", "bill_no": "", "bill_date": "YYYY-MM-DD",
  "items": "short comma separated list of item names", "gst": 0, "amount": 0
}"""


def _prompt(kind, text):
    if kind == "bill":
        rules = ("This is a tax invoice / bill. 'gst' is the total GST (CGST+SGST or IGST) amount in rupees, "
                 "'amount' is the final invoice total including GST.")
        schema = BILL_SCHEMA
    else:
        rules = ("This is a supplier quotation / proforma invoice sent to Nirma University. The vendor is the "
                 "SELLER, never Nirma University. 'rate' is the unit price BEFORE GST. 'gst' is the GST percent. "
                 "Put shipping/packing/delivery charges in 'other' (before GST), not as an item, and the GST percent "
                 "charged on them in 'other_gst' (0 if not taxed). 'round_off' is the rounding line (e.g. -0.24). "
                 "If prices already include GST, convert rate back to the pre-GST value. 'gst_total' is the total "
                 "tax amount, 'grand_total' the final payable amount.")
        schema = QUOTE_SCHEMA
    return (f"Extract details from the document text below. {rules} Use numbers (no commas, no currency "
            f"symbols). Unknown fields: empty string or 0. Reply with ONLY this JSON shape:\n{schema}\n\n"
            f"--- DOCUMENT TEXT ---\n{text[:15000]}")


def llm_structure(kind, text, settings):
    provider = settings.get("llm_provider") or "xai"
    key = settings.get("llm_key")
    if not key or provider not in PROVIDERS:
        return None
    model = settings.get("llm_model") or DEFAULT_MODELS[provider]
    r = requests.post(PROVIDERS[provider], timeout=120,
                      headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                      json={"model": model, "temperature": 0,
                            "messages": [{"role": "system", "content": "You convert business documents to JSON."},
                                         {"role": "user", "content": _prompt(kind, text)}]})
    if r.status_code >= 400:
        raise RuntimeError(f"{provider} error {r.status_code}: {r.text[:300]}")
    content = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        raise RuntimeError("LLM did not return JSON")
    return json.loads(m.group(0))


# ------------------------------------------------------------------ fallback
GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
NIRMA_GST = "24AAATT6829N1ZY"


def _num(s):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return 0.0


def _date(s):
    m = re.search(r"(\d{1,2})[-/. ](\d{1,2}|[A-Za-z]{3,9})[-/. ,]+(\d{2,4})", s)
    if not m:
        return ""
    d, mo, y = m.groups()
    months = "jan feb mar apr may jun jul aug sep oct nov dec".split()
    if not mo.isdigit():
        mo = str(months.index(mo[:3].lower()) + 1) if mo[:3].lower() in months else "1"
    y = ("20" + y) if len(y) == 2 else y
    return f"{y}-{int(mo):02d}-{int(d):02d}"


def heuristic(kind, text):
    gsts = [g for g in GSTIN.findall(text) if g != NIRMA_GST]
    amounts = [_num(a) for a in re.findall(r"(?:Total|TOTAL|Grand Total|Amount)[^\d\n]{0,25}([\d,]+\.?\d*)", text)]
    grand = max(amounts) if amounts else 0
    # a document number: on the same line as the label, and containing at least one digit
    no = None
    for pat in (r"(?:Quotation|Invoice|Proforma Invoice|Bill|Order|PI)[ \t]*(?:No\.?|#|Number)[ \t]*[:#.]?[ \t]*([A-Z0-9][\w/-]*\d[\w/-]*)",
                r"(?:Quotation|Invoice|Bill)[ \t]*[:#][ \t]*([A-Z0-9][\w/-]*\d[\w/-]*)",
                r"(?:Quotation|Invoice)[^\n]{0,15}?\b([A-Z]{2,}\w*[/-][\w/-]*\d[\w/-]*)"):
        no = re.search(pat, text, re.I)
        if no:
            break
    dt = re.search(r"(?:Date|Dated)\s*[:.]?\s*([^\n]{6,20})", text, re.I)
    first_line = next((l.strip() for l in text.splitlines() if len(l.strip()) > 3), "")
    if kind == "bill":
        return {"biller": first_line, "gst_no": gsts[0] if gsts else "", "bill_no": no.group(1) if no else "",
                "bill_date": _date(dt.group(1)) if dt else "", "items": "", "gst": 0, "amount": grand}
    return {"vendor": {"name": first_line, "address": "", "gst": gsts[0] if gsts else ""},
            "quote_no": no.group(1) if no else "", "quote_date": _date(dt.group(1)) if dt else "",
            "items": [], "discount": 0, "other": 0, "gst_total": 0, "grand_total": grand,
            "payment": "", "delivery": ""}


def scan(path, kind, settings):
    text, method = extract_text(path, settings)
    data, used = None, "regex"
    err = None
    try:
        data = llm_structure(kind, text, settings)
        if data is not None:
            used = settings.get("llm_provider") or "xai"
    except Exception as e:  # keep going with the fallback, but report it
        err = str(e)
    if data is None:
        data = heuristic(kind, text)
    return {"data": data, "text": text, "ocr": method, "parser": used, "warning": err}
