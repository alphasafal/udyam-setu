# Udyam Setu: Project Udyam Digital prototype (Airtel SYNC, Track A)

A small business goes from "what do I need?" to a working connection in one sitting, on a phone, in its own language.
Built for the Airtel SYNC case (fictional operator *Accel Business*) by Safal Gupta, B.Tech CSE, VIT Vellore.

- **Live demo** (runs in the browser; uses Claude when the viewer allows it, otherwise the offline parser): https://claude.ai/artifact/15HCtChjeL3t5oFPn9SdSB
- **Demo video**: `docs/Udyam_Setu_Demo.mp4` (1 min 49 s)
- **Business case deck**: `docs/Business_Case_Deck.pdf` · **workings**: `docs/business_case.py` → `docs/business_case.md`
- **Architecture** (each part marked Built / Simulated / Planned): `docs/architecture.png`
- **Privacy note** (1 page): `docs/Udyam_Setu_Privacy_Note.pdf`

## Run it

```bash
pip install -r requirements.txt        # needs the tesseract binary too (apt install tesseract-ocr / brew install tesseract)
export ANTHROPIC_API_KEY=...           # optional: turns on the GenAI advisor (ADVISOR_MODEL defaults to claude-haiku-5-5)
uvicorn app.main:app --port 8765       # owner journey: http://localhost:8765   back office: /backoffice
python -m pytest -q                    # 65 tests
python docs/business_case.py           # regenerates the business case tables
```

Without a key everything still runs: the offline parser and reviewed templates take over, so a demo never breaks.

## How the advisor uses GenAI, and what it is not allowed to do

| Job | Who does it | Guard |
|---|---|---|
| Understand what the owner typed (any Indian language, Hinglish, typos) | Claude (`app/llm.py: understand`) | Output must be one of the fixed answer values; anything else is dropped. Phone, e-mail, GSTIN, PAN, Aadhaar and Udyam numbers are redacted before the text leaves the service. The offline parser fills any gaps. |
| Choose products, quantities, prices, contract, eligibility | Rule engine (`app/catalogue.py`) | Deterministic; enforces city tier, minimum employees and sites, `requires_gstin`, `requires_one_of`, catalogue price bands. |
| Explain the recommendation in the owner's language | Claude (`app/llm.py: explain`) | Every price, quantity and day count from the rule engine must appear unchanged, or the reviewed template is shown instead. |

The client is an interface (`LLMClient`), so Accel could swap in any model, including one hosted in India.

## What is in the journey

| Screen | What it does | Where |
|---|---|---|
| **Saathi (advisor)** | Tap five answers or describe the business in free text; only missing questions are asked; assumptions are stated. "I just want a SIM" gets exactly that. Factories go to a specialist (with GST-registration help if they have no GSTIN). | `app/advisor.py`, `app/llm.py`, `app/nlu.py` |
| **Quote** | One monthly number; add-ons toggle live; dependencies re-checked on every toggle; install time from the selected products. | `app/catalogue.py`, `/api/reprice` |
| **Smart KYC** | Consent per purpose → GSTIN/Udyam lookup → upload → blur/tilt check → OCR → look-alike repair accepted only if the GSTIN checksum passes and the registry has the record → name, bill-age and signatory checks → pass / ask / hold with reasons. | `app/kyc.py` |
| **Tracker** | Order states, ETA, WhatsApp message preview, install slot, consent withdrawal, purge date. | `app/orders.py` |
| **Back office** | Stalled leads ranked by a logistic propensity model (5-fold CV AUC 0.71); live orders; masked audit log. | `app/propensity.py`, `web/backoffice.html` |

## Smart KYC on the 12 specimen applicants (asserted in `tests/test_all.py`)

| Applicant | Finding | Decision |
|---|---|---|
| K01 | GSTIN Cancelled in registry; Udyam number blank | hold |
| K02 | Photo tilted 7°; straightened, read, consistent | pass (self-fixed) |
| K03 | Consistent | pass |
| K04 | GST certificate too blurred | ask: retake |
| K05 | Udyam certificate missing; DigiLocker fetch offered | ask |
| K06 | Digit 8 vs registry 5: a real change, not a look-alike; checksum fails | hold |
| K07 | Legal name differs from registry | hold |
| K08 | Printed 0 for O; repaired, checksum valid | pass (self-fixed) |
| K09 | Consistent | pass |
| K10 | OCR read I for J; repaired, confirmed by registry | pass (self-fixed) |
| K11 | Electricity bill 257 days old (limit 90) | ask: new bill |
| K12 | Consistent | pass |

## Tests (65)

Rule engine on every segment · GSTIN checksum on all 3,534 registry records · look-alike repair (and refusal) · the 12 specimens ·
30 owner descriptions (15 tuned, 15 unseen) routed to the right bundle · GenAI layer with a fake model: invalid values dropped, PII never sent,
an explanation that changes a price is rejected, model failure falls back offline · regressions for bugs found in review.

## Business case (from `docs/business_case.py`)

Conversion 7.4% → 13.1% (targets set per segment), cost per activation ₹15,053 → ₹5,549 (field team kept as a fixed cost),
Year 1 net +₹0.11 Cr after a ₹1.2 Cr build, Year 2 net +₹7.1 Cr, payback around month 12; at 10% conversion payback is month 15.
Every assumption is a named constant in the script.

## Repository layout

```
app/catalogue.py    catalogue, rule engine, bundle templates
app/advisor.py      question flow, languages, GenAI-first understanding and explanation
app/llm.py          model client interface, PII redaction, output validation
app/nlu.py          offline free-text parser (fallback and gap-filler)
app/kyc.py          capture quality, OCR, GSTIN checksum and repair, registry adapters, decisions
app/propensity.py   logistic propensity model trained from smb_leads.csv
app/orders.py       orders, tracker events, consent ledger, masked audit log (SQLite)
app/main.py         FastAPI routes; serves web/
web/                owner journey (mobile web) and back office
tests/test_all.py   65 tests
docs/               deck, business case, architecture, privacy note, demo script and video, live-demo build
data/               the synthetic pack (catalogue, leads, mock registries, specimen documents)
```

All businesses, people, identifiers and documents are fictional (Accel YTL Hackathon synthetic pack).
