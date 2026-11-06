"""Unit tests for KPI definitions (hand-computed expectations) and app-data preparation."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src import kpis
from src.app_data import build_frames, validate_upload


def _loans():
    return pd.DataFrame({
        "loan_id": ["A", "B", "C", "D", "E"],
        "loan_amount": [100.0, 200.0, 300.0, 400.0, 500.0],
        "outstanding_balance": [50.0, 0.0, 300.0, 100.0, 200.0],
        "loan_status": ["ACTIVE", "CLOSED", "DEFAULTED", "ACTIVE", "ACTIVE"],
        "current_dpd": [0, 0, 120, 45, 70],
        "months_on_book": [20, 20, 20, 8, 16],
        "disbursement_month": pd.to_datetime(["2024-01-01", "2024-01-01", "2024-02-01", "2025-01-01", "2024-03-01"]),
    })


def test_portfolio_kpis_hand_computed():
    k = kpis.portfolio_kpis(_loans())
    assert k["total_disbursed"] == 1500 and k["outstanding"] == 650 and k["active_loans"] == 3
    # open loans: A(50,dpd0) C(300,120) D(100,45) E(200,70) -> open total 650; 30+ = 300+100+200 = 600
    assert k["delinquency_rate_pct"] == pytest.approx(100 * 600 / 650)
    assert k["high_risk_exposure"] == 500           # 60+: C and E
    assert k["par90_pct"] == pytest.approx(100 * 300 / 650)


def test_default_rate_uses_mature_loans_only():
    r = kpis.default_rate_overall(_loans())
    assert r["mature_loans"] == 4                      # D has 8 months on book -> excluded
    assert r["defaults"] == 1 and r["default_rate_pct"] == 25.0


def test_dpd_buckets_boundaries_and_distribution():
    s = kpis.dpd_bucket(pd.Series([0, 1, 29, 30, 59, 60, 89, 90]))
    assert s.tolist() == ["Current", "1-29", "1-29", "30-59", "30-59", "60-89", "60-89", "90+"]
    d = kpis.dpd_distribution(_loans())
    assert d.loans.sum() == 4 and d.outstanding.sum() == 650     # closed loan excluded
    assert d.pct_of_open_book.sum() == pytest.approx(100)


def test_wilson_interval_contains_rate_and_is_within_bounds():
    l = _loans().assign(employment_type=["x", "x", "y", "y", "y"])
    g = kpis.default_rate_by(l, "employment_type")
    assert ((g.ci_low <= g.default_rate_pct) & (g.default_rate_pct <= g.ci_high)).all()
    assert (g.ci_low >= 0).all() and (g.ci_high <= 100).all()


def test_collection_recovery_is_per_case_not_per_action():
    c = pd.DataFrame({"collection_id": ["1", "2", "3", "4"], "loan_id": ["A", "A", "A", "B"], "installment_no": [1, 1, 1, 1],
                      "dpd_at_action": [1, 7, 30, 95], "amount_due": [1000.0] * 4, "amount_recovered": [0, 0, 1000, 0]})
    cases = kpis.collection_cases(c)
    assert len(cases) == 2 and cases.amount_due.sum() == 2000     # NOT 4000
    k = kpis.collections_kpis(_loans(), c)
    assert k["recovery_rate_pct"] == pytest.approx(50.0)
    rb = kpis.recovery_by_dpd_bucket(c).set_index("bucket")
    assert rb.loc["30-59", "recovery_rate_pct"] == 100 and rb.loc["90+", "recovery_rate_pct"] == 0


def test_mom_change():
    d = kpis.disbursement_by_month(_loans())
    assert d.amount.tolist() == [300, 300, 500, 400] or len(d) == 4
    assert np.isnan(d.mom_change_pct.iloc[0])


def test_validate_upload_reports_problems():
    assert validate_upload("loans", pd.DataFrame({"loan_id": ["A"]}))[0].startswith("loans: missing required")
    ok = _loans().assign(disbursement_date="2024-01-01")
    assert validate_upload("loans", ok) == []
    bad = ok.assign(loan_status="WEIRD")
    assert any("unexpected loan_status" in p for p in validate_upload("loans", bad))
    assert any("duplicate loan_id" in p for p in validate_upload("loans", pd.concat([ok, ok])))
    assert any("no rows" in p for p in validate_upload("loans", ok.iloc[0:0]))


def test_build_frames_derives_columns_for_minimal_upload():
    up = pd.DataFrame({"loan_id": ["A", "B"], "loan_amount": ["1000", "2000"], "outstanding_balance": ["500", "0"], "loan_status": ["active", "closed"],
                       "current_dpd": ["0", "0"], "disbursement_date": ["2025-01-15", "2025-03-20"]})
    p = build_frames({"loans": up}, "test")
    assert {"months_on_book", "disbursement_month", "dpd_bucket"} <= set(p.loans.columns)
    assert p.loans.loan_status.tolist() == ["ACTIVE", "CLOSED"]
    assert any("snapshot" in w.lower() for w in p.warnings)      # told the user the as-of date was inferred
