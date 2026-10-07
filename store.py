"""SQLite storage. Each table keeps a JSON 'data' blob plus a few searchable columns."""
import json
import os
import sqlite3
from datetime import datetime

from rules import DEFAULT_SLABS

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("PORTAL_DB") or os.path.join(HERE, "data", "portal.db")
TABLES = ["projects", "vendors", "items", "purchases", "advances", "reimbursements", "ledger"]


def conn():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    fresh = not os.path.exists(DB)
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        for t in TABLES:
            c.execute(f"CREATE TABLE IF NOT EXISTS {t} (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                      f"name TEXT, data TEXT, created TEXT, updated TEXT)")
    if fresh:
        seed()


def now():
    return datetime.now().isoformat(timespec="seconds")


# ------------------------------------------------------------------ generic CRUD
def _row(r):
    d = json.loads(r["data"] or "{}")
    d["id"] = r["id"]
    d["_created"] = r["created"]
    d["_updated"] = r["updated"]
    return d


def all_(table, order="id DESC"):
    with conn() as c:
        return [_row(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY {order}")]


def get(table, id_):
    with conn() as c:
        r = c.execute(f"SELECT * FROM {table} WHERE id=?", (id_,)).fetchone()
        return _row(r) if r else None


def save(table, data):
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    id_ = data.pop("id", None)
    name = data.get("name") or data.get("title") or data.get("description") or ""
    blob = json.dumps(data, ensure_ascii=False)
    with conn() as c:
        if id_:
            c.execute(f"UPDATE {table} SET name=?, data=?, updated=? WHERE id=?", (name, blob, now(), id_))
        else:
            cur = c.execute(f"INSERT INTO {table} (name, data, created, updated) VALUES (?,?,?,?)",
                            (name, blob, now(), now()))
            id_ = cur.lastrowid
    return get(table, id_)


def delete(table, id_):
    with conn() as c:
        c.execute(f"DELETE FROM {table} WHERE id=?", (id_,))


def get_settings():
    with conn() as c:
        out = {r["key"]: json.loads(r["value"]) for r in c.execute("SELECT * FROM settings")}
    out.setdefault("slabs", DEFAULT_SLABS)
    out.setdefault("llm_provider", "xai")
    return out


def set_settings(d):
    with conn() as c:
        for k, v in d.items():
            c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (k, json.dumps(v)))


# ------------------------------------------------------------------ vendor / item memory
def norm(s):
    return " ".join((s or "").lower().replace(".", " ").replace(",", " ").split())


def find_vendor(name="", gst=""):
    gst = (gst or "").strip().upper()
    n = norm(name)
    for v in all_("vendors"):
        if gst and (v.get("gst") or "").upper() == gst:
            return v
        if n and (norm(v.get("name")) == n or (len(n) > 5 and (n in norm(v.get("name")) or norm(v.get("name")) in n))):
            return v
    return None


def remember_vendor(v):
    """Create or update a vendor from details seen on a quotation."""
    if not (v or {}).get("name"):
        return None
    found = find_vendor(v.get("name"), v.get("gst"))
    if found:
        changed = False
        for k in ("address", "gst", "phone", "email", "contact_person"):
            if v.get(k) and not found.get(k):
                found[k] = v[k]
                changed = True
        return save("vendors", found) if changed else found
    return save("vendors", {k: v.get(k, "") for k in ("name", "address", "gst", "phone", "email", "contact_person")})


def remember_items(items, vendor_name, when):
    existing = {norm(i.get("description")): i for i in all_("items")}
    for it in items or []:
        key = norm(it.get("description"))
        if not key:
            continue
        rec = existing.get(key) or {"description": it.get("description")}
        rec.update({"rate": it.get("rate"), "gst": it.get("gst", 18), "hsn": it.get("hsn") or rec.get("hsn", ""),
                    "vendor": vendor_name or rec.get("vendor", ""), "last_date": when})
        hist = rec.get("history") or []
        hist.append({"vendor": vendor_name, "rate": it.get("rate"), "date": when})
        rec["history"] = hist[-10:]
        save("items", rec)


# ------------------------------------------------------------------ seed with Madhav's existing data
def _private(name):
    """Personal details (phone numbers, IDs) live in data/private_seed.json, which is not in git."""
    path = os.path.join(HERE, "data", "private_seed.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f).get(name, {})
    return {}


def seed():
    set_settings({"slabs": DEFAULT_SLABS, "llm_provider": "xai", "llm_model": "", "llm_key": "", "vision_key": "",
                  "output_dir": os.path.join(os.path.dirname(HERE), "Purchase docs", "Generated")})
    save("projects", {
        "name": "KISAN KAWACH", "project": "KISAN KAWACH", "letter_style": "nu",
        "grant": "CSR Grant from Infineon Technologies",
        "ref_prefix": "NU/IT/Purchase/ CSR Grant from Infineon Technologies/{fy}/",
        "budget_code": "R1A04B", "budget_head_po": "CSR GRANT FROM INFINEON", "department": "GA",
        "institute": "Institute of Technology", "dop_authority": "VP",
        "provision": 300000, "opening_utilized": 246616, "opening_as_of": "2026-09-17",
        "opening_note": "Utilized amount shown on the Waveshare display PO (17-09-2026). Correct it here if needed.",
        "mentor_name": "Dr. Jayeshkumar J Patel (APEC)", "mentor_title": "Mentor, KISAN KAWACH",
        "hod": "HoD- EC (N.P Gajjar)", "ar": "Asst. Registrar, SoT-NU", "director": "Director, SoT NU",
        "exec_registrar": "Exec. Registrar, NU", "vp": "Vice President, NU",
        "payee": "", "contact": "", "payee_dept": "EC,ITNU",
        "advance_purpose": "KISAN KAWACH ( CSR Grant from Infineon Technologies )", "advance_approver": "HOD,EC",
        "adjust_particular": "Material purchase for KISAN KAWACH (CSR Grant from Infineon Technologies )",
        "adjust_ref_prefix": "NU/IT/{project}/{fy}/Advance Adjustment Voucher/",
        "voucher_mentor": "Mentor,APEC \nDr.Jayeshkumar J Patel", "voucher_hod": "HOD,EC \nDr. NP Gajjar",
        "voucher_approver": "HOD,EC(Dr. NP Gajjar)",
        **_private("KISAN KAWACH"),
    })
    save("projects", {
        "name": "PrithviX (Incubation)", "project": "PrithviX", "letter_style": "incubation",
        "grant": "Incubation", "ref_prefix": "", "budget_code": "", "provision": 0, "opening_utilized": 0,
        "mentor_name": "Dr. Darshita Shah", "mentor_title": "Mentor, APME(ITNU)",
        "through": "Rashmika Shah\nManager-Incubation Cell",
        "to": "Dr. Mehul Naik\nHead,Centre for Entrepreneurship",
        "intro_paragraphs": [
            "We are a startup Incubated at Nirma University named ‘PrithviX’ building Two products:\n"
            "1. Autonomous Rover for precision fertiliser application\n"
            "2. SAAS Platform for dealers and farmers to increase the profit of the dealers and a one stop "
            "solution in farming practise.",
            "We are currently in the Phase-I of building an Autonomous Rover and the completion of Phase-I of "
            "software. To increase the efficiency of the team and early rolling down in upcoming phases, we "
            "require the below for the team so that we can complete the prototype stage soon and start revenue "
            "generation."],
    })
    vendors = [
        ("DAZZLE ROBOTICS PVT. LTD.", "B1+B2+B3/5 GIDC Electronics Estate, Sector 25, Gandhinagar - 382044, Gujarat, India.",
         "24AADCD2072M1ZP", "+91-79-29750885", "support@robokits.co.in", "Robokits"),
        ("ALL TECH ELECTRONICS", "C-211 SIDDHI VINAYAK TOWER,KATARIA AUTOMOBILES ROAD,BEHIND ADANI CNG PUMP, MAKARBA, S.G. HIGHWAY,\nAHMEDABAD-380051",
         "24ACVPG3865E1ZF", "9898599620", "alltechele@yahoo.com", "Upendra Gohil"),
        ("HI TECH ENTERPRISES", "8TH FLOOR ,Flat No.: 803,Key Tech Park Wing A ,Swami Vivekanand Marg\nLocality/Sub Locality: Jogeshwari West",
         "27AJZPG5206G1ZZ", "", "", ""),
        ("GROWIT INDIA PVT LTD", "606A,Union Heights, Opposite Lalbhai Stadium,Vesu, Choryasi,Surat,Gujarat",
         "24AAICG3267A1ZZ", "", "", ""),
        ("MACFOS LIMITED", "Sumant Building, Dynamic Logistics Trade Park\nSurvey No. 78/1 Dighi, Bhosari Alandi Road Pune 411015, Maharashtra",
         "27AALCM3536H1ZA", "02068197600", "info@robu.in", "Robu.in"),
        ("TECHIESMS", "53FF, First Floor, Rajratna Shopping Centre, Rajendra Park Road, Odhav,\nAhmedabad, GJ, 382415",
         "24GKPPS8925F1ZH", "8200079034", "", ""),
        ("PRAYOGTECH", "PRAYOG INDIA, 2nd Floor, City centre, Club Road, Sujata chowk,\nRanchi, Jharkhand (JH-20) 834001",
         "20ALEPH2363L1ZE", "+91 8409498926", "sales@prayogindia.in", ""),
        ("INFARMSYS TECHNOLOGIES PRIVATE LIMITED", "", "33AAFCI1240N1ZP", "+91 78927 21984", "info@farmsys.co", ""),
        ("EVELTA ELECTRONICS PVT LTD", "", "", "", "", ""),
        ("HYDRO SPRAY TECH", "", "", "", "", ""),
        ("YOGI ENTERPRISES", "", "", "", "", ""),
        ("KUTRON ELECTRONICS", "", "", "", "", ""),
        ("AVANI ELECTRONICS", "", "", "", "", ""),
        ("ALPHA OFFICE SOLUTIONS", "", "", "", "", ""),
        ("YOUR SOLUTIONS", "", "", "", "", ""),
        ("SHARVI TECHNOLOGIES", "", "", "", "", ""),
        ("AJIT ENGINEERING & FABRICATORS", "", "", "", "", ""),
    ]
    for name, addr, gst, ph, em, person in vendors:
        save("vendors", {"name": name, "address": addr, "gst": gst, "phone": ph, "email": em,
                         "contact_person": person, "payment": "", "delivery": ""})
    hist = [
        ("Mega Torque DC Planetary Geared Encoder Servo Motor 250W 100RPM 18VDC 255Kgcm (RMCS-2016)", 3912, "DAZZLE ROBOTICS PVT. LTD.", "2025-12-16"),
        ("GenX Pro+ Solid State 22.2V 6S 39000mah 7C Premium Lithium Ion Solid State Rechargeable Battery 350wh/kg (RKI-6661)", 38395, "DAZZLE ROBOTICS PVT. LTD.", "2025-12-26"),
        ("RPLIDAR A2M12 - 360 Laser Range Scanner 18m", 23321, "DAZZLE ROBOTICS PVT. LTD.", "2026-02-13"),
        ("GROWIT SOIL GURU PRO (WITHOUT SUBCRIPTION)", 30508, "GROWIT INDIA PVT LTD", "2026-03-13"),
        ("Evolis ASMI Id Card Printer", 40000, "HI TECH ENTERPRISES", "2026-03-06"),
        ("Evolis Primacy 2 Full Panel Ribbon", 3000, "HI TECH ENTERPRISES", "2026-03-06"),
        ("Plain PVC Blank Cards", 5, "HI TECH ENTERPRISES", "2026-03-06"),
        ("Adafruit 9-DOF Orientation IMU Fusion Breakout – BNO085 (BNO080) – STEMMA QT / Qwiic", 2900, "ALL TECH ELECTRONICS", "2026-03-13"),
        ("NUCLEO-H723ZG - STM32 Nucleo-144 STM32H723ZG Development Board", 3325, "EVELTA ELECTRONICS PVT LTD", "2026-02-16"),
        ("NVIDIA Jetson Orin™ Nano Super Developer Kit", 24950, "ALL TECH ELECTRONICS", "2026-05-27"),
        ("Metal Enclosure Box for Nvidia Orin Nano Developer kit", 1400, "ALL TECH ELECTRONICS", "2026-05-27"),
        ("EVM M.2 NVMe Internal SSD", 4500, "ALL TECH ELECTRONICS", "2026-05-27"),
        ("ELP High Speed Wide Angle Global Shutter USB Camera (AR0234)", 15500, "ALL TECH ELECTRONICS", "2026-06-02"),
        ("SparkFun Teensy 4.1 with header", 4350, "ALL TECH ELECTRONICS", "2026-06-02"),
        ("WAVE SHARE 7INCH CAPACITIVE HDMI LCD DISPLAY", 5895, "ALL TECH ELECTRONICS", "2026-09-17"),
        ("Rhino Motion Controls Mega Torque Planetary DC Geared Motor 250W 100RPM 18VDC", 3548, "DAZZLE ROBOTICS PVT. LTD.", "2026-08-17"),
        ("XL4016E1 DC-DC 12A 300W Step-Down 5-40V to 1.2-35V Adjustable Power Supply Module", 268, "DAZZLE ROBOTICS PVT. LTD.", "2026-08-17"),
        ("Sabertooth Dual 32A Motor Driver", 10007.63, "MACFOS LIMITED", "2025-10-06"),
        ("MECHANICAL CHASIS WITH SPRINKLER SYSTEM AS PER DESIGN", 30000, "HYDRO SPRAY TECH", "2026-03-06"),
        ("Wheel hub", 625, "HYDRO SPRAY TECH", "2026-06-27"),
        ("Sprocket 3/8 inch pitch", 296.61, "HYDRO SPRAY TECH", "2026-06-09"),
        ("Galvanised Iron Sheet (per kg)", 65.25, "", "2026-08-19"),
    ]
    for desc, rate, vend, d in hist:
        save("items", {"description": desc, "rate": rate, "gst": 18, "hsn": "", "vendor": vend, "last_date": d,
                       "history": [{"vendor": vend, "rate": rate, "date": d}]})
