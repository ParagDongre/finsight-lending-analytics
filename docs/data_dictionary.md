# Data dictionary (SYNTHETIC data)

Layers: `raw.*` = source extract as text, `analytics.*` = cleaned, typed, constrained (+ derived), `etl.*` = audit trail, `reporting.*` = Power BI views.
Currency: INR. As-of (snapshot) date: 2026-06-30. "Derived" = created by the ETL.

## analytics.customers  (PK customer_id)
| Field | Type | Meaning / rules |
|---|---|---|
| customer_id | varchar(10) | Unique customer key, `C000001...` |
| age | smallint, NULL ok | Age at first application; valid 18-75, otherwise NULL (logged rule C03/C04) |
| gender | varchar | Male / Female / Other. **Not a risk driver in this simulation; excluded from real credit models** |
| city_tier | varchar | Tier 1 (metro) / Tier 2 / Tier 3 |
| employment_type | varchar | Salaried, Self-Employed, Gig Worker, Business Owner, Contract Worker, Unknown (missing/unrecognised, rules C05-C07) |
| acquisition_channel | varchar | Organic, Paid Digital, Partner Referral, Customer Referral |
| signup_date | date, NULL ok | App sign-up date (invalid calendar dates nulled, C08) |
| age_band | varchar | Derived: 18-24, 25-34, 35-44, 45+ |

## analytics.customer_financial_profiles  (PK profile_id; FK customer_id)
One row per loan application: the profile *as at application date* (so repeat borrowers have several rows).
| Field | Meaning / rules |
|---|---|
| profile_date | Application date |
| monthly_income | INR/month, > 0, NULL if missing (flagged P03, never imputed in the database) |
| income_missing | Derived flag |
| existing_monthly_emi | EMI obligations from other loans, >= 0 |
| credit_score | Bureau-style 300-900; NULL if missing/invalid |
| credit_utilization_pct | % of revolving limit used, 0-100 |
| dependents, home_ownership, years_in_employment | Household / employment stability fields |
| previous_loans_count | Number of earlier loans with this lender |
| income_bracket | Derived: Below 20K, 20K-35K, 35K-50K, 50K-75K, 75K+ |

## analytics.loans  (PK loan_id; FKs customer_id, profile_id)
| Field | Meaning / rules |
|---|---|
| loan_purpose | Stated purpose |
| loan_amount | Principal disbursed, > 0 |
| interest_rate | Annual %, 1-60 |
| tenure_months | 1-60 |
| emi_amount | Monthly instalment (standard amortisation formula) |
| disbursement_date / first_due_date / maturity_date | Key dates; disbursement <= snapshot |
| outstanding_balance | Principal still owed at snapshot; 0 when CLOSED; never > loan_amount |
| current_dpd | Days past due of the oldest unpaid instalment at snapshot (0 if none) |
| loan_status | ACTIVE, CLOSED (fully repaid, nothing overdue), DEFAULTED (current_dpd >= 90) |
| snapshot_date | As-of date of the extract |
| disbursement_month, months_on_book, dpd_bucket | Derived. dpd_bucket: Current, 1-29, 30-59, 60-89, 90+ |
| foir | Derived: (existing_monthly_emi + emi_amount) / monthly_income; NULL if income missing |

## analytics.repayments  (PK repayment_id; FK loan_id; UNIQUE loan_id + installment_no)
One row per instalment that has fallen due by the snapshot.
| Field | Meaning |
|---|---|
| installment_no, due_date, due_amount | Schedule |
| paid_amount, paid_date | Cash received; NULL date and 0 amount when UNPAID |
| dpd | PAID rows: days late at payment (0 if on time/early). UNPAID/PARTIAL: days overdue at snapshot |
| repayment_status | PAID_ON_TIME, PAID_LATE, PARTIAL, UNPAID |
| due_month, dpd_bucket, is_late | Derived |

## analytics.collections  (PK collection_id; FK loan_id)
One row per collection **action** (a loan-instalment typically has several actions as it ages). Group by (loan_id, installment_no) for **cases**.
| Field | Meaning |
|---|---|
| action_date, dpd_at_action | When and how overdue |
| channel | SMS, APP_PUSH, CALL, FIELD_VISIT, LEGAL_NOTICE |
| outcome | PROMISE_TO_PAY, NO_RESPONSE, REFUSED_TO_PAY, PAID_IN_FULL, PARTIAL_PAYMENT |
| amount_due | The overdue instalment amount (repeated on each action of the case - do not sum across actions) |
| amount_recovered | Cash recovered attributed to the action |
| collection_status | OPEN, PROMISE_TO_PAY, ESCALATED, RESOLVED, WRITTEN_OFF |
| action_month, dpd_bucket | Derived |

## etl.* audit tables
`pipeline_runs`, `data_quality_issues` (one row per rejected / fixed / flagged record with rule id, reason, JSON of the raw record),
`dq_rule_results` (failures per rule), `dq_table_counts` (raw = clean + rejected, enforced by a CHECK constraint).

## Rule action meanings
REJECTED = row quarantined (not in analytics); FIXED = value corrected or nulled, row kept; FLAGGED = kept unchanged, logged. Rule ids are listed in `reports/data_quality_report.md`.
