-- Reporting views for Power BI (flat, business-friendly columns). SYNTHETIC data.
-- Apply after the ETL:  psql -d finsight -f database/powerbi_views.sql
CREATE SCHEMA IF NOT EXISTS reporting;

CREATE OR REPLACE VIEW reporting.vw_loans AS
SELECT l.loan_id, l.customer_id, l.loan_purpose, l.loan_amount, l.interest_rate, l.tenure_months, l.emi_amount,
       l.disbursement_date, l.disbursement_month, l.maturity_date, l.outstanding_balance, l.current_dpd, l.dpd_bucket,
       l.loan_status, l.months_on_book, l.foir, l.snapshot_date,
       (l.months_on_book >= 15)                                 AS is_mature,          -- default rate denominator
       (l.loan_status = 'DEFAULTED')                            AS is_default,
       (l.loan_status <> 'CLOSED')                              AS is_open,
       c.employment_type, c.city_tier, c.acquisition_channel, c.gender, c.age_band,
       COALESCE(p.income_bracket, 'Unknown')                    AS income_bracket,
       CASE WHEN p.credit_score IS NULL THEN 'Missing'
            WHEN p.credit_score < 600 THEN '<600'  WHEN p.credit_score < 650 THEN '600-649'
            WHEN p.credit_score < 700 THEN '650-699' WHEN p.credit_score < 750 THEN '700-749'
            WHEN p.credit_score < 800 THEN '750-799' ELSE '800+' END AS credit_band
FROM analytics.loans l
JOIN analytics.customers c                    ON c.customer_id = l.customer_id
JOIN analytics.customer_financial_profiles p  ON p.profile_id  = l.profile_id;

CREATE OR REPLACE VIEW reporting.vw_repayments AS
SELECT repayment_id, loan_id, installment_no, due_date, due_month, due_amount, paid_amount, paid_date, dpd, dpd_bucket,
       repayment_status, is_late, GREATEST(due_amount - paid_amount, 0) AS shortfall_amount
FROM analytics.repayments;

-- One row per collection CASE (loan, instalment): avoids counting amount_due once per action.
CREATE OR REPLACE VIEW reporting.vw_collection_cases AS
SELECT loan_id, installment_no, MAX(amount_due) AS amount_due, SUM(amount_recovered) AS amount_recovered,
       MAX(dpd_at_action) AS max_dpd_reached, COUNT(*) AS actions, MIN(action_date) AS first_action_date,
       DATE_TRUNC('month', MIN(action_date))::date AS first_action_month,
       CASE WHEN MAX(dpd_at_action) < 30 THEN '1-29' WHEN MAX(dpd_at_action) < 60 THEN '30-59'
            WHEN MAX(dpd_at_action) < 90 THEN '60-89' ELSE '90+' END AS dpd_bucket_reached
FROM analytics.collections GROUP BY loan_id, installment_no;

CREATE OR REPLACE VIEW reporting.vw_collection_actions AS
SELECT collection_id, loan_id, installment_no, action_date, action_month, dpd_at_action, dpd_bucket, channel, outcome,
       amount_due, amount_recovered, collection_status
FROM analytics.collections;

CREATE OR REPLACE VIEW reporting.vw_date AS
SELECT d::date AS date, DATE_TRUNC('month', d)::date AS month_start, TO_CHAR(d, 'YYYY-MM') AS year_month,
       EXTRACT(YEAR FROM d)::int AS year, EXTRACT(QUARTER FROM d)::int AS quarter
FROM generate_series('2023-06-01'::date, '2026-12-31'::date, interval '1 day') AS g(d);
