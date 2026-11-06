"""Unit tests for individual validation / transformation rules using tiny hand-built frames."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from etl import transform as T
from src.validation.rules import IssueLog, dpd_bucket, to_date, to_num

SNAP = date(2026, 6, 30)


def _df(rows, cols):
    d = pd.DataFrame(rows, columns=cols, dtype="string")
    d["_src_row"] = range(2, len(d) + 2)
    return d


CUST_COLS = ["customer_id", "age", "gender", "city_tier", "employment_type", "acquisition_channel", "signup_date"]


def _cust(**over):
    base = dict(customer_id="C1", age="30", gender="Male", city_tier="Tier 1", employment_type="Salaried",
                acquisition_channel="Organic", signup_date="2024-01-01")
    base.update(over)
    return [base[c] for c in CUST_COLS]


# ---------------- parsing helpers ----------------
def test_to_num_coerces_garbage_to_nan():
    s = pd.Series(["1", " 2.5 ", "abc", None, "-3"], dtype="string")
    out = to_num(s)
    assert out.tolist()[:2] == [1.0, 2.5] and np.isnan(out[2]) and np.isnan(out[3]) and out[4] == -3


def test_to_date_rejects_impossible_calendar_dates():
    s = pd.Series(["2024-02-29", "2024-02-30", "2024-13-01", "31/12/2024"], dtype="string")
    out = to_date(s)
    assert out.notna().tolist() == [True, False, False, False]


@pytest.mark.parametrize("dpd,bucket", [(0, "Current"), (1, "1-29"), (29, "1-29"), (30, "30-59"), (59, "30-59"),
                                        (60, "60-89"), (89, "60-89"), (90, "90+"), (400, "90+")])
def test_dpd_bucket_boundaries(dpd, bucket):
    assert dpd_bucket(pd.Series([dpd])).iloc[0] == bucket


# ---------------- customers ----------------
def test_customer_duplicates_are_rejected_and_logged_first_kept():
    raw = _df([_cust(), _cust(), _cust(customer_id="C2")], CUST_COLS)
    log = IssueLog()
    clean = T.transform_customers(raw, log)
    assert sorted(clean.customer_id) == ["C1", "C2"]
    assert log.rules[("customers", "C01")]["failures"] == 1
    assert log.issues_df().query("rule_id == 'C01'").src_row.tolist() == [3]       # the 2nd occurrence


def test_customer_invalid_age_is_nulled_not_dropped():
    raw = _df([_cust(customer_id="C1", age="150"), _cust(customer_id="C2", age="abc"), _cust(customer_id="C3", age=None)], CUST_COLS)
    log = IssueLog()
    clean = T.transform_customers(raw, log)
    assert len(clean) == 3 and clean.age.isna().all()
    assert log.rules[("customers", "C04")]["failures"] == 2
    assert log.rules[("customers", "C03")]["failures"] == 1


def test_employment_standardised_and_unknown_handled():
    raw = _df([_cust(customer_id="C1", employment_type="  GIG WORKER "), _cust(customer_id="C2", employment_type=None),
               _cust(customer_id="C3", employment_type="Astronaut")], CUST_COLS)
    log = IssueLog()
    clean = T.transform_customers(raw, log).set_index("customer_id")
    assert clean.loc["C1", "employment_type"] == "Gig Worker"
    assert clean.loc["C2", "employment_type"] == "Unknown" and clean.loc["C3", "employment_type"] == "Unknown"
    assert log.rules[("customers", "C06")]["failures"] == 1
    assert log.rules[("customers", "C05")]["failures"] == 1
    assert log.rules[("customers", "C07")]["failures"] == 1


# ---------------- loans ----------------
LOAN_COLS = ["loan_id", "customer_id", "profile_id", "loan_purpose", "loan_amount", "interest_rate", "tenure_months",
             "emi_amount", "disbursement_date", "first_due_date", "maturity_date", "outstanding_balance", "current_dpd",
             "loan_status", "snapshot_date"]


def _loan(**over):
    base = dict(loan_id="L1", customer_id="C1", profile_id="P1", loan_purpose="Medical", loan_amount="100000", interest_rate="15",
                tenure_months="12", emi_amount="9025.83", disbursement_date="2025-01-10", first_due_date="2025-02-10",
                maturity_date="2026-01-10", outstanding_balance="50000", current_dpd="0", loan_status="ACTIVE", snapshot_date="2026-06-30")
    base.update(over)
    return [base[c] for c in LOAN_COLS]


def _prof_clean():
    return pd.DataFrame({"profile_id": ["P1"], "monthly_income": [50000.0], "existing_monthly_emi": [5000.0]})


@pytest.mark.parametrize("over,rule", [
    (dict(loan_amount="-5"), "L04"), (dict(loan_amount="abc"), "L04"), (dict(interest_rate="0"), "L05"),
    (dict(interest_rate="120"), "L05"), (dict(tenure_months="0"), "L06"), (dict(disbursement_date="2025-02-30"), "L07"),
    (dict(disbursement_date="2027-01-01"), "L08"), (dict(outstanding_balance="-1"), "L09"),
    (dict(outstanding_balance="999999"), "L09"), (dict(loan_status="WEIRD"), "L10"),
    (dict(loan_status="CLOSED", outstanding_balance="500"), "L11"), (dict(loan_status="DEFAULTED", current_dpd="10"), "L11"),
    (dict(customer_id="NOPE"), "L02"),
])
def test_loan_rules_reject_bad_rows(over, rule):
    raw = _df([_loan(**over)], LOAN_COLS)
    log = IssueLog()
    clean = T.transform_loans(raw, {"C1"}, {"C1"}, {"P1"}, _prof_clean(), SNAP, log)
    assert len(clean) == 0
    assert log.rules[("loans", rule)]["failures"] >= 1


def test_loan_good_row_passes_and_derived_fields_are_correct():
    raw = _df([_loan()], LOAN_COLS)
    log = IssueLog()
    clean = T.transform_loans(raw, {"C1"}, {"C1"}, {"P1"}, _prof_clean(), SNAP, log)
    assert len(clean) == 1 and log.issues_df().empty
    row = clean.iloc[0]
    assert row.months_on_book == 17                      # 2025-01-10 -> 2026-06-30
    assert row.dpd_bucket == "Current"
    assert row.foir == pytest.approx((5000 + 9025.83) / 50000, abs=1e-4)
    assert row.disbursement_month == pd.Timestamp("2025-01-01")


def test_loan_parent_rejected_is_a_cascade_not_an_orphan():
    raw = _df([_loan(customer_id="C1")], LOAN_COLS)
    log = IssueLog()
    T.transform_loans(raw, {"C1"}, set(), {"P1"}, _prof_clean(), SNAP, log)      # C1 exists in raw but was rejected
    assert log.rules[("loans", "L02b")]["failures"] == 1 and log.rules[("loans", "L02")]["failures"] == 0


# ---------------- repayments ----------------
REP_COLS = ["repayment_id", "loan_id", "installment_no", "due_date", "due_amount", "paid_amount", "paid_date", "dpd", "repayment_status"]


def _rep(**over):
    base = dict(repayment_id="R1", loan_id="L1", installment_no="1", due_date="2025-02-10", due_amount="1000.00",
                paid_amount="1000.00", paid_date="2025-02-10", dpd="0", repayment_status="PAID_ON_TIME")
    base.update(over)
    return [base[c] for c in REP_COLS]


def _raw_loans():
    return _df([_loan()], LOAN_COLS)


@pytest.mark.parametrize("over,rule", [
    (dict(paid_amount="-10"), "R03"), (dict(due_amount="0"), "R03"), (dict(paid_date=None), "R05"),
    (dict(repayment_status="UNPAID"), "R06"), (dict(repayment_status="PARTIAL"), "R06"),
    (dict(paid_amount="1500", ), "R10"), (dict(due_date="2024-12-01", paid_date="2024-12-01"), "R08"),
    (dict(paid_date="2025-01-05", due_date="2025-02-10"), "R07"), (dict(dpd="-3"), "R11"),
    (dict(dpd="9"), "R11"), (dict(paid_date="2025-02-31"), "R04"), (dict(loan_id="NOPE"), "R02"),
    (dict(installment_no="0"), "R12"),
])
def test_repayment_rules_reject_bad_rows(over, rule):
    raw = _df([_rep(**over)], REP_COLS)
    log = IssueLog()
    clean = T.transform_repayments(raw, _raw_loans(), {"L1"}, log)
    assert len(clean) == 0, f"row should be rejected by {rule}"
    assert log.rules[("repayments", rule)]["failures"] >= 1


def test_repayment_late_payment_dpd_and_flag():
    raw = _df([_rep(paid_date="2025-02-15", dpd="5", repayment_status="PAID_LATE")], REP_COLS)
    clean = T.transform_repayments(raw, _raw_loans(), {"L1"}, IssueLog())
    assert clean.iloc[0].dpd == 5 and bool(clean.iloc[0].is_late) and clean.iloc[0].dpd_bucket == "1-29"


def test_repayment_duplicate_installment_with_new_id_is_caught():
    raw = _df([_rep(), _rep(repayment_id="R2")], REP_COLS)
    log = IssueLog()
    clean = T.transform_repayments(raw, _raw_loans(), {"L1"}, log)
    assert len(clean) == 1 and log.rules[("repayments", "R09")]["failures"] == 1


def test_valid_unpaid_and_partial_rows_pass():
    raw = _df([_rep(repayment_id="R1", paid_amount="0.00", paid_date=None, dpd="120", repayment_status="UNPAID"),
               _rep(repayment_id="R2", installment_no="2", paid_amount="400.00", paid_date="2025-03-20", dpd="95",
                    due_date="2025-03-10", repayment_status="PARTIAL")], REP_COLS)
    clean = T.transform_repayments(raw, _raw_loans(), {"L1"}, IssueLog())
    assert len(clean) == 2


# ---------------- collections ----------------
COL_COLS = ["collection_id", "loan_id", "installment_no", "action_date", "dpd_at_action", "channel", "outcome",
            "amount_due", "amount_recovered", "collection_status"]


def _col(**over):
    base = dict(collection_id="K1", loan_id="L1", installment_no="1", action_date="2025-02-17", dpd_at_action="7", channel="CALL",
                outcome="NO_RESPONSE", amount_due="1000", amount_recovered="0", collection_status="OPEN")
    base.update(over)
    return [base[c] for c in COL_COLS]


@pytest.mark.parametrize("over,rule", [(dict(amount_recovered="-1"), "K03"), (dict(amount_recovered="5000"), "K04"),
                                       (dict(channel="PIGEON"), "K06"), (dict(loan_id="NOPE"), "K02"),
                                       (dict(action_date="2025-99-01"), "K05")])
def test_collection_rules(over, rule):
    log = IssueLog()
    clean = T.transform_collections(_df([_col(**over)], COL_COLS), {"L1"}, {"L1"}, log)
    assert len(clean) == 0 and log.rules[("collections", rule)]["failures"] >= 1
