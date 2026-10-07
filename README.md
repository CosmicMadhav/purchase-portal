# Purchase Portal

Local web app that fills Madhav's own Nirma purchase formats.

**Start:** double-click `start.bat` (opens http://127.0.0.1:5050). Needs Python + MS Word/Excel (already installed).

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
