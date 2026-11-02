"""Run with:  python -m pytest -q
Covers the rule engine, the GSTIN validator and the 12 specimen KYC applicants."""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import catalogue, kyc, advisor  # noqa: E402

# ---- rule engine -------------------------------------------------------------
SEG_PROFILES = {
    "micro_nogst": catalogue.Profile(segment="micro", employees=3, sites=1, city_tier=2, has_gstin=False, current_internet="hotspot", needs=["billing", "cctv"]),
    "micro_gst": catalogue.Profile(segment="micro", employees=3, sites=1, city_tier=2, has_gstin=True, current_internet="hotspot", needs=["customers"]),
    "prof": catalogue.Profile(segment="prof", employees=12, sites=1, city_tier=1, has_gstin=True, current_internet="home", needs=["email", "phone"]),
    "multi": catalogue.Profile(segment="multi", employees=40, sites=5, city_tier=1, has_gstin=True, current_internet="mixed", needs=["uptime"]),
    "mfg": catalogue.Profile(segment="mfg", employees=60, sites=1, city_tier=2, has_gstin=True, current_internet="leased", needs=["iot"]),
}


@pytest.mark.parametrize("name,profile", SEG_PROFILES.items())
def test_every_bundle_respects_catalogue_rules(name, profile):
    rec = catalogue.recommend(profile)
    q = catalogue.price_bundle(rec["items"])
    sel = [l["product_id"] for l in q["lines"] if l["selected"]]
    for pid in sel:
        assert catalogue.eligibility_errors(pid, profile, sel) == [], f"{name}: {pid} violates rules"
    for l in q["lines"]:
        assert catalogue.price_in_band(l["product_id"], l["unit_price"])
    assert q["monthly"] > 0


def test_no_gstin_never_gets_gst_products():
    rec = catalogue.recommend(SEG_PROFILES["micro_nogst"])
    q = catalogue.price_bundle(rec["items"])
    for l in q["lines"]:
        if l["selected"]:
            assert not catalogue.CATALOGUE[l["product_id"]].requires_gstin


def test_tier2_never_gets_1g_fibre():
    p = catalogue.Profile(segment="prof", employees=12, city_tier=2, has_gstin=True)
    rec = catalogue.recommend(p)
    assert "P03" not in [l.product_id for l in rec["items"]]


def test_advisor_summary_in_hindi():
    out = advisor.advise({"business_type": "kirana", "employees": "1-5|1", "current_internet": "hotspot", "needs": ["billing"], "has_gstin": "no", "city_tier": "2", "language": "hi"})
    assert "₹" in out["summary"] and out["bundle_name"] == "Dukaan Start"
    assert out["quote"]["monthly"] == 1797  # AirFiber 899 + Postpaid 299 + Cloud POS 599 (asked for billing)


# ---- GSTIN validator ---------------------------------------------------------
def test_checksum_on_whole_registry():
    assert all(kyc.gstin_checksum_ok(g) for g in kyc.GSTIN_REGISTRY)


def test_repair_confusables():
    assert kyc.repair_gstin("24X0RXG9365M1Z3")["value"] == "24XORXG9365M1Z3"   # printed 0 for O
    assert kyc.repair_gstin("27QHIXK0658U1ZL")["value"] == "27QHJXK0658U1ZL"   # OCR I for J
    bad = kyc.repair_gstin("08YKZXS8189L1Z0")                                   # real digit change: must NOT be "repaired"
    assert not kyc.gstin_checksum_ok(bad["value"]) and not bad["repaired"]


def test_mask():
    assert kyc.mask("27QHJXK0658U1ZL") == "27QH…1ZL"


# ---- the 12 specimen applicants --------------------------------------------
EXPECTED = {  # decision, and a phrase that must appear in the checks
    "K01": ("hold", "Cancelled"), "K02": ("pass", "tilted"), "K03": ("pass", ""), "K04": ("ask", "blurred"),
    "K05": ("ask", "DigiLocker"), "K06": ("hold", "checksum"), "K07": ("hold", "Shri Physio"), "K08": ("pass", "0→O"),
    "K09": ("pass", ""), "K10": ("pass", "I→J"), "K11": ("ask", "257 days"), "K12": ("pass", ""),
}
LEAD = {'K01': 'L00045', 'K02': 'L01287', 'K03': 'L03571', 'K04': 'L01014', 'K05': 'L04014', 'K06': 'L00115', 'K07': 'L03349', 'K08': 'L03473', 'K09': 'L04779', 'K10': 'L04525', 'K11': 'L03485', 'K12': 'L03558'}


@pytest.fixture(scope="module")
def leads():
    with open(kyc.DATA / "smb_leads.csv", encoding="utf-8") as f:
        return {r["lead_id"]: r for r in csv.DictReader(f)}


@pytest.mark.parametrize("k", sorted(EXPECTED))
def test_specimen(k, leads):
    L = leads[LEAD[k]]
    r = kyc.run_kyc(k, kyc.specimen_docs(k), {"business_name": L["business_name"], "gstin": L["gstin"], "udyam_number": L["udyam_number"], "contact_name": L["contact_name"]})
    dec, phrase = EXPECTED[k]
    assert r.decision == dec, f"{k}: {[ (c.status, c.detail) for c in r.checks]}"
    assert phrase in " ".join(c.detail for c in r.checks)


# ---- 15 judge-style live scenarios (free text → bundle) ---------------------
SCENARIOS = [
    ("I run a bakery chain in Pune, 3 outlets and 14 staff, want CCTV and one bill, have GST", "Multi-site", ["P10", "P23"]),
    ("Mera salon Jaipur me hai, phone ka hotspot chalta hai, bill machine aur whatsapp pe offers bhejna hai, gst nahi hai", "Dukaan Start", ["P04", "P19"]),
    ("Dental clinic in Nagpur with 8 people. Home broadband keeps dropping during billing. Need email on our domain and backup.", "Clinic & Office", ["P02", "P09", "P16"]),
    ("I just want a SIM for my shop", "Just a SIM", ["P07"]),
    ("auto parts unit in Ludhiana, 60 workers, leased line now, need machine monitoring and firewall, gst registered", "Factory Connect (quoted after site survey)", ["P05", "P21", "P24"]),
    ("CA firm, 12 staff, Delhi, need toll free number and IVR, we are GST registered", "Clinic & Office", ["P12", "P13"]),
    ("small kirana store, 2 people, no gst, want upi billing", "Dukaan Start", ["P19"]),
    ("We are a gym with five branches in Bengaluru, 40 staff, mixed ISPs, want CCTV and one dashboard, GST number is there", "Multi-site", ["P10"]),
    ("Pharmacy chain 4 stores Hyderabad; GST registered; want POS and whatsapp orders", "Multi-site", ["P19", "P15"]),
    ("coaching centre Lucknow 6 teachers, website and cloud email, home wifi", "Clinic & Office", ["P16", "P18"]),
    ("restaurant in Kochi, 20 staff, cctv cameras and customer wifi, gst registered", "Dukaan Plus", ["P23", "P22"]),
    ("printing press Surat 30 workers, antivirus and backup, business broadband from local isp", "Factory Connect (quoted after site survey)", ["P20", "P17"]),
    ("mobile repair shop Indore one person hotspot", "Dukaan Start", ["P04", "P07"]),
    ("travel agency Mumbai 5 people phone lines and website, no gst", "Clinic & Office", ["P18"]),
    ("textile unit in Coimbatore 100 workers need leased line and iot sensors on machines, we have gstin", "Factory Connect (quoted after site survey)", ["P05", "P24"]),
]


@pytest.mark.parametrize("text,bundle,must", SCENARIOS)
def test_live_scenario(text, bundle, must):
    from app.nlu import parse
    ans = parse(text); ans["language"] = "en"
    out = advisor.advise(ans)
    assert out["bundle_name"] == bundle, (out["bundle_name"], ans)
    sel = [l["product_id"] for l in out["quote"]["lines"] if l["selected"]]
    for p in must:
        assert p in sel, (p, sel, out["removed"])
    # the rule engine must hold for whatever came out
    prof = advisor.build_profile(ans)
    for pid in sel:
        assert catalogue.eligibility_errors(pid, prof, sel) == []


def test_no_gst_travel_agency_gets_no_telephony():
    from app.nlu import parse
    ans = parse("travel agency Mumbai 5 people phone lines and website, no gst"); ans["language"] = "en"
    out = advisor.advise(ans)
    assert "P12" not in [l["product_id"] for l in out["quote"]["lines"] if l["selected"]]
    assert any(r["product_id"] in ("P12", "P13") for r in out["removed"])


def test_missing_gst_is_declared_as_assumption():
    from app.nlu import parse
    ans = parse("auto parts unit in Ludhiana, 60 workers, need machine monitoring"); ans["language"] = "en"
    out = advisor.advise(ans)
    assert any("GSTIN" in a for a in out["assumptions"])


# ---- GenAI layer (fake model; no network) -----------------------------------
class FakeLLM:
    def __init__(self, replies):
        self.replies = list(replies); self.seen = []
    def complete(self, system, user, max_tokens=400):
        self.seen.append(user)
        r = self.replies.pop(0) if self.replies else ""
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def fake_llm():
    from app import llm
    yield lambda replies: (llm.set_client(FakeLLM(replies)), llm.get_client())[1]
    llm.set_client(None)


def test_genai_understands_tamil_and_drops_invalid_values(fake_llm):
    import json as _j
    c = fake_llm([_j.dumps({"business_type": "clinic", "employees": "6-25|1", "needs": ["email", "teleport"], "has_gstin": "yes",
                            "city": "Chennai", "current_internet": "warp-drive"})])
    a = advisor.parse_free_text("சென்னையில் எங்கள் பல் மருத்துவமனை, 10 பேர், GST உள்ளது, மின்னஞ்சல் வேண்டும்", "en")
    assert a["_source"] == "genai" and a["business_type"] == "clinic" and a["has_gstin"] == "yes"
    assert a["needs"] == ["email"]                      # 'teleport' dropped
    assert "current_internet" not in a                   # invalid value dropped
    assert a["city_tier"] == "1"                        # city → tier from our table, not the model


def test_genai_never_sees_pii(fake_llm):
    c = fake_llm(["{}"])
    advisor.parse_free_text("my GSTIN is 27QHJXK0658U1ZL, call 9876543210 or a@b.in, PAN ABCXE1234F", "en")
    sent = c.seen[0]
    for secret in ("27QHJXK0658U1ZL", "9876543210", "a@b.in", "ABCXE1234F"):
        assert secret not in sent


def test_genai_explanation_rejected_if_numbers_change(fake_llm):
    fake_llm(["Dukaan Start is just ₹999 a month!"])      # model invents a price
    out = advisor.advise({"business_type": "kirana", "employees": "1-5|1", "current_internet": "hotspot", "needs": [], "has_gstin": "no", "city_tier": "2", "language": "en"})
    assert out["summary_source"] == "template" and "₹999" not in out["summary"]


def test_genai_explanation_accepted_when_faithful(fake_llm):
    base = advisor.advise({"business_type": "kirana", "employees": "1-5|1", "current_internet": "hotspot", "needs": [], "has_gstin": "no", "city_tier": "2", "language": "hi"})
    import re as _re
    nums = " ".join(_re.findall(r"₹[\d,]+|\b\d+\b", base["summary"]))
    fake_llm([f"आपकी दुकान के लिए Dukaan Start सही रहेगा। {nums}"])
    out = advisor.advise({"business_type": "kirana", "employees": "1-5|1", "current_internet": "hotspot", "needs": [], "has_gstin": "no", "city_tier": "2", "language": "hi"})
    assert out["summary_source"] == "genai"


def test_model_down_falls_back_to_offline(fake_llm):
    fake_llm([RuntimeError("timeout")])
    a = advisor.parse_free_text("salon in Jaipur, hotspot, want billing", "en")
    assert a["_source"] == "offline" and a["business_type"] == "salon"


# ---- regression tests for bugs found in review ------------------------------
def test_hinglish_sim_only():
    from app.nlu import parse
    assert "simonly" in parse("Kirana dukaan hai Surat mein, bas ek SIM chahiye business ke liye")["needs"]


def test_jio_phone_is_hotspot():
    from app.nlu import parse
    assert parse("medical store, internet comes from my Jio phone")["current_internet"] == "hotspot"


def test_sites_with_adjective_and_overlap():
    from app.nlu import parse
    assert parse("I own two dental clinics in Chennai with 15 staff")["employees"].endswith("|2")
    assert parse("gym with five branches in Bengaluru, 40 staff")["employees"].endswith("|5")


def test_factory_without_gstin_gets_starter_lines_and_gst_help():
    out = advisor.advise({"business_type": "factory", "employees": "26-100|1", "has_gstin": "no", "city_tier": "2", "language": "en"})
    sel = [l["product_id"] for l in out["quote"]["lines"] if l["selected"]]
    assert "P05" not in sel and "P08" in sel and "GST registration" in out["handoff_reason"]


# ---- 15 more owner descriptions the parser was NOT tuned on (segment routing) ----
UNSEEN = [
    ("We have a small medical store in Patna, me and my brother run it, internet comes from my Jio phone", "micro"),
    ("I own two dental clinics in Chennai with about 15 staff total, need appointments and patient data safe", "prof"),
    ("Hum log Indore mein ek coaching institute chalate hain, 8 teachers, online classes ke liye fast net chahiye", "prof"),
    ("chartered accountant practice, 4 people, Vadodara, worried about client data and ransomware, GST registered", "prof"),
    ("A restaurant group with 6 outlets across Mumbai and Pune, 120 employees, we need one bill and CCTV everywhere", "multi"),
    ("plastic moulding factory in Nashik, 45 workers, machines keep breaking down unexpectedly", "mfg"),
    ("Boutique in Kolkata. Only me. I sell on Instagram and WhatsApp mostly.", "micro"),
    ("diagnostic lab, Lucknow, 20 staff, reports must reach patients on whatsapp, internet keeps going down", "prof"),
    ("I run a sweet shop in Jaipur, want a billing machine and a QR for UPI", "micro"),
    ("Hotel group, 3 properties in Goa, guests complain about wifi", "multi"),
    ("pharmacy chain, 9 stores in Bengaluru, central inventory, GST yes", "multi"),
    ("Kirana dukaan hai Surat mein, bas ek SIM chahiye business ke liye", "micro"),
    ("Our architecture studio in Hyderabad has 7 designers who send huge files to clients", "prof"),
    ("food processing unit near Ludhiana, 80 staff, need a reliable leased line and fleet tracking for 5 trucks", "mfg"),
    ("Gym with 3 branches in Delhi, want members to check in and CCTV", "multi"),
]


@pytest.mark.parametrize("text,segment", UNSEEN)
def test_unseen_descriptions_route_to_right_segment(text, segment):
    from app.nlu import parse
    ans = parse(text); ans["language"] = "en"
    assert advisor.build_profile(ans).segment == segment, ans


def test_summary_install_days_match_selected_items():
    out = advisor.advise({"business_type": "salon", "employees": "1-5|1", "current_internet": "hotspot", "needs": ["billing", "customers"], "has_gstin": "yes", "city_tier": "2", "language": "en"})
    sel = [l["product_id"] for l in out["quote"]["lines"] if l["selected"]]
    assert out["install_days"] == max(catalogue.CATALOGUE[p].install_days for p in sel)
    assert f"about {out['install_days']} days" in out["summary"] and out["quote"]["monthly"] == 3195


# ---- the deck's business-case numbers must regenerate from the model ----------
def test_business_case_matches_deck():
    import runpy
    g = runpy.run_path(str(Path(__file__).resolve().parent.parent / "docs" / "business_case.py"), run_name="bc")
    st, S = g["steady"](), g["simulate"]()
    assert round(st["bundle"] / 5000, 3) == 0.133 and round(st["sim"]) == 95
    assert round(st["allin"] / st["bundle"]) == 10839
    assert S["payback"] == 15 and round(S["npv"] / 1e7, 1) == 11.9
    assert [round(y / 1e7, 2) for y in S["y"]] == [-0.97, 5.97, 10.76]
    # every single risk still pays back inside 36 months; all three together do not (the pilot gates on them)
    for name, kw in g["CASES"][:-1]:
        assert g["simulate"](**kw)["payback"] is not None, name
    assert g["simulate"](**g["CASES"][-1][1])["payback"] is None


def test_chain_add_ons_follow_needs():
    from app.nlu import parse
    a = parse("Pharmacy chain 4 stores Hyderabad; GST registered; want POS and whatsapp orders and one dashboard"); a["language"] = "en"
    out = advisor.advise(a)
    sel = [l["product_id"] for l in out["quote"]["lines"] if l["selected"]]
    assert "P10" in sel and "P19" in sel and "P23" not in sel and out["quote"]["monthly"] == 25283


def test_micro_add_ons_follow_needs_not_gstin():
    out = advisor.advise({"business_type": "kirana", "employees": "1-5|1", "current_internet": "hotspot", "needs": [], "has_gstin": "yes", "city_tier": "2", "language": "en"})
    assert out["quote"]["monthly"] == 1198      # a GSTIN alone does not switch on WhatsApp, POS or Wi-Fi
