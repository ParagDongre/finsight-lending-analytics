"""Inject KNOWN data-quality defects into the clean synthetic extracts.

Why: a pipeline that never meets bad data proves nothing. Every defect injected here is counted in
`data/raw/_injection_manifest.json` so tests can assert that the ETL detected at least that many.

Output frames are all-string (what a CSV extract from a source system looks like).
Defect sets are disjoint per table so counts are unambiguous.
"""
from __future__ import annotations

from io import StringIO

import numpy as np
import pandas as pd


def _to_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Round-trip through CSV so everything is a string, missing = NaN (like a real extract)."""
    return pd.read_csv(StringIO(df.to_csv(index=False)), dtype=str, keep_default_na=False, na_values=[""])


class _Picker:
    def __init__(self, n: int, rng: np.random.Generator):
        self.n, self.rng, self.used = n, rng, set()

    def pick(self, frac: float | None = None, count: int | None = None) -> np.ndarray:
        k = count if count is not None else max(1, int(round(self.n * frac)))
        pool = np.array([i for i in range(self.n) if i not in self.used])
        chosen = self.rng.choice(pool, size=min(k, len(pool)), replace=False)
        self.used.update(int(i) for i in chosen)
        return chosen


def inject_defects(clean: dict[str, pd.DataFrame], rng: np.random.Generator, snapshot):
    raw = {k: _to_raw(v) for k, v in clean.items()}
    m: dict[str, int] = {}

    # ---------------- customers ----------------
    c = raw["customers"]
    pk = _Picker(len(c), rng)
    i = pk.pick(0.015); c.loc[c.index[i], "employment_type"] = np.nan; m["C05_employment_missing"] = len(i)
    i = pk.pick(0.020)
    c.loc[c.index[i], "employment_type"] = c.loc[c.index[i], "employment_type"].map(lambda s: f"  {str(s).upper()} ")
    m["C06_employment_nonstandard"] = len(i)
    i = pk.pick(0.010); c.loc[c.index[i], "age"] = np.nan; m["C03_age_missing"] = len(i)
    i = pk.pick(0.003); c.loc[c.index[i], "age"] = rng.choice(["7", "15", "150", "-4"], size=len(i)); m["C04_age_out_of_range"] = len(i)
    i = pk.pick(0.002); c.loc[c.index[i], "signup_date"] = "2024-13-45"; m["C08_signup_date_invalid"] = len(i)
    i = pk.pick(0.005)
    dup = c.iloc[i].copy()
    m["C01_duplicate_pk"] = len(i)
    raw["customers"] = pd.concat([c, dup], ignore_index=True)

    # ---------------- profiles ----------------
    p = raw["customer_financial_profiles"]
    pk = _Picker(len(p), rng)
    i = pk.pick(0.012); p.loc[p.index[i], "monthly_income"] = np.nan; m["P03_income_missing"] = len(i)
    i = pk.pick(0.001); p.loc[p.index[i], "monthly_income"] = "-25000"; m["P04_income_invalid"] = len(i)
    i = pk.pick(0.010); p.loc[p.index[i], "credit_score"] = np.nan; m["P05a_credit_score_missing"] = len(i)
    i = pk.pick(0.002); p.loc[p.index[i], "credit_score"] = rng.choice(["0", "1200", "-1"], size=len(i)); m["P05_credit_score_out_of_range"] = len(i)
    i = pk.pick(0.003)
    dup = p.iloc[i].copy(); m["P01_duplicate_pk"] = len(i)
    raw["customer_financial_profiles"] = pd.concat([p, dup], ignore_index=True)

    # ---------------- loans ----------------
    l = raw["loans"]
    pk = _Picker(len(l), rng)
    i = pk.pick(0.0015); l.loc[l.index[i], "loan_amount"] = (-l.loc[l.index[i], "loan_amount"].astype(float)).astype(str); m["L04_amount_invalid"] = len(i)
    i = pk.pick(0.0010); l.loc[l.index[i], "interest_rate"] = rng.choice(["0", "120"], size=len(i)); m["L05_rate_out_of_range"] = len(i)
    i = pk.pick(0.0005); l.loc[l.index[i], "tenure_months"] = rng.choice(["0", "-12"], size=len(i)); m["L06_tenure_invalid"] = len(i)
    i = pk.pick(0.0010); l.loc[l.index[i], "disbursement_date"] = "2024-02-30"; m["L07_disbursement_date_invalid"] = len(i)
    i = pk.pick(0.0010); l.loc[l.index[i], "disbursement_date"] = "2027-01-15"; m["L08_disbursement_date_in_future"] = len(i)
    i = pk.pick(0.0010); l.loc[l.index[i], "customer_id"] = [f"C9{n:05d}" for n in range(len(i))]; m["L02_customer_orphan"] = len(i)
    i = pk.pick(0.0010)
    m["L11_status_inconsistent"] = 0
    for ix in i:   # mark ACTIVE/DEFAULTED loans as CLOSED while still owing money
        if l.at[l.index[ix], "loan_status"] != "CLOSED" and float(l.at[l.index[ix], "outstanding_balance"]) > 1:
            l.at[l.index[ix], "loan_status"] = "CLOSED"; m["L11_status_inconsistent"] += 1
    i = pk.pick(0.003)
    dup = l.iloc[i].copy(); m["L01_duplicate_pk"] = len(i)
    raw["loans"] = pd.concat([l, dup], ignore_index=True)

    # ---------------- repayments ----------------
    r = raw["repayments"]
    pk = _Picker(len(r), rng)
    i = pk.pick(0.0010); r.loc[r.index[i], "paid_amount"] = "-1500.00"; m["R03_amount_invalid"] = len(i)
    paid_rows = np.array([ix for ix in range(len(r)) if r.at[r.index[ix], "repayment_status"] == "PAID_ON_TIME"])
    j = rng.choice(paid_rows, size=max(1, int(0.0015 * len(r))), replace=False)
    j = np.array([x for x in j if x not in pk.used]); pk.used.update(int(x) for x in j)
    r.loc[r.index[j], "paid_date"] = np.nan; m["R05_paid_amount_without_date"] = len(j)
    unpaid_rows = np.array([ix for ix in range(len(r)) if r.at[r.index[ix], "repayment_status"] == "UNPAID" and ix not in pk.used])
    j = rng.choice(unpaid_rows, size=max(1, int(0.0010 * len(r))), replace=False); pk.used.update(int(x) for x in j)
    r.loc[r.index[j], "paid_amount"] = "2500.00"; m["R06_status_amount_mismatch"] = len(j)
    i = pk.pick(0.0005); r.loc[r.index[i], "dpd"] = "-5"; m["R11_dpd_inconsistent"] = len(i)
    i = pk.pick(0.0005); r.loc[r.index[i], "paid_amount"] = (r.loc[r.index[i], "due_amount"].astype(float) * 3).round(2).astype(str); m["R10_overpayment"] = len(i)
    i = pk.pick(0.0010); r.loc[r.index[i], "loan_id"] = [f"L9{n:05d}" for n in range(len(i))]; m["R02_loan_orphan"] = len(i)
    i = pk.pick(0.0010)
    for ix in i:
        r.at[r.index[ix], "due_date"] = "2023-01-01"      # before any disbursement
    m["R08_due_before_disbursement"] = len(i)
    i = pk.pick(0.0020)
    dup = r.iloc[i].copy(); m["R01_duplicate_pk"] = len(i)
    raw["repayments"] = pd.concat([r, dup], ignore_index=True)

    # ---------------- collections ----------------
    k = raw["collections"]
    pk = _Picker(len(k), rng)
    i = pk.pick(0.0010); k.loc[k.index[i], "amount_recovered"] = "-100.00"; m["K03_amount_invalid"] = len(i)
    i = pk.pick(0.0010); k.loc[k.index[i], "amount_recovered"] = (k.loc[k.index[i], "amount_due"].astype(float) * 2).round(2).astype(str); m["K04_recovered_exceeds_due"] = len(i)
    i = pk.pick(0.0010); k.loc[k.index[i], "loan_id"] = [f"L9{n:05d}" for n in range(len(i))]; m["K02_loan_orphan"] = len(i)
    i = pk.pick(0.0010); k.loc[k.index[i], "channel"] = "CARRIER_PIGEON"; m["K06_domain_invalid"] = len(i)
    i = pk.pick(0.0020)
    dup = k.iloc[i].copy(); m["K01_duplicate_pk"] = len(i)
    raw["collections"] = pd.concat([k, dup], ignore_index=True)

    return raw, m
