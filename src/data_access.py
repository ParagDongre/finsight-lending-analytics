"""Load the clean analytics tables for Python analysis: PostgreSQL first, processed CSVs as fallback."""
from __future__ import annotations

from decimal import Decimal

import pandas as pd

from src import config

TABLES = ["customers", "customer_financial_profiles", "loans", "repayments", "collections"]
NUMERIC = {
    "customers": ["age"],
    "customer_financial_profiles": ["monthly_income", "existing_monthly_emi", "credit_score", "credit_utilization_pct",
                                    "dependents", "years_in_employment", "previous_loans_count"],
    "loans": ["loan_amount", "interest_rate", "tenure_months", "emi_amount", "outstanding_balance", "current_dpd",
              "months_on_book", "foir"],
    "repayments": ["due_amount", "paid_amount", "installment_no", "dpd"],
    "collections": ["amount_due", "amount_recovered", "installment_no", "dpd_at_action"],
}
DATES = {
    "customers": ["signup_date"],
    "customer_financial_profiles": ["profile_date"],
    "loans": ["disbursement_date", "first_due_date", "maturity_date", "snapshot_date", "disbursement_month"],
    "repayments": ["due_date", "paid_date", "due_month"],
    "collections": ["action_date", "action_month"],
}
BOOLS = {"customer_financial_profiles": ["income_missing"], "repayments": ["is_late"]}


def _coerce(name: str, df: pd.DataFrame) -> pd.DataFrame:
    for c in NUMERIC.get(name, []):
        df[c] = pd.to_numeric(df[c].map(lambda v: float(v) if isinstance(v, Decimal) else v), errors="coerce").astype("float64")
    for c in DATES.get(name, []):
        df[c] = pd.to_datetime(df[c])
    for c in BOOLS.get(name, []):
        df[c] = df[c].astype(bool)
    return df


def _from_db() -> dict[str, pd.DataFrame]:
    import psycopg
    out = {}
    with psycopg.connect(**config.db_params(), connect_timeout=3) as conn:
        for t in TABLES:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM analytics.{t}")
                cols = [d.name for d in cur.description]
                out[t] = _coerce(t, pd.DataFrame(cur.fetchall(), columns=cols))
    return out


def _from_csv() -> dict[str, pd.DataFrame]:
    return {t: _coerce(t, pd.read_csv(config.DATA_PROCESSED / f"{t}.csv")) for t in TABLES}


def load_tables(source: str = "auto") -> dict[str, pd.DataFrame]:
    """source: 'auto' (DB, then CSV), 'db' or 'csv'. Prints which source was used."""
    if source in ("auto", "db"):
        try:
            tabs = _from_db()
            print("[data] loaded from PostgreSQL (analytics schema)")
            return tabs
        except Exception as e:
            if source == "db":
                raise
            print(f"[data] PostgreSQL unavailable ({type(e).__name__}); falling back to data/processed CSVs")
    tabs = _from_csv()
    print("[data] loaded from data/processed CSVs")
    return tabs
