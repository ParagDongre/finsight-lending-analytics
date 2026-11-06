# Simulation design - what was planted in the synthetic data

Being explicit about planted effects keeps the project honest: analysis results can be checked against the known truth, and nobody should mistake them for real-world findings.

## Structure
- 33 monthly cohorts (Jul 2023 - Mar 2026); monthly applications grow from ~300 to ~900, with a 15 % festive-season bump in Oct/Nov. 22 % of loans go to repeat customers (who may borrow again only after the previous loan matured without default).
- One financial-profile row per application. Loans amortise with the standard EMI formula; instalments are simulated one by one up to the 30 Jun 2026 snapshot; collections actions are generated at 1, 3, 7, 15, 30, 45, 60, 90, 120, 150, 180 days overdue.

## Planted default drivers (logistic latent model, intercept calibrated for ~9-10 % lifetime default)
| Driver | Direction |
|---|---|
| Credit score | lower score -> more default |
| FOIR (obligations / income) | higher -> more default (strongest affordability effect) |
| Employment type | gig > contract > self-employed > business owner > salaried |
| Credit utilisation, loan-to-income, tenure | higher -> more default |
| City tier, acquisition channel | Tier 3, partner referral, paid digital -> more default; customer referral -> less |
| Age < 30, previous loans | young -> more; repeat customers -> less |
| **Cohort drift** | extra risk phased in for loans from Jul 2024 onwards (so newer cohorts deteriorate) |
| **Gender** | **no effect (deliberate null)**, to test that we do not "find" spurious significance |

Other deliberate features: interest rate is priced from credit score (so the two are correlated); missing income/score/age are random (no link to default); ~7 % of non-defaulting loans have one stressed instalment; late-payment probability rises with latent risk and with the drift.

## What the simulator does NOT model (see docs/limitations.md)
Write-offs, restructuring, prepayment, fees, macro conditions, fraud, seasonality in repayment behaviour, and the effect of collections actions on outcomes (collections outcomes are generated from the instalment outcome, so channel "effectiveness" is not causal).

## Injected data defects
`src/generation/dirty.py` injects 32 defect types (duplicate keys, orphan foreign keys, negative amounts, invalid dates, out-of-range values, inconsistent statuses, overpayments, ...) and records counts in `data/raw/_injection_manifest.json`. A test requires the ETL to catch every type.
