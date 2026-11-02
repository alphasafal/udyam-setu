"""Udyam Setu business case. Every figure on the deck's metrics and business-case slides comes from here.

Run:  python docs/business_case.py          (prints the tables, writes docs/business_case.md)

Method:
  PRICE   What the advisor's rule engine would quote each of the 5,000 leads in data/smb_leads.csv.
  MARGIN  Per product line (connectivity, communication, resold software, security, devices), applied to each
          bundle's actual product mix, for today's bundles and for the advisor's quotes alike.
  VOLUME  For each fixable leak, a stated share of the lost leads is recovered and continues from the next stage
          at TODAY's downstream conversion for that segment. Leaks the journey cannot fix are untouched.
          Factories get half the effect (they stay field-led). "Only wanted a mobile plan" leads are sold a SIM
          and reported separately from bundle activations.
  CHURN   During the first 6 months it falls toward the rate of today's customers who chased at most twice
          (an assumption to test in the pilot, not a proven cause); after month 6 every cohort loses 1% a month.
  COST    Field team kept as a fixed cost; partners paid on activation and retention; digital journey costs;
          free AirFiber units; ₹1.2 Cr app build + ₹0.8 Cr BSS/OSS/CRM integration; ₹6 L a month to run.
  TIME    A 36-month simulation: monthly cohorts, the new journey ramping 25/55/85/100% over four quarters,
          compared with today's process over the same 36 months.
Every ASSUMPTION is a named constant.
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

# ------------------------------------------------------------------ margins by product line (ASSUMPTION)
LINE_MARGIN = {"Connectivity": 0.60, "Communication": 0.50, "Cloud & Productivity": 0.30, "Security": 0.40, "IoT & Physical": 0.35}
# Benchmark for connectivity: Airtel India reported a 60.1% EBITDA margin in Q1 FY27. Resold software and devices carry far less.


def mix_margin(items):
    """items: list of (product_id, qty). Revenue-weighted margin of the mix at catalogue minimum prices."""
    rev = sum(CATALOGUE[p].price_min * q for p, q in items)
    if not rev:
        return LINE_MARGIN["Connectivity"]
    return sum(CATALOGUE[p].price_min * q * LINE_MARGIN[CATALOGUE[p].category] for p, q in items) / rev


# ------------------------------------------------------------------ the advisor's quote for every lead
NEED_OF = {"P19": "billing", "P15": "customers", "P14": "customers", "P23": "cctv", "P16": "email", "P17": "email", "P12": "phone", "P13": "phone",
           "P09": "uptime", "P10": "central", "P18": "website", "P24": "iot", "P25": "fleet", "P20": "security", "P21": "security", "P22": "wifi"}
NET = {"Mobile hotspot": "hotspot", "Home broadband": "home", "Business broadband": "business", "Leased line": "leased", "Mixed per site": "mixed"}


def advisor_quote(r):
    needs = sorted({NEED_OF[p] for p in str(r.products_of_interest).split(";") if p in NEED_OF})
    seg = SEGCODE[r.segment]
    p = Profile(business_type="", segment=seg, employees=int(r.employee_count), sites=int(r.num_sites), city_tier=int(r.city_tier),
                has_gstin=r.has_gstin == "Y", current_internet=NET.get(r.current_internet, "none"), needs=needs)
    if seg in ("micro", "prof") and p.sites >= 3:
        p.segment = "multi"
    q = price_bundle(recommend(p)["items"])
    sel = [(l["product_id"], l["qty"]) for l in q["lines"] if l["selected"]]
    return q["monthly"], mix_margin(sel), any(pid == "P04" for pid, _ in sel)


def today_margin(bp):
    if not isinstance(bp, str):
        return float("nan")
    return mix_margin([(i.split("x")[0], int(i.split("x")[1])) for i in bp.split(";")])


qa = d.apply(lambda r: pd.Series(advisor_quote(r), index=["quote", "q_margin", "airfiber"]), axis=1)
d = pd.concat([d, qa], axis=1)
d["t_margin"] = d.bundle_products.apply(today_margin)
SIM_ONLY_VALUE = CATALOGUE["P07"].price_min * 2          # a SIM-only customer takes about two lines
SIM_MARGIN = LINE_MARGIN["Connectivity"]

# ------------------------------------------------------------------ leak recovery (ASSUMPTION)
RECOVERY = {
    "Unreachable after 3 attempts": (0.20, "Contacted"),       # instant WhatsApp/web reply instead of 3 call attempts
    "Wrong or invalid number": (0.10, "Contacted"),            # a self-serve link reaches a few; most are dead numbers
    "Owner had no time for a visit": (0.40, "Needs assessed"),  # no visit needed
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
    "Only wanted a mobile plan": (0.35, "SIM"),                   # sold exactly that, counted separately
}
NOT_FIXABLE = ["Not interested on first call", "Locked in with current provider", "Competitor offered cheaper plan", "Decided to wait"]
SEG_REACH = {"micro": 1.0, "prof": 1.0, "multi": 1.0, "mfg": 0.5}   # factories stay field-led

# ------------------------------------------------------------------ churn
a_all = d[d.act == 1]
CHURN_FACTOR = a_all.loc[a_all.customer_follow_up_calls <= 2, "churn"].mean() / a_all.churn.mean()   # ≈ 0.78
LATE_CHURN_MONTHLY = 0.01      # ASSUMPTION: after month 6, 1% of every cohort leaves each month

# ------------------------------------------------------------------ costs (₹)
COST_PER_LEAD = {"WhatsApp Business conversations (≈6 per lead)": 6 * 0.9, "LLM advisor (≈4k tokens per lead, incl. retries)": 4.0}
COST_PER_KYC = {"GSTIN + Udyam lookups via an API aggregator": 6.0, "OCR + document checks (cloud compute)": 2.0, "DigiLocker fetch when used": 5.0}
COST_PER_ACT = {"Aadhaar eSign (OTP) via a licensed ESP": 25.0, "Human review of held/asked cases (≈25% of KYCs, 8 min)": 40.0}
AIRFIBER_SUBSIDY = 2500        # ASSUMPTION: AirFiber unit given free (catalogue setup fee ₹0); other products recover equipment via setup fees
PARTNER_FEE = {"micro": (1500, 1000), "prof": (3000, 2000), "multi": (6000, 4000), "mfg": (0, 0)}   # on activation, + at month 6 if active
ASSIST_SHARE = {"micro": 0.10, "prof": 0.25, "multi": 1.0, "mfg": 0.0}   # chains: partners lead, field sales advise on SD-WAN design
SETU_SHARE, SETU_FEE = {"micro": 0.25, "prof": 0.0, "multi": 0.0, "mfg": 0.0}, 300
FIELD_FIXED_Q = d.loc[d.lead_source == "Field sales", "acquisition_cost_inr"].sum()
TODAY_PARTNER_Q = d.loc[d.lead_source == "Channel partner", "acquisition_cost_inr"].sum()
TODAY_OTHER_VAR_Q = d.loc[~d.lead_source.isin(["Field sales", "Channel partner"]), "acquisition_cost_inr"].sum()
BUILD_APP = 1.2e7              # ASSUMPTION: 8-person squad × 6 months × ₹2.5 L loaded
BUILD_INTEGRATION = 0.8e7      # ASSUMPTION: BSS/OSS, CRM, billing and provisioning integration
BUILD = BUILD_APP + BUILD_INTEGRATION
RUN_PER_MONTH = 6e5            # ASSUMPTION: cloud, model evaluation, monitoring, 2 FTE operations
RAMP = [0.25, 0.55, 0.85, 1.0]
ANNUAL_DISCOUNT = 0.12
MONTHS = 36


def segment_view(lift, rec_scale=1.0, value_scale=1.0, churn_add=0.0, margin_scale=1.0):
    """One quarter of 5,000 leads at a given lift (0 = today's process, 1 = full new journey)."""
    out = {}
    for s in SEGS:
        g = d[d.segment == s]
        code = SEGCODE[s]
        acts0 = g.act.sum()
        p_from = {st: g[g.si >= i].act.mean() for i, st in enumerate(ORDER)}
        p_from["Activated"] = 1.0
        rec, sim = 0.0, 0.0
        for reason, (r, st) in RECOVERY.items():
            lost = (g.drop_reason == reason).sum()
            r = r * SEG_REACH[code] * rec_scale * lift
            if st == "SIM":
                sim += lost * r
            else:
                rec += lost * r * p_from[st]
        acts = acts0 + rec
        val0, adv = g[g.act == 1].monthly_bundle_value_inr.mean(), g.quote.mean()
        m0, madv = g[g.act == 1].t_margin.mean(), (g.quote * g.q_margin).sum() / g.quote.sum()
        quote = (val0 * (1 - lift) + adv * lift) * (value_scale if lift > 0 else 1.0)
        margin = (m0 * (1 - lift) + madv * lift) * (margin_scale if lift > 0 else 1.0)
        churn0 = g[g.act == 1].churn.mean()
        churn6 = min(0.95, churn0 * (1 - (1 - CHURN_FACTOR) * lift) + (churn_add if lift > 0 else 0.0))
        leads = len(g)
        all_acts = acts + sim
        var = (leads * sum(COST_PER_LEAD.values()) + all_acts * 1.3 * sum(COST_PER_KYC.values()) + all_acts * sum(COST_PER_ACT.values())) * lift
        fee, ret = PARTNER_FEE[code]
        partner = acts * ASSIST_SHARE[code] * (fee + ret * (1 - churn6)) * lift
        setu = all_acts * SETU_SHARE[code] * SETU_FEE * lift
        cpe = acts * g.airfiber.mean() * AIRFIBER_SUBSIDY * lift
        out[s] = dict(leads=leads, acts0=acts0, acts=acts, sim=sim, quote=quote, adv=adv, val0=val0, margin=margin, m0=m0, madv=madv,
                      churn0=churn0, churn6=churn6, var=var, partner=partner, setu=setu, cpe=cpe)
    return out


def quarter_cost(v, lift):
    new_var = sum(x["var"] + x["partner"] + x["setu"] + x["cpe"] for x in v.values())
    return FIELD_FIXED_Q + (TODAY_PARTNER_Q + TODAY_OTHER_VAR_Q) * (1 - lift) + new_var


def simulate(**kw):
    """36 months, monthly cohorts. Returns series for the new journey and for today's process, plus a summary."""
    views = {}

    def view(lift):
        if lift not in views:
            views[lift] = segment_view(lift, **kw) if lift > 0 else segment_view(0.0)
        return views[lift]

    def run(new: bool):
        cohorts, rows = [], []
        for m in range(1, MONTHS + 1):
            lift = RAMP[min((m - 1) // 3, 3)] if new else 0.0
            v = view(lift)
            for x in v.values():
                cohorts.append((m, x["acts"] / 3 * x["quote"], x["margin"], x["churn6"]))
                if x["sim"]:
                    cohorts.append((m, x["sim"] / 3 * SIM_ONLY_VALUE * kw.get("value_scale", 1.0), SIM_MARGIN * kw.get("margin_scale", 1.0), x["churn6"]))
            mrr = contrib = 0.0
            for (m0, base, mg, c6) in cohorts:
                age = m - m0
                h1 = 1 - (1 - c6) ** (1 / 6)
                surv = (1 - h1) ** min(age, 6) * (1 - LATE_CHURN_MONTHLY) ** max(age - 6, 0)
                mrr += base * surv
                contrib += base * surv * mg
            acq = quarter_cost(v, lift) / 3
            rows.append(dict(m=m, mrr=mrr, contrib=contrib, acq=acq))
        return rows

    new, base = run(True), run(False)
    inc = [(a["contrib"] - b["contrib"]) - (a["acq"] - b["acq"]) - RUN_PER_MONTH for a, b in zip(new, base)]
    cum, payback = -BUILD, None
    for i, x in enumerate(inc, 1):
        cum += x
        if payback is None and cum >= 0:
            payback = i
    r = (1 + ANNUAL_DISCOUNT) ** (1 / 12) - 1
    npv = -BUILD + sum(x / (1 + r) ** i for i, x in enumerate(inc, 1))
    yr = lambda k: sum(inc[12 * k:12 * (k + 1)])
    win = lambda k: zip(new[12 * k:12 * k + 12], base[12 * k:12 * k + 12])
    return dict(new=new, base=base, inc=inc, payback=payback, npv=npv, y=[yr(0) - BUILD, yr(1), yr(2)],
                inc_rev=[sum(a["mrr"] - b["mrr"] for a, b in win(k)) for k in range(3)],
                inc_contrib=[sum(a["contrib"] - b["contrib"] for a, b in win(k)) for k in range(3)],
                acq_delta=[sum(a["acq"] - b["acq"] for a, b in win(k)) for k in range(3)])


def steady(**kw):
    v = segment_view(1.0, **kw)
    bundle = sum(x["acts"] for x in v.values()); sim = sum(x["sim"] for x in v.values())
    acq = quarter_cost(v, 1.0); allin = acq + RUN_PER_MONTH * 3
    return dict(v=v, bundle=bundle, sim=sim, acq=acq, allin=allin)


CASES = [("Plan", {}), ("Recovery 25% lower", {"rec_scale": 0.75}), ("Recovery halved", {"rec_scale": 0.5}),
         ("Prices 15% lower", {"value_scale": 0.85}), ("Churn 5 points higher", {"churn_add": 0.05}), ("Margins 20% lower", {"margin_scale": 0.8}),
         ("All three at once: recovery halved, prices −15%, churn +5", {"rec_scale": 0.5, "value_scale": 0.85, "churn_add": 0.05})]


def lk(x): return f"₹{x / 1e5:,.1f} L"
def crs(x): return f"{x / 1e7:+.2f}"


def ltv_cac(st):
    v = st["v"]; out = {}
    for s in SEGS:
        x = v[s]
        h1 = 1 - (1 - x["churn6"]) ** (1 / 6)
        months = sum((1 - h1) ** min(a, 6) * (1 - LATE_CHURN_MONTHLY) ** max(a - 6, 0) for a in range(36))
        out[s] = x["quote"] * x["margin"] * months
    blended = sum(v[s]["acts"] * out[s] for s in SEGS) / st["bundle"]
    return out, blended, blended / (st["allin"] / st["bundle"])


if __name__ == "__main__":
    S = simulate(); st = steady(); v = st["v"]
    L = []; P = L.append
    acts0 = a_all.shape[0]; base_q_cost = FIELD_FIXED_Q + TODAY_PARTNER_Q + TODAY_OTHER_VAR_Q
    P("# Udyam Setu — business case workings\n")
    P(f"Today, per quarter: {len(d):,} leads, {acts0} activations ({acts0 / len(d):.1%}), sales and partner spend {lk(base_q_cost)} "
      f"(₹{base_q_cost / acts0:,.0f} per activation), new MRR {lk(a_all.monthly_bundle_value_inr.sum())}, 6-month churn {a_all.churn.mean():.1%} by count / "
      f"{(a_all.monthly_bundle_value_inr * a_all.churn).sum() / a_all.monthly_bundle_value_inr.sum():.1%} by revenue.\n")
    P("## Month 12, per segment\n")
    P("| Segment | Leads | Bundle conversion | Bundle activations (+ SIM-only) | Advisor's quote ₹/mo (today) | Margin (today) | 6-mo churn |")
    P("|---|---|---|---|---|---|---|")
    for s in SEGS:
        x = v[s]
        P(f"| {SHORT[s]} | {x['leads']:,} | {x['acts0'] / x['leads']:.1%} → {x['acts'] / x['leads']:.1%} | {x['acts0']} → {x['acts']:.0f} (+{x['sim']:.0f}) | "
          f"{x['adv']:,.0f} ({x['val0']:,.0f}) | {x['madv']:.0%} ({x['m0']:.0%}) | {x['churn0']:.1%} → {x['churn6']:.1%} |")
    P(f"\nBlended: bundle conversion {acts0 / len(d):.1%} → {st['bundle'] / len(d):.1%} ({st['bundle']:.0f} bundle activations, {st['bundle'] / acts0:.1f}× today), "
      f"plus {st['sim']:.0f} SIM-only sales a quarter.\n")
    P("## Acquisition cost, month 12 (one quarter)\n")
    P("| Item | ₹ per quarter |"); P("|---|---|")
    P(f"| Field team (kept; redeployed to factories and SD-WAN design for chains) | {lk(FIELD_FIXED_Q)} |")
    P(f"| Partner payouts (activation + month-6 retention) | {lk(sum(x['partner'] for x in v.values()))} (today {lk(TODAY_PARTNER_Q)}) |")
    P(f"| Setu points | {lk(sum(x['setu'] for x in v.values()))} |")
    P(f"| Digital journey (WhatsApp, LLM, lookups, eSign, human review) | {lk(sum(x['var'] for x in v.values()))} |")
    P(f"| Free AirFiber units | {lk(sum(x['cpe'] for x in v.values()))} |")
    P(f"| Programme run cost | {lk(RUN_PER_MONTH * 3)} |")
    P(f"| **Total** | **{lk(st['allin'])}** (today {lk(base_q_cost)}): ₹{st['allin'] / st['bundle']:,.0f} per bundle activation (today ₹{base_q_cost / acts0:,.0f}) |")
    P(f"\nTotal spend rises {st['allin'] / base_q_cost - 1:.0%}; cost per activation falls because bundle activations rise {st['bundle'] / acts0:.1f}×.\n")
    P("## Three years, incremental vs today's process (₹ crore)\n")
    P("| | Year 1 | Year 2 | Year 3 |"); P("|---|---|---|---|")
    P("| Revenue | " + " | ".join(f"{x / 1e7:.2f}" for x in S["inc_rev"]) + " |")
    P("| Contribution (margin by product line) | " + " | ".join(f"{x / 1e7:.2f}" for x in S["inc_contrib"]) + " |")
    P("| Acquisition cost saved (run cost shown below) | " + " | ".join(f"{-x / 1e7:.2f}" for x in S["acq_delta"]) + " |")
    P(f"| Build (₹1.2 Cr app + ₹0.8 Cr integration) and run (₹6 L a month) | {-(BUILD + RUN_PER_MONTH * 12) / 1e7:.2f} | {-RUN_PER_MONTH * 12 / 1e7:.2f} | {-RUN_PER_MONTH * 12 / 1e7:.2f} |")
    P("| **Net** | " + " | ".join(f"**{crs(x)}**" for x in S["y"]) + " |")
    P(f"\nPayback month {S['payback']}. 3-year NPV at {ANNUAL_DISCOUNT:.0%}: ₹{S['npv'] / 1e7:.2f} Cr.\n")
    seg_ltv, blended_ltv, ratio = ltv_cac(st)
    P(f"36-month contribution per bundle customer (LTV) ₹{blended_ltv:,.0f} vs all-in acquisition ₹{st['allin'] / st['bundle']:,.0f}: LTV/CAC {ratio:.1f}. "
      + "; ".join(f"{SHORT[s]} ₹{l:,.0f}" for s, l in seg_ltv.items()) + ".\n")
    P("## Sensitivity\n")
    P("| Case | Bundle conversion | Year 1 | Year 2 | Year 3 | Payback | 3-yr NPV |"); P("|---|---|---|---|---|---|---|")
    for name, kw in CASES:
        o = simulate(**kw); so = steady(**kw)
        P(f"| {name} | {so['bundle'] / len(d):.1%} | {crs(o['y'][0])} | {crs(o['y'][1])} | {crs(o['y'][2])} | "
          f"{'month ' + str(o['payback']) if o['payback'] else 'beyond 36 months'} | {o['npv'] / 1e7:+.2f} |")
    P("\n## Assumptions\n")
    P("| Leak | Lost leads | Share recovered | Continues from |"); P("|---|---|---|---|")
    for reason, (r, stg) in RECOVERY.items():
        P(f"| {reason} | {(d.drop_reason == reason).sum()} | {r:.0%} | {stg} |")
    P(f"| Not touched: {', '.join(NOT_FIXABLE)} | {d.drop_reason.isin(NOT_FIXABLE).sum()} | 0% | |")
    P(f"\nMargins by product line: {', '.join(f'{k} {m:.0%}' for k, m in LINE_MARGIN.items())}. Late churn {LATE_CHURN_MONTHLY:.0%} a month after month 6. "
      f"Churn factor in the first 6 months {CHURN_FACTOR:.2f} (customers with ≤ 2 chase calls vs all; a correlation, to be tested in the pilot).")
    out = "\n".join(L)
    (ROOT / "docs" / "business_case.md").write_text(out, encoding="utf-8")
    print(out)
