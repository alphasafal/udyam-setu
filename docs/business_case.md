# Udyam Setu — business case workings

Baseline quarter: 5,000 leads, 368 activations (7.4%), acquisition spend ₹55.4 L, cost per activation ₹15,053, new MRR ₹45.4 L, 6-month churn 15.2%.

## Segment baseline → month-12 target

| Segment | Leads/qtr | Conv. today → target | Avg bundle ₹/mo | 6-mo churn today → target |
|---|---|---|---|---|
| Micro | 2,709 | 4.1% → 9% | 2,505 | 22.7% → 15% |
| Prof. offices | 1,247 | 11.1% → 20% | 6,796 | 13.8% → 9% |
| Multi-site | 755 | 11.0% → 16% | 31,233 | 10.8% → 7% |
| Manufacturers | 289 | 12.8% → 14% | 19,980 | 8.1% → 6% |

Blended month-12: conversion 13.1%, activations 654/qtr, revenue-weighted 6-mo churn 8.1%, new MRR ₹68.9 L/qtr (avg bundle ₹10,523), acquisition + journey cost ₹36.3 L/qtr (₹5,549 per activation including the unchanged field team; variable part ₹901).

## Variable cost stack (₹)

- per lead: WhatsApp Business conversations (≈6 per lead): 5.4
- per lead: LLM advisor (≈4k tokens in/out per lead, incl. retries): 4.0
- per KYC attempt: GSTIN + Udyam lookups (via GSP/API aggregator): 6.0
- per KYC attempt: OCR + document checks (cloud compute): 2.0
- per KYC attempt: DigiLocker fetch (when used): 5.0
- per activation: Aadhaar eSign (OTP) via ESP: 25.0
- per activation: Human verification of held/asked cases (≈25% of KYCs, 8 min): 40.0
- partner assist ₹1,500 + ₹1,000 at month 6; Setu point ₹300 (half at activation, half at month 3); field team (₹30.4 L/qtr today) kept as a fixed cost and redeployed to manufacturers and multi-site

Digital journey variable cost: ₹154 per activation.

## Year 1 (ramp 25% / 55% / 85% / 100% of uplift by quarter)

| | ₹ |
|---|---|
| Incremental revenue, churn-adjusted | ₹2.75 Cr |
| Incremental contribution @ 55% margin | ₹1.51 Cr |
| Variable acquisition cost saved vs today (partner commissions, per-lead ops; field team unchanged) | ₹0.52 Cr |
| Programme cost (build ₹1.20 Cr + run ₹6.0 L/month) | −₹1.92 Cr |
| **Year-1 net** | **₹0.11 Cr** |
| Year-2 incremental revenue / net (no new build) | ₹12.86 Cr / **₹7.12 Cr** |

Payback on the build: month 12. Run-rate after ramp: ₹11.13 Cr incremental churn-adjusted ARR added per year, plus ₹76.3 L a year lower acquisition spend.

## Sensitivity (blended month-12 conversion)

| Blended conversion | Activations/qtr | Year-1 net | Year-2 net | Payback | Run-rate incremental ARR |
|---|---|---|---|---|---|
| 10.0% | 500 | ₹-0.62 Cr | ₹3.65 Cr | month 15 | ₹5.60 Cr |
| 12.0% | 600 | ₹-0.15 Cr | ₹5.89 Cr | month 13 | ₹9.18 Cr |
| 13.5% | 675 | ₹0.21 Cr | ₹7.58 Cr | month 11 | ₹11.86 Cr |

In the weakest case (10%) the build pays back in month 15 and Year 2 still nets ₹3.65 Cr.
