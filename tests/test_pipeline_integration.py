"""Integration tests: generator determinism, no false positives on clean data, every injected defect caught,
row accounting, and business-calculation invariants on the generated data."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from etl.dq_report import injected_vs_detected
from etl.transform import transform_all
from src import config
from src.generation.generate_data import add_months, emi_formula


# ---------------- generator ----------------
def test_generator_is_deterministic(small_clean):
    from datetime import date
    old = (config.FIRST_DISBURSEMENT_MONTH, config.LAST_DISBURSEMENT_MONTH)
    config.FIRST_DISBURSEMENT_MONTH, config.LAST_DISBURSEMENT_MONTH = date(2025, 10, 1), date(2026, 1, 1)
    try:
        from src.generation.generate_data import generate
        again = generate(seed=7); again.pop("_stats")
    finally:
        config.FIRST_DISBURSEMENT_MONTH, config.LAST_DISBURSEMENT_MONTH = old
    for k in small_clean:
        pd.testing.assert_frame_equal(small_clean[k], again[k])


def test_add_months_clamps_month_end():
    from datetime import date
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    assert add_months(date(2025, 11, 15), 3) == date(2026, 2, 15)


def test_emi_formula_amortises_to_zero():
    P, r, n = 100000.0, 15.0, 12
    emi = emi_formula(P, r, n)
    bal = P
    for _ in range(n):
        bal = bal * (1 + r / 1200) - emi
    assert abs(bal) < 1e-6


# ---------------- ground-truth invariants (business calculations) ----------------
def test_loan_status_matches_dpd_and_balance(small_clean):
    L = small_clean["loans"]
    assert ((L.loan_status == "DEFAULTED") == (L.current_dpd >= 90)).all()
    assert (L.loc[L.loan_status == "CLOSED", "outstanding_balance"] == 0).all()
    assert (L.outstanding_balance <= L.loan_amount).all() and (L.outstanding_balance >= 0).all()


def test_reported_dpd_equals_oldest_unpaid_installment(small_clean):
    L, R = small_clean["loans"].set_index("loan_id"), small_clean["repayments"]
    unpaid = R[R.repayment_status.isin(["UNPAID", "PARTIAL"])].groupby("loan_id").dpd.max()
    recomputed = unpaid.reindex(L.index).fillna(0)
    open_loans = L.loan_status != "CLOSED"
    assert (recomputed[open_loans] == L.current_dpd[open_loans]).all()


def test_repayment_amounts_and_dpd_rules_hold(small_clean):
    R = small_clean["repayments"]
    paid = R[R.repayment_status.isin(["PAID_ON_TIME", "PAID_LATE"])]
    assert (paid.paid_amount == paid.due_amount).all()
    exp = (pd.to_datetime(paid.paid_date) - pd.to_datetime(paid.due_date)).dt.days.clip(lower=0)
    assert (paid.dpd == exp).all()
    assert (R[R.repayment_status == "UNPAID"].paid_amount == 0).all()


def test_no_future_dated_events(small_clean):
    snap = pd.Timestamp(config.SNAPSHOT_DATE)
    R, K = small_clean["repayments"], small_clean["collections"]
    assert (pd.to_datetime(R.due_date) < snap).all()
    assert (pd.to_datetime(R.paid_date.dropna()) <= snap).all()
    assert (pd.to_datetime(K.action_date) <= snap).all()


def test_collection_recovery_never_exceeds_amount_due(small_clean):
    K = small_clean["collections"]
    assert (K.amount_recovered <= K.amount_due).all()


# ---------------- ETL on clean data: no false positives ----------------
def test_clean_data_passes_without_rejections(small_clean_as_raw):
    res = transform_all(small_clean_as_raw, config.SNAPSHOT_DATE)
    assert (res.counts.rejected_rows == 0).all(), res.counts
    assert (res.counts.fixed_rows == 0).all()
    assert res.rule_results.query("rule_id.str.startswith('X')").failures.sum() == 0   # reconciliation also clean


# ---------------- ETL on dirty data ----------------
def test_every_injected_defect_is_detected(small_dirty):
    raw, manifest = small_dirty
    res = transform_all(raw, config.SNAPSHOT_DATE)
    iv = injected_vs_detected(res, manifest)
    missed = iv[~iv.caught]
    assert missed.empty, f"undetected defects:\n{missed}"


def test_no_row_silently_disappears(small_dirty):
    raw, _ = small_dirty
    res = transform_all(raw, config.SNAPSHOT_DATE)
    c = res.counts
    assert (c.raw_rows == c.clean_rows + c.rejected_rows).all()
    # every rejected row has at least one logged REJECTED issue with a reason
    rej = res.issues[res.issues.action == "REJECTED"]
    assert rej.reason.notna().all() and (rej.reason.str.len() > 0).all()


def test_clean_output_respects_referential_integrity(small_dirty):
    raw, _ = small_dirty
    c = transform_all(raw, config.SNAPSHOT_DATE).clean
    assert c["loans"].customer_id.isin(c["customers"].customer_id).all()
    assert c["loans"].profile_id.isin(c["customer_financial_profiles"].profile_id).all()
    assert c["repayments"].loan_id.isin(c["loans"].loan_id).all()
    assert c["collections"].loan_id.isin(c["loans"].loan_id).all()
    assert c["customer_financial_profiles"].customer_id.isin(c["customers"].customer_id).all()


def test_clean_output_has_no_invalid_values(small_dirty):
    raw, _ = small_dirty
    c = transform_all(raw, config.SNAPSHOT_DATE).clean
    assert (c["loans"].loan_amount > 0).all() and c["loans"].interest_rate.between(1, 60).all()
    assert (c["repayments"].paid_amount >= 0).all() and (c["repayments"].dpd >= 0).all()
    assert c["customers"].age.dropna().between(18, 75).all()
    assert c["customers"].employment_type.isin(
        ["Salaried", "Self-Employed", "Gig Worker", "Business Owner", "Contract Worker", "Unknown"]).all()
    assert not c["customers"].customer_id.duplicated().any()
    assert not c["repayments"].duplicated(["loan_id", "installment_no"]).any()
    # missing income is kept as NULL (never silently imputed) and flagged
    p = c["customer_financial_profiles"]
    assert (p.monthly_income.isna() == p.income_missing).all()
