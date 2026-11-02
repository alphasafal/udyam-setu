"""Udyam Setu — FastAPI backend serving the single-page journey + back office."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import advisor, catalogue, kyc, orders
from .propensity import Propensity

WEB = Path(__file__).resolve().parent.parent / "web"
app = FastAPI(title="Udyam Setu", version="0.1")
orders.init_db()
PROP = Propensity()
NOTICE_VERSION = "2026-10-v1"


# ---- advisor ----------------------------------------------------------------
@app.get("/api/questions")
def questions(lang: str = "en"):
    return {"languages": advisor.LANGS, "questions": [
        {"id": q["id"], "multi": q.get("multi", False), "text": q["text"].get(lang, q["text"]["en"]),
         "options": [{"v": o["v"], "label": o.get(lang, o["en"])} for o in q["options"]]} for q in advisor.QUESTIONS]}


class Answers(BaseModel):
    answers: Dict[str, object]
    language: str = "en"
    free_text: Optional[str] = None


@app.post("/api/advise")
def advise(a: Answers):
    ans = dict(a.answers)
    if a.free_text:
        parsed = advisor.parse_free_text(a.free_text, a.language) or {}
        parsed.pop("_source", None)
        for k, v in parsed.items():
            ans.setdefault(k, v)
    ans["language"] = a.language
    out = advisor.advise(ans)
    out["llm_used"] = advisor.llm_available()
    return out


class FreeText(BaseModel):
    text: str
    language: str = "en"


@app.post("/api/parse")
def parse_text(f: FreeText):
    """Free text → partial answers. Offline NLU, or the LLM when a key is set (same schema)."""
    ans = advisor.parse_free_text(f.text, f.language) or {}
    labels = {q["id"]: {o["v"]: o.get(f.language, o["en"]) for o in q["options"]} for q in advisor.QUESTIONS}
    for k, v in advisor.EXTRA_NEED_LABELS.items():
        labels["needs"][k] = v.get(f.language, v["en"])
    understood = []
    for k, v in ans.items():
        if k in labels:
            vals = v if isinstance(v, list) else [v]
            understood += [labels[k].get(str(x), str(x)) for x in vals]
        elif k == "city":
            understood.append(str(v))
    source = ans.pop("_source", "offline")
    return {"answers": ans, "understood": understood, "source": source, "llm_used": advisor.llm_available()}


class Reprice(BaseModel):
    answers: Dict[str, object]
    language: str = "en"
    selected: Dict[str, bool]


@app.post("/api/reprice")
def reprice(r: Reprice):
    ans = dict(r.answers); ans["language"] = r.language
    profile = advisor.build_profile(ans)
    rec = catalogue.recommend(profile)
    q = catalogue.price_bundle(rec["items"], r.selected)
    # a toggled-on add-on may need something else in the bundle; the rule engine says so
    sel_ids = [l["product_id"] for l in q["lines"] if l["selected"]]
    warnings = []
    for pid in sel_ids:
        for e in catalogue.eligibility_errors(pid, profile, sel_ids):
            warnings.append(e)
    return {"quote": q, "warnings": warnings, "install_days": max([catalogue.CATALOGUE[p].install_days for p in sel_ids] or [0])}


@app.get("/api/catalogue")
def cat():
    return [vars(p) for p in catalogue.CATALOGUE.values()]


# ---- KYC ---------------------------------------------------------------------
@app.get("/api/lookup/gstin/{g}")
def lookup_gstin(g: str):
    rep = kyc.repair_gstin(g)
    r = kyc.gstin_lookup(rep["value"])
    orders.audit("owner", "lookup.gstin", rep["value"], "pre-fill KYC")
    if not r:
        return {"found": False, "gstin_masked": kyc.mask(rep["value"]), "checksum_ok": kyc.gstin_checksum_ok(rep["value"]), "note": rep["note"]}
    return {"found": True, "gstin_masked": kyc.mask(r["gstin"]), "legal_name": r["legal_name"], "trade_name": r["trade_name"], "status": r["status"],
            "constitution": r["constitution"], "address": r["principal_place_of_business"], "state": r["state"], "repaired": rep["repaired"], "note": rep["note"]}


@app.get("/api/lookup/udyam/{u}")
def lookup_udyam(u: str):
    r = kyc.udyam_lookup(u.upper())
    orders.audit("owner", "lookup.udyam", u, "pre-fill KYC")
    if not r:
        return {"found": False}
    return {"found": True, "udyam_masked": kyc.mask(u), "enterprise_name": r["enterprise_name"], "type": r["enterprise_type"], "activity": r["major_activity"], "city": r["city"], "state": r["state"]}


@app.post("/api/kyc")
async def run_kyc(business_name: str = Form(""), gstin: str = Form(""), udyam_number: str = Form(""), contact_name: str = Form(""),
                  consent_purposes: str = Form(""), language: str = Form("en"),
                  gst_certificate: Optional[UploadFile] = File(None), udyam_certificate: Optional[UploadFile] = File(None),
                  address_proof: Optional[UploadFile] = File(None), signatory_id: Optional[UploadFile] = File(None)):
    if "kyc" not in consent_purposes.split(","):
        raise HTTPException(400, "Consent for identity verification was not given; nothing was uploaded or stored.")
    tmp = Path(tempfile.mkdtemp(prefix="kyc_"))
    docs = {}
    for name, up in (("gst_certificate", gst_certificate), ("udyam_certificate", udyam_certificate), ("address_proof", address_proof), ("signatory_id", signatory_id)):
        if up and up.filename:
            p = tmp / f"{name}.png"
            with open(p, "wb") as f:
                shutil.copyfileobj(up.file, f)
            docs[name] = str(p)
        else:
            docs[name] = None
    try:
        res = kyc.run_kyc("web", docs, {"business_name": business_name, "gstin": gstin.upper(), "udyam_number": udyam_number.upper(), "contact_name": contact_name})
    finally:
        shutil.rmtree(tmp, ignore_errors=True)   # images never persist in the prototype; production keeps them in the vault with a TTL
    orders.audit("kyc-service", "kyc.decision", res.gstin or business_name, res.decision)
    return res.to_dict()


@app.get("/api/kyc/specimen/{k}")
def kyc_specimen(k: str):
    """Run the pipeline on one of the 12 bundled specimen applicants (K01..K12)."""
    import csv
    M = {'K01': 'L00045', 'K02': 'L01287', 'K03': 'L03571', 'K04': 'L01014', 'K05': 'L04014', 'K06': 'L00115', 'K07': 'L03349', 'K08': 'L03473', 'K09': 'L04779', 'K10': 'L04525', 'K11': 'L03485', 'K12': 'L03558'}
    if k not in M:
        raise HTTPException(404, "unknown specimen")
    leads = {r["lead_id"]: r for r in csv.DictReader(open(kyc.DATA / "smb_leads.csv", encoding="utf-8"))}
    L = leads[M[k]]
    res = kyc.run_kyc(k, kyc.specimen_docs(k), {"business_name": L["business_name"], "gstin": L["gstin"], "udyam_number": L["udyam_number"], "contact_name": L["contact_name"]})
    d = res.to_dict(); d["business_name"] = L["business_name"]
    return d


# ---- orders / tracker --------------------------------------------------------
class NewOrder(BaseModel):
    business: str
    phone: str
    language: str = "en"
    answers: Dict[str, object]
    selected: Dict[str, bool]
    bundle_name: str
    contract_months: int
    kyc_decision: str
    gstin: str = ""
    consent_purposes: List[str]


@app.post("/api/orders")
def new_order(o: NewOrder):
    ans = dict(o.answers); ans["language"] = o.language
    profile = advisor.build_profile(ans)
    rec = catalogue.recommend(profile)
    q = catalogue.price_bundle(rec["items"], o.selected)
    sel = [l["product_id"] for l in q["lines"] if l["selected"]]
    install = max([catalogue.CATALOGUE[p].install_days for p in sel] or [0])
    od = orders.create_order(o.business, o.phone, o.language, q, o.bundle_name, o.contract_months, install, o.kyc_decision, o.gstin)
    orders.record_consent(od["id"], o.consent_purposes, NOTICE_VERSION, o.language)
    return orders.get_order(od["id"])


@app.get("/api/orders/{oid}")
def get_order(oid: str):
    od = orders.get_order(oid)
    if not od:
        raise HTTPException(404)
    od["whatsapp_preview"] = orders.whatsapp_message(od, od["language"])
    return od


@app.post("/api/orders/{oid}/advance")
def advance(oid: str):
    od = orders.advance(oid)
    od["whatsapp_preview"] = orders.whatsapp_message(od, od["language"])
    return od


@app.post("/api/orders/{oid}/slot")
def slot(oid: str, slot: str = Form(...)):
    return orders.set_slot(oid, slot)


@app.post("/api/orders/{oid}/withdraw")
def withdraw(oid: str):
    orders.withdraw_consent(oid)
    return {"ok": True}


# ---- back office -------------------------------------------------------------
@app.get("/api/backoffice/queue")
def queue():
    return {"cv_auc": round(PROP.cv_auc, 3), "leads": PROP.stalled_queue(25)}


@app.post("/api/backoffice/score")
def score(lead: Dict[str, object]):
    return PROP.score_lead(lead)


@app.get("/api/backoffice/orders")
def bo_orders():
    return orders.list_orders()


@app.get("/api/backoffice/audit")
def bo_audit():
    return orders.recent_audit(30)


@app.get("/api/privacy")
def privacy():
    return {"notice_version": NOTICE_VERSION, "document_retention_days": orders.DOC_RETENTION_DAYS, "rejected_retention_days": orders.REJECTED_RETENTION_DAYS,
            "stored_fields": ["business name", "masked phone", "GSTIN (masked outside the KYC store)", "bundle", "consent record"],
            "never_stored": ["PAN", "Aadhaar number", "document images after the retention period", "unmasked identifiers in logs"]}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/backoffice")
def backoffice():
    return FileResponse(WEB / "backoffice.html")


app.mount("/static", StaticFiles(directory=WEB), name="static")
