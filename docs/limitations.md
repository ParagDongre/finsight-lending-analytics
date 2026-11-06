# Known limitations

**Evidence status.** What was actually executed and tested in building this repository: data generation, ETL into PostgreSQL 16, 28 SQL queries (executed; several cross-checked in pandas), EDA / statistics / both models (executed, results in `reports/results/`), four executed notebooks, a headless Streamlit smoke test, and 114 automated tests. What was **not** done: a Power BI `.pbix` (no Power BI Desktop available; specification and DAX only), a deployment of the Streamlit app to a hosting service, any test against real data, a security review.

1. **Synthetic data.** All findings describe a simulation with planted effects; they are not lending benchmarks.
2. **No write-offs (L1).** Defaulted loans stay at full balance, inflating PAR30 and "defaulted share of outstanding".
3. **Right-censoring.** Default is observed only for mature loans (>= 15 months); recent cohorts are assessed only through early-delinquency measures.
4. **Association, not causation.** Applies to the regression, the models and the collections-channel comparisons.
5. **Selection bias.** Only funded loans exist; no rejected-applicant data (reject inference not attempted).
6. **Model scope.** One out-of-time split; no hyperparameter search, calibration or fairness audit; class weighting distorts probabilities.
7. **Repeat borrowers** create non-independence; reported p-values are slightly optimistic.
8. **Streamlit app.** Read-only; uploads validated for required columns and obvious problems only (no column mapping, limited date/currency parsing); no authentication, authorisation, audit logging or multi-tenant isolation; loads full tables into memory (fine for ~250K rows, not for millions). Not for confidential data until those are addressed.
9. **Database bootstrap is destructive.** `database/schema.sql` drops and recreates the `raw`, `analytics` and `etl` schemas; use only on a dedicated development database. No migrations framework.
10. **KPI definitions** (default, PAR30, recovery) are reasonable choices but must be agreed with a business owner before real use.
11. **Environment.** Tested on Python 3.13, PostgreSQL 16, pandas 3, scikit-learn 1.9, Streamlit 1.67 in a Linux container; other versions are untested.
