# Udyam Setu: Project Udyam Digital prototype (Airtel SYNC, Track A)

A small business goes from "what do I need?" to a working connection in one sitting, on a phone, in its own language.
Built for the Airtel SYNC case (fictional operator *Accel Business*) by Safal Gupta, B.Tech CSE, VIT Vellore.

- **Everything in one place (GitHub Pages)**: https://alphasafal.github.io/udyam-setu/
- **Live demo, no sign-in**: https://alphasafal.github.io/udyam-setu/live/ · **GenAI demo** (asks the viewer to allow a language model): https://claude.ai/artifact/15HCtChjeL3t5oFPn9SdSB
- **Demo video**: `docs/Udyam_Setu_Demo.mp4` (under 3 minutes)
- **Business case deck**: `docs/Business_Case_Deck.pdf` · **workings**: `docs/business_case.py` → `docs/business_case.md`
- **Architecture** (each part marked Built / Simulated / Planned): `docs/architecture.png`
- **Privacy note** (1 page): `docs/Udyam_Setu_Privacy_Note.pdf`

## Run it

```bash
pip install -r requirements.txt        # needs the tesseract binary too (apt install tesseract-ocr / brew install tesseract)
export ANTHROPIC_API_KEY=...           # optional: turns on the GenAI advisor (ADVISOR_MODEL defaults to claude-haiku-5-5)
uvicorn app.main:app --port 8765       # owner journey: http://localhost:8765   back office: /backoffice
python -m pytest -q                    # 68 tests
python docs/business_case.py           # regenerates the business case tables
```

Without a key everything still runs: the offline parser and reviewed templates take over, so a demo never breaks.

## How the advisor uses GenAI, and what it is not allowed to do

| Job | Who does it | Guard |
|---|---|---|
| Understand what the owner typed (any Indian language, Hinglish, typos) | Language model (`app/llm.py: understand`) | Output must be one of the fixed answer values; anything else is dropped. Phone, e-mail, GSTIN, PAN, Aadhaar and Udyam numbers are redacted before the text leaves the service. The offline parser fills any gaps. |
| Choose products, quantities, prices, contract, eligibility | Rule engine (`app/catalogue.py`) | Deterministic; enforces city tier, minimum employees and sites, `requires_gstin`, `requires_one_of`, catalogue price bands. |
| Explain the recommendation in the owner's language | Language model (`app/llm.py: explain`) | Every price, quantity and day count from the rule engine must appear unchanged, or the reviewed template is shown instead. |

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

## Tests (68)

Rule engine on every segment · GSTIN checksum on all 3,534 registry records · look-alike repair (and refusal) · the 12 specimens ·
30 owner descriptions (15 tuned, 15 unseen) routed to the right bundle · GenAI layer with a fake model: invalid values dropped, PII never sent,
an explanation that changes a price is rejected, model failure falls back offline · regression tests for every fixed bug ·
the deck's business-case numbers regenerate exactly from `docs/business_case.py`.

## Business case (from `docs/business_case.py`, written to `docs/business_case.md`)

A 36-month model in which each month's new customers are tracked separately.

- **Price**: what the advisor's rule engine would quote each of the 5,000 leads in the data (chains come out below what they buy today, so no upselling is assumed).
- **Volume**: a stated share of each fixable leak is recovered and continues at today's downstream conversion; leaks the journey cannot fix are untouched; factories get half the effect. Leads who only wanted a mobile plan are sold just that and counted separately.
- **Margin**: set per product line (connectivity 60%, communication 50%, security 40%, IoT 35%, cloud 30%).
- **Churn**: 6-month churn moves toward the rate of today's customers who chased at most twice (an assumption the pilot tests), then 1% a month.
- **Cost**: field team kept as a fixed cost; partner payouts held near today's level; free AirFiber units; digital journey cost; ₹2.0 Cr build (₹1.2 Cr app, ₹0.8 Cr integration); ₹6 L a month to run.

Result: bundle activation 7.4% → 13.3% (plus about 95 SIM-only sales a quarter); all-in cost per bundle activation ₹15,053 → ₹10,839;
net −₹0.97 Cr, +₹5.97 Cr, +₹10.76 Cr over three years; payback month 15; 3-year NPV ₹11.95 Cr at 12%.
Each downside on its own (recovery −25% or halved, prices −15%, churn +5 points, margins −20%) still pays back, by month 29 at worst.
Recovery halved, prices −15% and churn +5 together do not pay back within three years (NPV −₹5.07 Cr), so the pilot is randomised within each city and gated before any scale spend.

## Repository layout

```
app/catalogue.py    catalogue, rule engine, bundle templates (chain add-ons follow the owner's needs)
app/advisor.py      question flow, languages, GenAI-first understanding and explanation
app/llm.py          model client interface, PII redaction, output validation
app/nlu.py          offline free-text parser (fallback and gap-filler)
app/kyc.py          capture quality, OCR, GSTIN checksum and repair, registry adapters, decisions
app/propensity.py   logistic propensity model trained from smb_leads.csv
app/orders.py       orders, tracker events, consent ledger, masked audit log (SQLite)
app/main.py         FastAPI routes; serves web/
web/                owner journey (mobile web) and back office
tests/test_all.py   68 tests
docs/               GitHub Pages site: index.html, live/ (demo), deck, business case, architecture, privacy note, video
data/               the synthetic pack (catalogue, leads, mock registries, specimen documents)
```

All businesses, people, identifiers and documents are fictional (Accel YTL Hackathon synthetic pack).
