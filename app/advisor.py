"""Saathi — the needs-discovery advisor.

GenAI-first: when a model is configured (app/llm.py), Claude understands the
owner's free text in any language and explains the recommendation in their
language. The rule engine (app/catalogue.py) always decides products, prices
and eligibility, and every model output is validated. With no model the same
flow runs on the offline parser and reviewed templates, so a demo never breaks.
"""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from .catalogue import Profile, recommend, price_bundle, CATALOGUE

LANGS = {"en": "English", "hi": "हिन्दी", "mr": "मराठी"}

# ---- question bank ---------------------------------------------------------
QUESTIONS = [
    {
        "id": "business_type",
        "text": {"en": "Namaste! What does your business do?",
                 "hi": "नमस्ते! आपका व्यवसाय क्या करता है?",
                 "mr": "नमस्कार! तुमचा व्यवसाय काय करतो?"},
        "options": [
            {"v": "kirana", "en": "Shop / kirana / pharmacy", "hi": "दुकान / किराना / फ़ार्मेसी", "mr": "दुकान / किराणा / फार्मसी"},
            {"v": "salon", "en": "Salon / restaurant / cafe", "hi": "सैलून / रेस्टोरेंट / कैफ़े", "mr": "सलून / रेस्टॉरंट / कॅफे"},
            {"v": "clinic", "en": "Clinic / CA firm / coaching / office", "hi": "क्लिनिक / सीए फ़र्म / कोचिंग / ऑफ़िस", "mr": "क्लिनिक / सीए फर्म / कोचिंग / ऑफिस"},
            {"v": "chain", "en": "Chain with several outlets", "hi": "कई आउटलेट वाली चेन", "mr": "अनेक आउटलेट असलेली साखळी"},
            {"v": "factory", "en": "Factory / manufacturing unit", "hi": "फ़ैक्ट्री / उत्पादन इकाई", "mr": "कारखाना / उत्पादन युनिट"},
        ],
    },
    {
        "id": "employees",
        "text": {"en": "How many people work there, and at how many locations?",
                 "hi": "वहाँ कितने लोग काम करते हैं, और कितनी जगहों पर?",
                 "mr": "तिथे किती लोक काम करतात, आणि किती ठिकाणी?"},
        "options": [
            {"v": "1-5|1", "en": "1–5 people, one place", "hi": "1–5 लोग, एक जगह", "mr": "1–5 लोक, एक ठिकाण"},
            {"v": "6-25|1", "en": "6–25 people, one place", "hi": "6–25 लोग, एक जगह", "mr": "6–25 लोक, एक ठिकाण"},
            {"v": "6-25|3", "en": "Up to 25 people, 2–5 places", "hi": "25 तक लोग, 2–5 जगहें", "mr": "25 पर्यंत लोक, 2–5 ठिकाणे"},
            {"v": "26-100|1", "en": "26–100 people, one place", "hi": "26–100 लोग, एक जगह", "mr": "26–100 लोक, एक ठिकाण"},
            {"v": "26-100|6", "en": "26–100 people, 6–10 places", "hi": "26–100 लोग, 6–10 जगहें", "mr": "26–100 लोक, 6–10 ठिकाणे"},
        ],
    },
    {
        "id": "current_internet",
        "text": {"en": "How do you get internet today?",
                 "hi": "आज आप इंटरनेट कैसे चलाते हैं?",
                 "mr": "आज तुम्ही इंटरनेट कसे वापरता?"},
        "options": [
            {"v": "hotspot", "en": "Phone hotspot", "hi": "फ़ोन का हॉटस्पॉट", "mr": "फोनचा हॉटस्पॉट"},
            {"v": "home", "en": "Home broadband", "hi": "घर वाला ब्रॉडबैंड", "mr": "घरचे ब्रॉडबँड"},
            {"v": "business", "en": "Business broadband / local ISP", "hi": "बिज़नेस ब्रॉडबैंड / लोकल ISP", "mr": "बिझनेस ब्रॉडबँड / स्थानिक ISP"},
            {"v": "leased", "en": "Leased line", "hi": "लीज़्ड लाइन", "mr": "लीज्ड लाइन"},
            {"v": "none", "en": "Nothing yet", "hi": "अभी कुछ नहीं", "mr": "अजून काही नाही"},
        ],
    },
    {
        "id": "needs",
        "multi": True,
        "text": {"en": "What would you like to fix first? Pick as many as you like.",
                 "hi": "सबसे पहले क्या ठीक करना चाहेंगे? जितने चाहें चुनें।",
                 "mr": "सर्वात आधी काय दुरुस्त करायचे आहे? हवे तितके निवडा."},
        "options": [
            {"v": "billing", "en": "Billing / UPI / inventory", "hi": "बिलिंग / UPI / स्टॉक", "mr": "बिलिंग / UPI / स्टॉक"},
            {"v": "customers", "en": "Reach customers on WhatsApp / SMS", "hi": "ग्राहकों तक WhatsApp / SMS से पहुँचना", "mr": "WhatsApp / SMS द्वारे ग्राहकांपर्यंत पोहोचणे"},
            {"v": "cctv", "en": "CCTV I can see on my phone", "hi": "CCTV जो फ़ोन पर दिखे", "mr": "फोनवर दिसणारे CCTV"},
            {"v": "email", "en": "Email on my own domain, backup", "hi": "अपने डोमेन पर ईमेल, बैकअप", "mr": "स्वतःच्या डोमेनवर ईमेल, बॅकअप"},
            {"v": "phone", "en": "Office phone lines / IVR", "hi": "ऑफ़िस फ़ोन लाइनें / IVR", "mr": "ऑफिस फोन लाइन / IVR"},
            {"v": "uptime", "en": "Internet must never go down", "hi": "इंटरनेट कभी बंद न हो", "mr": "इंटरनेट कधीही बंद पडू नये"},
            {"v": "website", "en": "A simple website", "hi": "एक साधारण वेबसाइट", "mr": "एक साधी वेबसाइट"},
            {"v": "iot", "en": "Machine monitoring", "hi": "मशीन मॉनिटरिंग", "mr": "मशीन मॉनिटरिंग"},
        ],
    },
    {
        "id": "has_gstin",
        "text": {"en": "Does the business have a GSTIN? (It unlocks WhatsApp Business, SMS and telephony products; if not, no problem.)",
                 "hi": "क्या व्यवसाय के पास GSTIN है? (इससे WhatsApp Business, SMS और टेलीफ़ोनी मिलते हैं; नहीं है तो भी कोई बात नहीं।)",
                 "mr": "व्यवसायाकडे GSTIN आहे का? (त्यामुळे WhatsApp Business, SMS आणि टेलिफोनी मिळते; नसेल तरी हरकत नाही.)"},
        "options": [
            {"v": "yes", "en": "Yes", "hi": "हाँ", "mr": "होय"},
            {"v": "no", "en": "No / not sure", "hi": "नहीं / पता नहीं", "mr": "नाही / माहीत नाही"},
        ],
    },
    {
        "id": "city_tier",
        "text": {"en": "Which city?", "hi": "कौन सा शहर?", "mr": "कोणते शहर?"},
        "options": [
            {"v": "1", "en": "Delhi, Mumbai, Bengaluru, Hyderabad, Chennai, Kolkata, Pune, Ahmedabad", "hi": "दिल्ली, मुंबई, बेंगलुरु, हैदराबाद, चेन्नई, कोलकाता, पुणे, अहमदाबाद", "mr": "दिल्ली, मुंबई, बेंगळुरू, हैदराबाद, चेन्नई, कोलकाता, पुणे, अहमदाबाद"},
            {"v": "2", "en": "Another city (Jaipur, Indore, Nagpur, Kochi, Surat…)", "hi": "कोई और शहर (जयपुर, इंदौर, नागपुर, कोच्चि, सूरत…)", "mr": "दुसरे शहर (जयपूर, इंदूर, नागपूर, कोची, सुरत…)"},
        ],
    },
]

EXTRA_NEED_LABELS = {"central": {"en": "One dashboard for all sites", "hi": "सभी शाखाओं का एक डैशबोर्ड", "mr": "सर्व शाखांसाठी एक डॅशबोर्ड"}, "simonly": {"en": "Just a mobile line", "hi": "सिर्फ़ मोबाइल लाइन", "mr": "फक्त मोबाइल लाइन"},
                     "wifi": {"en": "Wi-Fi for customers", "hi": "ग्राहकों के लिए वाई-फ़ाई", "mr": "ग्राहकांसाठी वाय-फाय"},
                     "security": {"en": "Security / antivirus", "hi": "सुरक्षा / एंटीवायरस", "mr": "सुरक्षा / अँटीव्हायरस"}}
SEG_BY_TYPE = {"kirana": "micro", "salon": "micro", "clinic": "prof", "chain": "multi", "factory": "mfg"}
SIM_SUMMARY = {"en": "You said you only want a mobile line, so that is all I am quoting: {bundle}, ₹{monthly:,} a month, no contract, SIM at your door tomorrow. The add-ons stay switched off unless you tap them.",
               "hi": "आपने कहा सिर्फ़ मोबाइल लाइन चाहिए, तो बस वही: {bundle}, ₹{monthly:,} प्रति माह, कोई अनुबंध नहीं, SIM कल आपके पास। ऐड-ऑन तब तक बंद रहेंगे जब तक आप न चुनें।",
               "mr": "तुम्ही फक्त मोबाइल लाइन हवी म्हणालात, म्हणून फक्त तेच: {bundle}, ₹{monthly:,} दरमहा, करार नाही, SIM उद्या तुमच्याकडे. अ‍ॅड-ऑन तुम्ही निवडेपर्यंत बंद."}


def build_profile(answers: Dict[str, object]) -> Profile:
    p = Profile()
    p.business_type = str(answers.get("business_type", "kirana"))
    p.segment = SEG_BY_TYPE.get(p.business_type, "micro")
    emp, sites = str(answers.get("employees", "1-5|1")).split("|")
    p.employees = {"1-5": 3, "6-25": 12, "26-100": 40}.get(emp, 3)
    p.sites = int(sites)
    if p.sites >= 3 and p.segment in ("micro", "prof"):
        p.segment = "multi"
    p.current_internet = str(answers.get("current_internet", "hotspot"))
    needs = answers.get("needs", [])
    p.needs = list(needs) if isinstance(needs, (list, tuple)) else [n for n in str(needs).split(",") if n]
    p.has_gstin = str(answers.get("has_gstin", "no")) == "yes"
    p.city_tier = int(answers.get("city_tier", 2))
    p.business_type = p.business_type if p.business_type in SEG_BY_TYPE else "kirana"
    p.language = str(answers.get("language", "en"))
    return p


SUMMARY = {
    "en": "Here is what I would set up for a {btype} with {emp} people{sites}: {bundle}. {n} products, one bill of ₹{monthly:,} a month. The connection goes live in about {days} days. Tap any add-on to switch it on or off; the price updates as you go.",
    "hi": "आपके {btype} के लिए, जहाँ {emp} लोग काम करते हैं{sites}, मैं यह सुझाऊँगा: {bundle}। {n} प्रोडक्ट, एक ही बिल ₹{monthly:,} प्रति माह। कनेक्शन लगभग {days} दिन में चालू हो जाएगा। कोई भी ऐड-ऑन छूकर चालू/बंद करें; दाम तुरंत बदल जाएगा।",
    "mr": "तुमच्या {btype} साठी, जिथे {emp} लोक काम करतात{sites}, मी हे सुचवेन: {bundle}. {n} उत्पादने, एकच बिल ₹{monthly:,} दरमहा. कनेक्शन सुमारे {days} दिवसांत सुरू होईल. कोणतेही अ‍ॅड-ऑन चालू/बंद करा; किंमत लगेच बदलते.",
}
BTYPE = {"kirana": {"en": "shop", "hi": "दुकान", "mr": "दुकान"}, "salon": {"en": "salon or restaurant", "hi": "सैलून/रेस्टोरेंट", "mr": "सलून/रेस्टॉरंट"},
         "clinic": {"en": "clinic or office", "hi": "क्लिनिक/ऑफ़िस", "mr": "क्लिनिक/ऑफिस"}, "chain": {"en": "multi-outlet business", "hi": "मल्टी-आउटलेट व्यवसाय", "mr": "मल्टी-आउटलेट व्यवसाय"},
         "factory": {"en": "factory", "hi": "फ़ैक्ट्री", "mr": "कारखाना"}}
WHY_HI = {  # reviewed phrase bank; LLM may rewrite but never invent
    "P04": {"hi": "प्लग-एंड-प्ले 5G AirFiber: 2 दिन में चालू, फ़ाइबर खुदाई नहीं", "mr": "प्लग-अँड-प्ले 5G AirFiber: 2 दिवसांत सुरू, फायबर खोदकाम नाही"},
    "P01": {"hi": "दुकान के लिए 100 Mbps फ़ाइबर", "mr": "दुकानासाठी 100 Mbps फायबर"},
    "P02": {"hi": "300 Mbps बिज़नेस फ़ाइबर", "mr": "300 Mbps बिझनेस फायबर"},
    "P07": {"hi": "एक बिज़नेस मोबाइल लाइन, 50 GB — दुकान का नंबर अलग रहे", "mr": "एक बिझनेस मोबाइल लाइन, 50 GB — दुकानाचा नंबर वेगळा"},
    "P08": {"hi": "150 GB, रोमिंग और प्रायोरिटी केयर वाली मोबाइल लाइनें", "mr": "150 GB, रोमिंग व प्रायॉरिटी केअर मोबाइल लाइन"},
    "P09": {"hi": "मुख्य लाइन बंद हो तो 4G/5G बैकअप अपने आप", "mr": "मुख्य लाइन बंद पडल्यास 4G/5G बॅकअप आपोआप"},
    "P15": {"hi": "वेरिफ़ाइड WhatsApp चैनल और कैटलॉग, 1,000 बातचीत/माह", "mr": "व्हेरिफाइड WhatsApp चॅनेल व कॅटलॉग, 1,000 संभाषणे/महिना"},
    "P19": {"hi": "टैबलेट पर GST बिलिंग, स्टॉक और UPI", "mr": "टॅबलेटवर GST बिलिंग, स्टॉक व UPI"},
    "P22": {"hi": "ग्राहकों के लिए अलग Wi-Fi, कंटेंट फ़िल्टर के साथ", "mr": "ग्राहकांसाठी वेगळे Wi-Fi, कंटेंट फिल्टरसह"},
    "P23": {"hi": "HD कैमरे, 30 दिन क्लाउड रिकॉर्डिंग, फ़ोन पर देखें", "mr": "HD कॅमेरे, 30 दिवस क्लाउड रेकॉर्डिंग, फोनवर पहा"},
    "P18": {"hi": "डोमेन, 5 पेज की वेबसाइट और SSL", "mr": "डोमेन, 5 पानांची वेबसाइट व SSL"},
    "P16": {"hi": "अपने डोमेन पर ईमेल, डॉक्यूमेंट और वीडियो मीटिंग", "mr": "स्वतःच्या डोमेनवर ईमेल, डॉक्युमेंट व व्हिडिओ मीटिंग"},
    "P20": {"hi": "PC और फ़ोन के लिए एंटीवायरस/रैंसमवेयर सुरक्षा", "mr": "PC व फोनसाठी अँटीव्हायरस/रॅन्समवेअर संरक्षण"},
    "P17": {"hi": "PC और फ़ोन का 1 TB ऑटोमैटिक बैकअप", "mr": "PC व फोनचा 1 TB ऑटोमॅटिक बॅकअप"},
    "P12": {"hi": "IVR और कॉल रिकॉर्डिंग वाली क्लाउड फ़ोन लाइनें", "mr": "IVR व कॉल रेकॉर्डिंगसह क्लाउड फोन लाइन"},
    "P11": {"hi": "CCTV/रिमोट एक्सेस के लिए फ़िक्स्ड पब्लिक IP", "mr": "CCTV/रिमोट अ‍ॅक्सेससाठी फिक्स्ड पब्लिक IP"},
    "P13": {"hi": "1800 टोल-फ़्री नंबर", "mr": "1800 टोल-फ्री नंबर"},
    "P10": {"hi": "सभी साइटों के लिंक एक डैशबोर्ड पर", "mr": "सर्व साइट्सचे लिंक एका डॅशबोर्डवर"},
    "P05": {"hi": "99.5% SLA वाली 20 Mbps डेडिकेटेड लीज़्ड लाइन", "mr": "99.5% SLA सह 20 Mbps डेडिकेटेड लीज्ड लाइन"},
    "P21": {"hi": "Accel SOC द्वारा मैनेज्ड फ़ायरवॉल", "mr": "Accel SOC द्वारे मॅनेज्ड फायरवॉल"},
    "P24": {"hi": "मशीन अपटाइम और बिजली के लिए IoT सेंसर", "mr": "मशीन अपटाइम व विजेसाठी IoT सेन्सर"},
    "P25": {"hi": "गाड़ियों पर GPS ट्रैकर", "mr": "वाहनांवर GPS ट्रॅकर"},
}


def advise(answers: Dict[str, object]) -> dict:
    lang = str(answers.get("language", "en"))
    profile = build_profile(answers)
    rec = recommend(profile)
    quote = price_bundle(rec["items"])
    for line in quote["lines"]:
        if lang != "en" and line["product_id"] in WHY_HI:
            line["why"] = WHY_HI[line["product_id"]][lang]
    sites_txt = {"en": f" across {profile.sites} sites", "hi": f", {profile.sites} जगहों पर", "mr": f", {profile.sites} ठिकाणी"}[lang] if profile.sites > 1 else ""
    if "simonly" in profile.needs:
        summary = SIM_SUMMARY[lang].format(bundle=rec["bundle_name"], monthly=quote["monthly"])
    else:
        summary = SUMMARY[lang].format(btype=BTYPE[profile.business_type][lang], emp=profile.employees, sites=sites_txt,
                                   bundle=rec["bundle_name"], n=sum(1 for l in quote["lines"] if l["selected"]),
                                       monthly=quote["monthly"], days=rec["install_days"])
    facts = {"bundle": rec["bundle_name"], "monthly_price": f"₹{quote['monthly']:,}", "setup": f"₹{quote['setup']:,}",
             "contract_months": rec["contract_months"], "live_in_days": rec["install_days"],
             "products": [{"name": l["name"], "qty": l["qty"], "why": l["why"]} for l in quote["lines"] if l["selected"]],
             "owner_said": profile.needs}
    ex = _llm.explain(facts, summary, {"en": "English", "hi": "Hindi", "mr": "Marathi"}.get(lang, "English"))
    summary, summary_source = ex["text"], ex["source"]
    asked_for = [l["product_id"] for l in quote["lines"] if l["selected"]]
    assumptions = []
    if "has_gstin" not in answers:
        assumptions.append({"en": "I assumed no GSTIN; say yes to unlock WhatsApp Business, SMS and telephony.", "hi": "मैंने मान लिया कि GSTIN नहीं है; हाँ कहें तो WhatsApp Business, SMS और टेलीफ़ोनी खुल जाएँगे।", "mr": "मी GSTIN नाही असे गृहीत धरले; होय म्हणाल तर WhatsApp Business, SMS व टेलिफोनी उघडतील."}[lang])
    if "city_tier" not in answers:
        assumptions.append({"en": "I assumed a tier-2 city; some products are tier-1 only.", "hi": "मैंने टियर-2 शहर माना; कुछ प्रोडक्ट सिर्फ़ टियर-1 में हैं।", "mr": "मी टियर-2 शहर गृहीत धरले; काही उत्पादने फक्त टियर-1 मध्ये आहेत."}[lang])
    return {
        "summary_source": summary_source,
        "assumptions": assumptions,
        "profile": profile.__dict__,
        "bundle_name": rec["bundle_name"],
        "contract_months": rec["contract_months"],
        "install_days": rec["install_days"],
        "removed": rec["removed"],
        "quote": quote,
        "summary": summary,
        "covers_needs": asked_for,
        "handoff": profile.segment == "mfg",
        "handoff_reason": ("Leased lines need a site survey; a specialist will call within one working day with this profile already filled in."
                           + ("" if profile.has_gstin else " A leased line, managed firewall and IoT need an active GSTIN, so the specialist will help with GST registration first; until then we can start with business mobile lines and email.")) if profile.segment == "mfg" else "",
    }


# ---- GenAI layer -------------------------------------------------------------
from . import llm as _llm


def llm_available() -> bool:
    return _llm.get_client() is not None


def answer_schema() -> Dict[str, List[str]]:
    return {q["id"]: [o["v"] for o in q["options"]] for q in QUESTIONS}


def parse_free_text(text: str, lang: str = "en") -> Optional[Dict[str, object]]:
    """GenAI understanding first; the offline parser fills anything the model left out
    (and is the whole answer when no model is configured)."""
    from .nlu import parse
    offline = parse(text)
    ai = _llm.understand(text, answer_schema(), lang)
    merged = dict(offline)
    merged.update(ai)                      # model wins where it answered (validated values only)
    if "needs" in offline and "needs" in ai:
        merged["needs"] = list(dict.fromkeys(list(ai["needs"]) + list(offline["needs"])))
    if "city" in merged and "city_tier" not in ai:
        from .nlu import CITY_TIER
        t = CITY_TIER.get(str(merged["city"]).lower())
        if t:
            merged["city_tier"] = str(t)
    merged["_source"] = "genai" if ai else "offline"
    return merged or None


def maybe_llm_polish(summary: str, lang: str, facts: Optional[dict] = None) -> str:
    return _llm.explain(facts or {"summary": summary}, summary, {"en": "English", "hi": "Hindi", "mr": "Marathi"}.get(lang, "English"))["text"]
