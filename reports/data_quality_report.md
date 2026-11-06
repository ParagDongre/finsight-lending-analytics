# Data Quality Report
_Generated 2026-11-05 07:27. All data is SYNTHETIC; defects were injected deliberately by `src/generation/dirty.py` so the pipeline has something to catch._

## 1. Record counts by table
`balanced` confirms **raw rows = clean rows + rejected rows** (nothing silently dropped). `fixed`/`flagged` rows are kept in the clean table (value corrected or noted).

| table_name | raw_rows | clean_rows | rejected_rows | fixed_rows | flagged_rows | balanced |
|---|---|---|---|---|---|---|
| customers | 16896 | 16812 | 84 | 672 | 168 | yes |
| customer_financial_profiles | 20344 | 20263 | 81 | 41 | 446 | yes |
| loans | 20344 | 20131 | 213 | 0 | 0 | yes |
| repayments | 236510 | 232795 | 3715 | 0 | 0 | yes |
| collections | 232524 | 229472 | 3052 | 0 | 0 | yes |

## 2. Rule results (rules with at least one failure)
| table_name | rule_id | action | failures | description |
|---|---|---|---|---|
| collections | K01 | REJECTED | 464 | Duplicate collection_id (first occurrence kept) |
| collections | K02 | REJECTED | 232 | ORPHAN: loan_id does not exist in source loans |
| collections | K02b | REJECTED | 1672 | CASCADE: loan_id refers to a loans record that was itself rejected |
| collections | K03 | REJECTED | 232 | amount_due missing/<=0 or amount_recovered missing/negative |
| collections | K04 | REJECTED | 232 | amount_recovered exceeds amount_due |
| collections | K06 | REJECTED | 232 | channel / outcome / collection_status not in allowed domain |
| customer_financial_profiles | P01 | REJECTED | 61 | Duplicate profile_id (first occurrence kept) |
| customer_financial_profiles | P03 | FLAGGED | 243 | monthly_income missing (kept as NULL, income_missing=TRUE) |
| customer_financial_profiles | P04 | REJECTED | 20 | monthly_income non-numeric or <= 0 |
| customer_financial_profiles | P05 | FIXED | 41 | credit_score outside 300-900 (set to NULL) |
| customer_financial_profiles | P05a | FLAGGED | 203 | credit_score missing (kept as NULL) |
| customers | C01 | REJECTED | 84 | Duplicate customer_id (first occurrence kept) |
| customers | C03 | FLAGGED | 168 | Age missing (kept as NULL) |
| customers | C04 | FIXED | 50 | Age non-numeric or outside 18-75 (set to NULL) |
| customers | C05 | FIXED | 252 | Employment type missing (set to 'Unknown') |
| customers | C06 | FIXED | 336 | Employment type had inconsistent case/whitespace (standardised) |
| customers | C08 | FIXED | 34 | signup_date is not a valid calendar date (set to NULL) |
| loans | L01 | REJECTED | 61 | Duplicate loan_id (first occurrence kept) |
| loans | L02 | REJECTED | 20 | ORPHAN: customer_id does not exist in source customers |
| loans | L03b | REJECTED | 20 | CASCADE: profile_id refers to a customer_financial_profiles record that was itself rejected |
| loans | L04 | REJECTED | 30 | loan_amount / emi_amount missing, non-numeric or <= 0 |
| loans | L05 | REJECTED | 20 | interest_rate missing or outside 1-60 % |
| loans | L06 | REJECTED | 10 | tenure_months missing, non-integer or outside 1-60 |
| loans | L07 | REJECTED | 20 | A date column is missing or not a valid calendar date |
| loans | L08 | REJECTED | 20 | disbursement_date is after the snapshot date |
| loans | L09 | REJECTED | 30 | outstanding_balance missing, negative or greater than loan_amount |
| loans | L11 | REJECTED | 12 | loan_status inconsistent with outstanding_balance / current_dpd |
| loans | X01 | FLAGGED | 42 | Reported current_dpd differs from DPD recomputed from clean repayments (may be explained by quarantined installments) |
| loans | X02 | FLAGGED | 1454 | Number of clean repayment rows differs from the number of installments due by the snapshot (usually a quarantined installment) |
| repayments | R01 | REJECTED | 472 | Duplicate repayment_id (first occurrence kept) |
| repayments | R02 | REJECTED | 236 | ORPHAN: loan_id does not exist in source loans |
| repayments | R02b | REJECTED | 1724 | CASCADE: loan_id refers to a loans record that was itself rejected |
| repayments | R03 | REJECTED | 236 | due_amount missing/<=0 or paid_amount missing/negative |
| repayments | R05 | REJECTED | 595 | paid_amount > 0 but paid_date missing |
| repayments | R06 | REJECTED | 459 | repayment_status inconsistent with paid_amount / due_amount |
| repayments | R07 | REJECTED | 193 | paid_date is before the loan's disbursement_date |
| repayments | R08 | REJECTED | 442 | due_date is on/before the loan's disbursement_date |
| repayments | R10 | REJECTED | 130 | paid_amount exceeds due_amount (overpayment) |
| repayments | R11 | REJECTED | 340 | dpd negative/missing or inconsistent with paid_date - due_date |

## 3. Injected defects vs detected
Detected >= injected is expected (cascading rejections and natural overlaps add extra detections).

| defect | rule_id | injected | detected | caught |
|---|---|---|---|---|
| C05_employment_missing | C05 | 252 | 252 | True |
| C06_employment_nonstandard | C06 | 336 | 336 | True |
| C03_age_missing | C03 | 168 | 168 | True |
| C04_age_out_of_range | C04 | 50 | 50 | True |
| C08_signup_date_invalid | C08 | 34 | 34 | True |
| C01_duplicate_pk | C01 | 84 | 84 | True |
| P03_income_missing | P03 | 243 | 243 | True |
| P04_income_invalid | P04 | 20 | 20 | True |
| P05a_credit_score_missing | P05a | 203 | 203 | True |
| P05_credit_score_out_of_range | P05 | 41 | 41 | True |
| P01_duplicate_pk | P01 | 61 | 61 | True |
| L04_amount_invalid | L04 | 30 | 30 | True |
| L05_rate_out_of_range | L05 | 20 | 20 | True |
| L06_tenure_invalid | L06 | 10 | 10 | True |
| L07_disbursement_date_invalid | L07 | 20 | 20 | True |
| L08_disbursement_date_in_future | L08 | 20 | 20 | True |
| L02_customer_orphan | L02 | 20 | 20 | True |
| L11_status_inconsistent | L11 | 12 | 12 | True |
| L01_duplicate_pk | L01 | 61 | 61 | True |
| R03_amount_invalid | R03 | 236 | 236 | True |
| R05_paid_amount_without_date | R05 | 354 | 595 | True |
| R06_status_amount_mismatch | R06 | 236 | 459 | True |
| R11_dpd_inconsistent | R11 | 118 | 340 | True |
| R10_overpayment | R10 | 118 | 130 | True |
| R02_loan_orphan | R02 | 236 | 236 | True |
| R08_due_before_disbursement | R08 | 236 | 442 | True |
| R01_duplicate_pk | R01 | 472 | 472 | True |
| K03_amount_invalid | K03 | 232 | 232 | True |
| K04_recovered_exceeds_due | K04 | 232 | 232 | True |
| K02_loan_orphan | K02 | 232 | 232 | True |
| K06_domain_invalid | K06 | 232 | 232 | True |
| K01_duplicate_pk | K01 | 464 | 464 | True |

**Defect types caught: 32 / 32**

## 4. Cross-table reconciliation (flag-only)
| table_name | rule_id | failures | description |
|---|---|---|---|
| loans | X01 | 42 | Reported current_dpd differs from DPD recomputed from clean repayments (may be explained by quarantined installments) |
| loans | X02 | 1454 | Number of clean repayment rows differs from the number of installments due by the snapshot (usually a quarantined installment) |

## 5. Where the full detail lives
- `data/rejected/*.csv` and `etl.data_quality_issues` hold every rejected / fixed / flagged record with its raw values.
- `etl.dq_rule_results` and `etl.dq_table_counts` hold the tables above.