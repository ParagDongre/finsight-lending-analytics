# Interview preparation - FinSight

**Golden rule:** say "synthetic" in the first sentence and never present a number as a real lending statistic. Interviewers reward honesty about what the project proves (pipeline, reasoning, rigour) and what it does not (real-world effect sizes).

## 1. The 90-second project explanation
"FinSight is an end-to-end analytics project for a simulated digital personal-loan lender. I generated a reproducible synthetic dataset of ~20K loans with planted risk drivers and deliberately injected 32 types of data defects. I built an ETL that validates, fixes or quarantines every record with a logged reason, and loads raw, clean and audit layers into PostgreSQL. I wrote 28 business SQL queries, then did EDA, hypothesis tests and two models in Python, and built a Streamlit app plus a Power BI specification. The analysis found, for example, that loans with obligations above 60 % of income are 23 % of mature loans but about half of defaults, and that recovery falls from 96 % to 3 % as cases age past 90 days - though I treat the second as association, not proof that early contact works. I was careful about right-censoring, leakage and multiple testing, and I'm explicit about limitations - for example the simulation has no write-offs, which inflates delinquency. The Power BI part is a specification; I did not build the .pbix."

## 2. Key technical decisions to be ready to defend
| Decision | Why | Trade-off |
|---|---|---|
| Raw layer as TEXT | No bad value can block or silently vanish | Typing happens later |
| Reject vs fix vs flag | Recoverable fields kept (flagged); broken rows quarantined | Judgement calls per rule |
| Mature-loan default rate | Avoids right-censoring | Newest cohorts excluded |
| Out-of-time split | Mimics deployment, no look-ahead | Smaller test set |
| Logistic regression as headline model | Matched/beat trees (AUC 0.805), interpretable | May miss interactions |
| Recovery on cases, not actions | `amount_due` repeats on each action | Needs a grouping step |
| Gender kept as a deliberate null | Demonstrates no spurious significance | Would be excluded in a real model |

## 3. SQL questions (20)  - answers refer to `database/queries/business_queries.sql`
1. Total disbursed by month? *(GROUP BY month - Q01)*
2. Why `FILTER (WHERE ...)` instead of `CASE`? *Same result, clearer for conditional aggregates in PostgreSQL.*
3. INNER vs LEFT JOIN - where did you need LEFT? *Q21/Q28: loans with no repayment rows must still appear.*
4. Why a CTE? *Readability, reuse; Q08 collapses actions into cases first.*
5. Month-over-month change without self-join? *`LAG()` window - Q12.*
6. Difference between `RANK`, `DENSE_RANK`, `ROW_NUMBER`? *Ties: RANK skips, DENSE_RANK doesn't, ROW_NUMBER breaks ties arbitrarily; Q11/Q18/Q26.*
7. Top-N per group? *`ROW_NUMBER() OVER (PARTITION BY ...)` then filter - Q26.*
8. `WHERE` vs `HAVING`? *Row filter before grouping vs group filter after; Q04 HAVING COUNT(*) >= 100.*
9. Why `NULLIF` in denominators? *Avoid divide-by-zero.*
10. Rolling 3-month average? *Window frame `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW` - Q25.*
11. What does `ROLLUP` do? *Adds subtotal/grand-total rows - Q16.*
12. Correlated subquery vs `EXISTS`? *EXISTS stops at first match - Q09.*
13. How would you find duplicate loan IDs? *`GROUP BY loan_id HAVING COUNT(*) > 1`.*
14. Why do old vintages show PAR30 of 85 % in Q16? *Survivorship in the denominator: good loans repaid and left; use same-age vintage curves (Q28).*
15. How do you avoid double-counting amounts in collections? *Group to (loan, instalment) cases first.*
16. How would you speed up Q09/Q28 on 100x data? *Indexes on repayments(loan_id, installment_no), pre-aggregate first-6 flags in a materialised view.*
17. `COUNT(*)` vs `COUNT(col)` vs `COUNT(DISTINCT ...)`? *Rows / non-null / unique; Q24 uses distinct pairs.*
18. How do you treat NULL income in a bracket query? *Own 'Unknown' bucket (Q05), never dropped.*
19. Write DPD buckets in SQL. *CASE WHEN ladder - Q06.*
20. How did you test SQL? *Executed all queries; recomputed 8 in pandas and compared (tests/test_sql_queries.py).*

## 4. Statistics questions (15)
1. Mean vs median for loan amount? *Skew 2.3: mean ₹149.7K > median ₹117K; report median.*
2. Variance vs SD? *SD is in original units.*
3. What is a p-value? *P(result at least this extreme | H0). Not P(H0 true).*
4. Which test for gig vs salaried default rate, and why? *Two-proportion z-test; independent groups, expected counts >> 5.*
5. Why report effect size and CI too? *With n≈10K tiny effects are significant; CI shows precision and size.*
6. Why a Holm correction? *Four tests -> inflated false-positive rate; Holm controls family-wise error and is less conservative than Bonferroni.*
7. Gender result? *p = 0.30, no evidence of difference - consistent with simulation null; I did not search for significance.*
8. What does a 95 % CI mean? *Procedure captures truth in 95 % of repeats; not 95 % probability for this interval.*
9. Why Wilson interval for proportions? *Better coverage for small n / extreme rates than normal approx.*
10. CLT - what did you show? *Sample means of skewed loan amounts become symmetric by n≈1000; SD of means ≈ SD/√n.*
11. Pearson vs Spearman? *Linear vs rank/monotone; Spearman robust to outliers.*
12. Why Mann-Whitney for credit score? *No normality assumption; confirmed with Welch t; Cohen's d -0.68.*
13. Type I vs Type II error? *False positive vs missed effect.*
14. Interpret an odds ratio of 1.46 per +10 pp FOIR. *Odds of default are 46 % higher per +10 pp, holding other variables fixed - not probability, not causal.*
15. Why not use a random split for validation? *Look-ahead; out-of-time AUC 0.805 vs random 0.797 here, but in drifting real data the gap can be large.*

## 5. ETL and data-quality questions (10)
1. How do you guarantee nothing is silently dropped? *Row accounting `raw = clean + rejected` enforced in code and by a DB CHECK.*
2. Orphan vs cascade rejection? *Orphan never existed in the parent source; cascade = parent was rejected.*
3. When fix, when reject? *Recoverable attribute -> fix/flag; structural or financial inconsistency -> quarantine.*
4. How do you test a validator? *Inject known defects, assert detection >= injected (32/32), plus no false positives on clean data.*
5. How do you treat missing income? *Keep NULL + flag; modelling imputes inside the CV pipeline.*
6. Idempotency? *Schema reset + full reload; same seed -> identical outputs.*
7. Why a raw layer? *Lineage and reprocessing without re-extraction.*
8. What does detected > injected mean? *Cascades and natural overlaps; not an error.*
9. Cross-table reconciliation? *X01/X02 flag DPD and instalment-count mismatches caused by quarantined rows.*
10. What would you add for production? *Migrations, incremental loads, schema contracts, alerting, row-level lineage IDs, data SLAs.*

## 6. Power BI questions (10)  - be honest the .pbix was not built
1. Star vs flat model? *Flattened loans view + facts keyed on loan_id; simple DAX.*
2. Measure vs calculated column? *Measures evaluate in filter context at query time; columns are stored row-level.*
3. `CALCULATE` role? *Changes filter context.*
4. Why a separate collection-cases table? *Prevents summing amount_due per action.*
5. `DIVIDE` vs `/`? *Safe divide-by-zero.*
6. Import vs DirectQuery? *Import for speed at this size; DirectQuery for live data.*
7. Relationship direction? *Single, dimension-to-fact; avoid bi-directional ambiguity.*
8. How do you validate a dashboard? *Reconcile cards to SQL/Python (acceptance table in dax_measures.md).*
9. Time intelligence needs? *A marked date table.*
10. Row-level security? *Roles with DAX filters; not implemented here.*

## 7. Financial analytics / lending domain (10)
1. DPD? *Days since the oldest due amount went unpaid.* 2. PAR30/PAR90? *Share of balance 30+/90+ DPD.* 3. Default definition? *Commonly 90+ DPD.* 4. NPA? *Non-performing asset, typically 90+ DPD in Indian regulation.* 5. FOIR? *Fixed obligations / income.* 6. Roll rate? *Share of balances moving from one DPD bucket to the next.* 7. Vintage analysis? *Cohorts compared at equal age.* 8. EMI? *Equated monthly instalment (amortisation).* 9. Recovery vs collection efficiency? *Amount recovered on overdue cases vs paid/due in a period.* 10. Why not use gender in credit decisions? *Fairness/legal risk; here it shows no signal anyway.*

## 8. Business-case questions
- **Defaults rose - what do you check first?** Segment mix, channel mix, cohort vintage curves at equal age, FOIR/score distribution of recent approvals, then macro/seasonality. (Mine: +1.8 pp early delinquency in newer cohorts; mix partly explains.)
- **Should we cap FOIR at 60 %?** It isolates ~50 % of defaults in ~23 % of loans, but revenue lost, pricing and customer behaviour are unknown -> run a randomised pilot.
- **Does calling earlier increase recovery?** The data can't tell (selection by DPD). Design an A/B test randomising first-contact timing for 1-7 DPD cases.
- **Your portfolio delinquency is 27 % - is that bad?** In this simulation defaulted loans are never written off; use write-off-adjusted PAR and trend, not the level.

## 9. Limitations you should volunteer
Synthetic, no write-offs, right-censoring, selection bias, observational only, Power BI not built, app not security-reviewed, one validation split, no profitability data.
