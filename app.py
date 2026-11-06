"""FinSight - Lending & Business Analytics (Streamlit).

    streamlit run app.py

Data sources: (1) bundled SYNTHETIC demo data (PostgreSQL if reachable, else data/processed CSVs),
              (2) your own CSV uploads (session memory only; never written to PostgreSQL or disk).
The app is read-only. ALL bundled data is synthetic and must not be read as real lending statistics.
"""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src import config, kpis
from src.app_data import REQUIRED, build_frames, load_local, load_results, local_data_available, validate_upload

st.set_page_config(page_title="FinSight | Lending Analytics", page_icon="📊", layout="wide")
PALETTE = ["#2a6f97", "#c44e52", "#8c9bb0", "#55a868", "#dd8452", "#8172b3"]
px.defaults.color_discrete_sequence = PALETTE
px.defaults.template = "plotly_white"
st.markdown("""<style>
.block-container {max-width: 1400px; padding-top: 1.2rem;}
[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.25); border-radius: 10px; padding: 12px 16px;}
.syn {border-left: 4px solid #dd8452; padding: 8px 14px; background: rgba(221,132,82,.10); border-radius: 4px; font-size: .9rem;}
</style>""", unsafe_allow_html=True)


def inr(v) -> str:
    if v is None or pd.isna(v):
        return "-"
    return f"₹{v/1e7:,.2f} Cr" if abs(v) >= 1e7 else f"₹{v:,.0f}"


def pct(v, d=2) -> str:
    return "-" if v is None or pd.isna(v) else f"{v:.{d}f}%"


# --------------------------------------------------------------------- data
@st.cache_data(show_spinner="Loading data...")
def _local():
    return load_local()


with st.sidebar:
    st.title("FinSight")
    st.caption("Lending & Business Analytics")
    mode = st.radio("Data source", ["Synthetic demo data", "Upload my CSVs"], help="Uploads stay in this browser session; nothing is stored.")
    prep = None
    if mode == "Synthetic demo data":
        if local_data_available():
            prep = _local()
        else:
            try:
                prep = _local()
            except Exception:
                st.error("No demo data found. Run `python -m etl.run_pipeline --generate --no-db` first (see README).")
    else:
        st.caption("Upload files using the FinSight column names (see docs/data_dictionary.md). Loans is required; the others unlock more pages.")
        ups, problems = {}, []
        for key in ["loans", "repayments", "collections", "customers", "customer_financial_profiles"]:
            f = st.file_uploader(key.replace("_", " ").title(), type="csv", key=f"up_{key}")
            if f is not None:
                try:
                    df = pd.read_csv(f)
                    problems += validate_upload(key, df)
                    ups[key] = df
                except Exception as e:
                    problems.append(f"{key}: could not read CSV ({type(e).__name__})")
        for p in problems:
            st.error(p)
        if "loans" in ups and not any(p.startswith("loans") for p in problems):
            prep = build_frames(ups, "Uploaded CSV files (session only)")

if prep is None:
    st.title("FinSight")
    st.info("Choose a data source in the sidebar. For uploads, start with a Loans CSV.")
    st.stop()

loans_all, rep_all, col_all = prep.loans, prep.repayments, prep.collections

# filters
with st.sidebar:
    st.divider(); st.subheader("Filters")
    lo, hi = loans_all.disbursement_date.min().date(), loans_all.disbursement_date.max().date()
    dr = st.date_input("Disbursement date", (lo, hi), min_value=lo, max_value=hi)
    d0, d1 = (dr if isinstance(dr, tuple) and len(dr) == 2 else (lo, hi))
    flt = {}
    for col, label in [("employment_type", "Employment type"), ("city_tier", "City tier"), ("acquisition_channel", "Acquisition channel")]:
        if col in loans_all.columns:
            opts = sorted(loans_all[col].dropna().unique())
            flt[col] = st.multiselect(label, opts, default=opts)
    st.caption(f"Data: {prep.source}  |  As-of date: {prep.snapshot.date()}")

loans = loans_all[(loans_all.disbursement_date.dt.date >= d0) & (loans_all.disbursement_date.dt.date <= d1)]
for c, sel in flt.items():
    loans = loans[loans[c].isin(sel)]
ids = set(loans.loan_id)
rep = rep_all[rep_all.loan_id.isin(ids)] if len(rep_all) else rep_all
col = col_all[col_all.loan_id.isin(ids)] if len(col_all) else col_all

st.title("FinSight - Lending & Business Analytics")
if mode == "Synthetic demo data":
    st.markdown('<div class="syn"><b>SYNTHETIC DATA.</b> Everything shown is simulated for a portfolio project. Figures are not real lending statistics, '
                'and model/test results describe the simulation, not the real world.</div>', unsafe_allow_html=True)
for w in prep.warnings:
    st.warning(w)
if loans.empty:
    st.warning("No loans match the current filters."); st.stop()
if loans.loan_id.duplicated().any():
    st.warning("Duplicate loan_id values in loans; KPIs may be inflated.")

tabs = st.tabs(["Portfolio overview", "Credit & risk", "Collections", "Models & statistics", "Data quality", "About"])

# ------------------------------------------------------------- 1 Portfolio
with tabs[0]:
    k = kpis.portfolio_kpis(loans)
    c = st.columns(5)
    c[0].metric("Total disbursement", inr(k["total_disbursed"]), help="Sum of loan_amount for filtered loans")
    c[1].metric("Outstanding portfolio", inr(k["outstanding"]), help="Principal outstanding at the as-of date")
    c[2].metric("Active loans", f"{k['active_loans']:,}", help="loan_status = ACTIVE (excludes CLOSED and DEFAULTED)")
    c[3].metric("Average loan amount", inr(k["avg_loan"]))
    c[4].metric("Portfolio delinquency rate", pct(k["delinquency_rate_pct"]), help="PAR30: balance of open loans 30+ DPD / balance of open loans")
    a, b = st.columns(2)
    d = kpis.disbursement_by_month(loans)
    f = px.bar(d, x="disbursement_month", y="amount", title="Monthly disbursement"); f.update_layout(xaxis_title=None, yaxis_title="Amount disbursed (₹)")
    a.plotly_chart(f, width="stretch")
    mo = loans.groupby("disbursement_month").outstanding_balance.sum().reset_index()
    f = px.area(mo, x="disbursement_month", y="outstanding_balance", title="Outstanding balance today, by disbursement month (vintage)")
    f.update_layout(xaxis_title=None, yaxis_title="Outstanding (₹)"); b.plotly_chart(f, width="stretch")
    a, b = st.columns(2)
    sm = loans.loan_status.value_counts().rename_axis("status").reset_index(name="loans")
    a.plotly_chart(px.pie(sm, names="status", values="loans", hole=.55, title="Loan status distribution"), width="stretch")
    seg_col = st.session_state.get("seg", "employment_type")
    seg_opts = [c_ for c_ in ["employment_type", "city_tier", "acquisition_channel", "income_bracket", "age_band", "loan_purpose"] if c_ in loans.columns]
    with b:
        seg_col = st.selectbox("Segment breakdown by", seg_opts, key="seg") if seg_opts else None
        if seg_col:
            sg = loans.groupby(seg_col).agg(loans=("loan_id", "count"), outstanding=("outstanding_balance", "sum"), avg_loan=("loan_amount", "mean")).reset_index().sort_values("outstanding", ascending=False)
            f = px.bar(sg, x=seg_col, y="outstanding", hover_data=["loans", "avg_loan"], title=f"Outstanding by {seg_col}"); f.update_layout(xaxis_title=None)
            st.plotly_chart(f, width="stretch")
    with st.expander("Month-over-month disbursement table"):
        st.dataframe(d.assign(amount=d.amount.round(0), mom_change_pct=d.mom_change_pct.round(1)), width="stretch", hide_index=True)

# ------------------------------------------------------------- 2 Risk
with tabs[1]:
    k = kpis.portfolio_kpis(loans); dr_ = kpis.default_rate_overall(loans)
    c = st.columns(4)
    c[0].metric("Default rate (mature loans)", pct(dr_["default_rate_pct"]), help=f"{dr_['defaults']:,} defaults / {dr_['mature_loans']:,} loans with >= 15 months on book")
    c[1].metric("Delinquency rate (PAR30)", pct(k["delinquency_rate_pct"]))
    c[2].metric("Average DPD (open loans)", f"{k['avg_dpd_open']:.1f}")
    c[3].metric("High-risk exposure (60+ DPD)", inr(k["high_risk_exposure"]))
    st.caption("Default rates use only loans with >= 15 months on book. Younger loans have not had time to default, so including them would understate risk.")
    a, b = st.columns(2)
    for holder, col_name, title in [(a, "income_bracket", "Default rate by income group"), (b, "employment_type", "Default rate by employment type")]:
        if col_name in loans.columns:
            g = kpis.default_rate_by(loans, col_name, min_n=30)
            f = px.bar(g, x=col_name, y="default_rate_pct", error_y=g.ci_high - g.default_rate_pct, error_y_minus=g.default_rate_pct - g.ci_low, hover_data=["mature_loans", "defaults"], title=title + " (95% CI)")
            f.update_layout(xaxis_title=None, yaxis_title="Default rate (%)"); holder.plotly_chart(f, width="stretch")
        else:
            holder.info(f"Upload customers / profiles to see {title.lower()}.")
    a, b = st.columns(2)
    dd = kpis.dpd_distribution(loans)
    a.plotly_chart(px.bar(dd, x="dpd_bucket", y="outstanding", hover_data=["loans", "pct_of_open_book"], title="DPD distribution (open loans, by outstanding)"), width="stretch")
    if len(rep):
        co = kpis.cohort_performance(loans, rep)
        f = px.line(co, x="disbursement_month", y=["pct_30dpd_first6", "default_rate_pct_mature"], markers=True, title="Loan cohort performance")
        f.update_layout(xaxis_title=None, yaxis_title="%", legend_title=None); b.plotly_chart(f, width="stretch")
        st.caption("Cohorts are compared at the same age: share reaching 30+ DPD within the first 6 instalments (all cohorts with >= 7 months on book), and default rate for mature cohorts only.")
    else:
        b.info("Upload a Repayments CSV to see cohort performance.")
    if "credit_band" in loans.columns:
        g = kpis.default_rate_by(loans, "credit_band", min_n=30).sort_values("credit_band")
        st.plotly_chart(px.bar(g, x="credit_band", y="default_rate_pct", hover_data=["mature_loans"], title="Default rate by credit-score band"), width="stretch")

# ------------------------------------------------------------- 3 Collections
with tabs[2]:
    if not len(col):
        st.info("No collections data loaded.")
    else:
        ck = kpis.collections_kpis(loans, col)
        ov = kpis.overdue_amount(rep, loans) if len(rep) else float("nan")
        c = st.columns(4)
        c[0].metric("Total overdue amount", inr(ov), help="Unpaid + partial instalment shortfall on open loans")
        c[1].metric("Amount collected", inr(ck["amount_collected"]), help="Recovered across collection cases")
        c[2].metric("Recovery rate", pct(ck["recovery_rate_pct"]), help="Recovered / amount due, per case (loan, instalment), not per action")
        c[3].metric("Overdue accounts", f"{ck['overdue_accounts']:,}", help="Open loans with current_dpd > 0")
        a, b = st.columns(2)
        ma = col.groupby("action_month").agg(recovered=("amount_recovered", "sum"), actions=("collection_id", "count")).reset_index()
        a.plotly_chart(px.bar(ma, x="action_month", y="recovered", title="Monthly collections (amount recovered)"), width="stretch")
        rb = kpis.recovery_by_dpd_bucket(col)
        b.plotly_chart(px.bar(rb, x="bucket", y="recovery_rate_pct", hover_data=["cases"], title="Recovery rate by DPD bucket reached"), width="stretch")
        a, b = st.columns(2)
        a.plotly_chart(px.pie(col.collection_status.value_counts().rename_axis("status").reset_index(name="actions") if "collection_status" in col else col.outcome.value_counts().rename_axis("status").reset_index(name="actions"),
                              names="status", values="actions", hole=.5, title="Collection status distribution (actions)"), width="stretch")
        op = loans[(loans.loan_status != "CLOSED") & (loans.current_dpd > 0)]
        sc = "employment_type" if "employment_type" in op.columns else "dpd_bucket"
        sg = op.groupby(sc).outstanding_balance.sum().reset_index().sort_values("outstanding_balance", ascending=False)
        b.plotly_chart(px.bar(sg, x=sc, y="outstanding_balance", title=f"Overdue exposure by {sc} (outstanding of loans with DPD > 0)"), width="stretch")
        st.caption("Recovery by channel is NOT causal: channels are used at different DPD stages (SMS early, legal notices late), so do not read channel rates as channel quality.")

# ------------------------------------------------------------- 4 Models
with tabs[3]:
    stt, mld, mrp = load_results("statistics"), load_results("ml_default"), load_results("ml_repayment")
    if not (stt or mld or mrp):
        st.info("Run the analysis scripts to populate this tab (see README): `python -m src.analytics.statistics_analysis`, `python -m src.modelling.default_model`, `python -m src.modelling.repayment_model`.")
    if mode != "Synthetic demo data" and (stt or mld or mrp):
        st.warning("These results were computed on the bundled synthetic data, not on your uploads.")
    if stt:
        st.subheader("Hypothesis tests (Holm-adjusted)")
        hs = pd.DataFrame(stt["holm_summary"]).rename(columns={"test": "Hypothesis", "p_raw": "p-value", "p_holm": "Holm-adjusted p", "reject_H0_at_5pct": "Reject H0 (5%)"})
        st.dataframe(hs.style.format({"p-value": "{:.3g}", "Holm-adjusted p": "{:.3g}"}), hide_index=True, width="stretch")
        h = stt["hypotheses"]
        st.caption(f"Gig vs salaried default-rate difference: {100*h['H1']['diff']:.1f} pp (95% CI {100*h['H1']['diff_ci'][0]:.1f} to {100*h['H1']['diff_ci'][1]:.1f}). "
                   f"Gender (female vs male): {100*h['H2']['diff']:.1f} pp, p = {h['H2']['p_value']:.2f} - no evidence of a difference (the simulation has no gender effect). "
                   "Significance is not importance, and all tests are observational.")
    if mld:
        st.subheader("Default classification (out-of-time test)")
        m = pd.DataFrame(mld["metrics"]).T[["roc_auc_test", "pr_auc_test", "precision", "recall", "f1", "threshold"]]
        st.dataframe(m.style.format("{:.3f}"), width="stretch")
        ld = mld["leakage_demo"]
        st.caption(f"Leakage demo: a model that is given current_dpd scores AUC {ld['leaky_auc']:.2f} but is unusable at origination; the honest out-of-time AUC is {ld['honest_out_of_time_auc']:.2f}. "
                   f"Top-20% riskiest loans capture {100*mld['top20pct_capture']:.0f}% of defaults.")
    if mrp:
        st.subheader("Repayment regression (first 6 instalments)")
        st.dataframe(pd.DataFrame(mrp["metrics"]).T[["MAE", "RMSE", "R2"]].style.format("{:.4f}"), width="stretch")
    figs = [("ml_default_roc_confusion", "ROC and confusion matrices"), ("ml_default_importance", "Permutation importance"), ("stats_ci_employment", "Default rate CIs")]
    for fname, cap in figs:
        p = config.FIGURES / f"{fname}.png"
        if p.exists():
            st.image(str(p), caption=cap + " (synthetic data)")

# ------------------------------------------------------------- 5 Data quality
with tabs[4]:
    p = config.REPORTS / "data_quality_report.md"
    st.subheader("ETL data-quality report")
    if p.exists():
        st.markdown(p.read_text(encoding="utf-8"))
    else:
        st.info("No ETL report found. Run `python -m etl.run_pipeline --no-db`.")
    st.subheader("Loaded data profile")
    prof = pd.DataFrame([{"table": n, "rows": len(df), "columns": df.shape[1], "missing cells": int(df.isna().sum().sum())}
                         for n, df in [("loans", loans_all), ("repayments", rep_all), ("collections", col_all)] if len(df)])
    st.dataframe(prof, hide_index=True, width="stretch")

# ------------------------------------------------------------- 6 About
with tabs[5]:
    st.markdown(f"""
**What this is.** FinSight is a portfolio analytics project: a reproducible synthetic data generator, an ETL with data-quality quarantine, PostgreSQL analytics schema,
28 documented SQL queries, EDA / statistics / ML scripts, and Power BI specifications. This app is a read-only view over that work.

**KPI definitions** (same in SQL, this app and Power BI):
- *Default*: 90+ days past due at the as-of date. *Default rate*: defaults / loans, **mature loans only** (>= 15 months on book).
- *Delinquency rate (PAR30)*: balance of open loans 30+ DPD / balance of open loans. *High-risk exposure*: balance of open loans 60+ DPD.
  **Simulation caveat:** defaulted loans stay on the book at full outstanding balance (no write-offs are simulated), so PAR30 here is far higher than a real lender would report after write-offs.
- *Recovery rate*: recovered / due on collection **cases**, not actions.

**Limits.** Synthetic data; no authentication or role-based access; no audit trail of user activity; uploads are validated for required columns only; KPI definitions should be confirmed with a business owner before any real use.
Not a credit-decision system.
""")
    st.caption(f"As-of date: {prep.snapshot.date()} | Source: {prep.source}")
