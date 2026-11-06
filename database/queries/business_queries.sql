-- =====================================================================================================
-- FinSight business SQL  (PostgreSQL 16, schema `analytics`)       ALL DATA IS SYNTHETIC
--
-- Conventions used in every query
--   * "Default"        = loan_status = 'DEFAULTED' = 90+ days past due at the snapshot date (2026-06-30).
--   * "Mature loans"   = months_on_book >= 15. Only mature loans are used for default RATES, because a young loan
--                        has not had time to default yet (right-censoring would make recent cohorts look safe).
--   * "Outstanding"    = principal outstanding at snapshot (analytics.loans.outstanding_balance).
--   * "Missed payment" = installment UNPAID/PARTIAL or paid 30+ days late.
--   * Collections rows are ACTIONS (several per overdue installment). Recovery metrics therefore first collapse
--     actions into one "case" per (loan_id, installment_no) so amounts due are not counted several times.
--
-- Block format (parsed by tests/test_sql_queries.py and database/run_queries.py):
--   -- @id / @title / @question / @why  followed by one SQL statement ending in ';'
-- =====================================================================================================

-- @id: Q01
-- @title: Total loans disbursed by month
-- @question: How many loans and how many rupees did we disburse each month?
-- @why: Disbursement volume is the top-line growth metric and the denominator for every later cohort analysis.
-- @tags: aggregation, date
SELECT disbursement_month,
       COUNT(*)                         AS loans_disbursed,
       SUM(loan_amount)                 AS amount_disbursed,
       ROUND(AVG(loan_amount), 0)       AS avg_loan_amount
FROM analytics.loans
GROUP BY disbursement_month
ORDER BY disbursement_month;

-- @id: Q02
-- @title: Total outstanding loan portfolio
-- @question: How big is the book today and how is it split across ACTIVE / CLOSED / DEFAULTED?
-- @why: Outstanding principal is the exposure the business is actually carrying; defaulted balance is the loss pool.
-- @tags: aggregation, window
SELECT loan_status,
       COUNT(*)                                                        AS loans,
       SUM(outstanding_balance)                                        AS outstanding,
       ROUND(100.0 * SUM(outstanding_balance) / SUM(SUM(outstanding_balance)) OVER (), 2) AS pct_of_portfolio,
       SUM(SUM(outstanding_balance)) OVER ()                           AS portfolio_total
FROM analytics.loans
GROUP BY loan_status
ORDER BY outstanding DESC;

-- @id: Q03
-- @title: Average loan size by customer segment (employment type)
-- @question: Do different customer segments borrow different amounts, and relative to their income?
-- @why: Loan-to-income shows whether a segment is stretched; a large absolute ticket with a high ratio is a risk flag.
-- @tags: join, aggregation
SELECT c.employment_type                                  AS segment,
       COUNT(*)                                           AS loans,
       ROUND(AVG(l.loan_amount), 0)                       AS avg_loan_amount,
       ROUND(AVG(l.loan_amount / p.monthly_income), 2)    AS avg_loan_to_monthly_income
FROM analytics.loans l
JOIN analytics.customers c                    ON c.customer_id = l.customer_id
JOIN analytics.customer_financial_profiles p  ON p.profile_id  = l.profile_id
GROUP BY c.employment_type
ORDER BY avg_loan_amount DESC;

-- @id: Q04
-- @title: Default rate by employment type
-- @question: Which employment segments default most (mature loans only)?
-- @why: Drives segment-level pricing, limits and underwriting policy.
-- @tags: join, group by, having, filter
SELECT c.employment_type,
       COUNT(*)                                                           AS mature_loans,
       COUNT(*) FILTER (WHERE l.loan_status = 'DEFAULTED')                AS defaults,
       ROUND(100.0 * COUNT(*) FILTER (WHERE l.loan_status = 'DEFAULTED') / COUNT(*), 2) AS default_rate_pct
FROM analytics.loans l
JOIN analytics.customers c ON c.customer_id = l.customer_id
WHERE l.months_on_book >= 15
GROUP BY c.employment_type
HAVING COUNT(*) >= 100
ORDER BY default_rate_pct DESC;

-- @id: Q05
-- @title: Default rate by income bracket
-- @question: Does default risk fall as income rises? What about customers with missing income?
-- @why: Tests whether income-based eligibility cut-offs are well placed; NULL income is shown separately, not hidden.
-- @tags: CTE, CASE WHEN
WITH bracketed AS (
    SELECT l.loan_id, l.loan_status,
           CASE WHEN p.monthly_income IS NULL  THEN '0) Unknown'
                WHEN p.monthly_income < 20000  THEN '1) <20K'
                WHEN p.monthly_income < 35000  THEN '2) 20-35K'
                WHEN p.monthly_income < 50000  THEN '3) 35-50K'
                WHEN p.monthly_income < 75000  THEN '4) 50-75K'
                ELSE                                '5) 75K+' END AS income_bracket
    FROM analytics.loans l
    JOIN analytics.customer_financial_profiles p ON p.profile_id = l.profile_id
    WHERE l.months_on_book >= 15
)
SELECT income_bracket,
       COUNT(*)                                              AS mature_loans,
       COUNT(*) FILTER (WHERE loan_status = 'DEFAULTED')     AS defaults,
       ROUND(100.0 * COUNT(*) FILTER (WHERE loan_status = 'DEFAULTED') / COUNT(*), 2) AS default_rate_pct
FROM bracketed
GROUP BY income_bracket
ORDER BY income_bracket;

-- @id: Q06
-- @title: Delinquency distribution by DPD bucket
-- @question: Across all open loans, how much exposure sits in each days-past-due bucket?
-- @why: The standard delinquency ladder; movement into 30+/60+ buckets is the earliest signal of portfolio stress.
-- @tags: CASE WHEN, window
SELECT CASE WHEN current_dpd = 0  THEN '0 Current'
            WHEN current_dpd < 30 THEN '1-29'
            WHEN current_dpd < 60 THEN '30-59'
            WHEN current_dpd < 90 THEN '60-89'
            ELSE '90+' END                                       AS dpd_bucket,
       COUNT(*)                                                  AS loans,
       SUM(outstanding_balance)                                  AS outstanding,
       ROUND(100.0 * SUM(outstanding_balance) / SUM(SUM(outstanding_balance)) OVER (), 2) AS pct_of_open_book
FROM analytics.loans
WHERE loan_status <> 'CLOSED'
GROUP BY 1
ORDER BY MIN(current_dpd);

-- @id: Q07
-- @title: Monthly repayment performance
-- @question: For installments falling due each month, how many were paid on time / late / not paid, and what share of the money came in?
-- @why: Collection efficiency by due-month is the core operating KPI. Recent months look worse partly because late payers have not paid yet.
-- @tags: aggregation, date, filter
SELECT due_month,
       COUNT(*)                                                         AS installments_due,
       ROUND(100.0 * COUNT(*) FILTER (WHERE repayment_status = 'PAID_ON_TIME') / COUNT(*), 2) AS on_time_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE repayment_status = 'PAID_LATE')    / COUNT(*), 2) AS paid_late_pct,
       ROUND(100.0 * COUNT(*) FILTER (WHERE repayment_status IN ('UNPAID','PARTIAL')) / COUNT(*), 2) AS unpaid_or_partial_pct,
       ROUND(100.0 * SUM(paid_amount) / SUM(due_amount), 2)             AS collection_efficiency_pct
FROM analytics.repayments
GROUP BY due_month
ORDER BY due_month;

-- @id: Q08
-- @title: Collection recovery rate
-- @question: Of the instalments that needed collections effort, what share of the amount due was recovered?
-- @why: Measures whether collections operations convert overdue amounts into cash. Cases (not actions) avoid double counting the amount due.
-- @tags: CTE, aggregation
WITH cases AS (
    SELECT loan_id, installment_no,
           MAX(amount_due)        AS amount_due,
           SUM(amount_recovered)  AS recovered,
           COUNT(*)               AS actions
    FROM analytics.collections
    GROUP BY loan_id, installment_no
)
SELECT COUNT(*)                                                         AS collection_cases,
       SUM(amount_due)                                                  AS amount_due,
       SUM(recovered)                                                   AS amount_recovered,
       ROUND(100.0 * SUM(recovered) / SUM(amount_due), 2)               AS recovery_rate_pct,
       COUNT(*) FILTER (WHERE recovered >= amount_due * 0.999)          AS fully_recovered_cases,
       ROUND(100.0 * COUNT(*) FILTER (WHERE recovered >= amount_due * 0.999) / COUNT(*), 2) AS fully_recovered_pct,
       ROUND(AVG(actions), 2)                                           AS avg_actions_per_case
FROM cases;

-- @id: Q09
-- @title: Loan cohort performance
-- @question: By disbursement month, what share of loans hit 30+ DPD within their first 6 instalments, and (for mature cohorts) defaulted?
-- @why: Shows whether newer cohorts are underwritten worse than older ones, long before they are mature enough to show defaults.
-- @tags: subquery, EXISTS, date
WITH cohort AS (
    SELECT l.loan_id, l.disbursement_month, l.loan_status, l.months_on_book,
           EXISTS (SELECT 1 FROM analytics.repayments r
                   WHERE r.loan_id = l.loan_id AND r.installment_no <= 6 AND r.dpd >= 30) AS hit_30dpd_first6
    FROM analytics.loans l
    WHERE l.months_on_book >= 7                      -- all of the first 6 instalments have fallen due
)
SELECT disbursement_month,
       COUNT(*)                                                        AS loans,
       ROUND(100.0 * AVG(hit_30dpd_first6::int), 2)                    AS pct_30dpd_in_first_6_installments,
       COUNT(*) FILTER (WHERE months_on_book >= 15)                    AS mature_loans,
       ROUND(100.0 * AVG((loan_status = 'DEFAULTED')::int) FILTER (WHERE months_on_book >= 15), 2) AS default_rate_pct_mature
FROM cohort
GROUP BY disbursement_month
ORDER BY disbursement_month;

-- @id: Q10
-- @title: Customers with repeated missed payments
-- @question: Which customers have 3 or more missed installments (unpaid, partial or 30+ days late)?
-- @why: A watch-list for collections prioritisation and for blocking repeat lending to chronic non-payers.
-- @tags: join, group by, having
SELECT c.customer_id, c.employment_type,
       COUNT(*)                          AS missed_installments,
       COUNT(DISTINCT r.loan_id)         AS loans_affected,
       MAX(r.dpd)                        AS worst_dpd,
       BOOL_OR(l.loan_status = 'DEFAULTED') AS has_defaulted_loan
FROM analytics.repayments r
JOIN analytics.loans l     ON l.loan_id = r.loan_id
JOIN analytics.customers c ON c.customer_id = l.customer_id
WHERE r.repayment_status IN ('UNPAID', 'PARTIAL') OR r.dpd >= 30
GROUP BY c.customer_id, c.employment_type
HAVING COUNT(*) >= 3
ORDER BY missed_installments DESC, worst_dpd DESC, c.customer_id
LIMIT 50;

-- @id: Q11
-- @title: Top segments by outstanding exposure
-- @question: Which employment x city-tier segments hold the most outstanding principal, and how risky are they?
-- @why: Concentration risk: a big segment with an above-average delinquency rate matters more than a small one.
-- @tags: CTE, RANK, window
WITH seg AS (
    SELECT c.employment_type, c.city_tier,
           SUM(l.outstanding_balance) AS outstanding,
           COUNT(*) FILTER (WHERE l.loan_status <> 'CLOSED') AS open_loans,
           SUM(l.outstanding_balance) FILTER (WHERE l.current_dpd >= 30) AS outstanding_30plus
    FROM analytics.loans l
    JOIN analytics.customers c ON c.customer_id = l.customer_id
    GROUP BY c.employment_type, c.city_tier
)
SELECT RANK() OVER (ORDER BY outstanding DESC)                     AS exposure_rank,
       employment_type, city_tier, open_loans, outstanding,
       ROUND(100.0 * outstanding / SUM(outstanding) OVER (), 2)     AS pct_of_portfolio,
       ROUND(100.0 * COALESCE(outstanding_30plus, 0) / NULLIF(outstanding, 0), 2) AS par30_pct
FROM seg
ORDER BY exposure_rank
LIMIT 10;

-- @id: Q12
-- @title: Month-over-month change in disbursements
-- @question: How did disbursed amount change versus the previous month (absolute and %)?
-- @why: Separates genuine growth from seasonal spikes (festive months) and flags sudden origination changes.
-- @tags: window, LAG
WITH m AS (
    SELECT disbursement_month, SUM(loan_amount) AS amount, COUNT(*) AS loans
    FROM analytics.loans GROUP BY disbursement_month
)
SELECT disbursement_month, loans, amount,
       LAG(amount) OVER w                                              AS prev_month_amount,
       amount - LAG(amount) OVER w                                     AS abs_change,
       ROUND(100.0 * (amount - LAG(amount) OVER w) / NULLIF(LAG(amount) OVER w, 0), 2) AS mom_change_pct
FROM m
WINDOW w AS (ORDER BY disbursement_month)
ORDER BY disbursement_month;

-- @id: Q13
-- @title: Repayment trends by loan tenure
-- @question: How do on-time rate, unpaid rate and default rate vary with tenure?
-- @why: Informs which tenures to promote or restrict; long tenures carry more time for things to go wrong.
-- @tags: CTE, join, filter
WITH inst AS (
    SELECT l.tenure_months,
           COUNT(DISTINCT l.loan_id) AS loans,
           COUNT(*) AS installments,
           ROUND(100.0 * COUNT(*) FILTER (WHERE r.repayment_status = 'PAID_ON_TIME') / COUNT(*), 2) AS on_time_pct,
           ROUND(100.0 * COUNT(*) FILTER (WHERE r.repayment_status IN ('UNPAID','PARTIAL')) / COUNT(*), 2) AS unpaid_or_partial_pct,
           ROUND(AVG(r.dpd) FILTER (WHERE r.repayment_status = 'PAID_LATE'), 1) AS avg_days_late_when_late
    FROM analytics.repayments r
    JOIN analytics.loans l ON l.loan_id = r.loan_id
    GROUP BY l.tenure_months
), dflt AS (
    SELECT tenure_months,
           ROUND(100.0 * AVG((loan_status = 'DEFAULTED')::int), 2) AS default_rate_pct_mature
    FROM analytics.loans WHERE months_on_book >= 15
    GROUP BY tenure_months
)
SELECT i.*, d.default_rate_pct_mature
FROM inst i LEFT JOIN dflt d ON d.tenure_months = i.tenure_months
ORDER BY i.tenure_months;

-- @id: Q14
-- @title: Loans with overdue repayments
-- @question: Which open loans have overdue instalments, how much is overdue, and for how long?
-- @why: The working list for the collections team, sorted by amount at stake.
-- @tags: join, group by
SELECT l.loan_id, l.customer_id, c.employment_type, l.loan_status, l.current_dpd,
       COUNT(*)                                  AS overdue_installments,
       ROUND(SUM(r.due_amount - r.paid_amount), 2) AS overdue_amount,
       MIN(r.due_date)                           AS oldest_unpaid_due_date,
       l.outstanding_balance
FROM analytics.loans l
JOIN analytics.customers c  ON c.customer_id = l.customer_id
JOIN analytics.repayments r ON r.loan_id = l.loan_id AND r.repayment_status IN ('UNPAID', 'PARTIAL')
WHERE l.loan_status <> 'CLOSED'
GROUP BY l.loan_id, l.customer_id, c.employment_type, l.loan_status, l.current_dpd, l.outstanding_balance
ORDER BY overdue_amount DESC, l.loan_id
LIMIT 100;

-- @id: Q15
-- @title: Customer-level repayment history
-- @question: For the customer with the most loans, what is the full instalment-by-instalment history, with a running count of late payments?
-- @why: Template for the "customer 360" view an underwriter or collector opens; the running count shows behaviour across loans.
-- @tags: CTE, window, join
WITH target AS (
    SELECT customer_id FROM analytics.loans
    GROUP BY customer_id ORDER BY COUNT(*) DESC, customer_id LIMIT 1
)
SELECT l.customer_id, l.loan_id, l.disbursement_date, r.installment_no, r.due_date, r.paid_date,
       r.repayment_status, r.dpd,
       SUM((r.dpd > 0)::int) OVER (PARTITION BY l.customer_id ORDER BY l.disbursement_date, r.installment_no) AS cumulative_late_installments
FROM analytics.loans l
JOIN target t              ON t.customer_id = l.customer_id
JOIN analytics.repayments r ON r.loan_id = l.loan_id
ORDER BY l.disbursement_date, r.installment_no;

-- @id: Q16
-- @title: Portfolio at risk (PAR30 / PAR90) by vintage year
-- @question: What share of open exposure is 30+ and 90+ days past due, by year of disbursement and overall?
-- @why: PAR30 and PAR90 are the headline asset-quality ratios lenders report to boards and investors. CAUTION: old vintages look terrible because their good loans have already repaid and left the denominator, leaving mostly defaulted balances; compare vintages with Q28 (same-age) instead.
-- @tags: CTE, ROLLUP, filter
WITH open_book AS (
    SELECT EXTRACT(YEAR FROM disbursement_date)::int AS vintage_year, outstanding_balance, current_dpd
    FROM analytics.loans WHERE loan_status <> 'CLOSED'
)
SELECT COALESCE(vintage_year::text, 'ALL') AS vintage_year,
       SUM(outstanding_balance) AS outstanding,
       ROUND(100.0 * SUM(outstanding_balance) FILTER (WHERE current_dpd >= 30) / NULLIF(SUM(outstanding_balance), 0), 2) AS par30_pct,
       ROUND(100.0 * SUM(outstanding_balance) FILTER (WHERE current_dpd >= 90) / NULLIF(SUM(outstanding_balance), 0), 2) AS par90_pct
FROM open_book
GROUP BY ROLLUP (vintage_year)
ORDER BY vintage_year;

-- @id: Q17
-- @title: Default rate by credit-score band
-- @question: How steeply does default risk rise as bureau score falls?
-- @why: Validates the credit score as a risk-ranking tool and shows where the approval cut-off should sit.
-- @tags: CASE WHEN, join
WITH b AS (
    SELECT l.loan_status,
           CASE WHEN p.credit_score IS NULL THEN '0) Missing'
                WHEN p.credit_score < 600 THEN '1) <600'
                WHEN p.credit_score < 650 THEN '2) 600-649'
                WHEN p.credit_score < 700 THEN '3) 650-699'
                WHEN p.credit_score < 750 THEN '4) 700-749'
                WHEN p.credit_score < 800 THEN '5) 750-799'
                ELSE '6) 800+' END AS score_band
    FROM analytics.loans l
    JOIN analytics.customer_financial_profiles p ON p.profile_id = l.profile_id
    WHERE l.months_on_book >= 15
)
SELECT score_band, COUNT(*) AS mature_loans,
       ROUND(100.0 * AVG((loan_status = 'DEFAULTED')::int), 2) AS default_rate_pct
FROM b GROUP BY score_band ORDER BY score_band;

-- @id: Q18
-- @title: Default rate by acquisition channel and city tier, ranked within channel
-- @question: Within each acquisition channel, which city tiers are riskiest?
-- @why: Marketing spend should follow risk-adjusted quality, not just volume.
-- @tags: window, RANK, PARTITION BY, HAVING
WITH x AS (
    SELECT c.acquisition_channel, c.city_tier, COUNT(*) AS mature_loans,
           ROUND(100.0 * AVG((l.loan_status = 'DEFAULTED')::int), 2) AS default_rate_pct
    FROM analytics.loans l
    JOIN analytics.customers c ON c.customer_id = l.customer_id
    WHERE l.months_on_book >= 15
    GROUP BY c.acquisition_channel, c.city_tier
    HAVING COUNT(*) >= 150
)
SELECT acquisition_channel, city_tier, mature_loans, default_rate_pct,
       RANK() OVER (PARTITION BY acquisition_channel ORDER BY default_rate_pct DESC) AS risk_rank_in_channel
FROM x
ORDER BY acquisition_channel, risk_rank_in_channel;

-- @id: Q19
-- @title: Default rate by affordability (FOIR band)
-- @question: Do borrowers whose total EMIs consume more of their income default more?
-- @why: FOIR (fixed obligations to income ratio) is a classic affordability cap; this checks where risk accelerates.
-- @tags: CASE WHEN
SELECT CASE WHEN foir IS NULL THEN '0) Unknown (income missing)'
            WHEN foir < 0.30 THEN '1) <30%'
            WHEN foir < 0.45 THEN '2) 30-45%'
            WHEN foir < 0.60 THEN '3) 45-60%'
            ELSE '4) 60%+' END AS foir_band,
       COUNT(*) AS mature_loans,
       ROUND(100.0 * AVG((loan_status = 'DEFAULTED')::int), 2) AS default_rate_pct
FROM analytics.loans
WHERE months_on_book >= 15
GROUP BY 1
ORDER BY 1;

-- @id: Q20
-- @title: New vs repeat customers
-- @question: Do repeat borrowers (with a previous loan with us) default less than first-time borrowers?
-- @why: Decides how aggressively to cross-sell and whether repeat customers deserve better pricing.
-- @tags: join, CASE WHEN
SELECT CASE WHEN p.previous_loans_count = 0 THEN 'New customer' ELSE 'Repeat customer' END AS customer_type,
       COUNT(*) AS mature_loans,
       ROUND(100.0 * AVG((l.loan_status = 'DEFAULTED')::int), 2) AS default_rate_pct
FROM analytics.loans l
JOIN analytics.customer_financial_profiles p ON p.profile_id = l.profile_id
WHERE l.months_on_book >= 15
GROUP BY 1
ORDER BY 1;

-- @id: Q21
-- @title: Early-warning power of 30+ DPD
-- @question: Of mature loans that ever reached 30+ DPD on any instalment, what share ended up defaulted compared with loans that never did?
-- @why: If 30+ DPD strongly predicts default, early outreach at that point is where collections effort pays most. Note the 'Never 30+' row is near zero BY DEFINITION (reaching 90+ DPD requires passing 30+); the informative number is the share of 30+ loans that went on to default.
-- @tags: CTE, LEFT JOIN
WITH m AS (
    SELECT l.loan_id, l.loan_status, COALESCE(MAX(r.dpd), 0) AS max_dpd
    FROM analytics.loans l
    LEFT JOIN analytics.repayments r ON r.loan_id = l.loan_id
    WHERE l.months_on_book >= 15
    GROUP BY l.loan_id, l.loan_status
)
SELECT CASE WHEN max_dpd >= 30 THEN 'Reached 30+ DPD' ELSE 'Never 30+ DPD' END AS history,
       COUNT(*) AS loans,
       COUNT(*) FILTER (WHERE loan_status = 'DEFAULTED') AS defaulted,
       ROUND(100.0 * COUNT(*) FILTER (WHERE loan_status = 'DEFAULTED') / COUNT(*), 2) AS default_rate_pct
FROM m
GROUP BY 1
ORDER BY 1;

-- @id: Q22
-- @title: Collection channel activity and outcomes
-- @question: For each collections channel, how many actions were taken, at what DPD, and how often did the action end with the instalment paid?
-- @why: Shows where effort is spent. Outcomes are NOT causal: channels are used at different DPDs, so compare with care.
-- @tags: aggregation
SELECT channel,
       COUNT(*)                                                                  AS actions,
       ROUND(AVG(dpd_at_action), 1)                                              AS avg_dpd_at_action,
       ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'PAID_IN_FULL') / COUNT(*), 2)    AS pct_ending_in_full_payment,
       ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'PROMISE_TO_PAY') / COUNT(*), 2)  AS pct_promise_to_pay,
       ROUND(100.0 * COUNT(*) FILTER (WHERE outcome = 'NO_RESPONSE') / COUNT(*), 2)     AS pct_no_response
FROM analytics.collections
GROUP BY channel
ORDER BY actions DESC;

-- @id: Q23
-- @title: Recovery by DPD bucket reached
-- @question: Collapsing actions into cases, how much of the amount due is recovered depending on how deep (max DPD) the case got?
-- @why: Recovery falls sharply as DPD rises; this quantifies the value of acting early.
-- @tags: CTE, CASE WHEN
WITH cases AS (
    SELECT loan_id, installment_no, MAX(amount_due) AS amount_due, SUM(amount_recovered) AS recovered,
           MAX(dpd_at_action) AS max_dpd
    FROM analytics.collections GROUP BY loan_id, installment_no
)
SELECT CASE WHEN max_dpd < 30 THEN '1-29'
            WHEN max_dpd < 60 THEN '30-59'
            WHEN max_dpd < 90 THEN '60-89'
            ELSE '90+' END AS dpd_bucket_reached,
       COUNT(*) AS cases, SUM(amount_due) AS amount_due, SUM(recovered) AS amount_recovered,
       ROUND(100.0 * SUM(recovered) / SUM(amount_due), 2) AS recovery_rate_pct
FROM cases
GROUP BY 1
ORDER BY MIN(max_dpd);

-- @id: Q24
-- @title: Monthly collections trend
-- @question: How many cases were worked each month and how much cash did collections recover?
-- @why: Tracks collections productivity and workload over time.
-- @tags: aggregation, date, COUNT DISTINCT
SELECT action_month,
       COUNT(*)                                          AS actions,
       COUNT(DISTINCT (loan_id, installment_no))         AS cases_touched,
       SUM(amount_recovered)                             AS amount_recovered,
       COUNT(*) FILTER (WHERE outcome = 'PAID_IN_FULL')  AS cases_paid_in_full
FROM analytics.collections
GROUP BY action_month
ORDER BY action_month;

-- @id: Q25
-- @title: Are repayment patterns changing? Late-payment share with a rolling 3-month average
-- @question: Is the share of installments that are not paid on the due date rising over time?
-- @why: A rising trend across cohorts is the signature of weakening underwriting or a macro shock. Rolling average removes noise.
-- @tags: CTE, window frame
WITH m AS (
    SELECT due_month, COUNT(*) AS installments,
           100.0 * AVG((dpd > 0)::int) AS late_pct
    FROM analytics.repayments
    GROUP BY due_month
)
SELECT due_month, installments, ROUND(late_pct, 2) AS late_pct,
       ROUND(AVG(late_pct) OVER (ORDER BY due_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS late_pct_rolling_3m
FROM m
ORDER BY due_month;

-- @id: Q26
-- @title: Top 3 defaulted exposures per employment type
-- @question: Which individual defaulted loans carry the largest outstanding balance within each employment type?
-- @why: Large single-name losses drive write-off planning and recovery escalation.
-- @tags: window, ROW_NUMBER, PARTITION BY, subquery
SELECT *
FROM (
    SELECT c.employment_type, l.loan_id, l.customer_id, l.outstanding_balance, l.current_dpd,
           ROW_NUMBER() OVER (PARTITION BY c.employment_type ORDER BY l.outstanding_balance DESC, l.loan_id) AS rn
    FROM analytics.loans l
    JOIN analytics.customers c ON c.customer_id = l.customer_id
    WHERE l.loan_status = 'DEFAULTED'
) t
WHERE rn <= 3
ORDER BY employment_type, rn;

-- @id: Q27
-- @title: Data-quality audit summary (from the ETL audit tables)
-- @question: Which validation rules fired in the latest pipeline run, and how many records did each affect?
-- @why: Gives analysts visibility into data trust; every rejected / fixed record is traceable in etl.data_quality_issues.
-- @tags: join, subquery, lineage
SELECT t.table_name, t.rule_id, t.action, t.failures, t.description
FROM etl.dq_rule_results t
WHERE t.run_id = (SELECT MAX(run_id) FROM etl.pipeline_runs) AND t.failures > 0
ORDER BY t.table_name, t.failures DESC, t.rule_id;

-- @id: Q28
-- @title: Vintage curves - share of loans ever 30+ DPD by instalment number
-- @question: For each half-year cohort, what % of loans had hit 30+ DPD by instalment 3, 6, 9 and 12?
-- @why: Vintage curves compare cohorts at the same age, the fairest way to see whether newer cohorts deteriorate faster.
-- @tags: CTE, CROSS JOIN, conditional aggregation
WITH f AS (
    SELECT l.loan_id, l.months_on_book,
           EXTRACT(YEAR FROM l.disbursement_date)::int || '-H' ||
           CASE WHEN EXTRACT(MONTH FROM l.disbursement_date) <= 6 THEN '1' ELSE '2' END AS cohort,
           MIN(r.installment_no) FILTER (WHERE r.dpd >= 30) AS first_30dpd_installment
    FROM analytics.loans l
    LEFT JOIN analytics.repayments r ON r.loan_id = l.loan_id
    GROUP BY l.loan_id, l.months_on_book, l.disbursement_date
)
SELECT cohort, ks.k AS installment_k,
       COUNT(*) FILTER (WHERE months_on_book >= ks.k + 1) AS loans_observed,
       ROUND(100.0 * COUNT(*) FILTER (WHERE months_on_book >= ks.k + 1 AND first_30dpd_installment <= ks.k)
             / NULLIF(COUNT(*) FILTER (WHERE months_on_book >= ks.k + 1), 0), 2) AS pct_ever_30dpd_by_k
FROM f
CROSS JOIN (VALUES (3), (6), (9), (12)) AS ks(k)
GROUP BY cohort, ks.k
HAVING COUNT(*) FILTER (WHERE months_on_book >= ks.k + 1) >= 200
ORDER BY cohort, ks.k;
