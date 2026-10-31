# Udyam Setu — Project Udyam Digital prototype (Airtel SYNC, Track A)

A small business goes from "what do I need?" to a live, working connection in one sitting — on a phone, in its own language.
Built for the Airtel SYNC case (fictional operator *Accel Business*) by Safal Gupta, B.Tech CSE, VIT Vellore.

**Live demo (runs entirely in the browser, no install):** https://claude.ai/artifact/15HCtChjeL3t5oFPn9SdSB  
**Demo video:** `docs/Udyam_Setu_Demo.mp4` · **Business case deck:** `docs/Business_Case_Deck.pdf` · **Privacy note:** `docs/Udyam_Setu_Privacy_Note.pdf` · **Architecture:** `docs/architecture.png`

Everything runs offline on the synthetic data pack. No API keys are required; if `ANTHROPIC_API_KEY` is set the advisor
also parses free-text answers with an LLM and rewrites its summary more naturally — but prices and eligibility always come
from the deterministic rule engine, never from the model.

## Run it

```bash
pip install -r requirements.txt          # fastapi, uvicorn, pandas, scikit-learn, opencv-python-headless, pytesseract, pillow
# tesseract must be installed (apt install tesseract-ocr / brew install tesseract)
uvicorn app.main:app --port 8765
# owner journey:  http://localhost:8765
# back office:    http://localhost:8765/backoffice
python -m pytest -q                      # 40 tests: rule engine, GSTIN validator, 12 specimen KYC applicants, 15 live advisor scenarios
```

## What is in the journey

| Screen | What it does | Where |
|---|---|---|
| **Saathi (advisor)** | Five tap-to-answer questions, or free text in English / Hinglish / Hindi (`app/nlu.py` parses business type, staff, sites, city → tier, internet today, needs, GST; an LLM can do the same into the same schema). Only the missing questions are asked. Bundle from the 25-product catalogue with a one-line *why* per product; products the rules do not allow are listed with the reason; anything assumed is declared. "I just want a SIM" gets exactly that (280 leads a quarter drop for this today). Manufacturers are handed to a specialist with the profile pre-filled. | `app/advisor.py`, `app/nlu.py`, `app/catalogue.py` |
| **Quote & checkout** | One monthly number; add-ons toggle live; the rule engine re-checks dependencies (`requires_one_of`, `requires_gstin`, tier, size) on every toggle. | `/api/reprice` |
| **Smart KYC** | Consent screen per purpose → GSTIN/Udyam lookup pre-fills → guided upload → blur/skew check → OCR → look-alike repair tested against the GSTIN checksum → registry status → name / address-age / signatory checks → **pass / ask / hold** with reasons in plain words. | `app/kyc.py` |
| **Tracker** | Order states with ETA, WhatsApp message preview at each change, install-slot picker, consent withdrawal, document purge date. | `app/orders.py` |
| **Back office** (stretch) | Leads the advisor could not close, ranked by a logistic propensity model (5-fold CV AUC 0.71); live orders; masked audit log. | `app/propensity.py`, `web/backoffice.html` |

## Results on the 12 specimen applicants (`GET /api/kyc/specimen/K01` … `K12`)

| Applicant | Finding | Decision |
|---|---|---|
| K01 | GSTIN is **Cancelled** in the registry; Udyam certificate has a blank number | hold |
| K02 | Certificate photographed at −7°; deskewed, OCR'd, all consistent | pass (self-healed) |
| K03 | Clean | pass |
| K04 | GST certificate too blurred (Laplacian variance ≈ 1 vs ≈ 1,000 for a clean scan) | ask: retake one photo |
| K05 | Udyam certificate missing; number known from the application → DigiLocker fetch offered | ask |
| K06 | GSTIN on certificate differs from the registered number by a real digit (8 vs 5), not an OCR look-alike; checksum fails | hold |
| K07 | Legal name on certificate ("Shri Physio Clinic") ≠ registry ("Neelgiri Physio Clinic") | hold |
| K08 | Printed digit `0` where the registry has letter `O`; repaired, checksum valid, Active | pass (self-healed) |
| K09 | Clean; bill 5 days old | pass |
| K10 | OCR read `I` for `J`; repaired and confirmed by the registry | pass (self-healed) |
| K11 | Electricity bill dated 2025-10-31 — 257 days old against the 90-day rule | ask: recent address proof |
| K12 | Clean | pass |

The current (non-digital) process in the leads file activated **22 customers with cancelled or suspended GSTINs**; this pipeline holds every one.

## Repository layout

```
app/catalogue.py    product catalogue + rule engine + bundle templates (prices always inside the catalogue band)
app/advisor.py      question flow, multilingual strings, optional LLM parsing/polish with guardrails
app/nlu.py          offline free-text parser (English / Hinglish / Hindi keywords) → same answer schema
app/kyc.py          capture quality, OCR, GSTIN checksum + look-alike repair, registry adapters, decision engine
app/propensity.py   logistic propensity model trained from smb_leads.csv at startup
app/orders.py       SQLite orders, tracker events, consent ledger, masked audit log
app/main.py         FastAPI routes; serves web/
web/index.html      owner journey (mobile-first, 3 languages)
web/backoffice.html partner / sales view
tests/test_all.py   rule-engine, validator and specimen tests
docs/               architecture diagram, privacy note, deck, demo script (e2e.py), screenshots, demo video
docs/live/          build of the single-file live demo (template.html + data.json → udyam_setu_live.html)
data/               the synthetic pack (catalogue, leads, mock registries, specimen documents)
```

## Privacy choices (see `docs/Udyam_Setu_Privacy_Note.pdf`)

Consent per purpose before any upload, in the owner's language · lookup before documents · PAN/Aadhaar never stored ·
images deleted 30 days after a decision (7 if rejected; the prototype deletes immediately after extraction) ·
identifiers masked in every UI and log (`27QH…1ZL`) · append-only consent ledger with notice version · withdraw from the tracker page.

## Demo

`python docs/e2e.py --video` drives the whole journey in a headless browser with captions and records it
(`docs/video/`). `docs/Udyam_Setu_Demo.mp4` is the 1 min 48 s cut.

## Live judge scenarios

`tests/test_all.py::test_live_scenario` runs 15 free-text descriptions (bakery chain in Pune, Hinglish salon owner, CA firm wanting IVR, "I just want a SIM", textile unit wanting IoT…) through the parser and the rule engine and asserts the bundle, the must-have products and that no eligibility rule is broken.

All businesses, people, identifiers and documents are fictional (Accel YTL Hackathon synthetic pack).
