"""Udyam Setu business case — every figure on the deck's business-case slide comes from here.

Run:  python docs/business_case.py          (prints the tables, writes docs/business_case.md)

Baseline = the Apr–Jun 2026 quarter in data/smb_leads.csv (5,000 leads).
Everything marked ASSUMPTION is a judgement call, stated so a reviewer can change it.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
d = pd.read_csv(ROOT / "data" / "smb_leads.csv")
d["act"] = (d.outcome == "Activated").astype(int)
d["churn"] = (d.churned_within_6_months == "Y").astype(int)

SEGS = ["Micro retail & services", "Professional offices", "Small multi-site businesses", "Small manufacturers"]
SHORT = {"Micro retail & services": "Micro", "Professional offices": "Prof. offices", "Small multi-site businesses": "Multi-site", "Small manufacturers": "Manufacturers"}

# ---------------------------------------------------------------- baseline
base = {}
for s in SEGS:
    x = d[d.segment == s]
    a = x[x.act == 1]
    base[s] = dict(leads=len(x), conv=a.shape[0] / len(x), acts=a.shape[0], bundle=a.monthly_bundle_value_inr.mean(),
                   churn6=a.churn.mean(), spend=x.acquisition_cost_inr.sum(),
                   var_spend=x.loc[x.lead_source != "Field sales", "acquisition_cost_inr"].sum())
# Field-sales cost is treated as FIXED (salaried team): it is redeployed to manufacturers and multi-site, not cut.
FIELD_FIXED_Q = d.loc[d.lead_source == "Field sales", "acquisition_cost_inr"].sum()
B_LEADS = len(d); B_ACTS = int(d.act.sum()); B_SPEND = d.acquisition_cost_inr.sum()
B_MRR = d.loc[d.act == 1, "monthly_bundle_value_inr"].sum()
B_CHURN = d.loc[d.act == 1, "churn"].mean()

# ---------------------------------------------------------------- targets (month 12, steady state)
# ASSUMPTION: conversion lift per segment. Rationale per segment:
#  micro  4.1% → 9%   : 1,124 never-reached + 827 visit leaks are mostly micro; self-serve removes both
#  prof  11.1% → 20%  : quote leak (799) and paperwork leak (273) close; GSTIN holders already convert 9.6%
#  multi 11.0% → 16%  : partner-assisted; installation slips (98) and quote delays remain partly human
#  mfg   12.8% → 14%  : stays field-led; only pre-qualification and survey booking improve
TARGET_CONV = {"Micro retail & services": 0.09, "Professional offices": 0.20, "Small multi-site businesses": 0.16, "Small manufacturers": 0.14}
# ASSUMPTION: 6-month churn targets. Data: churn is 6% for customers with 1 chase call, 28% with 5;
# NPS falls with days-to-activate. The tracker removes chase calls and the advisor stops off-target selling.
TARGET_CHURN = {"Micro retail & services": 0.15, "Professional offices": 0.09, "Small multi-site businesses": 0.07, "Small manufacturers": 0.06}

# ---------------------------------------------------------------- unit costs (₹)
# ASSUMPTION, per lead that enters the digital journey (all leads):
COST_PER_LEAD = {
    "WhatsApp Business conversations (≈6 per lead)": 6 * 0.9,
    "LLM advisor (≈4k tokens in/out per lead, incl. retries)": 4.0,
}
# per KYC attempt (≈ quote-accepted leads; 1.3 attempts per activation)
COST_PER_KYC = {"GSTIN + Udyam lookups (via GSP/API aggregator)": 6.0, "OCR + document checks (cloud compute)": 2.0, "DigiLocker fetch (when used)": 5.0}
# per activation
COST_PER_ACT = {"Aadhaar eSign (OTP) via ESP": 25.0, "Human verification of held/asked cases (≈25% of KYCs, 8 min)": 40.0}
# ASSUMPTION: assisted channel costs per activation, replacing today's per-stage field/partner spend
PARTNER_ASSIST_FEE = 1500     # flat fee per assisted activation (multi-site, stalled high-propensity leads)
PARTNER_RETENTION = 1000      # paid only if the customer is still active at month 6
SETU_POINT_FEE = 300          # ₹150 at activation + ₹150 if active at month 3
FIELD_COST_MFG = None  # manufacturers stay field-led; covered by the fixed field team
# share of activations that need a partner assist, per segment (ASSUMPTION)
ASSIST_SHARE = {"Micro retail & services": 0.10, "Professional offices": 0.20, "Small multi-site businesses": 1.0, "Small manufacturers": 0.0}
SETU_SHARE = {"Micro retail & services": 0.25, "Professional offices": 0.0, "Small multi-site businesses": 0.0, "Small manufacturers": 0.0}
# marketing to generate the same 5,000 leads a quarter is unchanged and excluded on both sides.

# ---------------------------------------------------------------- programme costs (₹)
BUILD_ONE_TIME = 1.2e7   # ASSUMPTION: 8-person squad × 6 months × ₹2.5L loaded = ₹1.2 Cr (advisor, KYC, tracker, partner app, integrations)
RUN_PER_MONTH = 6e5      # ASSUMPTION: cloud, LLM eval, model monitoring, 2 FTE support/ops
GROSS_MARGIN = 0.55      # ASSUMPTION: contribution margin on bundle revenue after network, CPE amortisation, third-party licences

LEADS_PER_Q = 5000
RAMP = [0.25, 0.55, 0.85, 1.0]   # share of the conversion uplift achieved in quarters 1–4 (pilot → scale)


def quarter(lift_share: float, conv_override: dict | None = None):
    """One quarter of 5,000 leads at a given share of the target uplift."""
    out = {"acts": 0.0, "mrr": 0.0, "acq": 0.0, "var": 0.0, "retained_mrr": 0.0, "by_seg": {}}
    for s in SEGS:
        b = base[s]
        tgt = (conv_override or TARGET_CONV)[s]
        conv = b["conv"] + (tgt - b["conv"]) * lift_share
        churn = b["churn6"] + (TARGET_CHURN[s] - b["churn6"]) * lift_share
        leads = b["leads"] * LEADS_PER_Q / B_LEADS
        acts = leads * conv
        mrr = acts * b["bundle"]
        # NEW variable cost: digital journey + partner assists + Setu points (field team is fixed, below)
        var = leads * sum(COST_PER_LEAD.values()) + acts * 1.3 * sum(COST_PER_KYC.values()) + acts * sum(COST_PER_ACT.values())
        assist = acts * ASSIST_SHARE[s] * (PARTNER_ASSIST_FEE + PARTNER_RETENTION * (1 - churn)) + acts * SETU_SHARE[s] * SETU_POINT_FEE
        today_var = b["var_spend"] * LEADS_PER_Q / B_LEADS
        acq_total = today_var * (1 - lift_share) + (var + assist) * lift_share
        out["acts"] += acts; out["mrr"] += mrr; out["acq"] += acq_total; out["var"] += var * lift_share
        out["retained_mrr"] += mrr * (1 - churn)
        out["by_seg"][s] = dict(conv=conv, acts=acts, mrr=mrr, churn=churn)
    out["acq_var"] = out["acq"]
    out["acq"] = out["acq_var"] + FIELD_FIXED_Q
    return out


def year(conv_override=None):
    qs = [quarter(r, conv_override) for r in RAMP]
    base_q = quarter(0.0)
    rows = []
    cum_mrr_base = cum_mrr_new = 0.0
    rev_new = rev_base = 0.0
    for i, q in enumerate(qs):
        # each quarter's cohort bills for the remaining months of the year; assume mid-quarter activation
        months_left = 12 - (3 * i + 1.5)
        rev_new += q["retained_mrr"] * months_left
        rev_base += base_q["retained_mrr"] * months_left
        rows.append(q)
    acq_new = sum(q["acq"] for q in qs); acq_base = base_q["acq"] * 4
    inc_rev = rev_new - rev_base
    inc_contrib = inc_rev * GROSS_MARGIN
    acq_saving = acq_base - acq_new
    prog_cost = BUILD_ONE_TIME + RUN_PER_MONTH * 12
    y1_net = inc_contrib + acq_saving - prog_cost
    # run-rate after ramp: one steady-state quarter vs baseline, annualised
    ss = qs[-1]
    inc_arr_retained = (ss["retained_mrr"] - base_q["retained_mrr"]) * 4 * 12  # 4 cohorts a year, 12 months
    inc_contrib_ss_month = (ss["retained_mrr"] - base_q["retained_mrr"]) * GROSS_MARGIN  # new monthly contribution added per quarter cohort
    acq_saving_ss_q = base_q["acq"] - ss["acq"]
    # payback: months until cumulative (incremental contribution + acquisition saving - run) covers build
    cum, month, stacked_contrib = -BUILD_ONE_TIME, 0, 0.0
    while cum < 0 and month < 60:
        month += 1
        qi = min((month - 1) // 3, 3)
        if (month - 1) % 3 == 1:       # cohort lands mid-quarter
            stacked_contrib += (rows[qi]["retained_mrr"] - base_q["retained_mrr"]) * GROSS_MARGIN
        cum += stacked_contrib + (base_q["acq"] - rows[qi]["acq"]) / 3 - RUN_PER_MONTH
    # Year 2: year-1 cohorts bill all 12 months; four steady-state cohorts join; run cost continues
    y1_cohorts = sum(q["retained_mrr"] for q in rows) - base_q["retained_mrr"] * 4
    y2_rev = y1_cohorts * 12 + (ss["retained_mrr"] - base_q["retained_mrr"]) * sum(12 - (3 * i + 1.5) for i in range(4))
    y2_net = y2_rev * GROSS_MARGIN + (base_q["acq"] - ss["acq"]) * 4 - RUN_PER_MONTH * 12
    return dict(quarters=rows, base_q=base_q, y2_rev=y2_rev, y2_net=y2_net, inc_rev=inc_rev, inc_contrib=inc_contrib, acq_saving=acq_saving, prog_cost=prog_cost,
                y1_net=y1_net, inc_arr_retained=inc_arr_retained, payback_months=month, ss=ss,
                acq_saving_ss_q=acq_saving_ss_q, inc_contrib_ss_month=inc_contrib_ss_month)


def cr(x): return f"₹{x / 1e7:,.2f} Cr"
def lk(x): return f"₹{x / 1e5:,.1f} L"


def blended(conv_scale):
    """Scale every segment's uplift so the blended month-12 conversion hits roughly conv_scale."""
    lo = {s: base[s]["conv"] for s in SEGS}
    full = sum(base[s]["leads"] * TARGET_CONV[s] for s in SEGS) / B_LEADS
    k = (conv_scale - B_ACTS / B_LEADS) / (full - B_ACTS / B_LEADS)
    return {s: lo[s] + (TARGET_CONV[s] - lo[s]) * k for s in SEGS}


if __name__ == "__main__":
    Y = year()
    ss, bq = Y["ss"], Y["base_q"]
    lines = []
    P = lines.append
    P("# Udyam Setu — business case workings\n")
    P(f"Baseline quarter: {B_LEADS:,} leads, {B_ACTS} activations ({B_ACTS / B_LEADS:.1%}), acquisition spend {lk(B_SPEND)}, "
      f"cost per activation ₹{B_SPEND / B_ACTS:,.0f}, new MRR {lk(B_MRR)}, 6-month churn {B_CHURN:.1%}.\n")
    P("## Segment baseline → month-12 target\n")
    P("| Segment | Leads/qtr | Conv. today → target | Avg bundle ₹/mo | 6-mo churn today → target |")
    P("|---|---|---|---|---|")
    for s in SEGS:
        b = base[s]
        P(f"| {SHORT[s]} | {b['leads']:,} | {b['conv']:.1%} → {TARGET_CONV[s]:.0%} | {b['bundle']:,.0f} | {b['churn6']:.1%} → {TARGET_CHURN[s]:.0%} |")
    conv_ss = ss["acts"] / LEADS_PER_Q
    churn_ss = 1 - ss["retained_mrr"] / ss["mrr"]
    P(f"\nBlended month-12: conversion {conv_ss:.1%}, activations {ss['acts']:.0f}/qtr, revenue-weighted 6-mo churn {churn_ss:.1%}, "
      f"new MRR {lk(ss['mrr'])}/qtr (avg bundle ₹{ss['mrr'] / ss['acts']:,.0f}), acquisition + journey cost {lk(ss['acq'])}/qtr "
      f"(₹{ss['acq'] / ss['acts']:,.0f} per activation including the unchanged field team; variable part ₹{ss['acq_var'] / ss['acts']:,.0f}).\n")
    P("## Variable cost stack (₹)\n")
    for k, v in {**COST_PER_LEAD}.items(): P(f"- per lead: {k}: {v:.1f}")
    for k, v in COST_PER_KYC.items(): P(f"- per KYC attempt: {k}: {v:.1f}")
    for k, v in COST_PER_ACT.items(): P(f"- per activation: {k}: {v:.1f}")
    P(f"- partner assist ₹{PARTNER_ASSIST_FEE:,} + ₹{PARTNER_RETENTION:,} at month 6; Setu point ₹{SETU_POINT_FEE} (half at activation, half at month 3); field team (₹{FIELD_FIXED_Q / 1e5:,.1f} L/qtr today) kept as a fixed cost and redeployed to manufacturers and multi-site")
    P(f"\nDigital journey variable cost: ₹{ss['var'] / ss['acts']:,.0f} per activation.\n")
    P("## Year 1 (ramp 25% / 55% / 85% / 100% of uplift by quarter)\n")
    P("| | ₹ |")
    P("|---|---|")
    P(f"| Incremental revenue, churn-adjusted | {cr(Y['inc_rev'])} |")
    P(f"| Incremental contribution @ {GROSS_MARGIN:.0%} margin | {cr(Y['inc_contrib'])} |")
    P(f"| Variable acquisition cost saved vs today (partner commissions, per-lead ops; field team unchanged) | {cr(Y['acq_saving'])} |")
    P(f"| Programme cost (build {cr(BUILD_ONE_TIME)} + run {lk(RUN_PER_MONTH)}/month) | −{cr(Y['prog_cost'])} |")
    P(f"| **Year-1 net** | **{cr(Y['y1_net'])}** |")
    P(f"| Year-2 incremental revenue / net (no new build) | {cr(Y['y2_rev'])} / **{cr(Y['y2_net'])}** |")
    P(f"\nPayback on the build: month {Y['payback_months']}. Run-rate after ramp: {cr(Y['inc_arr_retained'])} incremental churn-adjusted ARR added per year, "
      f"plus {lk(Y['acq_saving_ss_q'] * 4)} a year lower acquisition spend.\n")
    P("## Sensitivity (blended month-12 conversion)\n")
    P("| Blended conversion | Activations/qtr | Year-1 net | Year-2 net | Payback | Run-rate incremental ARR |")
    P("|---|---|---|---|---|---|")
    sens = []
    for c in (0.10, 0.12, 0.135):
        o = year(blended(c))
        sens.append((c, o))
        P(f"| {c:.1%} | {o['ss']['acts']:.0f} | {cr(o['y1_net'])} | {cr(o['y2_net'])} | month {o['payback_months']} | {cr(o['inc_arr_retained'])} |")
    worst = sens[0][1]
    P(f"\nIn the weakest case ({sens[0][0]:.0%}) the build pays back in month {worst['payback_months']} and Year 2 still nets {cr(worst['y2_net'])}.\n")
    out = "\n".join(lines)
    (ROOT / "docs" / "business_case.md").write_text(out, encoding="utf-8")
    print(out)
