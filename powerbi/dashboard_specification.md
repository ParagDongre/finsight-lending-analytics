# Power BI dashboard specification and build guide (SYNTHETIC data)

> **Status: not implemented in Power BI by the author.** Power BI Desktop is Windows-only and was not available. Everything below is a build guide.
> The numbers it expects were verified in SQL and Python. The Streamlit app (`app.py`) implements the same three views and is the tested reference.
> Do not describe the dashboards as built until you have built and checked them against the acceptance table in `dax_measures.md`.

## 1. Connect to the data
**Option A - CSV (simplest).** Run `python -m powerbi.export_for_powerbi`. In Power BI Desktop: *Get data > Text/CSV*, import the five files in `powerbi/data/`.
**Option B - PostgreSQL.** Run `psql -d finsight -f database/powerbi_views.sql`, then *Get data > PostgreSQL database* (server `localhost`, database `finsight`), import the `reporting.*` views.
Use *Import* mode. Enter credentials in Power BI's credential dialog; never save them in files.

## 2. Data model (star-ish schema)

| From (many) | To (one) | Column | Direction |
|---|---|---|---|
| Loans[disbursement_date] | Date[date] | date | single |
| Repayments[loan_id] | Loans[loan_id] | loan_id | single (Loans filters Repayments) |
| CollectionCases[loan_id] | Loans[loan_id] | loan_id | single |
| CollectionActions[loan_id] | Loans[loan_id] | loan_id | single |

Notes: Customer attributes are already flattened into `Loans`, so there is no customer dimension. Mark `Date` as a date table. Keep only the disbursement relationship active; for repayment-date analysis use `USERELATIONSHIP` or `Repayments[due_month]` directly.
Hide ID/technical columns. Sort `year_month` text by `month_start`.

## 3. Global slicers (sync across pages)
Disbursement date range (Date[date]), Employment type, City tier, Acquisition channel, Loan purpose, Loan status.

## 4. Page 1 - Portfolio overview
- **KPI cards (5):** Total Disbursement, Outstanding Portfolio, Active Loans, Average Loan Amount, Portfolio Delinquency Rate.
- **Monthly disbursement trend:** clustered column, X = `Date[month_start]` (via Loans disbursement relationship), Y = Total Disbursement; add `Disbursement MoM %` in tooltip.
- **Outstanding portfolio trend:** area chart, X = `Loans[disbursement_month]` (vintage), Y = Outstanding Portfolio. (This is outstanding *by vintage today*, not a historical time series - the extract is a single snapshot. Title it accordingly.)
- **Loan status distribution:** donut, legend = `loan_status`, values = Loans Count.
- **Customer segment breakdown:** bar chart, axis = switchable field parameter (employment type / city tier / channel / income bracket), values = Outstanding Portfolio.
- Layout: KPI strip across the top (5 equal cards), 2x2 grid of visuals below, slicers in a left rail.

## 5. Page 2 - Credit and risk analytics
- **KPI cards (4):** Default Rate, Portfolio Delinquency Rate, Average DPD (Open), High-Risk Exposure (60+ DPD).
- **Default rate by income group:** column chart, axis = `income_bracket` (sort Below 20K -> 75K+, Unknown separate), values = Default Rate; show `Mature Loans` in tooltip so small groups are visible.
- **Default rate by employment type:** bar chart sorted descending, same tooltip.
- **DPD distribution:** column chart, axis = `dpd_bucket` (order Current, 1-29, 30-59, 60-89, 90+), values = Open Outstanding (filter `is_open`).
- **Loan cohort performance:** line chart, X = `disbursement_month`, Y1 = `% 30DPD In First 6 Instalments`, Y2 = Default Rate (mature cohorts only; the line stops where cohorts are too young - say so in a text box).
- Guard against misreading: add a card note "Default rate uses loans with >= 15 months on book".

## 6. Page 3 - Collections analytics
- **KPI cards (4):** Total Overdue Amount, Amount Collected, Recovery Rate, Overdue Accounts.
- **Monthly collections trend:** column chart, X = `CollectionActions[action_month]`, Y = `SUM(CollectionActions[amount_recovered])`.
- **Recovery by DPD bucket:** column chart, axis = `CollectionCases[dpd_bucket_reached]`, values = Recovery Rate.
- **Collection status distribution:** donut, legend = `CollectionActions[collection_status]`, values = Actions.
- **Segment-wise overdue exposure:** bar chart, axis = employment type, values = Outstanding Portfolio filtered to `current_dpd > 0` and open loans.
- Note: do not compare channel recovery rates as channel quality; channels are used at different DPD stages.

## 7. Visual standards
One accent colour for the primary series, a red for risk/default series, neutral grey for context; no more than 6 colours per chart; sort bars by value unless the axis is ordinal; format money as ₹ with Cr/M abbreviations; label every chart with what is counted; display a footer text box "Synthetic data - not real lending statistics".

## 8. Testing checklist
1. Cards with no filters match the table in `dax_measures.md`.
2. Slicing to a single employment type: Default Rate equals the value in SQL Q04 for that type (`database/run_queries.py --id Q04`).
3. Recovery Rate uses CollectionCases; summing `amount_due` over CollectionActions would give a wrong (inflated) denominator.
4. Page-level slicer sync works; no blanks in DPD order; tooltips show sample sizes.
