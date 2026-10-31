"""Drive the whole journey in a headless browser; take screenshots; optionally record video.
python docs/e2e.py --video   (writes docs/shots/*.png and docs/video/*.webm)
"""
import sys, time, pathlib
from playwright.sync_api import sync_playwright

BASE = "http://localhost:8765"
OUT = pathlib.Path(__file__).parent / "shots"; OUT.mkdir(exist_ok=True)
VID = pathlib.Path(__file__).parent / "video"; VID.mkdir(exist_ok=True)
record = "--video" in sys.argv
lang = "hi" if "--hi" in sys.argv else "en"


def cap(page, txt, secs=2.2):
    page.evaluate("t => window.showCaption(t)", txt)
    if record:
        time.sleep(secs)


with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1280, "height": 720}, record_video_dir=str(VID) if record else None, record_video_size={"width": 1280, "height": 720})
    page = ctx.new_page()
    def card(title, lines, secs):
        html = "<body style='margin:0;background:#1c1c1e;color:#fff;font-family:Helvetica,Arial;display:flex;align-items:center;justify-content:center;height:100vh'><div style='max-width:900px;padding:40px'><div style='color:#E40000;font-weight:700;letter-spacing:.1em;font-size:16px'>AIRTEL SYNC · PROJECT UDYAM DIGITAL · TRACK A</div><h1 style='font-size:46px;margin:12px 0 10px'>" + title + "</h1>" + "".join("<p style='font-size:22px;color:#d9d9de;margin:6px 0'>" + l + "</p>" for l in lines) + "</div></body>"
        page.set_content(html)
        if record: time.sleep(secs)
    card("Udyam Setu", ["A small business goes from “what do I need?” to a live connection in one sitting.", "Working prototype · advisor → quote → Smart KYC → tracker → back office", "Safal Gupta · VIT Vellore"], 5)
    page.goto(BASE); page.wait_for_selector(".chip")
    if lang != "en":
        page.select_option("#lang", lang); page.wait_for_timeout(500)
    cap(page, "1 · Saathi asks five plain questions — no salesperson, no visit", 3)
    page.screenshot(path=OUT / "01_advisor.png")
    page.select_option("#lang", "hi"); page.wait_for_selector(".chip"); page.wait_for_timeout(400)
    cap(page, "Same journey in Hindi (and Marathi) — the owner's language, not the salesperson's", 3.5)
    page.screenshot(path=OUT / "01b_advisor_hindi.png")
    page.select_option("#lang", "mr"); page.wait_for_selector(".chip"); page.wait_for_timeout(400)
    cap(page, "Marathi", 1.5)
    page.select_option("#lang", "en"); page.wait_for_selector(".chip"); page.wait_for_timeout(300)
    # free-text path first
    page.fill("#free", "bakery chain in Pune, 3 outlets, 14 staff, want CCTV and one bill, have GST")
    cap(page, "Owners can also just describe the business. The parser (offline, or an LLM with the same schema) fills what it understood…", 3.5)
    page.click("#go"); page.wait_for_timeout(700)
    cap(page, "…and Saathi asks only what is still missing — here, just how the shops get internet today", 3.5)
    while page.query_selector("#chips"):
        page.click("#chips .chip[data-v=business]") if page.query_selector("#chips .chip[data-v=business]") else page.click("#chips .chip")
        page.click("#go"); page.wait_for_timeout(300)
    page.wait_for_selector(".price"); page.wait_for_timeout(500)
    cap(page, "A 3-outlet chain gets the Multi-site bundle: fibre + failover + SD-WAN + CCTV + POS per site, one toll-free number. ₹19,782 a month, one bill", 5)
    page.screenshot(path=OUT / "02b_quote_multisite.png")
    page.evaluate("location.reload()"); page.wait_for_selector(".chip"); page.wait_for_timeout(400)
    page.fill("#free", "I just want a SIM for my shop"); page.click("#go"); page.wait_for_timeout(600)
    while page.query_selector("#chips"):
        page.click("#chips .chip"); page.click("#go"); page.wait_for_timeout(250)
    page.wait_for_selector(".price"); page.wait_for_timeout(300)
    cap(page, "280 leads a quarter dropped because they 'only wanted a mobile plan'. Say that, and that is all you are sold: a SIM, no contract. Add-ons stay off", 5)
    page.evaluate("location.reload()"); page.wait_for_selector(".chip"); page.wait_for_timeout(400)
    cap(page, "Now the five-tap path, for an owner who would rather tap than type", 2.5)
    # Q1 business type: salon
    page.click(".chip[data-v=salon]"); page.wait_for_timeout(400); page.click("#go")
    cap(page, "Owner answers by tapping; free text works too (parsed into the same profile)", 2)
    page.click(".chip[data-v='1-5|1']"); page.click("#go"); page.wait_for_timeout(300)
    page.click(".chip[data-v=hotspot]"); page.click("#go"); page.wait_for_timeout(300)
    page.click(".chip[data-v=billing]"); page.click(".chip[data-v=customers]"); page.click(".chip[data-v=cctv]"); page.click("#go"); page.wait_for_timeout(300)
    page.click(".chip[data-v=yes]"); page.click("#go"); page.wait_for_timeout(300)
    page.click(".chip[data-v='2']"); page.click("#go")
    page.wait_for_selector(".price"); page.wait_for_timeout(600)
    cap(page, "2 · One monthly number. Each product says why it is there. Rule engine decided eligibility; the model only explains", 4)
    page.screenshot(path=OUT / "02_quote.png")
    page.click(".toggle[data-p=P18]"); page.wait_for_timeout(700)
    cap(page, "Add-ons toggle live — the price updates as the owner decides", 2.5)
    page.click(".toggle[data-p=P18]"); page.wait_for_timeout(500)
    page.click("#accept"); page.wait_for_selector("#c1")
    cap(page, "3 · Consent first, per purpose, in the owner's language. Retention stated up front (DPDP Act 2023)", 4)
    page.screenshot(path=OUT / "03_consent.png")
    page.check("#c1"); page.check("#c2"); page.click("#agree"); page.wait_for_selector("#gst")
    page.fill("#gst", "08YKZXS5189L1ZO"); page.click("#lk"); page.wait_for_selector("#lkres .tag")
    page.fill("#ud", "UDYAM-RJ-00-6577157"); page.click("#lku"); page.wait_for_selector("#lkures .tag")
    cap(page, "GSTIN and Udyam lookups pre-fill the form — the owner types less, we store less", 3)
    page.screenshot(path=OUT / "04_kyc_lookup.png")
    page.select_option("#spec", "K08"); page.click("#run"); page.wait_for_selector("#esign", timeout=120000)
    cap(page, "Smart KYC on specimen K08: OCR read 0 for O → checksum repair → registry confirms Active → PASS", 4.5)
    page.screenshot(path=OUT / "05_kyc_pass.png")
    # show a hold case too
    page.click("text=Back") if page.query_selector("text=Back") else None
    page.evaluate("renderKyc()"); page.wait_for_selector("#spec")
    page.select_option("#spec", "K01"); page.click("#run"); page.wait_for_selector(".check", timeout=120000)
    cap(page, "Specimen K01: GSTIN is Cancelled in the registry and the Udyam number is blank → HOLD, in plain words", 4.5)
    page.screenshot(path=OUT / "06_kyc_hold.png")
    page.evaluate("renderKyc()"); page.wait_for_selector("#spec")
    page.select_option("#spec", "K06"); page.click("#run"); page.wait_for_selector(".check", timeout=120000)
    cap(page, "Specimen K06: the certificate differs from the registered GSTIN by a real digit (8 vs 5), not a look-alike. Repair is refused, checksum fails → HOLD", 5)
    page.screenshot(path=OUT / "06b_kyc_k06.png")
    page.evaluate("renderKyc()"); page.wait_for_selector("#spec")
    page.fill("#biz", "Saffron Unisex Salon"); page.fill("#ph", "9876543210"); page.fill("#ct", "Pooja Shah")
    page.select_option("#spec", "K12"); page.click("#run"); page.wait_for_selector("#esign", timeout=120000)
    page.click("#esign"); page.wait_for_selector(".track")
    cap(page, "4 · Tracker: order placed, e-signed, autopay set. WhatsApp message at every state change — no status calls", 4)
    page.screenshot(path=OUT / "07_tracker.png")
    page.select_option("#slot", "Tomorrow 10–12"); page.click("#slotb"); page.wait_for_timeout(600)
    page.click("#adv"); page.wait_for_timeout(500); page.click("#adv"); page.wait_for_timeout(700)
    cap(page, "Owner picks the install slot; each step is pushed, not chased", 3)
    page.screenshot(path=OUT / "08_tracker_progress.png")
    # back office
    page.goto(BASE + "/backoffice"); page.wait_for_selector("#queue tbody tr"); page.wait_for_timeout(800)
    page.evaluate("""() => { const c = document.createElement('div'); c.id='caption'; c.style.cssText='position:fixed;left:0;right:0;bottom:0;background:rgba(28,28,30,.92);color:#fff;font-size:16px;padding:12px 18px;text-align:center'; document.body.appendChild(c); window.showCaption = t => { c.textContent = t; c.style.display = t ? 'block':'none'; }; }""")
    cap(page, "Back office: leads the advisor could not close, ranked by propensity score (AUC 0.71). Partners call quintile 5 first", 4.5)
    page.screenshot(path=OUT / "09_backoffice.png")
    cap(page, "Audit log: every lookup, consent and decision — identifiers masked, actor and reason recorded", 3.5)
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)"); time.sleep(2 if record else 0)
    card("What changes", ["Lead → activation 7.4% → 14% · lead-to-live 17.6 days → ≤4 · status calls 3 → <0.5", "Cost per activation ₹15,000 → ₹6,000 · zero activations on cancelled GSTINs", "Rule engine owns price & eligibility · consent-first KYC · partners finish what the advisor starts", "github.com/alphasafal/udyam-setu · 40 tests pass · live demo: claude.ai/artifact/15HCtChjeL3t5oFPn9SdSB"], 7)
    ctx.close(); b.close()
print("done", lang)
