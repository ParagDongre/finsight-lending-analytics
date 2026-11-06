"""LOAD step: PostgreSQL loading with COPY (fast) inside one transaction.

Credentials are read from environment variables / .env (see .env.example). None are stored in code.
"""
from __future__ import annotations

from io import StringIO

import pandas as pd
import psycopg

from src import config

ANALYTICS_ORDER = ["customers", "customer_financial_profiles", "loans", "repayments", "collections"]


def connect() -> psycopg.Connection:
    return psycopg.connect(**config.db_params())


def run_sql_file(conn: psycopg.Connection, path) -> None:
    conn.execute(open(path, encoding="utf-8").read())


def copy_df(conn: psycopg.Connection, df: pd.DataFrame, qualified_table: str, columns: list[str] | None = None) -> None:
    columns = columns or list(df.columns)
    buf = StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="\\N")
    cols = ", ".join(columns)
    with conn.cursor() as cur:
        with cur.copy(f"COPY {qualified_table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '\\N')") as cp:
            cp.write(buf.getvalue())


def load_raw(conn, raw: dict[str, pd.DataFrame]) -> None:
    for name, df in raw.items():
        copy_df(conn, df, f"raw.{name}")


def load_analytics(conn, clean: dict[str, pd.DataFrame]) -> None:
    for name in ANALYTICS_ORDER:
        df = clean[name].copy()
        for c in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[c]):
                df[c] = df[c].dt.strftime("%Y-%m-%d")
            elif pd.api.types.is_bool_dtype(df[c]):
                df[c] = df[c].map({True: "true", False: "false"})
        copy_df(conn, df, f"analytics.{name}")


def load_audit(conn, issues: pd.DataFrame, rule_results: pd.DataFrame, counts: pd.DataFrame,
               seed: int, snapshot, notes: str = "") -> int:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO etl.pipeline_runs (seed, snapshot_date, notes) VALUES (%s,%s,%s) RETURNING run_id",
                    (seed, snapshot, notes))
        run_id = cur.fetchone()[0]
    iss = issues.copy()
    iss.insert(0, "run_id", run_id)
    copy_df(conn, iss, "etl.data_quality_issues",
            ["run_id", "table_name", "src_row", "record_key", "rule_id", "action", "reason", "raw_record"])
    rr = rule_results.copy(); rr.insert(0, "run_id", run_id)
    copy_df(conn, rr, "etl.dq_rule_results", ["run_id", "table_name", "rule_id", "description", "action", "failures"])
    cc = counts.copy(); cc.insert(0, "run_id", run_id)
    copy_df(conn, cc, "etl.dq_table_counts",
            ["run_id", "table_name", "raw_rows", "clean_rows", "rejected_rows", "fixed_rows", "flagged_rows"])
    return run_id
