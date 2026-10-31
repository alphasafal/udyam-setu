"""Smart KYC: capture quality → extract → repair → look up → match → decide.

Every check is deterministic and produces a sentence the owner can act on.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional

DATA = Path(__file__).resolve().parent.parent / "data"
TODAY = date(2026, 7, 15)          # per README: use 2026-07-15 as "today"
ADDRESS_PROOF_MAX_AGE_DAYS = 90
BLUR_THRESHOLD = 50.0              # variance of Laplacian; specimen K04 scores ~1, clean scans ~1,000+

CP = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
UDYAM_RE = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")


# ---- registries ------------------------------------------------------------
def _load(name, key):
    with open(DATA / name, newline="", encoding="utf-8") as f:
        return {r[key]: r for r in csv.DictReader(f)}


GSTIN_REGISTRY = _load("mock_gstin_registry.csv", "gstin")
UDYAM_REGISTRY = _load("mock_udyam_registry.csv", "udyam_number")


def mask(ident: str) -> str:
    """27QHJXK0658U1ZL → 27QH…1ZL. Used in every log line and UI."""
    if not ident:
        return ""
    return ident[:4] + "…" + ident[-3:] if len(ident) > 8 else ident[:2] + "…"


def gstin_lookup(gstin: str) -> Optional[dict]:
    r = GSTIN_REGISTRY.get(gstin)
    return dict(r) if r else None


def udyam_lookup(num: str) -> Optional[dict]:
    r = UDYAM_REGISTRY.get(num)
    return dict(r) if r else None


# ---- GSTIN format + checksum ----------------------------------------------
def gstin_checksum_ok(g: str) -> bool:
    if len(g) != 15 or any(c not in CP for c in g):
        return False
    total = 0
    for i, ch in enumerate(g[:14]):
        v = CP.index(ch) * (1 if i % 2 == 0 else 2)
        total += v // 36 + v % 36
    return CP[(36 - total % 36) % 36] == g[14]


def gstin_format_ok(g: str) -> bool:
    # README: the 4th PAN character is always 'X' in this synthetic set; accept it.
    return bool(GSTIN_RE.match(g))


# OCR confusables, position-aware: GSTIN layout is
# DD AAAAA DDDD A X Z X  (D digit, A letter, X alnum)
TO_DIGIT = {"O": "0", "D": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2", "G": "6"}
TO_ALPHA = {"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"}
ALTS = {"0": ["O"], "O": ["0"], "1": ["I"], "I": ["1", "J", "L", "T"], "T": ["I"], "J": ["I"], "L": ["I", "1"],
        "5": ["S"], "S": ["5"], "8": ["B"], "B": ["8"], "2": ["Z"], "Z": ["2"], "G": ["6"], "6": ["G"], "D": ["0"], "Q": ["O", "0"]}
DIGIT_POS = set(range(0, 2)) | set(range(7, 11))
ALPHA_POS = set(range(2, 7)) | {11}


def _diff_note(a: str, b: str) -> str:
    return ", ".join(f"position {i + 1}: {x}→{y}" for i, (x, y) in enumerate(zip(a, b)) if x != y)


def near_misses(g: str) -> List[str]:
    """Registry GSTINs one character away from g (used to explain a hold)."""
    return [k for k in GSTIN_REGISTRY if len(k) == len(g) and sum(x != y for x, y in zip(k, g)) == 1]


def repair_gstin(raw: str) -> dict:
    """Try to recover a valid, registry-known GSTIN from an OCR reading.
    Returns {value, repaired(bool), note}. A repair is accepted only when the
    result passes the checksum; a single-character guess must also exist in
    the registry, so this can never invent a GSTIN."""
    g = re.sub(r"[^0-9A-Z]", "", raw.upper())
    if gstin_format_ok(g) and gstin_checksum_ok(g):
        return {"value": g, "repaired": False, "note": ""}
    chars = list(g[:15])
    if len(chars) == 15:
        # pass 1: fix characters whose class is wrong for their position
        for i, ch in enumerate(chars):
            if i in DIGIT_POS and not ch.isdigit() and ch in TO_DIGIT:
                chars[i] = TO_DIGIT[ch]
            elif i in ALPHA_POS and ch.isdigit() and ch in TO_ALPHA:
                chars[i] = TO_ALPHA[ch]
        cand = "".join(chars)
        if gstin_format_ok(cand) and gstin_checksum_ok(cand):
            return {"value": cand, "repaired": cand != g, "note": f"OCR look-alike fixed ({_diff_note(g, cand)}); checksum now valid"}
        # pass 2: one look-alike substitution that passes checksum AND exists in the registry
        for i, ch in enumerate(cand):
            for alt in ALTS.get(ch, []):
                c2 = cand[:i] + alt + cand[i + 1:]
                if gstin_format_ok(c2) and gstin_checksum_ok(c2) and c2 in GSTIN_REGISTRY:
                    return {"value": c2, "repaired": True, "note": f"OCR look-alike fixed ({_diff_note(g, c2)}); checksum valid and record found in registry"}
        g = cand
    nm = near_misses(g)
    note = "checksum fails even after look-alike repair"
    if nm:
        note += f"; the nearest registry record is {mask(nm[0])} ({_diff_note(g, nm[0])}), which is not an OCR look-alike, so the document itself differs from the registry"
    return {"value": g, "repaired": False, "note": note}


# ---- OCR -------------------------------------------------------------------
def image_quality(path: str) -> dict:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
    img = cv2.imread(path)
    if img is None:
        return {"ok": False, "blur": 0.0, "skew": 0.0, "reason": "file could not be read"}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thr > 0))
    skew = float(cv2.minAreaRect(coords)[-1]) if len(coords) else 0.0
    # minAreaRect reports an upright page as -90 or 90; fold into (-45, 45]
    if skew > 45:
        skew -= 90
    elif skew <= -45:
        skew += 90
    reason = ""
    if blur < BLUR_THRESHOLD:
        reason = "photo is too blurred to read; please retake in good light, holding the phone still"
    return {"ok": blur >= BLUR_THRESHOLD, "blur": round(blur, 1), "skew": round(skew, 2), "reason": reason}


def ocr_text(path: str, skew: float = 0.0) -> str:
    import cv2  # type: ignore
    import pytesseract  # type: ignore
    img = cv2.imread(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if abs(skew) > 1.5:
        h, w = gray.shape
        M = cv2.getRotationMatrix2D((w // 2, h // 2), -skew, 1)
        gray = cv2.warpAffine(gray, M, (w, h), borderValue=255)
    return pytesseract.image_to_string(gray, config="--psm 6")


FIELD_PATTERNS = {
    "gst_certificate": {
        "gstin": r"GSTIN\s*[:\-]?\s*([0-9A-Z]{15})",
        "legal_name": r"Legal name\s*[:\-]?\s*(.+)",
        "trade_name": r"Trade name\s*[:\-]?\s*(.+)",
        "constitution": r"Constitution\s*[:\-]?\s*(.+)",
    },
    "udyam_certificate": {
        "udyam_number": r"Udyam reg\.? number\s*[:\-]?\s*(UDYAM-?\s?[A-Z]{2}-?\s?\d{2}-?\s?\d{7})",
        "enterprise_name": r"Enterprise name\s*[:\-]?\s*(.+)",
        "city": r"City\s*[:\-]?\s*(.+)",
    },
    "address_proof": {
        "billed_to": r"Billed to\s*[:\-]?\s*(.+)",
        "bill_date": r"Bill date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})",
    },
    "signatory_id": {
        "name": r"Name\s*\n\s*(.+)",
        "designation": r"Designation\s*\n\s*(.+)",
        "for_business": r"For business\s*\n\s*(.+)",
        "valid_till": r"Valid till\s*\n\s*(\d{4}-\d{2}-\d{2})",
    },
}


def extract_fields(doc_type: str, text: str) -> Dict[str, str]:
    out = {}
    for k, pat in FIELD_PATTERNS[doc_type].items():
        m = re.search(pat, text, re.I)
        if m:
            v = m.group(1).strip()
            if k == "udyam_number":
                v = re.sub(r"[\s]", "", v.upper()).replace("UDYAM", "UDYAM-").replace("--", "-")
                v = re.sub(r"-+", "-", v)
            out[k] = v
    return out


# ---- matching helpers ------------------------------------------------------
def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def names_match(a: str, b: str) -> bool:
    na, nb = norm(a), norm(b)
    return bool(na) and bool(nb) and (na == nb or na in nb or nb in na)


def proprietor_from_legal(legal_name: str) -> str:
    m = re.match(r"(.+?)\s*\(Prop\.", legal_name or "")
    return m.group(1).strip() if m else ""


# ---- decision --------------------------------------------------------------
@dataclass
class Check:
    name: str
    status: str      # pass | fixed | ask | hold
    detail: str


@dataclass
class KycResult:
    applicant: str
    decision: str = "pass"   # pass | ask | hold
    checks: List[Check] = field(default_factory=list)
    extracted: Dict[str, Dict[str, str]] = field(default_factory=dict)
    gstin: str = ""
    udyam: str = ""
    legal_name: str = ""
    next_step: str = ""

    def add(self, name, status, detail):
        self.checks.append(Check(name, status, detail))
        order = {"pass": 0, "fixed": 1, "ask": 2, "hold": 3}
        if order[status] > order.get(self.decision, 0) and status in ("ask", "hold"):
            self.decision = status
        elif status == "ask" and self.decision == "pass":
            self.decision = "ask"

    def to_dict(self):
        d = asdict(self)
        d["gstin_masked"] = mask(self.gstin)
        d["udyam_masked"] = mask(self.udyam)
        return d


def run_kyc(applicant: str, docs: Dict[str, Optional[str]], declared: Optional[dict] = None) -> KycResult:
    """docs: {doc_type: image path or None}. declared: what the lead/advisor already knows
    (business_name, gstin, udyam_number, contact_name). Registry lookups come first;
    documents are only trusted after they agree with the registries."""
    declared = declared or {}
    r = KycResult(applicant=applicant)
    fields: Dict[str, Dict[str, str]] = {}

    # 1. capture quality + OCR
    for dt in ("gst_certificate", "udyam_certificate", "address_proof", "signatory_id"):
        p = docs.get(dt)
        if not p:
            fields[dt] = {}
            continue
        q = image_quality(p)
        if not q["ok"]:
            r.add(f"{dt} capture", "ask", q["reason"])
            fields[dt] = {"_unreadable": "1"}
            continue
        text = ocr_text(p, q["skew"])
        f = extract_fields(dt, text)
        if abs(q["skew"]) > 1.5:
            r.add(f"{dt} capture", "fixed", f"photo was tilted {q['skew']:+.1f}°; straightened before reading")
        fields[dt] = f
    r.extracted = fields

    # 2. GSTIN: extract → repair → checksum → registry status
    g_raw = fields["gst_certificate"].get("gstin") or declared.get("gstin") or ""
    if "_unreadable" in fields["gst_certificate"]:
        r.next_step = "Retake the GST certificate photo (one document)."
    elif not docs.get("gst_certificate") and not declared.get("gstin"):
        r.add("GSTIN", "ask", "No GSTIN given and no certificate uploaded. Products that need GST stay switched off; you can add it later.")
    if g_raw:
        rep = repair_gstin(g_raw)
        g = rep["value"]
        if rep["note"] and rep["repaired"]:
            r.add("GSTIN read", "fixed", rep["note"])
        if not (gstin_format_ok(g) and gstin_checksum_ok(g)):
            note = rep["note"]
            dg = declared.get("gstin") or ""
            if dg and len(dg) == len(g) and dg != g:
                note += f"; the application carries {mask(dg)}, which differs at {_diff_note(g, dg)} — not an OCR look-alike, so the certificate does not match the registered number"
            r.add("GSTIN checksum", "hold", f"GSTIN on the certificate ({mask(g)}): {note}. A person will review it.")
        else:
            reg = gstin_lookup(g)
            if not reg:
                r.add("GSTIN registry", "hold", f"{mask(g)} is not in the GST registry")
            else:
                r.gstin = g
                r.legal_name = reg["legal_name"]
                if reg["status"] != "Active":
                    r.add("GSTIN status", "hold", f"GSTIN {mask(g)} is {reg['status']} in the registry. We cannot sell GST-linked products on it; an active GSTIN is needed.")
                else:
                    r.add("GSTIN status", "pass", f"GSTIN {mask(g)} is Active; registered to {reg['legal_name']}")
                # declared vs registry
                if declared.get("gstin") and declared["gstin"] != g:
                    r.add("GSTIN vs application", "hold", f"certificate shows {mask(g)} but the application has {mask(declared['gstin'])}")
                # legal name on certificate vs registry
                cert_legal = fields["gst_certificate"].get("legal_name", "")
                if cert_legal and not names_match(cert_legal, reg["legal_name"]):
                    r.add("Legal name", "hold", f"certificate says “{cert_legal}” but the registry says “{reg['legal_name']}”")
                # trade name vs business name
                biz = declared.get("business_name") or fields["gst_certificate"].get("trade_name", "")
                if biz and not names_match(biz, reg["trade_name"]):
                    r.add("Trade name", "hold", f"business name “{biz}” does not match registry trade name “{reg['trade_name']}”")

    # 3. Udyam
    u_raw = fields["udyam_certificate"].get("udyam_number") or declared.get("udyam_number") or ""
    if docs.get("udyam_certificate") and "_unreadable" not in fields["udyam_certificate"] and not fields["udyam_certificate"].get("udyam_number"):
        r.add("Udyam number", "hold", "the Udyam certificate has no registration number printed on it")
    elif not docs.get("udyam_certificate") and declared.get("udyam_number"):
        r.add("Udyam certificate", "ask", f"certificate not uploaded; we can fetch {mask(declared['udyam_number'])} from DigiLocker with your consent instead")
    if u_raw and UDYAM_RE.match(u_raw):
        ur = udyam_lookup(u_raw)
        if not ur:
            r.add("Udyam registry", "hold", f"{mask(u_raw)} is not in the Udyam registry")
        else:
            r.udyam = u_raw
            biz = declared.get("business_name") or fields["udyam_certificate"].get("enterprise_name", "")
            if biz and not names_match(biz, ur["enterprise_name"]):
                r.add("Udyam name", "hold", f"Udyam record is for “{ur['enterprise_name']}”, not “{biz}”")
            else:
                r.add("Udyam", "pass", f"{mask(u_raw)} found: {ur['enterprise_name']}, {ur['enterprise_type']} enterprise, {ur['city']}")
    elif u_raw:
        r.add("Udyam format", "hold", f"{u_raw} is not a valid Udyam number format")

    # 4. Address proof: age and name
    ap = fields["address_proof"]
    if docs.get("address_proof") and "_unreadable" not in ap:
        bd = ap.get("bill_date")
        if bd:
            age = (TODAY - datetime.strptime(bd, "%Y-%m-%d").date()).days
            if age > ADDRESS_PROOF_MAX_AGE_DAYS:
                r.add("Address proof age", "ask", f"electricity bill is dated {bd}, {age} days old; we need one issued in the last {ADDRESS_PROOF_MAX_AGE_DAYS} days")
            else:
                r.add("Address proof age", "pass", f"bill dated {bd} ({age} days old)")
        else:
            r.add("Address proof date", "ask", "could not read the bill date; please upload a clearer copy")
        biz = declared.get("business_name") or fields["gst_certificate"].get("trade_name", "")
        if ap.get("billed_to") and biz and not names_match(ap["billed_to"], biz):
            r.add("Address proof name", "ask", f"bill is in the name of “{ap['billed_to']}”, not the business")
    elif not docs.get("address_proof"):
        r.add("Address proof", "ask", "no address proof uploaded")

    # 5. Signatory
    sg = fields["signatory_id"]
    if docs.get("signatory_id") and "_unreadable" not in sg:
        vt = sg.get("valid_till")
        if vt and datetime.strptime(vt, "%Y-%m-%d").date() < TODAY:
            r.add("Signatory ID validity", "ask", f"ID expired on {vt}")
        prop = proprietor_from_legal(r.legal_name)
        desig = (sg.get("designation") or "").lower()
        if prop:
            if names_match(sg.get("name", ""), prop):
                r.add("Signatory", "pass", f"{sg.get('name')} is the proprietor on record")
            else:
                r.add("Signatory", "hold", f"ID is for {sg.get('name')}, but the proprietor on record is {prop}; we need the proprietor to sign or an authorisation letter")
        elif desig and desig not in ("owner", "partner", "director", "proprietor"):
            r.add("Signatory authority", "ask", f"{sg.get('name')} is listed as “{sg.get('designation')}”; for a company or LLP we need a partner/director or a board authorisation letter")
        else:
            r.add("Signatory", "pass", f"{sg.get('name')} ({sg.get('designation')})")
        if declared.get("contact_name") and sg.get("name") and not names_match(declared["contact_name"], sg["name"]):
            r.add("Signatory vs application", "pass", f"signatory {sg['name']} differs from the application contact {declared['contact_name']}; recorded on the CAF")
    elif not docs.get("signatory_id"):
        r.add("Signatory ID", "ask", "no signatory ID uploaded")

    # next step text
    if not r.next_step:
        if r.decision == "pass":
            r.next_step = "All checks passed. E-sign the customer application form to finish."
        elif r.decision == "ask":
            asks = [c.detail for c in r.checks if c.status == "ask"]
            r.next_step = "One more thing: " + asks[0]
        else:
            holds = [c.detail for c in r.checks if c.status == "hold"]
            r.next_step = "We could not verify this automatically: " + holds[0] + " A verification officer will call within one working day."
    return r


def specimen_docs(k: str) -> Dict[str, Optional[str]]:
    base = DATA / "kyc_documents"
    out = {}
    for dt in ("gst_certificate", "udyam_certificate", "address_proof", "signatory_id"):
        p = base / f"{k}_{dt}.png"
        out[dt] = str(p) if p.exists() else None
    return out
