-- =====================================================================================
-- FinSight schema  (ALL DATA IS SYNTHETIC)
--
-- Three schemas keep raw and transformed data clearly separated:
--   raw        exact copy of the source CSV extracts, every column TEXT, nothing rejected
--   analytics  cleaned, typed, constrained, with derived fields  (query + Power BI layer)
--   etl        audit trail: every rejected / fixed / flagged record and every rule result
--
-- FULL REFRESH: this script drops and recreates the three schemas. Run it only against the
-- dedicated FinSight database.     psql -d finsight -f database/schema.sql
-- =====================================================================================
DROP SCHEMA IF EXISTS analytics CASCADE;
DROP SCHEMA IF EXISTS raw CASCADE;
DROP SCHEMA IF EXISTS etl CASCADE;
CREATE SCHEMA raw;
CREATE SCHEMA analytics;
CREATE SCHEMA etl;

-- -------------------------------------------------------------------------------------
-- RAW layer: everything TEXT so no bad value can ever make the load fail or be dropped.
-- _src_row = line number in the source CSV (header = line 1) for lineage.
-- -------------------------------------------------------------------------------------
CREATE TABLE raw.customers (
    customer_id TEXT, age TEXT, gender TEXT, city_tier TEXT, employment_type TEXT,
    acquisition_channel TEXT, signup_date TEXT, _src_row INTEGER, _loaded_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE raw.customer_financial_profiles (
    profile_id TEXT, customer_id TEXT, profile_date TEXT, monthly_income TEXT, existing_monthly_emi TEXT,
    credit_score TEXT, credit_utilization_pct TEXT, dependents TEXT, home_ownership TEXT,
    years_in_employment TEXT, previous_loans_count TEXT, _src_row INTEGER, _loaded_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE raw.loans (
    loan_id TEXT, customer_id TEXT, profile_id TEXT, loan_purpose TEXT, loan_amount TEXT, interest_rate TEXT,
    tenure_months TEXT, emi_amount TEXT, disbursement_date TEXT, first_due_date TEXT, maturity_date TEXT,
    outstanding_balance TEXT, current_dpd TEXT, loan_status TEXT, snapshot_date TEXT,
    _src_row INTEGER, _loaded_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE raw.repayments (
    repayment_id TEXT, loan_id TEXT, installment_no TEXT, due_date TEXT, due_amount TEXT, paid_amount TEXT,
    paid_date TEXT, dpd TEXT, repayment_status TEXT, _src_row INTEGER, _loaded_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE raw.collections (
    collection_id TEXT, loan_id TEXT, installment_no TEXT, action_date TEXT, dpd_at_action TEXT, channel TEXT,
    outcome TEXT, amount_due TEXT, amount_recovered TEXT, collection_status TEXT,
    _src_row INTEGER, _loaded_at TIMESTAMPTZ DEFAULT now());

-- -------------------------------------------------------------------------------------
-- ETL audit layer
-- -------------------------------------------------------------------------------------
CREATE TABLE etl.pipeline_runs (
    run_id SERIAL PRIMARY KEY, run_started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    seed INTEGER, snapshot_date DATE, notes TEXT);
CREATE TABLE etl.data_quality_issues (
    issue_id BIGSERIAL PRIMARY KEY, run_id INTEGER REFERENCES etl.pipeline_runs(run_id),
    table_name TEXT NOT NULL, src_row INTEGER, record_key TEXT, rule_id TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('REJECTED','FIXED','FLAGGED')),
    reason TEXT NOT NULL, raw_record JSONB);
CREATE TABLE etl.dq_rule_results (
    run_id INTEGER REFERENCES etl.pipeline_runs(run_id), table_name TEXT NOT NULL, rule_id TEXT NOT NULL,
    description TEXT NOT NULL, action TEXT NOT NULL, failures INTEGER NOT NULL,
    PRIMARY KEY (run_id, table_name, rule_id));
CREATE TABLE etl.dq_table_counts (
    run_id INTEGER REFERENCES etl.pipeline_runs(run_id), table_name TEXT NOT NULL,
    raw_rows INTEGER NOT NULL, clean_rows INTEGER NOT NULL, rejected_rows INTEGER NOT NULL,
    fixed_rows INTEGER NOT NULL, flagged_rows INTEGER NOT NULL,
    PRIMARY KEY (run_id, table_name),
    CHECK (raw_rows = clean_rows + rejected_rows));   -- nothing silently disappears

-- -------------------------------------------------------------------------------------
-- ANALYTICS layer (clean, typed, constrained)
-- -------------------------------------------------------------------------------------
CREATE TABLE analytics.customers (
    customer_id         VARCHAR(10) PRIMARY KEY,
    age                 SMALLINT CHECK (age BETWEEN 18 AND 75),            -- NULL when missing/invalid
    gender              VARCHAR(10) NOT NULL,
    city_tier           VARCHAR(10) NOT NULL,
    employment_type     VARCHAR(20) NOT NULL
        CHECK (employment_type IN ('Salaried','Self-Employed','Gig Worker','Business Owner','Contract Worker','Unknown')),
    acquisition_channel VARCHAR(20) NOT NULL,
    signup_date         DATE,
    age_band            VARCHAR(10)                                         -- derived
);

CREATE TABLE analytics.customer_financial_profiles (
    profile_id             VARCHAR(12) PRIMARY KEY,
    customer_id            VARCHAR(10) NOT NULL REFERENCES analytics.customers(customer_id),
    profile_date           DATE NOT NULL,                                   -- as at loan application
    monthly_income         NUMERIC(12,2) CHECK (monthly_income > 0),        -- NULL when missing
    income_missing         BOOLEAN NOT NULL,
    existing_monthly_emi   NUMERIC(12,2) NOT NULL CHECK (existing_monthly_emi >= 0),
    credit_score           SMALLINT CHECK (credit_score BETWEEN 300 AND 900),
    credit_utilization_pct NUMERIC(5,2) CHECK (credit_utilization_pct BETWEEN 0 AND 100),
    dependents             SMALLINT CHECK (dependents >= 0),
    home_ownership         VARCHAR(10),
    years_in_employment    NUMERIC(4,1) CHECK (years_in_employment >= 0),
    previous_loans_count   SMALLINT NOT NULL CHECK (previous_loans_count >= 0),
    income_bracket         VARCHAR(12)                                      -- derived
);

CREATE TABLE analytics.loans (
    loan_id             VARCHAR(10) PRIMARY KEY,
    customer_id         VARCHAR(10) NOT NULL REFERENCES analytics.customers(customer_id),
    profile_id          VARCHAR(12) NOT NULL REFERENCES analytics.customer_financial_profiles(profile_id),
    loan_purpose        VARCHAR(30) NOT NULL,
    loan_amount         NUMERIC(12,2) NOT NULL CHECK (loan_amount > 0),
    interest_rate       NUMERIC(5,2) NOT NULL CHECK (interest_rate BETWEEN 1 AND 60),   -- annual %
    tenure_months       SMALLINT NOT NULL CHECK (tenure_months BETWEEN 1 AND 60),
    emi_amount          NUMERIC(12,2) NOT NULL CHECK (emi_amount > 0),
    disbursement_date   DATE NOT NULL,
    first_due_date      DATE NOT NULL,
    maturity_date       DATE NOT NULL,
    outstanding_balance NUMERIC(12,2) NOT NULL CHECK (outstanding_balance >= 0),        -- principal outstanding at snapshot
    current_dpd         INTEGER NOT NULL CHECK (current_dpd >= 0),
    loan_status         VARCHAR(10) NOT NULL CHECK (loan_status IN ('ACTIVE','CLOSED','DEFAULTED')),
    snapshot_date       DATE NOT NULL,
    -- derived
    disbursement_month  DATE NOT NULL,
    months_on_book      SMALLINT NOT NULL,
    dpd_bucket          VARCHAR(8) NOT NULL,
    foir                NUMERIC(8,4),                                                   -- (existing EMI + new EMI) / income
    CHECK (disbursement_date <= snapshot_date),
    CHECK ((loan_status = 'CLOSED' AND outstanding_balance = 0) OR loan_status <> 'CLOSED'),
    CHECK ((loan_status = 'DEFAULTED') = (current_dpd >= 90) OR loan_status = 'CLOSED')
);
CREATE INDEX idx_loans_customer ON analytics.loans(customer_id);
CREATE INDEX idx_loans_month ON analytics.loans(disbursement_month);

CREATE TABLE analytics.repayments (
    repayment_id     VARCHAR(12) PRIMARY KEY,
    loan_id          VARCHAR(10) NOT NULL REFERENCES analytics.loans(loan_id),
    installment_no   SMALLINT NOT NULL CHECK (installment_no >= 1),
    due_date         DATE NOT NULL,
    due_amount       NUMERIC(12,2) NOT NULL CHECK (due_amount > 0),
    paid_amount      NUMERIC(12,2) NOT NULL CHECK (paid_amount >= 0),
    paid_date        DATE,
    dpd              INTEGER NOT NULL CHECK (dpd >= 0),     -- paid rows: days late at payment; UNPAID/PARTIAL: days overdue at snapshot
    repayment_status VARCHAR(14) NOT NULL CHECK (repayment_status IN ('PAID_ON_TIME','PAID_LATE','PARTIAL','UNPAID')),
    due_month        DATE NOT NULL,                         -- derived
    dpd_bucket       VARCHAR(8) NOT NULL,                   -- derived
    is_late          BOOLEAN NOT NULL,                      -- derived: dpd > 0
    UNIQUE (loan_id, installment_no),
    CHECK ((repayment_status = 'UNPAID' AND paid_amount = 0 AND paid_date IS NULL)
        OR (repayment_status <> 'UNPAID' AND paid_amount > 0 AND paid_date IS NOT NULL)),
    CHECK (paid_amount <= due_amount * 1.001)
);
CREATE INDEX idx_rep_loan ON analytics.repayments(loan_id);
CREATE INDEX idx_rep_due_month ON analytics.repayments(due_month);

CREATE TABLE analytics.collections (
    collection_id     VARCHAR(12) PRIMARY KEY,
    loan_id           VARCHAR(10) NOT NULL REFERENCES analytics.loans(loan_id),
    installment_no    SMALLINT NOT NULL,
    action_date       DATE NOT NULL,
    dpd_at_action     INTEGER NOT NULL CHECK (dpd_at_action >= 0),
    channel           VARCHAR(14) NOT NULL CHECK (channel IN ('SMS','APP_PUSH','CALL','FIELD_VISIT','LEGAL_NOTICE')),
    outcome           VARCHAR(16) NOT NULL CHECK (outcome IN ('PROMISE_TO_PAY','NO_RESPONSE','REFUSED_TO_PAY','PAID_IN_FULL','PARTIAL_PAYMENT')),
    amount_due        NUMERIC(12,2) NOT NULL CHECK (amount_due > 0),
    amount_recovered  NUMERIC(12,2) NOT NULL CHECK (amount_recovered >= 0),
    collection_status VARCHAR(16) NOT NULL CHECK (collection_status IN ('OPEN','PROMISE_TO_PAY','ESCALATED','RESOLVED','WRITTEN_OFF')),
    action_month      DATE NOT NULL,                         -- derived
    dpd_bucket        VARCHAR(8) NOT NULL,                   -- derived
    CHECK (amount_recovered <= amount_due * 1.001)
);
CREATE INDEX idx_col_loan ON analytics.collections(loan_id, installment_no);
CREATE INDEX idx_col_month ON analytics.collections(action_month);
