# Purchase Portal

Local web app that fills Madhav's own Nirma purchase formats.

## Run
**With Docker (recommended):** `docker compose up -d` → open http://localhost:5050
Everything (database, API keys, uploads, generated documents) stays in the local `data/` folder.
The image is built by GitHub Actions on every push: `ghcr.io/cosmicmadhav/purchase-portal:latest`.
Inside Docker the PDFs are made with LibreOffice (Liberation/Carlito fonts = same metrics as Times New Roman/Calibri).

**Without Docker (Windows + MS Office):** `pip install -r requirements.txt`, then `start.bat`.
PDFs are then exported by Word/Excel themselves.

Set `APP_PASSWORD` (environment variable / `.env` next to docker-compose.yml) to require a login.

## What it makes
| Document | Source format (in `doc_templates/`) |
|---|---|
| Purchase Permission (≤3k "PP 3000" style, Statement, Comparative Statement, VP chain) | your Jetson / PP 3000 / 100rpm motors .docx |
| PrithviX incubation permission | your Claude subscription .docx |
| Purchase Order (+ audit page when >10k) | your camera PO .docx |
| Quotation request letters (one per vendor) | PO layout |
| Advance Voucher | `Advance Voucher.xlsx` |
| Advance Adjustment Voucher | `Advance Adjustment AUG.xlsx` |
| Cash Voucher (reimbursement) | Advance Voucher sheet re-titled – no official format was available |

Outputs go to `Purchase docs\Generated\<project>\<date - title>\` (Settings → Output folder).

## Rules (Settings → Purchase value rules)
- ≤ ₹3,000: HOD, single quote, no PO/audit
- ₹3,001–10,000: 3 quotes, HOD, PO (Tally + normal), no audit
- ₹10,001–50,000: 3 quotes, Director, PO + Internal Audit + Outward
- > ₹50,000: 3 quotes, VP, PO + Internal Audit + Outward

Workflow ticks are gated: PO needs approved permission, audit needs PO, adjustment needs advance received,
cash voucher needs an approved permission (or post-facto reference).

## Quotation / bill scanning
Settings → Google Vision key (scanned PDFs/photos) + Grok key (xAI) or Groq key. Without keys, digital PDFs
are read with a basic reader (vendor via GSTIN, quote no., date).

## Data
`data/portal.db` (SQLite; vendors, items, purchases, keys). Delete it to re-seed from scratch.
Budget "utilized" = opening amount (Settings → project) + approved PO/card purchases + adjustment vouchers +
cash vouchers + manual entries.

## Tests
`python -m pytest tests` — 108 tests: money/rules (checked against 10 real past documents), every
document type and edge case, the API (workflow locks, budget, key/file security, scanning), real PDF
export, and browser tests (Playwright + Edge) at desktop and phone width. Inside Docker:
`docker run --rm ghcr.io/cosmicmadhav/purchase-portal sh -c "pip install pytest && python -m pytest tests --ignore=tests/test_ui.py"`.
Tests always use a temporary database, never `data/`.
