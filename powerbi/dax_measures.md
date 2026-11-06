# DAX measures (SYNTHETIC data)

> **Status: specification only.** No `.pbix` has been built or tested by the author of this repository. These measures are written to match the SQL views
> (`database/powerbi_views.sql`) and the Python KPIs (`src/kpis.py`). The three headline values were verified in SQL/Python
> (mature default rate **8.60 %**, PAR30 **27.38 %**, recovery **65.89 %**); after you build the report, **your cards must show the same numbers** - that is your acceptance test.

Tables (import from `powerbi/data/*.csv` or the `reporting.*` views): `Loans`, `Repayments`, `CollectionCases`, `CollectionActions`, `Date`.
Create a measures table: *Home > Enter data* with one blank column named `_`, name the table `_Measures`, then add the measures below.

## Portfolio

```dax
Total Disbursement = SUM ( Loans[loan_amount] )

Loans Count = COUNTROWS ( Loans )

Outstanding Portfolio = SUM ( Loans[outstanding_balance] )

Active Loans = CALCULATE ( COUNTROWS ( Loans ), Loans[loan_status] = "ACTIVE" )

Average Loan Amount = DIVIDE ( [Total Disbursement], [Loans Count] )

Open Outstanding = CALCULATE ( [Outstanding Portfolio], Loans[is_open] = TRUE () )

Delinquent Outstanding (30+) =
CALCULATE ( [Outstanding Portfolio], Loans[is_open] = TRUE (), Loans[current_dpd] >= 30 )

Portfolio Delinquency Rate = DIVIDE ( [Delinquent Outstanding (30+)], [Open Outstanding] )   -- format 0.00%
```

## Credit and risk

```dax
Mature Loans = CALCULATE ( COUNTROWS ( Loans ), Loans[is_mature] = TRUE () )

Defaults (Mature) = CALCULATE ( COUNTROWS ( Loans ), Loans[is_mature] = TRUE (), Loans[is_default] = TRUE () )

Default Rate = DIVIDE ( [Defaults (Mature)], [Mature Loans] )          -- ALWAYS mature loans only

Average DPD (Open) = CALCULATE ( AVERAGE ( Loans[current_dpd] ), Loans[is_open] = TRUE () )

High-Risk Exposure (60+ DPD) =
CALCULATE ( [Outstanding Portfolio], Loans[is_open] = TRUE (), Loans[current_dpd] >= 60 )

PAR90 = DIVIDE ( CALCULATE ( [Outstanding Portfolio], Loans[is_open] = TRUE (), Loans[current_dpd] >= 90 ), [Open Outstanding] )

-- Cohort view at constant age: share of loans with a 30+ DPD instalment among the first 6
Loans Hit 30DPD First 6 =
VAR _l = VALUES ( Loans[loan_id] )
RETURN
SUMX ( FILTER ( _l, CALCULATE ( COUNTROWS ( Loans ), Loans[months_on_book] >= 7 ) > 0 ),
       IF ( CALCULATE ( COUNTROWS ( Repayments ), Repayments[installment_no] <= 6, Repayments[dpd] >= 30 ) > 0, 1, 0 ) )

Cohort Eligible Loans = CALCULATE ( COUNTROWS ( Loans ), Loans[months_on_book] >= 7 )

% 30DPD In First 6 Instalments = DIVIDE ( [Loans Hit 30DPD First 6], [Cohort Eligible Loans] )
```

> Performance note: the cohort measure iterates loans x repayments. For a quicker model add a `hit_30dpd_first6` column to `Loans` in SQL/Power Query and use `AVERAGE`.

## Repayments

```dax
Instalments Due = COUNTROWS ( Repayments )
On-Time Rate = DIVIDE ( CALCULATE ( [Instalments Due], Repayments[repayment_status] = "PAID_ON_TIME" ), [Instalments Due] )
Collection Efficiency = DIVIDE ( SUM ( Repayments[paid_amount] ), SUM ( Repayments[due_amount] ) )
```

## Collections (use CollectionCases for amounts - never sum amount_due over actions)

```dax
Collection Cases = COUNTROWS ( CollectionCases )
Amount Collected = SUM ( CollectionCases[amount_recovered] )
Amount Due in Cases = SUM ( CollectionCases[amount_due] )
Recovery Rate = DIVIDE ( [Amount Collected], [Amount Due in Cases] )

Total Overdue Amount =
CALCULATE ( SUM ( Repayments[shortfall_amount] ),
            Repayments[repayment_status] IN { "UNPAID", "PARTIAL" },
            TREATAS ( VALUES ( Loans[loan_id] ), Repayments[loan_id] ),
            Loans[is_open] = TRUE () )

Overdue Accounts = CALCULATE ( COUNTROWS ( Loans ), Loans[is_open] = TRUE (), Loans[current_dpd] > 0 )

Actions = COUNTROWS ( CollectionActions )
```

## Time intelligence

```dax
Disbursement MoM % =
VAR _cur = [Total Disbursement]
VAR _prev = CALCULATE ( [Total Disbursement], DATEADD ( 'Date'[date], -1, MONTH ) )
RETURN DIVIDE ( _cur - _prev, _prev )
```

## Checks to run after building

| Card (no filters) | Expected |
|---|---|
| Loans Count | 20,131 |
| Total Disbursement | 3,013,006,000 |
| Outstanding Portfolio | 1,018,540,021 |
| Active Loans | 10,048 |
| Default Rate | 8.60 % |
| Portfolio Delinquency Rate | 27.38 % |
| Recovery Rate | 65.89 % |

(Values refer to seed 42 and the default generator settings; regenerate -> numbers change.)
