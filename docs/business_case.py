"""Udyam Setu business case (v2). Every figure on the deck's business-case and metrics slides comes from here.

Run:  python docs/business_case.py          (prints the tables, writes docs/business_case.md)

Method, so a reviewer can follow it:
  1. PRICE: what the advisor's rule engine would actually quote each of the 5,000 leads in data/smb_leads.csv
     (its segment, size, sites, city tier, GSTIN, current internet and products of interest). No assumed bundle values.
  2. VOLUME: start from today's funnel. For each coded leak, a stated share of the lost leads is recovered and
     continues from the next stage at TODAY's downstream conversion for that segment (the new journey surely
     improves those too, so this is conservative). Leaks the journey cannot fix (not interested, locked in,
     competitor cheaper, decided to wait) are not touched.
  3. CHURN: falls to the rate of today's customers who chased at most twice (11.9% vs 15.2%), applied per segment.
  4. COST: field team kept as a fixed cost; partners paid per activation with a retention payment; the digital
     journey's variable costs; free equipment where there is no setup fee; the programme's build and run cost.
Everything marked ASSUMPTION is a judgement call, kept as a named constant.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.catalogue import CATALOGUE, Profile, recommend, price_bundle  # noqa: E402

d = pd.read_csv(ROOT / "data" / "smb_leads.csv")
d["act"] = (d.outcome == "Activated").astype(int)
d["churn"] = (d.churned_within_6_months == "Y").astype(int)
SEGS = ["Micro retail & services", "Professional offices", "Small multi-site businesses", "Small manufacturers"]
SHORT = {"Micro retail & services": "Micro", "Professional offices": "Offices", "Small multi-site businesses": "Multi-site", "Small manufacturers": "Factories"}
SEGCODE = {"Micro retail & services": "micro", "Professional offices": "prof", "Small multi-site businesses": "multi", "Small manufacturers": "mfg"}
ORDER = ["Lead", "Contacted", "Needs assessed", "Quote accepted", "KYC complete", "Activated"]
d["si"] = d.stage_reached.map({s: i for i, s in enumerate(ORDER)})

# ------------------------------------------------------------------ 1. PRICE: the advisor's quote for every lead
NEED_OF = {"P19": "billing", "P15": "customers", "P14": "customers", "P23": "cctv", "P16": "email", "P17": "email", "P12": "phone", "P13": "phone",
           "P09": "uptime", "P10": "central", "P18": "website", "P24": "iot", "P25": "fleet", "P20": "security", "P21": "security", "P22": "wifi"}
NET = {"Mobile hotspot": "hotspot", "Home broadband": "home", "Business broadband": "business", "Leased line": "leased", "Mixed per site": "mixed"}


def advisor_quote(r) -> tuple[int, bool]:
    needs = sorted({NEED_OF[p] for p in str(r.products_of_interest).split(";") if p in NEED_OF})
    seg = SEGCODE[r.segment]
    p = Profile(business_type="", segment=seg, employees=int(r.employee_count), sites=int(r.num_sites), city_tier=int(r.city_tier),
                has_gstin=r.has_gstin == "Y", current_internet=NET.get(r.current_internet, "none"), needs=needs)
    if seg in ("micro", "prof") and p.sites >= 3:
        p.segment = "multi"
    rec = recommend(p)
    q = price_bundle(rec["items"])
    airfiber = any(l["product_id"] == "P04" and l["selected"] for l in q["lines"])
    return q["monthly"], airfiber


qa = d.apply(lambda r: pd.Series(advisor_quote(r), index=["quote", "airfiber"]), axis=1)
d = pd.concat([d, qa], axis=1)
SIM_ONLY_VALUE = CATALOGUE["P07"].price_min * 2          # a "just a SIM" customer takes about two lines

# ------------------------------------------------------------------ 2. VOLUME: recover part of each fixable leak
# ASSUMPTION: share of each leak the journey recovers, and the stage the recovered lead continues from.
RECOVERY = {
    "Unreachable after 3 attempts": (0.20, "Contacted"),      # instant WhatsApp/web reply instead of 3 call attempts
    "Wrong or invalid number": (0.10, "Contacted"),           # a self-serve link reaches a few; most are dead numbers
    "Owner had no time for a visit": (0.40, "Needs assessed"), # no visit needed
    "Visit not scheduled by sales": (0.40, "Needs assessed"),
    "Quote too complex to understand": (0.40, "Quote accepted"),  # one readable number
    "Quote took too long to arrive": (0.40, "Quote accepted"),    # instant quote
    "Price too high": (0.15, "Quote accepted"),                   # right-sized bundle, AirFiber instead of fibre
    "Missing GST or Udyam document": (0.40, "KYC complete"),      # registry lookup, DigiLocker
    "Found paperwork too long": (0.40, "KYC complete"),
    "Authorised signatory not available": (0.40, "KYC complete"),  # remote eSign
    "Document details did not match": (0.20, "KYC complete"),     # many are genuine mismatches and stay held
    "Installation delayed beyond 21 days": (0.40, "Activated"),   # AirFiber in 2 days; slot picker
    "First payment failed": (0.50, "Activated"),                  # UPI retry from the tracker
    "Customer cancelled before install": (0.20, "Activated"),     # proactive updates
    "Site not feasible for fibre": (0.50, "Activated"),           # AirFiber alternative
    "Only wanted a mobile plan": (0.35, "SIM"),                   # sold exactly that
}
# ASSUMPTION: how much of the journey each segment really gets. Factories stay field-led, so only half the effect.
SEG_REACH = {"micro": 1.0, "prof": 1.0, "multi": 1.0, "mfg": 0.5}
NOT_FIXABLE = ["Not interested on first call", "Locked in with current provider", "Competitor offered cheaper plan", "Decided to wait"]

# ------------------------------------------------------------------ 3. CHURN
a_all = d[d.act == 1]
CHURN_FACTOR = a_all.loc[a_all.customer_follow_up_calls <= 2, "churn"].mean() / a_all.churn.mean()   # ≈ 0.78

# ------------------------------------------------------------------ 4. COST (₹)
COST_PER_LEAD = {"WhatsApp Business conversations (≈6 per lead)": 6 * 0.9, "LLM advisor (≈4k tokens per lead, incl. retries)": 4.0}
COST_PER_KYC = {"GSTIN + Udyam lookups via an API aggregator": 6.0, "OCR + document checks (cloud compute)": 2.0, "DigiLocker fetch when used": 5.0}
COST_PER_ACT = {"Aadhaar eSign (OTP) via a licensed ESP": 25.0, "Human review of held/asked cases (≈25% of KYCs, 8 min)": 40.0}
AIRFIBER_SUBSIDY = 2500        # ASSUMPTION: AirFiber unit given free (catalogue setup fee is ₹0); other products recover equipment through their setup fee
# Partner pay (ASSUMPTION): paid only on activation, plus a retention payment if the customer is still active at month 6.
PARTNER_FEE = {"micro": (1500, 1000), "prof": (3000, 2000), "multi": (6000, 4000), "mfg": (0, 0)}   # per activation; multi-site per customer
ASSIST_SHARE = {"micro": 0.10, "prof": 0.25, "multi": 1.0, "mfg": 0.0}
SETU_SHARE, SETU_FEE = {"micro": 0.25, "prof": 0.0, "multi": 0.0, "mfg": 0.0}, 300   # ₹150 at activation + ₹150 at month 3
FIELD_FIXED_Q = d.loc[d.lead_source == "Field sales", "acquisition_cost_inr"].sum()   # salaried team: redeployed, not cut
TODAY_PARTNER_Q = d.loc[d.lead_source == "Channel partner", "acquisition_cost_inr"].sum()
TODAY_OTHER_VAR_Q = d.loc[~d.lead_source.isin(["Field sales", "Channel partner"]), "acquisition_cost_inr"].sum()
BUILD_ONE_TIME = 1.2e7         # ASSUMPTION: 8-person squad × 6 months × ₹2.5 L loaded
RUN_PER_MONTH = 6e5            # ASSUMPTION: cloud, model evaluation, monitoring, 2 FTE operations
GROSS_MARGIN = 0.55            # ASSUMPTION: contribution margin. Benchmark: Airtel India reported a 60.1% EBITDA margin in Q1 FY27,
                               # and contribution before overheads is higher than EBITDA, so 55% is conservative.
RAMP = [0.25, 0.55, 0.85, 1.0]  # share of the full effect reached in quarters 1–4


def segment_view(rec_scale=1.0, value_scale=1.0, churn_add=0.0, lift=1.0):
    """One quarter (5,000 leads). Per-segment numbers for the new journey at a given lift (0..1)."""
    out = {}
    for s in SEGS:
        g = d[d.segment == s]
        acts0 = g.act.sum()
        p_from = {st: g[g.si >= i].act.mean() for i, st in enumerate(ORDER)}
        p_from["Activated"] = 1.0
        rec_acts, sim_acts = 0.0, 0.0
        reach = SEG_REACH[SEGCODE[s]]
        for reason, (r, from_stage) in RECOVERY.items():
            lost = (g.drop_reason == reason).sum()
            r = r * reach
            if from_stage == "SIM":
                sim_acts += lost * r * rec_scale * lift
            else:
                rec_acts += lost * r * rec_scale * lift * p_from[from_stage]
        acts = acts0 + rec_acts
        # price: today's actual bundles move to the advisor's quote as the journey takes over
        val0 = g[g.act == 1].monthly_bundle_value_inr.mean()
        quote = (val0 * (1 - lift) + g.quote.mean() * lift) * value_scale
        mrr = acts * quote + sim_acts * SIM_ONLY_VALUE * value_scale
        churn0 = g[g.act == 1].churn.mean()
        churn = min(1.0, churn0 * (1 - (1 - CHURN_FACTOR) * lift) + churn_add)
        code = SEGCODE[s]
        tot_acts = acts + sim_acts
        leads = len(g)
        var = leads * sum(COST_PER_LEAD.values()) + tot_acts * 1.3 * sum(COST_PER_KYC.values()) + tot_acts * sum(COST_PER_ACT.values())
        fee, ret = PARTNER_FEE[code]
        partner = acts * ASSIST_SHARE[code] * (fee + ret * (1 - churn))
        setu = tot_acts * SETU_SHARE[code] * SETU_FEE
        cpe = acts * g.airfiber.mean() * AIRFIBER_SUBSIDY
        out[s] = dict(leads=leads, acts0=acts0, acts=tot_acts, sim=sim_acts, conv0=acts0 / leads, conv=tot_acts / leads, quote=quote,
                      val0=val0, advisor_quote=g.quote.mean(), mrr=mrr, churn0=churn0, churn=churn, var=var, partner=partner, setu=setu, cpe=cpe)
    return out


def totals(v):
    T = {k: sum(x[k] for x in v.values()) for k in ["leads", "acts0", "acts", "sim", "mrr", "var", "partner", "setu", "cpe"]}
    T["retained_mrr"] = sum(x["mrr"] * (1 - x["churn"]) for x in v.values())
    T["churn_rev"] = 1 - T["retained_mrr"] / T["mrr"]
    T["churn_cnt"] = sum(x["acts"] * x["churn"] for x in v.values()) / T["acts"]
    return T


BASE_MRR = a_all.monthly_bundle_value_inr.sum()
BASE_RET = (a_all.monthly_bundle_value_inr * (1 - a_all.churn)).sum()
BASE_ACQ_Q = d.acquisition_cost_inr.sum()


def quarter_cost(T, lift):
    """Acquisition cost of one quarter: field team fixed; partner and other variable spend move from today's model to the new one."""
    new_var = T["var"] + T["partner"] + T["setu"] + T["cpe"]
    today_var = TODAY_PARTNER_Q + TODAY_OTHER_VAR_Q
    return FIELD_FIXED_Q + today_var * (1 - lift) + new_var * lift


def year(margin=None, **kw):
    m = GROSS_MARGIN if margin is None else margin
    qs = []
    for lift in RAMP:
        T = totals(segment_view(lift=lift, **kw))
        T["acq"] = quarter_cost(T, lift)
        qs.append(T)
    ss = qs[-1]
    rev_new = rev_base = 0.0
    for i, q in enumerate(qs):
        months = 12 - (3 * i + 1.5)
        rev_new += q["retained_mrr"] * months
        rev_base += BASE_RET * months
    inc_rev = rev_new - rev_base
    acq_saving = BASE_ACQ_Q * 4 - sum(q["acq"] for q in qs)
    y1_net = inc_rev * m + acq_saving - BUILD_ONE_TIME - RUN_PER_MONTH * 12
    y1_cohorts = sum(q["retained_mrr"] for q in qs) - BASE_RET * 4
    y2_rev = y1_cohorts * 12 + (ss["retained_mrr"] - BASE_RET) * sum(12 - (3 * i + 1.5) for i in range(4))
    y2_save = (BASE_ACQ_Q - ss["acq"]) * 4
    y2_net = y2_rev * m + y2_save - RUN_PER_MONTH * 12
    cum, month, stacked = -BUILD_ONE_TIME, 0, 0.0
    while cum < 0 and month < 60:
        month += 1
        qi = min((month - 1) // 3, 3)
        if (month - 1) % 3 == 1:
            stacked += (qs[qi]["retained_mrr"] - BASE_RET) * m
        cum += stacked + (BASE_ACQ_Q - qs[qi]["acq"]) / 3 - RUN_PER_MONTH
    return dict(qs=qs, ss=ss, inc_rev=inc_rev, contrib=inc_rev * m, acq_saving=acq_saving, y1_net=y1_net,
                y2_rev=y2_rev, y2_contrib=y2_rev * m, y2_save=y2_save, y2_net=y2_net, payback=month)


def lk(x): return f"₹{x / 1e5:,.1f} L"


CASES = [("Plan", {}), ("Recovery 25% lower", {"rec_scale": 0.75}), ("Recovery halved", {"rec_scale": 0.5}),
         ("Bundle value 15% lower", {"value_scale": 0.85}), ("Churn 5 points higher", {"churn_add": 0.05}), ("Margin 45% instead of 55%", {"margin": 0.45})]

if __name__ == "__main__":
    Y = year(); ss = Y["ss"]; V = segment_view()
    L = []; P = L.append
    P("# Udyam Setu — business case workings (v2)\n")
    P(f"Baseline quarter: {len(d):,} leads, {a_all.shape[0]} activations ({a_all.shape[0] / len(d):.1%}), sales and partner spend {lk(BASE_ACQ_Q)} "
      f"(₹{BASE_ACQ_Q / a_all.shape[0]:,.0f} per activation), new MRR {lk(BASE_MRR)}, 6-month churn {a_all.churn.mean():.1%} by count / "
      f"{1 - BASE_RET / BASE_MRR:.1%} by revenue.\n")
    P("## Per segment, month 12\n")
    P("| Segment | Leads | Conversion today → month 12 | Activations | Advisor's quote ₹/mo (today's avg bundle) | 6-mo churn | New MRR, today → month 12 |")
    P("|---|---|---|---|---|---|---|")
    for s in SEGS:
        x = V[s]; g = d[d.segment == s]; base_mrr = g[g.act == 1].monthly_bundle_value_inr.sum()
        P(f"| {SHORT[s]} | {x['leads']:,} | {x['conv0']:.1%} → {x['conv']:.1%} | {x['acts0']} → {x['acts']:.0f} | {x['advisor_quote']:,.0f} ({x['val0']:,.0f}) | "
          f"{x['churn0']:.1%} → {x['churn']:.1%} | {lk(base_mrr)} → {lk(x['mrr'])} |")
    P(f"\nBlended month 12: conversion {ss['acts'] / len(d):.1%} ({ss['acts']:.0f} activations, of which {ss['sim']:.0f} SIM-only), new MRR {lk(ss['mrr'])} "
      f"(today {lk(BASE_MRR)}), 6-month churn {ss['churn_cnt']:.1%} by count / {ss['churn_rev']:.1%} by revenue.\n")
    P("## Cost per activation, month 12 (one quarter)\n")
    run_q = RUN_PER_MONTH * 3
    allin = ss["acq"] + run_q
    P("| Item | ₹ per quarter |"); P("|---|---|")
    P(f"| Field team (fixed, redeployed to factories and chains) | {lk(FIELD_FIXED_Q)} |")
    P(f"| Partner payouts (activation + month-6 retention) | {lk(ss['partner'])} (today {lk(TODAY_PARTNER_Q)}) |")
    P(f"| Setu points | {lk(ss['setu'])} |")
    P(f"| Digital journey variable cost | {lk(ss['var'])} |")
    P(f"| Free AirFiber units | {lk(ss['cpe'])} |")
    P(f"| Programme run cost | {lk(run_q)} |")
    P(f"| **All-in total** | **{lk(allin)}** → **₹{allin / ss['acts']:,.0f} per activation** (today ₹{BASE_ACQ_Q / a_all.shape[0]:,.0f}) |")
    P("\n## Years 1 and 2 (ramp 25 / 55 / 85 / 100% by quarter)\n")
    P("| ₹ crore, incremental vs today | Year 1 | Year 2 |"); P("|---|---|---|")
    P(f"| Revenue, after 6-month churn | {Y['inc_rev'] / 1e7:.2f} | {Y['y2_rev'] / 1e7:.2f} |")
    P(f"| Contribution at {GROSS_MARGIN:.0%} | {Y['contrib'] / 1e7:.2f} | {Y['y2_contrib'] / 1e7:.2f} |")
    P(f"| Acquisition cost saved (field team unchanged; net of partner pay, free AirFiber, journey cost) | {Y['acq_saving'] / 1e7:.2f} | {Y['y2_save'] / 1e7:.2f} |")
    P(f"| Build ₹1.20 Cr once; run ₹6 L a month | {-(BUILD_ONE_TIME + RUN_PER_MONTH * 12) / 1e7:.2f} | {-(RUN_PER_MONTH * 12) / 1e7:.2f} |")
    P(f"| **Net** | **{Y['y1_net'] / 1e7:+.2f}** | **{Y['y2_net'] / 1e7:+.2f}** |")
    P(f"\nPayback on the build: month {Y['payback']}.\n")
    P("## Sensitivity\n")
    P("| Case | Conversion | Year-1 net ₹ Cr | Year-2 net ₹ Cr | Payback |"); P("|---|---|---|---|---|")
    for name, kw in CASES:
        o = year(**kw)
        P(f"| {name} | {o['ss']['acts'] / len(d):.1%} | {o['y1_net'] / 1e7:+.2f} | {o['y2_net'] / 1e7:+.2f} | month {o['payback']} |")
    P("\n## Leak recovery assumptions\n")
    P("| Leak | Lost leads | Share recovered | Continues from |"); P("|---|---|---|---|")
    for reason, (r, st) in RECOVERY.items():
        P(f"| {reason} | {(d.drop_reason == reason).sum()} | {r:.0%} | {st} |")
    P(f"| Not touched: {', '.join(NOT_FIXABLE)} | {d.drop_reason.isin(NOT_FIXABLE).sum()} | 0% | — |")
    P(f"\nChurn factor (customers with ≤ 2 chase calls vs all): {CHURN_FACTOR:.2f}. Margin benchmark: Airtel India EBITDA margin 60.1% (Q1 FY27).")
    out = "\n".join(L)
    (ROOT / "docs" / "business_case.md").write_text(out, encoding="utf-8")
    print(out)
