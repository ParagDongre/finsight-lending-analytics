"""TRANSFORM step: validate, fix, quarantine and enrich the raw (all-string) extracts.

Input : dict of all-string DataFrames (+ _src_row) from etl.extract
Output: TransformResult with clean typed frames, a full issue log and per-rule / per-table counts.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from src.validation.rules import IssueLog, dpd_bucket, is_blank, table_counts, to_date, to_num

EMP_CANON = {k.lower(): k for k in ["Salaried", "Self-Employed", "Gig Worker", "Business Owner", "Contract Worker"]}
GENDERS = {"Male", "Female", "Other"}
TIERS = {"Tier 1", "Tier 2", "Tier 3"}
CHANNELS = {"Organic", "Paid Digital", "Partner Referral", "Customer Referral"}
LOAN_STATUS = {"ACTIVE", "CLOSED", "DEFAULTED"}
REPAY_STATUS = {"PAID_ON_TIME", "PAID_LATE", "PARTIAL", "UNPAID"}
COLL_CHANNEL = {"SMS", "APP_PUSH", "CALL", "FIELD_VISIT", "LEGAL_NOTICE"}
COLL_OUTCOME = {"PROMISE_TO_PAY", "NO_RESPONSE", "REFUSED_TO_PAY", "PAID_IN_FULL", "PARTIAL_PAYMENT"}
COLL_STATUS = {"OPEN", "PROMISE_TO_PAY", "ESCALATED", "RESOLVED", "WRITTEN_OFF"}


@dataclass
class TransformResult:
    clean: dict
    issues: pd.DataFrame
    rule_results: pd.DataFrame
    counts: pd.DataFrame


def _strip_all(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if c != "_src_row":
            out[c] = out[c].astype("string").str.strip()
    return out


def _fk(log, table, df, col, raw_parent_ids, clean_parent_ids, rid, parent_name):
    """Two FK rules: key never existed in the source (orphan) vs. parent existed but was rejected."""
    ids = df[col]
    never = ~ids.isin(raw_parent_ids)
    parent_rejected = ids.isin(raw_parent_ids) & ~ids.isin(clean_parent_ids)
    m1 = log.check(table, df, never, rid, "REJECTED", f"ORPHAN: {col} does not exist in source {parent_name}", df.columns[0])
    m2 = log.check(table, df, parent_rejected, rid + "b", "REJECTED",
                   f"CASCADE: {col} refers to a {parent_name} record that was itself rejected", df.columns[0])
    return m1 | m2


# --------------------------------------------------------------------------------------------
def transform_customers(raw: pd.DataFrame, log: IssueLog):
    t = "customers"
    emp_raw = raw["employment_type"].copy()
    df = _strip_all(raw)
    reject = log.check(t, df, is_blank(df.customer_id), "C02", "REJECTED", "Missing customer_id (primary key)", "customer_id")
    dup = df.duplicated("customer_id", keep="first") & ~reject
    reject |= log.check(t, df, dup, "C01", "REJECTED", "Duplicate customer_id (first occurrence kept)", "customer_id")

    age = to_num(df.age)
    log.check(t, df, df.age.isna(), "C03", "FLAGGED", "Age missing (kept as NULL)", "customer_id")
    bad_age = df.age.notna() & (age.isna() | ~age.between(18, 75))
    log.check(t, df, bad_age, "C04", "FIXED", "Age non-numeric or outside 18-75 (set to NULL)", "customer_id")
    df["age"] = age.where(~bad_age)

    emp_l = df.employment_type.str.lower()
    mapped = emp_l.map(EMP_CANON)
    missing = is_blank(df.employment_type)
    log.check(t, df, missing, "C05", "FIXED", "Employment type missing (set to 'Unknown')", "customer_id")
    nonstd = mapped.notna() & (emp_raw.astype("string") != mapped)
    log.check(t, df, nonstd, "C06", "FIXED", "Employment type had inconsistent case/whitespace (standardised)", "customer_id")
    unrec = ~missing & mapped.isna()
    log.check(t, df, unrec, "C07", "FIXED", "Employment type not recognised (set to 'Unknown')", "customer_id")
    df["employment_type"] = mapped.fillna("Unknown")

    for col, valid, rid in [("gender", GENDERS, "C09a"), ("city_tier", TIERS, "C09b"), ("acquisition_channel", CHANNELS, "C09c")]:
        bad = ~df[col].isin(valid)
        log.check(t, df, bad, rid, "FIXED", f"{col} not in allowed domain (set to 'Unknown')", "customer_id")
        df[col] = df[col].where(~bad, "Unknown")

    sd = to_date(df.signup_date)
    bad_sd = df.signup_date.notna() & sd.isna()
    log.check(t, df, bad_sd, "C08", "FIXED", "signup_date is not a valid calendar date (set to NULL)", "customer_id")
    df["signup_date"] = sd

    clean = df.loc[~reject].drop(columns="_src_row").copy()
    clean["age"] = clean["age"].astype("Int64")
    clean["age_band"] = pd.cut(clean["age"].astype(float), [17, 24, 34, 44, 100],
                               labels=["18-24", "25-34", "35-44", "45+"]).astype("string")
    return clean.reset_index(drop=True)


def transform_profiles(raw: pd.DataFrame, raw_cust_ids, clean_cust_ids, log: IssueLog):
    t, key = "customer_financial_profiles", "profile_id"
    df = _strip_all(raw)
    reject = log.check(t, df, is_blank(df[key]), "P00", "REJECTED", "Missing profile_id (primary key)", key)
    reject |= log.check(t, df, df.duplicated(key, keep="first") & ~reject, "P01", "REJECTED",
                        "Duplicate profile_id (first occurrence kept)", key)
    reject |= _fk(log, t, df, "customer_id", raw_cust_ids, clean_cust_ids, "P02", "customers")

    inc = to_num(df.monthly_income)
    log.check(t, df, df.monthly_income.isna(), "P03", "FLAGGED", "monthly_income missing (kept as NULL, income_missing=TRUE)", key)
    reject |= log.check(t, df, df.monthly_income.notna() & (inc.isna() | (inc <= 0)), "P04", "REJECTED",
                        "monthly_income non-numeric or <= 0", key)
    cs = to_num(df.credit_score)
    log.check(t, df, df.credit_score.isna(), "P05a", "FLAGGED", "credit_score missing (kept as NULL)", key)
    bad_cs = df.credit_score.notna() & (cs.isna() | ~cs.between(300, 900))
    log.check(t, df, bad_cs, "P05", "FIXED", "credit_score outside 300-900 (set to NULL)", key)
    emi = to_num(df.existing_monthly_emi)
    reject |= log.check(t, df, emi.isna() | (emi < 0), "P06", "REJECTED", "existing_monthly_emi missing, non-numeric or negative", key)
    util = to_num(df.credit_utilization_pct)
    bad_u = util.isna() | ~util.between(0, 100)
    log.check(t, df, bad_u, "P07", "FIXED", "credit_utilization_pct missing or outside 0-100 (set to NULL)", key)
    pdate = to_date(df.profile_date)
    reject |= log.check(t, df, pdate.isna(), "P08", "REJECTED", "profile_date invalid", key)
    dep, yrs, prev = to_num(df.dependents), to_num(df.years_in_employment), to_num(df.previous_loans_count)
    reject |= log.check(t, df, dep.isna() | (dep < 0) | yrs.isna() | (yrs < 0) | prev.isna() | (prev < 0), "P09", "REJECTED",
                        "dependents / years_in_employment / previous_loans_count missing, non-numeric or negative", key)

    out = pd.DataFrame({
        "profile_id": df[key], "customer_id": df.customer_id, "profile_date": pdate,
        "monthly_income": inc.where(inc > 0), "income_missing": inc.isna() | (inc <= 0),
        "existing_monthly_emi": emi, "credit_score": cs.where(~bad_cs), "credit_utilization_pct": util.where(~bad_u),
        "dependents": dep, "home_ownership": df.home_ownership, "years_in_employment": yrs, "previous_loans_count": prev})
    out = out.loc[~reject].copy()
    out["credit_score"] = out["credit_score"].astype("Int64")
    out["dependents"] = out["dependents"].astype("Int64")
    out["previous_loans_count"] = out["previous_loans_count"].astype("Int64")
    out["income_bracket"] = pd.cut(out["monthly_income"], [0, 20000, 35000, 50000, 75000, np.inf], right=False,
                                   labels=["Below 20K", "20K-35K", "35K-50K", "50K-75K", "75K+"]).astype("string")
    return out.reset_index(drop=True)


def transform_loans(raw: pd.DataFrame, raw_cust_ids, clean_cust_ids, raw_prof_ids, clean_prof, snapshot: date, log: IssueLog):
    t, key = "loans", "loan_id"
    df = _strip_all(raw)
    reject = log.check(t, df, is_blank(df[key]), "L00", "REJECTED", "Missing loan_id (primary key)", key)
    reject |= log.check(t, df, df.duplicated(key, keep="first") & ~reject, "L01", "REJECTED",
                        "Duplicate loan_id (first occurrence kept)", key)
    reject |= _fk(log, t, df, "customer_id", raw_cust_ids, clean_cust_ids, "L02", "customers")
    reject |= _fk(log, t, df, "profile_id", raw_prof_ids, set(clean_prof.profile_id), "L03", "customer_financial_profiles")

    amt, emi = to_num(df.loan_amount), to_num(df.emi_amount)
    reject |= log.check(t, df, amt.isna() | (amt <= 0) | emi.isna() | (emi <= 0), "L04", "REJECTED",
                        "loan_amount / emi_amount missing, non-numeric or <= 0", key)
    rate = to_num(df.interest_rate)
    reject |= log.check(t, df, rate.isna() | ~rate.between(1, 60), "L05", "REJECTED", "interest_rate missing or outside 1-60 %", key)
    ten = to_num(df.tenure_months)
    reject |= log.check(t, df, ten.isna() | ~ten.between(1, 60) | (ten % 1 != 0), "L06", "REJECTED",
                        "tenure_months missing, non-integer or outside 1-60", key)
    disb, fdue, mat, snap = (to_date(df[c]) for c in ["disbursement_date", "first_due_date", "maturity_date", "snapshot_date"])
    reject |= log.check(t, df, disb.isna() | fdue.isna() | mat.isna() | snap.isna(), "L07", "REJECTED",
                        "A date column is missing or not a valid calendar date", key)
    reject |= log.check(t, df, disb > pd.Timestamp(snapshot), "L08", "REJECTED", "disbursement_date is after the snapshot date", key)
    out_bal, dpd = to_num(df.outstanding_balance), to_num(df.current_dpd)
    reject |= log.check(t, df, out_bal.isna() | (out_bal < 0) | (out_bal > amt * 1.001), "L09", "REJECTED",
                        "outstanding_balance missing, negative or greater than loan_amount", key)
    reject |= log.check(t, df, ~df.loan_status.isin(LOAN_STATUS), "L10", "REJECTED", "loan_status not in allowed domain", key)
    reject |= log.check(t, df, dpd.isna() | (dpd < 0), "L12", "REJECTED", "current_dpd missing or negative", key)
    inconsistent = (((df.loan_status == "CLOSED") & (out_bal > 0.5)) | ((df.loan_status == "DEFAULTED") & (dpd < 90))
                    | ((df.loan_status == "ACTIVE") & (dpd >= 90)))
    reject |= log.check(t, df, inconsistent, "L11", "REJECTED",
                        "loan_status inconsistent with outstanding_balance / current_dpd", key)

    out = pd.DataFrame({
        "loan_id": df[key], "customer_id": df.customer_id, "profile_id": df.profile_id, "loan_purpose": df.loan_purpose,
        "loan_amount": amt, "interest_rate": rate, "tenure_months": ten.astype("Int64") if ten.notna().all() else ten,
        "emi_amount": emi, "disbursement_date": disb, "first_due_date": fdue, "maturity_date": mat,
        "outstanding_balance": out_bal, "current_dpd": dpd, "loan_status": df.loan_status, "snapshot_date": snap})
    out = out.loc[~reject].copy()
    out["tenure_months"] = out["tenure_months"].astype(int)
    out["current_dpd"] = out["current_dpd"].astype(int)
    out["disbursement_month"] = out.disbursement_date.dt.to_period("M").dt.to_timestamp()
    sd = pd.Timestamp(snapshot)
    out["months_on_book"] = ((sd.year - out.disbursement_date.dt.year) * 12 + (sd.month - out.disbursement_date.dt.month)
                             - (sd.day < out.disbursement_date.dt.day).astype(int))
    out["dpd_bucket"] = dpd_bucket(out.current_dpd)
    prof = clean_prof.set_index("profile_id")
    inc = out.profile_id.map(prof.monthly_income)
    ex = out.profile_id.map(prof.existing_monthly_emi)
    out["foir"] = ((ex + out.emi_amount) / inc).round(4)
    return out.reset_index(drop=True)


def transform_repayments(raw: pd.DataFrame, raw_loans: pd.DataFrame, clean_loan_ids, log: IssueLog):
    t, key = "repayments", "repayment_id"
    df = _strip_all(raw)
    raw_ids = set(raw_loans.loan_id.astype("string").str.strip())
    disb_lookup = to_date(raw_loans.disbursement_date).groupby(raw_loans.loan_id.astype("string").str.strip()).first()

    reject = log.check(t, df, is_blank(df[key]), "R00", "REJECTED", "Missing repayment_id (primary key)", key)
    dup_pk = df.duplicated(key, keep="first") & ~reject
    reject |= log.check(t, df, dup_pk, "R01", "REJECTED", "Duplicate repayment_id (first occurrence kept)", key)
    dup_li = df[~dup_pk].duplicated(["loan_id", "installment_no"], keep="first").reindex(df.index, fill_value=False) & ~reject
    reject |= log.check(t, df, dup_li, "R09", "REJECTED", "Second record for the same (loan_id, installment_no)", key)
    reject |= _fk(log, t, df, "loan_id", raw_ids, set(clean_loan_ids), "R02", "loans")

    inst = to_num(df.installment_no)
    reject |= log.check(t, df, inst.isna() | (inst < 1) | (inst % 1 != 0), "R12", "REJECTED", "installment_no invalid", key)
    due_a, paid_a = to_num(df.due_amount), to_num(df.paid_amount)
    reject |= log.check(t, df, due_a.isna() | (due_a <= 0) | paid_a.isna() | (paid_a < 0), "R03", "REJECTED",
                        "due_amount missing/<=0 or paid_amount missing/negative", key)
    due_d, paid_d = to_date(df.due_date), to_date(df.paid_date)
    reject |= log.check(t, df, due_d.isna() | (df.paid_date.notna() & paid_d.isna()), "R04", "REJECTED",
                        "due_date or paid_date not a valid calendar date", key)
    reject |= log.check(t, df, (paid_a > 0) & df.paid_date.isna(), "R05", "REJECTED", "paid_amount > 0 but paid_date missing", key)
    st = df.repayment_status
    paid_status = st.isin(["PAID_ON_TIME", "PAID_LATE"])
    mismatch = (~st.isin(REPAY_STATUS) | ((st == "UNPAID") & (paid_a > 0)) | (paid_status & (paid_a < due_a - 0.01))
                | ((st == "PARTIAL") & ((paid_a <= 0) | (paid_a >= due_a))))
    reject |= log.check(t, df, mismatch, "R06", "REJECTED", "repayment_status inconsistent with paid_amount / due_amount", key)
    disb = df.loan_id.map(disb_lookup)
    reject |= log.check(t, df, paid_d < disb, "R07", "REJECTED", "paid_date is before the loan's disbursement_date", key)
    reject |= log.check(t, df, due_d <= disb, "R08", "REJECTED", "due_date is on/before the loan's disbursement_date", key)
    reject |= log.check(t, df, paid_a > due_a * 1.001, "R10", "REJECTED", "paid_amount exceeds due_amount (overpayment)", key)
    dpd = to_num(df.dpd)
    expected = (paid_d - due_d).dt.days.clip(lower=0)
    bad_dpd = dpd.isna() | (dpd < 0) | (paid_status & paid_d.notna() & due_d.notna() & (dpd != expected))
    reject |= log.check(t, df, bad_dpd, "R11", "REJECTED", "dpd negative/missing or inconsistent with paid_date - due_date", key)

    out = pd.DataFrame({
        "repayment_id": df[key], "loan_id": df.loan_id, "installment_no": inst, "due_date": due_d,
        "due_amount": due_a, "paid_amount": paid_a, "paid_date": paid_d, "dpd": dpd, "repayment_status": st})
    out = out.loc[~reject].copy()
    out["installment_no"] = out.installment_no.astype(int)
    out["dpd"] = out.dpd.astype(int)
    out["due_month"] = out.due_date.dt.to_period("M").dt.to_timestamp()
    out["dpd_bucket"] = dpd_bucket(out.dpd)
    out["is_late"] = out.dpd > 0
    return out.reset_index(drop=True)


def transform_collections(raw: pd.DataFrame, raw_loan_ids, clean_loan_ids, log: IssueLog):
    t, key = "collections", "collection_id"
    df = _strip_all(raw)
    reject = log.check(t, df, is_blank(df[key]), "K00", "REJECTED", "Missing collection_id (primary key)", key)
    reject |= log.check(t, df, df.duplicated(key, keep="first") & ~reject, "K01", "REJECTED",
                        "Duplicate collection_id (first occurrence kept)", key)
    reject |= _fk(log, t, df, "loan_id", raw_loan_ids, set(clean_loan_ids), "K02", "loans")
    due_a, rec = to_num(df.amount_due), to_num(df.amount_recovered)
    reject |= log.check(t, df, due_a.isna() | (due_a <= 0) | rec.isna() | (rec < 0), "K03", "REJECTED",
                        "amount_due missing/<=0 or amount_recovered missing/negative", key)
    reject |= log.check(t, df, rec > due_a * 1.001, "K04", "REJECTED", "amount_recovered exceeds amount_due", key)
    ad = to_date(df.action_date)
    reject |= log.check(t, df, ad.isna(), "K05", "REJECTED", "action_date invalid", key)
    reject |= log.check(t, df, ~df.channel.isin(COLL_CHANNEL) | ~df.outcome.isin(COLL_OUTCOME) | ~df.collection_status.isin(COLL_STATUS),
                        "K06", "REJECTED", "channel / outcome / collection_status not in allowed domain", key)
    dpd, inst = to_num(df.dpd_at_action), to_num(df.installment_no)
    reject |= log.check(t, df, dpd.isna() | (dpd < 0) | inst.isna() | (inst < 1), "K07", "REJECTED",
                        "dpd_at_action or installment_no invalid", key)
    out = pd.DataFrame({
        "collection_id": df[key], "loan_id": df.loan_id, "installment_no": inst, "action_date": ad, "dpd_at_action": dpd,
        "channel": df.channel, "outcome": df.outcome, "amount_due": due_a, "amount_recovered": rec,
        "collection_status": df.collection_status})
    out = out.loc[~reject].copy()
    out["installment_no"] = out.installment_no.astype(int)
    out["dpd_at_action"] = out.dpd_at_action.astype(int)
    out["action_month"] = out.action_date.dt.to_period("M").dt.to_timestamp()
    out["dpd_bucket"] = dpd_bucket(out.dpd_at_action)
    return out.reset_index(drop=True)


def _expected_installments(disb: date, tenure: int, snapshot: date) -> int:
    n = 0
    for j in range(1, tenure + 1):
        y = disb.year + (disb.month - 1 + j) // 12
        m = (disb.month - 1 + j) % 12 + 1
        due = date(y, m, min(disb.day, calendar.monthrange(y, m)[1]))
        if due < snapshot:
            n += 1
    return n


def reconcile(clean: dict, snapshot: date, log: IssueLog) -> None:
    """Cross-table consistency checks (flag-only): reported DPD and installment completeness."""
    loans, rep = clean["loans"], clean["repayments"]
    t = "loans"
    unpaid = rep[rep.repayment_status.isin(["UNPAID", "PARTIAL"])].groupby("loan_id").dpd.max()
    recomputed = loans.loan_id.map(unpaid).fillna(0)
    ldf = loans.assign(_src_row=-1)   # clean frame carries no source row number
    mism = (loans.loan_status != "CLOSED") & (recomputed != loans.current_dpd)
    log.check(t, ldf, mism, "X01", "FLAGGED",
              "Reported current_dpd differs from DPD recomputed from clean repayments "
              "(may be explained by quarantined installments)", "loan_id")
    have = rep.groupby("loan_id").size()
    expected = pd.Series([_expected_installments(d.date(), int(n), snapshot)
                          for d, n in zip(loans.disbursement_date, loans.tenure_months)], index=loans.index)
    missing = expected - loans.loan_id.map(have).fillna(0)
    log.check(t, ldf, missing != 0, "X02", "FLAGGED",
              "Number of clean repayment rows differs from the number of installments due by the snapshot "
              "(usually a quarantined installment)", "loan_id")


def transform_all(raw: dict, snapshot: date) -> TransformResult:
    log = IssueLog()
    raw_cust_ids = set(raw["customers"].customer_id.astype("string").str.strip().dropna())
    cust = transform_customers(raw["customers"], log)
    raw_prof_ids = set(raw["customer_financial_profiles"].profile_id.astype("string").str.strip().dropna())
    prof = transform_profiles(raw["customer_financial_profiles"], raw_cust_ids, set(cust.customer_id), log)
    raw_loan_ids = set(raw["loans"].loan_id.astype("string").str.strip().dropna())
    loans = transform_loans(raw["loans"], raw_cust_ids, set(cust.customer_id), raw_prof_ids, prof, snapshot, log)
    rep = transform_repayments(raw["repayments"], raw["loans"], set(loans.loan_id), log)
    col = transform_collections(raw["collections"], raw_loan_ids, set(loans.loan_id), log)
    clean = dict(customers=cust, customer_financial_profiles=prof, loans=loans, repayments=rep, collections=col)
    reconcile(clean, snapshot, log)
    issues = log.issues_df()
    counts = pd.DataFrame([table_counts(n, len(raw[n]), len(clean[n]), issues) for n in clean])
    return TransformResult(clean, issues, log.rules_df(), counts)
