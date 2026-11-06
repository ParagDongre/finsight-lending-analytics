# %% [markdown]
# # 01 - Exploratory Data Analysis (SYNTHETIC data)
# **Goal:** understand distributions, missing values, outliers, segments and repayment trends *before* modelling.
# **Reminder:** every number below describes the simulation. The simulator has *designed* effects (see docs/simulation_design.md),
# so EDA here shows whether we can recover them, not real-world lending behaviour.

# %%
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

from src.data_access import load_tables
from src.analytics.common import setup, save_fig, save_results, banner
from src.modelling.features import loan_frame

setup(); banner()
t = load_tables()
df = loan_frame(t)
R, K = t["repayments"], t["collections"]
results = {}
print({k: v.shape for k, v in t.items()})

# %% [markdown]
# ## 1. Missing-value analysis
# Missingness is reported per column. Missing income / credit score / age were *kept as NULL* by the ETL (never silently imputed).
# We check whether missingness is related to default (if it were, the missing flag itself would carry signal).

# %%
miss_cols = ["age", "monthly_income", "credit_score", "credit_utilization_pct", "employment_type"]
miss = pd.DataFrame({"missing_n": df[miss_cols].isna().sum(), "missing_pct": (df[miss_cols].isna().mean() * 100).round(2)})
miss.loc["employment_type (== 'Unknown')", :] = [(df.employment_type == "Unknown").sum(), round((df.employment_type == "Unknown").mean() * 100, 2)]
print(miss)
mature = df[df.months_on_book >= 15]
mm = {}
for c in ["monthly_income", "credit_score", "age"]:
    mm[c] = {"default_rate_missing_pct": round(100 * mature.loc[mature[c].isna(), "is_default"].mean(), 2),
             "default_rate_present_pct": round(100 * mature.loc[mature[c].notna(), "is_default"].mean(), 2),
             "n_missing": int(mature[c].isna().sum())}
print(pd.DataFrame(mm).T)
results["missing"] = {"table": miss.to_dict(), "default_rate_by_missingness": mm}

fig, ax = plt.subplots(figsize=(6, 3))
miss["missing_pct"].iloc[:5].plot.barh(ax=ax, color="#4c72b0"); ax.set_xlabel("% missing"); ax.set_title("Missing values (loan-level frame)")
save_fig(fig, "eda_missing")

# %% [markdown]
# ## 2. Distributions of loan amount, income, interest rate
# Money variables are right-skewed: the **mean exceeds the median**, so we report both and view the log scale.

# %%
cols = ["loan_amount", "monthly_income", "interest_rate", "credit_score"]
desc = df[cols].describe(percentiles=[.05, .25, .5, .75, .95]).T
desc["skew"] = df[cols].skew()
print(desc.round(2))
results["distribution_summary"] = desc.round(3).to_dict()

fig, axes = plt.subplots(2, 3, figsize=(13, 6))
for ax, (c, log) in zip(axes.ravel(), [("loan_amount", False), ("loan_amount", True), ("monthly_income", False),
                                       ("monthly_income", True), ("interest_rate", False), ("credit_score", False)]):
    x = np.log10(df[c].dropna()) if log else df[c].dropna()
    sns.histplot(x, bins=50, ax=ax, color="#4c72b0"); ax.set_title(f"{c}" + (" (log10)" if log else ""))
save_fig(fig, "eda_distributions")

# %% [markdown]
# ## 3. Outlier analysis (IQR rule and z-score)
# Outliers are **flagged, not removed**: very large loans/incomes are plausible. We check whether outliers behave differently.

# %%
def iqr_outliers(s):
    q1, q3 = s.quantile([.25, .75]); iqr = q3 - q1
    return (s < q1 - 1.5 * iqr) | (s > q3 + 1.5 * iqr)

out = {}
for c in ["loan_amount", "monthly_income", "loan_to_income", "foir"]:
    s = df[c].dropna(); m = iqr_outliers(s)
    mat = df.loc[s.index][df.loc[s.index].months_on_book >= 15]
    mm_ = iqr_outliers(mat[c].dropna())
    out[c] = {"iqr_outliers": int(m.sum()), "pct": round(100 * m.mean(), 2),
              "default_rate_outliers_pct": round(100 * mat.loc[mm_[mm_].index, "is_default"].mean(), 2),
              "default_rate_non_outliers_pct": round(100 * mat.loc[mm_[~mm_].index, "is_default"].mean(), 2)}
print(pd.DataFrame(out).T)
results["outliers"] = out
fig, axes = plt.subplots(1, 3, figsize=(12, 3.5))
for ax, c in zip(axes, ["loan_amount", "monthly_income", "foir"]):
    sns.boxplot(x=df[c], ax=ax, color="#8da0cb", fliersize=2); ax.set_title(c)
save_fig(fig, "eda_outliers")

# %% [markdown]
# ## 4. Customer segmentation
# Segments by employment type x city tier. Default rate uses **mature loans only** (>= 15 months on book): younger loans have not
# had time to default (right-censoring), so including them would understate risk.

# %%
mature = df[df.months_on_book >= 15]
seg = (mature.groupby("employment_type").agg(loans=("loan_id", "count"), default_rate=("is_default", "mean"),
                                             avg_loan=("loan_amount", "mean"), avg_income=("monthly_income", "median"),
                                             avg_credit=("credit_score", "mean")).sort_values("default_rate", ascending=False))
seg["default_rate"] = (seg.default_rate * 100).round(2)
print(seg.round(1))
heat = mature.pivot_table(index="employment_type", columns="city_tier", values="is_default", aggfunc="mean") * 100
print(heat.round(1))
results["segments_by_employment"] = seg.round(2).to_dict()
fig, axes = plt.subplots(1, 2, figsize=(12, 4))
seg["default_rate"].plot.barh(ax=axes[0], color="#c44e52"); axes[0].set_title("Default rate % by employment type (mature loans)")
sns.heatmap(heat, annot=True, fmt=".1f", cmap="Reds", ax=axes[1]); axes[1].set_title("Default rate % - employment x city tier")
save_fig(fig, "eda_segments")

# %% [markdown]
# ## 5. Relationships with default (univariate)
# Default rate by decile of credit score, FOIR, and loan-to-income. A monotone pattern suggests a usable risk signal.

# %%
fig, axes = plt.subplots(1, 3, figsize=(14, 3.8))
dec = {}
for ax, c in zip(axes, ["credit_score", "foir", "loan_to_income"]):
    q = pd.qcut(mature[c], 10, duplicates="drop")
    r = mature.groupby(q, observed=True).is_default.mean() * 100
    dec[c] = [round(v, 2) for v in r.values]
    ax.plot(range(1, len(r) + 1), r.values, marker="o", color="#c44e52"); ax.set_title(f"Default % by {c} decile"); ax.set_xlabel("decile (1 = lowest)")
save_fig(fig, "eda_default_by_decile")
results["default_by_decile"] = dec
print(dec)

# %% [markdown]
# ## 6. Repayment trends over time
# Share of instalments not paid on the due date, by due month. **Caution:** the most recent months are biased - some late payers
# have not paid *yet*, and the portfolio mix changes (more young loans). So we also look at *cohort* views (Section 7).

# %%
R2 = R.assign(late=(R.dpd > 0).astype(int), unpaid=R.repayment_status.isin(["UNPAID", "PARTIAL"]).astype(int))
trend = R2.groupby("due_month").agg(installments=("late", "size"), late_pct=("late", "mean"), unpaid_pct=("unpaid", "mean"))
trend[["late_pct", "unpaid_pct"]] *= 100
print(trend.round(2).tail(8))
fig, ax = plt.subplots(figsize=(9, 3.8))
trend[["late_pct", "unpaid_pct"]].plot(ax=ax); ax.set_title("Instalments not paid on time, by due month (%)"); ax.set_ylabel("%")
save_fig(fig, "eda_repayment_trend")
results["repayment_trend_last6"] = trend.tail(6).round(2).reset_index().astype({"due_month": str}).to_dict("records")

# %% [markdown]
# ## 7. Cohort view - does newer vintage perform worse *at the same age*?
# We compare the % of loans with a 30+ DPD instalment among the **first 6 instalments**, for cohorts old enough to have all 6 observed.

# %%
first6 = R[R.installment_no <= 6].groupby("loan_id").dpd.max().rename("max_dpd_first6")
c7 = df[df.months_on_book >= 7].merge(first6, left_on="loan_id", right_index=True)
c7["hit30"] = (c7.max_dpd_first6 >= 30).astype(int)
cohort = c7.groupby("disbursement_month").agg(loans=("loan_id", "count"), pct_30dpd_first6=("hit30", "mean"))
cohort["pct_30dpd_first6"] *= 100
print(cohort.round(2).iloc[::3])
fig, ax = plt.subplots(figsize=(9, 3.8))
cohort["pct_30dpd_first6"].plot(marker="o", ax=ax, color="#c44e52"); ax.set_title("% of loans reaching 30+ DPD within first 6 instalments, by cohort"); ax.set_ylabel("%")
save_fig(fig, "eda_cohort_30dpd_first6")
results["cohort_30dpd_first6"] = cohort.round(2).reset_index().astype({"disbursement_month": str}).to_dict("records")

# %% [markdown]
# ## 8. Collections overview

# %%
cases = K.groupby(["loan_id", "installment_no"]).agg(due=("amount_due", "max"), rec=("amount_recovered", "sum"), max_dpd=("dpd_at_action", "max"))
cases["bucket"] = pd.cut(cases.max_dpd, [0, 29, 59, 89, 1e9], labels=["1-29", "30-59", "60-89", "90+"])
rec = cases.groupby("bucket", observed=True).agg(cases=("due", "size"), due=("due", "sum"), rec=("rec", "sum"))
rec["recovery_rate_pct"] = (100 * rec.rec / rec.due).round(2)
print(rec)
results["collections_recovery_by_dpd_bucket"] = rec.reset_index().astype({"bucket": str}).to_dict("records")
save_results("eda", results)
