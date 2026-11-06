"""KPI definitions used by the Streamlit app. Mirrors database/queries/business_queries.sql and powerbi/dax_measures.md.

Definitions (keep identical everywhere):
  * Default            : loan_status == 'DEFAULTED' (>= 90 days past due at snapshot).
  * Default rate       : defaults / loans, MATURE loans only (months_on_book >= 15).  Young loans have not had time to default.
  * Delinquency rate   : outstanding of OPEN loans with current_dpd >= 30 / outstanding of OPEN loans   (PAR30, by balance).
  * High-risk exposure : outstanding of open loans with current_dpd >= 60.
  * Recovery rate      : recovered / amount due, computed on collection CASES (loan_id, installment_no), not on actions.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MATURE_MOB = 15
DPD_ORDER = ["Current", "1-29", "30-59", "60-89", "90+"]


def dpd_bucket(s: pd.Series) -> pd.Series:
    return pd.cut(s.astype(float), [-np.inf, 0, 29, 59, 89, np.inf], labels=DPD_ORDER).astype(str)


def safe_pct(num, den):
    return float("nan") if not den else 100.0 * num / den


def portfolio_kpis(loans: pd.DataFrame) -> dict:
    open_ = loans[loans.loan_status != "CLOSED"]
    out_open = open_.outstanding_balance.sum()
    return dict(
        total_disbursed=float(loans.loan_amount.sum()), loans=int(len(loans)),
        outstanding=float(loans.outstanding_balance.sum()), active_loans=int((loans.loan_status == "ACTIVE").sum()),
        avg_loan=float(loans.loan_amount.mean()),
        delinquency_rate_pct=safe_pct(open_.loc[open_.current_dpd >= 30, "outstanding_balance"].sum(), out_open),
        par90_pct=safe_pct(open_.loc[open_.current_dpd >= 90, "outstanding_balance"].sum(), out_open),
        high_risk_exposure=float(open_.loc[open_.current_dpd >= 60, "outstanding_balance"].sum()),
        avg_dpd_open=float(open_.current_dpd.mean()) if len(open_) else float("nan"),
    )


def default_rate_overall(loans: pd.DataFrame) -> dict:
    m = loans[loans.months_on_book >= MATURE_MOB]
    k = int((m.loan_status == "DEFAULTED").sum())
    return dict(mature_loans=int(len(m)), defaults=k, default_rate_pct=safe_pct(k, len(m)))


def disbursement_by_month(loans: pd.DataFrame) -> pd.DataFrame:
    g = loans.groupby("disbursement_month").agg(loans=("loan_id", "count"), amount=("loan_amount", "sum")).reset_index()
    g["mom_change_pct"] = g.amount.pct_change() * 100
    return g


def default_rate_by(loans: pd.DataFrame, col: str, min_n: int = 1) -> pd.DataFrame:
    m = loans[loans.months_on_book >= MATURE_MOB]
    g = m.groupby(col, dropna=False).agg(mature_loans=("loan_id", "count"), defaults=("loan_status", lambda s: int((s == "DEFAULTED").sum()))).reset_index()
    g["default_rate_pct"] = 100 * g.defaults / g.mature_loans
    lo, hi = [], []
    for k, n in zip(g.defaults, g.mature_loans):       # Wilson 95% interval
        z, p = 1.96, k / n
        d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        lo.append(100 * (c - h)); hi.append(100 * (c + h))
    g["ci_low"], g["ci_high"] = lo, hi
    return g[g.mature_loans >= min_n].sort_values("default_rate_pct", ascending=False)


def dpd_distribution(loans: pd.DataFrame) -> pd.DataFrame:
    o = loans[loans.loan_status != "CLOSED"].copy()
    o["dpd_bucket"] = dpd_bucket(o.current_dpd)
    g = o.groupby("dpd_bucket").agg(loans=("loan_id", "count"), outstanding=("outstanding_balance", "sum")).reindex(DPD_ORDER).fillna(0).reset_index()
    g["pct_of_open_book"] = 100 * g.outstanding / g.outstanding.sum() if g.outstanding.sum() else 0
    return g


def cohort_performance(loans: pd.DataFrame, repayments: pd.DataFrame) -> pd.DataFrame:
    first6 = repayments[repayments.installment_no <= 6].groupby("loan_id").dpd.max().rename("max_dpd_first6")
    c = loans[loans.months_on_book >= 7].merge(first6, left_on="loan_id", right_index=True, how="left")
    c["hit30"] = (c.max_dpd_first6.fillna(0) >= 30).astype(int)
    c["default"] = (c.loan_status == "DEFAULTED").astype(int)
    g = c.groupby("disbursement_month").agg(loans=("loan_id", "count"), pct_30dpd_first6=("hit30", "mean")).reset_index()
    g["pct_30dpd_first6"] *= 100
    mat = c[c.months_on_book >= MATURE_MOB].groupby("disbursement_month").default.mean().mul(100).rename("default_rate_pct_mature").reset_index()
    return g.merge(mat, on="disbursement_month", how="left")


def monthly_repayment(repayments: pd.DataFrame) -> pd.DataFrame:
    r = repayments
    g = r.groupby("due_month").agg(installments=("repayment_id", "count"),
                                   on_time=("repayment_status", lambda s: (s == "PAID_ON_TIME").mean() * 100),
                                   paid_late=("repayment_status", lambda s: (s == "PAID_LATE").mean() * 100),
                                   unpaid_or_partial=("repayment_status", lambda s: s.isin(["UNPAID", "PARTIAL"]).mean() * 100),
                                   paid=("paid_amount", "sum"), due=("due_amount", "sum")).reset_index()
    g["collection_efficiency_pct"] = 100 * g.paid / g.due
    return g


def collection_cases(collections: pd.DataFrame) -> pd.DataFrame:
    return collections.groupby(["loan_id", "installment_no"]).agg(
        amount_due=("amount_due", "max"), recovered=("amount_recovered", "sum"), max_dpd=("dpd_at_action", "max"),
        actions=("collection_id", "count")).reset_index()


def collections_kpis(loans: pd.DataFrame, collections: pd.DataFrame) -> dict:
    cases = collection_cases(collections)
    open_ = loans[loans.loan_status != "CLOSED"]
    return dict(
        cases=int(len(cases)), amount_due=float(cases.amount_due.sum()), amount_collected=float(cases.recovered.sum()),
        recovery_rate_pct=safe_pct(cases.recovered.sum(), cases.amount_due.sum()),
        overdue_accounts=int((open_.current_dpd > 0).sum()),
    )


def recovery_by_dpd_bucket(collections: pd.DataFrame) -> pd.DataFrame:
    c = collection_cases(collections)
    c["bucket"] = pd.cut(c.max_dpd, [0, 29, 59, 89, np.inf], labels=["1-29", "30-59", "60-89", "90+"]).astype(str)
    g = c.groupby("bucket").agg(cases=("amount_due", "size"), amount_due=("amount_due", "sum"), recovered=("recovered", "sum")).reindex(["1-29", "30-59", "60-89", "90+"]).fillna(0).reset_index()
    g["recovery_rate_pct"] = 100 * g.recovered / g.amount_due.replace(0, np.nan)
    return g


def overdue_amount(repayments: pd.DataFrame, loans: pd.DataFrame) -> float:
    open_ids = set(loans.loc[loans.loan_status != "CLOSED", "loan_id"])
    r = repayments[repayments.repayment_status.isin(["UNPAID", "PARTIAL"]) & repayments.loan_id.isin(open_ids)]
    return float((r.due_amount - r.paid_amount).sum())
