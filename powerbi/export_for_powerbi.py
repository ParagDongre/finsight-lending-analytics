"""Write flat CSVs for Power BI Desktop (no database needed).

    python -m powerbi.export_for_powerbi            # reads PostgreSQL reporting views, falls back to data/processed CSVs
Outputs powerbi/data/{loans,repayments,collection_cases,collection_actions,date}.csv  (SYNTHETIC data; git-ignored)
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config
from src.app_data import build_frames, load_local
from src import kpis

OUT = Path(__file__).resolve().parent / "data"


def from_database() -> dict[str, pd.DataFrame]:
    import psycopg
    views = {"loans": "vw_loans", "repayments": "vw_repayments", "collection_cases": "vw_collection_cases",
             "collection_actions": "vw_collection_actions", "date": "vw_date"}
    out = {}
    with psycopg.connect(**config.db_params(), connect_timeout=3) as conn:
        for k, v in views.items():
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM reporting.{v}")
                out[k] = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    return out


def from_files() -> dict[str, pd.DataFrame]:
    p = load_local("csv")
    loans = p.loans.copy()
    loans["is_mature"] = loans.months_on_book >= 15
    loans["is_default"] = loans.loan_status == "DEFAULTED"
    loans["is_open"] = loans.loan_status != "CLOSED"
    rep = p.repayments.assign(shortfall_amount=lambda d: (d.due_amount - d.paid_amount).clip(lower=0))
    cases = kpis.collection_cases(p.collections).rename(columns={"recovered": "amount_recovered", "max_dpd": "max_dpd_reached"})
    cases["dpd_bucket_reached"] = pd.cut(cases.max_dpd_reached, [0, 29, 59, 89, 1e9], labels=["1-29", "30-59", "60-89", "90+"]).astype(str)
    days = pd.date_range("2023-06-01", "2026-12-31")
    dates = pd.DataFrame({"date": days, "month_start": days.to_period("M").to_timestamp(), "year_month": days.strftime("%Y-%m"), "year": days.year, "quarter": days.quarter})
    return {"loans": loans, "repayments": rep, "collection_cases": cases, "collection_actions": p.collections, "date": dates}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        tabs, src = from_database(), "PostgreSQL reporting views"
    except Exception as e:
        print(f"[export] database/views unavailable ({type(e).__name__}); using processed CSV files")
        tabs, src = from_files(), "processed CSV files"
    for k, df in tabs.items():
        df.to_csv(OUT / f"{k}.csv", index=False)
        print(f"  {k}.csv  {len(df):,} rows")
    print(f"exported from {src} -> {OUT}")


if __name__ == "__main__":
    main()
