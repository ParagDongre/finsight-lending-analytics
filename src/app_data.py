"""Data preparation for the Streamlit app: load (DB / local files / uploads), validate, and build the analysis frames.

Uploads are processed in memory only. Nothing here writes to PostgreSQL or to disk.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src import config
from src.data_access import NUMERIC, DATES, BOOLS, TABLES, _coerce, load_tables
from src.kpis import dpd_bucket

REQUIRED = {
    "loans": ["loan_id", "loan_amount", "outstanding_balance", "loan_status", "current_dpd", "disbursement_date"],
    "repayments": ["repayment_id", "loan_id", "installment_no", "due_date", "due_amount", "paid_amount", "repayment_status", "dpd"],
    "collections": ["collection_id", "loan_id", "installment_no", "action_date", "dpd_at_action", "amount_due", "amount_recovered", "channel", "outcome"],
    "customers": ["customer_id", "employment_type"],
    "customer_financial_profiles": ["profile_id", "monthly_income", "credit_score"],
}
LOAN_STATUSES = {"ACTIVE", "CLOSED", "DEFAULTED"}


@dataclass
class Prepared:
    loans: pd.DataFrame
    repayments: pd.DataFrame
    collections: pd.DataFrame
    snapshot: pd.Timestamp
    source: str
    warnings: list = field(default_factory=list)


def validate_upload(name: str, df: pd.DataFrame) -> list[str]:
    """Return human-readable problems (empty list = OK)."""
    problems = []
    missing = [c for c in REQUIRED.get(name, []) if c not in df.columns]
    if missing:
        problems.append(f"{name}: missing required column(s): {', '.join(missing)}")
    if df.empty:
        problems.append(f"{name}: file has no rows")
    if name == "loans" and not missing:
        bad = set(df.loan_status.astype(str).str.upper().unique()) - LOAN_STATUSES
        if bad:
            problems.append(f"loans: unexpected loan_status value(s): {sorted(bad)[:5]} (expected ACTIVE / CLOSED / DEFAULTED)")
        if df.loan_id.duplicated().any():
            problems.append(f"loans: {int(df.loan_id.duplicated().sum())} duplicate loan_id value(s)")
    return problems


def _band(s: pd.Series, bins, labels) -> pd.Series:
    return pd.cut(s, bins, labels=labels, right=False).astype("string")


def build_frames(tables: dict[str, pd.DataFrame], source: str) -> Prepared:
    """Coerce types, derive missing analytical columns, and join customer / profile attributes onto loans."""
    t = {k: v.copy() for k, v in tables.items() if v is not None}
    warnings: list[str] = []
    for name in ("loans", "repayments", "collections", "customers", "customer_financial_profiles"):
        if name in t:
            t[name] = _coerce_loose(name, t[name])
    loans, rep, col = t["loans"], t.get("repayments", pd.DataFrame()), t.get("collections", pd.DataFrame())

    loans["loan_status"] = loans.loan_status.astype(str).str.upper()
    if "snapshot_date" in loans.columns and loans.snapshot_date.notna().any():
        snapshot = pd.Timestamp(loans.snapshot_date.max())
    else:
        snapshot = pd.Timestamp(max([x for x in [loans.disbursement_date.max(), rep.get("due_date", pd.Series(dtype="datetime64[ns]")).max()] if pd.notna(x)]))
        warnings.append(f"No snapshot_date column - using {snapshot.date()} (latest date seen) as the as-of date.")
    if "disbursement_month" not in loans:
        loans["disbursement_month"] = loans.disbursement_date.dt.to_period("M").dt.to_timestamp()
    if "months_on_book" not in loans:
        loans["months_on_book"] = ((snapshot.year - loans.disbursement_date.dt.year) * 12 + (snapshot.month - loans.disbursement_date.dt.month)
                                   - (snapshot.day < loans.disbursement_date.dt.day).astype(int))
    if "dpd_bucket" not in loans:
        loans["dpd_bucket"] = dpd_bucket(loans.current_dpd)
    if len(rep):
        if "due_month" not in rep:
            rep["due_month"] = rep.due_date.dt.to_period("M").dt.to_timestamp()
    if len(col):
        if "action_month" not in col:
            col["action_month"] = col.action_date.dt.to_period("M").dt.to_timestamp()

    cust = t.get("customers")
    if cust is not None and len(cust) and "customer_id" in loans:
        keep = [c for c in ["customer_id", "employment_type", "city_tier", "acquisition_channel", "gender", "age_band", "age"] if c in cust.columns]
        loans = loans.drop(columns=[c for c in keep if c != "customer_id" and c in loans.columns]).merge(cust[keep], on="customer_id", how="left")
        if "age_band" not in loans.columns and "age" in loans.columns:
            loans["age_band"] = _band(loans.age, [18, 25, 35, 45, 100], ["18-24", "25-34", "35-44", "45+"])
    prof = t.get("customer_financial_profiles")
    if prof is not None and len(prof) and "profile_id" in loans:
        keep = [c for c in ["profile_id", "monthly_income", "credit_score", "credit_utilization_pct"] if c in prof.columns]
        loans = loans.drop(columns=[c for c in keep if c != "profile_id" and c in loans.columns]).merge(prof[keep], on="profile_id", how="left")
    if "monthly_income" in loans.columns:
        loans["income_bracket"] = _band(loans.monthly_income, [0, 20000, 35000, 50000, 75000, np.inf], ["Below 20K", "20K-35K", "35K-50K", "50K-75K", "75K+"]).fillna("Unknown")
    if "credit_score" in loans.columns:
        loans["credit_band"] = _band(loans.credit_score, [300, 600, 650, 700, 750, 800, 901], ["<600", "600-649", "650-699", "700-749", "750-799", "800+"]).fillna("Missing")
    if "tenure_months" in loans.columns:
        loans["tenure_months"] = loans.tenure_months.astype("float")
    for c in ["employment_type", "city_tier", "acquisition_channel"]:
        if c in loans.columns:
            loans[c] = loans[c].fillna("Unknown")
    return Prepared(loans, rep, col, snapshot, source, warnings)


def _coerce_loose(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Like data_access._coerce but tolerant of columns that are absent in uploads."""
    df = df.copy()
    for c in NUMERIC.get(name, []):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in DATES.get(name, []):
        if c in df:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    for c in BOOLS.get(name, []):
        if c in df:
            df[c] = df[c].astype(bool)
    return df


def load_local(source: str = "auto") -> Prepared:
    """Local synthetic demo data: PostgreSQL if reachable, otherwise data/processed CSVs."""
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        tabs = load_tables(source)
    msg = buf.getvalue().strip().replace("[data] ", "")
    return build_frames(tabs, msg)


def local_data_available() -> bool:
    return all((config.DATA_PROCESSED / f"{t}.csv").exists() for t in TABLES)


def load_results(name: str) -> dict | None:
    p = config.REPORTS / "results" / f"{name}.json"
    return json.loads(p.read_text()) if p.exists() else None
