"""Lead propensity score: logistic regression on fields known at lead creation.

Trained at startup from data/smb_leads.csv (5,000 synthetic leads). Cross-validated
AUC ≈ 0.71; the top quintile activates at ~15%, the bottom at ~2%.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

DATA = Path(__file__).resolve().parent.parent / "data"
CAT = ["lead_source", "segment", "city_tier", "preferred_language", "has_gstin", "has_udyam",
       "current_internet", "current_provider", "contact_role", "annual_turnover_band"]
NUM = ["employee_count", "num_sites", "monthly_telecom_spend_inr"]


class Propensity:
    def __init__(self):
        d = pd.read_csv(DATA / "smb_leads.csv")
        d["current_internet"] = d.current_internet.fillna("None")
        d["current_provider"] = d.current_provider.fillna("None")
        d["city_tier"] = d.city_tier.astype(str)
        y = (d.outcome == "Activated").astype(int)
        X = d[CAT + NUM]
        pre = ColumnTransformer([("c", OneHotEncoder(handle_unknown="ignore"), CAT), ("n", StandardScaler(), NUM)])
        self.pipe = Pipeline([("p", pre), ("m", LogisticRegression(max_iter=2000, C=0.5))])
        cv = cross_val_predict(self.pipe, X, y, cv=5, method="predict_proba")[:, 1]
        self.cv_auc = float(roc_auc_score(y, cv))
        self.pipe.fit(X, y)
        d["score"] = self.pipe.predict_proba(X)[:, 1]
        self.quintile_edges = list(d.score.quantile([0.2, 0.4, 0.6, 0.8]))
        self.leads = d
        names = self.pipe["p"].get_feature_names_out()
        self.coefs = sorted(zip(names, self.pipe["m"].coef_[0]), key=lambda t: -abs(t[1]))

    def quintile(self, score: float) -> int:
        return 1 + sum(score > e for e in self.quintile_edges)

    def score_lead(self, lead: Dict) -> dict:
        row = {k: lead.get(k) for k in CAT + NUM}
        row["city_tier"] = str(row.get("city_tier") or "2")
        for k in NUM:
            row[k] = float(row.get(k) or 0)
        for k in CAT:
            row[k] = row.get(k) or "None"
        X = pd.DataFrame([row])
        s = float(self.pipe.predict_proba(X)[0, 1])
        q = self.quintile(s)
        return {"score": round(s, 3), "quintile": q,
                "route": "partner call within 24 h if stalled" if q >= 4 else ("digital nurture only" if q <= 2 else "digital, partner after 72 h"),
                "drivers": self.explain(row)}

    def explain(self, row: Dict) -> List[str]:
        out = []
        for name, c in self.coefs:
            kind, _, rest = name.partition("__")
            if kind == "c":
                col, _, val = rest.partition("_")
                if str(row.get(col)) == val and abs(c) > 0.15:
                    out.append(f"{col.replace('_', ' ')} = {val} ({'+' if c > 0 else '−'})")
            if len(out) >= 4:
                break
        return out

    def stalled_queue(self, n: int = 25) -> List[dict]:
        """Back-office view: open leads the advisor could not close, highest score first."""
        d = self.leads
        open_ = d[(d.outcome == "Dropped") & (d.stage_reached.isin(["Needs assessed", "Quote accepted", "KYC complete"]))].copy()
        open_ = open_.sort_values("score", ascending=False).head(n)
        cols = ["lead_id", "business_name", "segment", "city", "lead_source", "stage_reached", "drop_reason", "preferred_language", "has_gstin", "monthly_telecom_spend_inr", "score"]
        rows = open_[cols].to_dict("records")
        for r in rows:
            r["quintile"] = self.quintile(r["score"])
            r["score"] = round(float(r["score"]), 3)
        return rows
