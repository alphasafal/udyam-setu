"""Offline natural-language understanding for the advisor.

Turns a free-text description of a business (English, Hinglish, or Hindi
keywords) into the same structured answers the tap-to-answer flow produces.
Deterministic and testable; the optional LLM path must emit the same schema.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

CITY_TIER = {'ahmedabad': 1, 'bengaluru': 1, 'bangalore': 1, 'bhopal': 2, 'chennai': 1, 'coimbatore': 2, 'delhi': 1, 'new delhi': 1, 'gurgaon': 1, 'gurugram': 1, 'noida': 1,
             'hyderabad': 1, 'indore': 2, 'jaipur': 2, 'kochi': 2, 'cochin': 2, 'kolkata': 1, 'lucknow': 2, 'ludhiana': 2, 'mumbai': 1, 'navi mumbai': 1, 'thane': 1, 'mysuru': 2, 'mysore': 2,
             'nagpur': 2, 'nashik': 2, 'patna': 2, 'pune': 1, 'surat': 2, 'vadodara': 2, 'baroda': 2, 'visakhapatnam': 2, 'vizag': 2, 'chandigarh': 2, 'bhubaneswar': 2, 'guwahati': 2, 'ranchi': 2, 'raipur': 2, 'dehradun': 2, 'agra': 2, 'kanpur': 2, 'varanasi': 2, 'rajkot': 2, 'madurai': 2, 'trichy': 2, 'mangalore': 2, 'hubli': 2, 'goa': 2, 'amritsar': 2, 'jodhpur': 2, 'udaipur': 2, 'kota': 2, 'meerut': 2, 'ghaziabad': 1, 'faridabad': 1}

TYPE_WORDS = {
    "factory": ["factory", "manufactur", "plant", "mill", "workshop", "foundry", "moulding", "molding", "packaging unit", "textile unit", "auto-parts", "auto parts", "food processing", "printing press", "karkhana", "फ़ैक्ट्री", "फैक्ट्री", "कारखाना", "यूनिट"],
    "chain": ["chain", "outlets", "branches", "stores in", "franchise", "hotel group", "gym", "pre-school", "preschool", "multiple locations", "all our shops", "शाखा", "आउटलेट"],
    "clinic": ["clinic", "doctor", "dental", "dentist", "physio", "diagnostic", "lab ", "pathology", "hospital", "ca firm", "chartered", "accountant", "coaching", "tuition", "institute", "office", "lawyer", "law office", "advocate", "architect", "consultan", "insurance", "real estate", "agency", "studio", "क्लिनिक", "कोचिंग", "दफ़्तर", "ऑफ़िस", "ऑफिस", "डॉक्टर"],
    "salon": ["salon", "parlour", "parlor", "restaurant", "cafe", "café", "bakery", "dhaba", "sweet shop", "mithai", "hotel", "eatery", "canteen", "सैलून", "रेस्टोरेंट", "होटल", "ढाबा", "बेकरी"],
    "kirana": ["shop", "kirana", "store", "pharmacy", "medical", "chemist", "boutique", "stationery", "hardware", "mobile repair", "optician", "grocery", "general store", "dukaan", "dukan", "दुकान", "किराना", "मेडिकल", "फ़ार्मेसी"],
}
NEED_WORDS = {
    "billing": ["bill", "billing", "upi", "pos", "inventory", "stock", "invoice", "gst billing", "बिलिंग", "बिल ", "स्टॉक"],
    "customers": ["whatsapp", "customer", "offer", "promotion", "sms", "marketing", "catalogue", "catalog", "orders on", "ग्राहक", "ऑफ़र"],
    "cctv": ["cctv", "camera", "surveillance", "कैमरा", "सीसीटीवी"],
    "email": ["email", "e-mail", "domain", "backup", "google workspace", "office 365", "ईमेल", "बैकअप"],
    "phone": ["ivr", "phone line", "landline", "call recording", "toll free", "toll-free", "1800", "receptionist", "calls", "टोल"],
    "uptime": ["never go down", "goes down", "keeps dropping", "downtime", "uptime", "backup internet", "failover", "reliable", "patients can't", "बंद हो", "नेट नहीं"],
    "website": ["website", "web site", "online presence", "वेबसाइट"],
    "iot": ["machine monitoring", "machines", "sensor", "energy use", "iot", "मशीनों", "मशीन मॉनिटर"],
    "security": ["ransomware", "virus", "antivirus", "firewall", "hack", "security", "सुरक्षा"],
    "wifi": ["customer wifi", "customer wi-fi", "guest wifi", "guest wi-fi", "wifi for customers", "free wifi", "ग्राहक वाई-फ़ाई"],
    "simonly": ["just a sim", "only a sim", "only sim", "only want a sim", "just want a sim", "just a mobile", "only mobile plan", "mobile plan only", "sirf sim", "bas sim", "सिर्फ़ सिम", "बस सिम"],
}


def _num(s: str) -> Optional[int]:
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
             "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "panch": 5, "das": 10, "bees": 20, "pachas": 50}
    s = s.strip().lower()
    if s.isdigit():
        return int(s)
    return words.get(s)


def parse(text: str) -> Dict[str, object]:
    """Return a partial answers dict: only the keys the text supports."""
    t = " " + text.lower().replace("\n", " ") + " "
    ans: Dict[str, object] = {}

    # business type (first category whose word appears earliest in the text wins)
    best = None
    for key, words in TYPE_WORDS.items():
        for w in words:
            i = t.find(w)
            if i >= 0 and (best is None or i < best[0]):
                best = (i, key)
    if best:
        ans["business_type"] = best[1]

    # people
    m = re.search(r"(\d+|[a-z]+)\s*(?:people|person|staff|employees|workers|team members|members|teachers|doctors|log|karmchari|कर्मचारी|लोग)", t)
    emp = _num(m.group(1)) if m else None
    # sites
    m2 = re.search(r"(\d+|[a-z]+)\s*(?:stores|outlets|branches|shops|locations|sites|clinics|centres|centers|restaurants|units|offices|dukaan|dukanein|शाखा|आउटलेट|दुकानें)", t)
    sites = _num(m2.group(1)) if m2 else None
    if sites and sites >= 2 and ans.get("business_type") in (None, "kirana", "salon", "clinic"):
        ans["business_type"] = "chain" if ans.get("business_type") != "clinic" or sites >= 3 else ans["business_type"]
    if emp is not None or sites is not None:
        e = emp or (3 if ans.get("business_type") in ("kirana", "salon", None) else 12)
        band = "1-5" if e <= 5 else ("6-25" if e <= 25 else "26-100")
        s = sites or 1
        ans["employees"] = f"{band}|{s}"

    # internet today
    if re.search(r"hotspot|phone data|mobile data|phone ka net|फ़ोन का|हॉटस्पॉट", t):
        ans["current_internet"] = "hotspot"
    elif re.search(r"leased line|lease line|dedicated line|लीज़्ड", t):
        ans["current_internet"] = "leased"
    elif re.search(r"home broadband|home wifi|ghar ka|घर वाला|jio ?fiber at home|home connection", t):
        ans["current_internet"] = "home"
    elif re.search(r"broadband|wifi|wi-fi|fibre|fiber|local isp|cable net|airtel|jio|bsnl|act ", t):
        ans["current_internet"] = "business"
    elif re.search(r"no internet|nothing yet|koi net nahi|कोई इंटरनेट नहीं", t):
        ans["current_internet"] = "none"

    # needs
    needs: List[str] = []
    for key, words in NEED_WORDS.items():
        if any(w in t for w in words):
            needs.append(key)
    if needs:
        ans["needs"] = needs

    # GSTIN
    if re.search(r"no gst|without gst|gst nahi|don't have gst|dont have gst|not registered|no gstin|जीएसटी नहीं", t):
        ans["has_gstin"] = "no"
    elif re.search(r"\bgst\b|gstin|gst registered|gst number|जीएसटी|\b\d{2}[a-z]{5}\d{4}[a-z][1-9a-z]z[0-9a-z]\b", t):
        ans["has_gstin"] = "yes"

    # city
    for city, tier in CITY_TIER.items():
        if re.search(r"\b" + re.escape(city) + r"\b", t):
            ans["city_tier"] = str(tier)
            ans["city"] = city.title()
            break
    return ans
