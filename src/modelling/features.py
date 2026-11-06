"""Feature definitions and dataset construction for the models - with leakage controls.

PREDICTION POINT = loan origination. A model may only use information that exists on the disbursement date:
the customer's attributes, the financial profile as at application, and the loan terms.

NEVER allowed as features (they are outcomes or are computed from the repayment history):
  loan_status, current_dpd, outstanding_balance, dpd_bucket, months_on_book, any repayments.* / collections.* value,
  and the targets themselves.  tests/test_features.py asserts this list is respected.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src import config

NUMERIC_FEATURES = ["age", "monthly_income", "existing_monthly_emi", "credit_score", "credit_utilization_pct",
                    "dependents", "years_in_employment", "previous_loans_count", "loan_amount", "interest_rate",
                    "tenure_months", "emi_amount", "foir", "loan_to_income"]
CATEGORICAL_FEATURES = ["employment_type", "gender", "city_tier", "acquisition_channel", "loan_purpose", "home_ownership"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES

FORBIDDEN_FEATURES = ["loan_status", "current_dpd", "outstanding_balance", "dpd_bucket", "months_on_book", "is_default",
                      "repayment_ratio_6", "maturity_date", "snapshot_date", "disbursement_date", "disbursement_month",
                      "due_date", "paid_date", "paid_amount", "dpd", "repayment_status", "amount_recovered"]

MATURE_MOB = 15          # default target observable: loan has had >= 15 months on book
REPAY_MOB = 9            # first 6 instalments fully observable (late payers have had time to pay)
TRAIN_END_DEFAULT = pd.Timestamp("2024-09-30")      # out-of-time split for the default model
TRAIN_END_REPAY = pd.Timestamp("2025-01-31")        # out-of-time split for the repayment model


def loan_frame(t: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """One row per loan: loan terms + customer attributes + profile at application (all known at origination)."""
    L, C, P = t["loans"], t["customers"], t["customer_financial_profiles"]
    df = (L.merge(C[["customer_id", "age", "gender", "city_tier", "employment_type", "acquisition_channel"]],
                  on="customer_id", how="left")
           .merge(P[["profile_id", "monthly_income", "existing_monthly_emi", "credit_score", "credit_utilization_pct",
                     "dependents", "home_ownership", "years_in_employment", "previous_loans_count"]],
                  on="profile_id", how="left"))
    df["loan_to_income"] = df.loan_amount / df.monthly_income
    df["is_default"] = (df.loan_status == "DEFAULTED").astype(int)
    return df


def default_dataset(t) -> pd.DataFrame:
    df = loan_frame(t)
    return df[df.months_on_book >= MATURE_MOB].copy()


def repayment_dataset(t) -> pd.DataFrame:
    """Target: share of the first 6 instalments' due amount actually paid (0..1). Only loans with all 6 rows present."""
    df = loan_frame(t)
    df = df[df.months_on_book >= REPAY_MOB]
    R = t["repayments"]
    first6 = R[R.installment_no <= 6].groupby("loan_id").agg(n=("installment_no", "count"), paid=("paid_amount", "sum"),
                                                              due=("due_amount", "sum"))
    first6 = first6[first6.n == 6]
    first6["repayment_ratio_6"] = (first6.paid / first6.due).clip(0, 1)
    return df.merge(first6[["repayment_ratio_6"]], left_on="loan_id", right_index=True, how="inner")


def temporal_split(df: pd.DataFrame, train_end: pd.Timestamp):
    """Out-of-time split: train on earlier disbursements, test on later ones (mimics real deployment)."""
    tr = df[df.disbursement_date <= train_end]
    te = df[df.disbursement_date > train_end]
    return tr, te


def make_preprocessor(scale: bool) -> ColumnTransformer:
    """Fit on TRAIN ONLY (inside a Pipeline). Median imputation + missing indicators; one-hot for categories."""
    num_steps = [("impute", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        num_steps.append(("scale", StandardScaler()))
    return ColumnTransformer([
        ("num", Pipeline(num_steps), NUMERIC_FEATURES),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="constant", fill_value="Unknown")),
                          ("onehot", OneHotEncoder(handle_unknown="ignore", min_frequency=20))]), CATEGORICAL_FEATURES),
    ])
