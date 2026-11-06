"""SQL query validation.

Static tests always run. DB tests need PostgreSQL loaded by `python -m etl.run_pipeline` and the processed
CSVs on disk; they cross-check SQL results against independent pandas calculations. They are skipped
(not failed) when the database is unreachable.
"""
from __future__ import annotations

import re

import pandas as pd
import psycopg
import pytest

from database.run_queries import parse_queries, run_query
from src import config

QUERIES = parse_queries()


# ---------------- static ----------------
def test_at_least_25_queries_with_documentation():
    assert len(QUERIES) >= 25
    ids = [q["id"] for q in QUERIES]
    assert len(ids) == len(set(ids))
    for q in QUERIES:
        for field in ("title", "question", "why", "sql"):
            assert q.get(field), f"{q['id']} missing {field}"
        assert q["sql"].rstrip().endswith(";"), f"{q['id']} must end with ;"


def test_required_sql_features_are_all_demonstrated():
    allsql = "\n".join(q["sql"].upper() for q in QUERIES)
    for feature in ["GROUP BY", "HAVING", "INNER JOIN|\\bJOIN\\b", "LEFT JOIN", "WITH \\w+ AS", "CASE WHEN", "OVER \\(",
                    "RANK\\(\\)", "ROW_NUMBER\\(\\)", "LAG\\(", "EXTRACT\\(", "EXISTS", "\\(\\s*SELECT", "PARTITION BY", "ORDER BY"]:
        assert re.search(feature, allsql), f"feature not demonstrated: {feature}"


def test_required_business_analyses_present():
    titles = " | ".join(q["title"].lower() for q in QUERIES)
    for needed in ["disbursed by month", "outstanding loan portfolio", "average loan size", "default rate by employment",
                   "default rate by income", "dpd bucket", "repayment performance", "recovery rate", "cohort",
                   "repeated missed", "exposure", "month-over-month", "tenure", "overdue", "repayment history"]:
        assert needed in titles, needed


# ---------------- database ----------------
@pytest.fixture(scope="module")
def conn():
    try:
        c = psycopg.connect(**config.db_params(), connect_timeout=3)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"PostgreSQL not reachable: {e}")
    try:
        c.execute("SELECT 1 FROM analytics.loans LIMIT 1")
    except Exception:
        pytest.skip("pipeline has not been run (analytics.loans missing)")
    yield c
    c.close()


@pytest.fixture(scope="module")
def tables():
    try:
        return {n: pd.read_csv(config.DATA_PROCESSED / f"{n}.csv") for n in
                ["customers", "customer_financial_profiles", "loans", "repayments", "collections"]}
    except FileNotFoundError:
        pytest.skip("processed CSVs missing")


@pytest.mark.db
@pytest.mark.parametrize("q", QUERIES, ids=[q["id"] for q in QUERIES])
def test_every_query_executes_and_returns_rows(conn, q):
    df = run_query(conn, q["sql"])
    assert len(df) > 0, f"{q['id']} returned no rows"


def _q(conn, qid):
    return run_query(conn, next(q for q in QUERIES if q["id"] == qid)["sql"])


@pytest.mark.db
def test_q01_totals_match_pandas(conn, tables):
    df, L = _q(conn, "Q01"), tables["loans"]
    assert df.loans_disbursed.sum() == len(L)
    assert float(df.amount_disbursed.sum()) == pytest.approx(L.loan_amount.sum())


@pytest.mark.db
def test_q02_portfolio_total_matches(conn, tables):
    df = _q(conn, "Q02")
    assert float(df.portfolio_total.iloc[0]) == pytest.approx(tables["loans"].outstanding_balance.sum())
    assert float(df.pct_of_portfolio.sum()) == pytest.approx(100, abs=0.05)


@pytest.mark.db
def test_q04_default_rate_by_employment_matches_pandas(conn, tables):
    df = _q(conn, "Q04").set_index("employment_type")
    m = tables["loans"].merge(tables["customers"], on="customer_id")
    m = m[m.months_on_book >= 15]
    exp = m.groupby("employment_type").loan_status.apply(lambda s: round(100 * (s == "DEFAULTED").mean(), 2))
    for emp, row in df.iterrows():
        assert float(row.default_rate_pct) == pytest.approx(exp[emp], abs=0.01)


@pytest.mark.db
def test_q06_dpd_buckets_cover_every_open_loan(conn, tables):
    df = _q(conn, "Q06")
    assert df.loans.sum() == (tables["loans"].loan_status != "CLOSED").sum()
    assert list(df.dpd_bucket) == ["0 Current", "1-29", "30-59", "60-89", "90+"]


@pytest.mark.db
def test_q08_recovery_rate_matches_pandas(conn, tables):
    df = _q(conn, "Q08").iloc[0]
    K = tables["collections"]
    cases = K.groupby(["loan_id", "installment_no"]).agg(due=("amount_due", "max"), rec=("amount_recovered", "sum"))
    assert df.collection_cases == len(cases)
    assert float(df.recovery_rate_pct) == pytest.approx(100 * cases.rec.sum() / cases.due.sum(), abs=0.01)
    assert 0 <= float(df.recovery_rate_pct) <= 100


@pytest.mark.db
def test_q12_mom_change_matches_pandas(conn, tables):
    df = _q(conn, "Q12")
    s = tables["loans"].groupby("disbursement_month").loan_amount.sum().sort_index()
    exp = (s.pct_change() * 100).round(2).iloc[1:].to_numpy()
    assert df.mom_change_pct.iloc[0] is None or pd.isna(df.mom_change_pct.iloc[0])
    assert df.mom_change_pct.iloc[1:].astype(float).to_numpy() == pytest.approx(exp, abs=0.01)


@pytest.mark.db
def test_q16_overall_par_matches_pandas(conn, tables):
    df = _q(conn, "Q16").set_index("vintage_year")
    L = tables["loans"]; L = L[L.loan_status != "CLOSED"]
    par30 = 100 * L.loc[L.current_dpd >= 30, "outstanding_balance"].sum() / L.outstanding_balance.sum()
    assert float(df.loc["ALL", "par30_pct"]) == pytest.approx(par30, abs=0.01)


@pytest.mark.db
def test_q21_partitions_all_mature_loans(conn, tables):
    df = _q(conn, "Q21")
    assert df.loans.sum() == (tables["loans"].months_on_book >= 15).sum()


@pytest.mark.db
def test_q10_returns_only_customers_with_three_or_more(conn):
    df = _q(conn, "Q10")
    assert (df.missed_installments >= 3).all()
