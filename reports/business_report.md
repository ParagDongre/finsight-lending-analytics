# FinSight - Portfolio, Credit Risk and Collections Report

> **SYNTHETIC DATA.** Every figure below comes from a simulated personal-loan book (seed 42, as-of date 30 Jun 2026). Findings describe the *simulation*, not real lending, and must not be quoted as industry statistics. The simulator contains designed effects (listed in `docs/simulation_design.md`); the analysis shows the pipeline can recover them, which is the point of the exercise.
> Reproduce every number: `python -m etl.run_pipeline --generate`, then the commands in the README. Source of each figure is given in brackets (SQL query id, or results file).

**Reading guide.** *Facts* are measured in the data. *Hypotheses* are explanations that fit the facts but are not proven. *Recommendations* are actions, each tied to the facts that motivate it. Expected impact is scenario arithmetic on synthetic data, not a forecast.

---

## 1. Business context and questions
A digital lender disburses unsecured personal loans (6-36 months). Management asked: (1) which segments default most, (2) how is the book performing, (3) which cohorts are deteriorating, (4) how effective is collections, (5) what is associated with default, (6) are repayment patterns changing, (7) which interventions could help.

## 2. Data and methods in brief
- 20,131 loans, 16,812 customers, 232,795 instalments, 229,472 collection actions after ETL. The ETL quarantined 213 loans, 3,715 instalments and 3,052 collection actions with logged reasons; nothing was dropped silently (`reports/data_quality_report.md`). The raw extract contained 32 injected defect types and all 32 were caught.
- **Definitions.** Default = 90+ days past due (DPD) at the as-of date. *Default rate* uses **mature loans only** (>= 15 months on book; n = 10,364) because younger loans have not had time to default. Delinquency rate = balance of open loans 30+ DPD / balance of open loans (PAR30). Recovery rate is computed on collection *cases* (loan x instalment), not actions.
- Statistics: two-proportion z-tests, chi-square, Mann-Whitney, logistic regression; Holm correction across four pre-specified hypotheses. ML: out-of-time split (train: disbursed to Sep 2024; test: Oct 2024 - Mar 2025).

## 3. Observed facts

### 3.1 Portfolio
| Metric | Value | Source |
|---|---|---|
| Loans / disbursed | 20,131 / ₹301.30 Cr (avg ₹149,670) | Q01 |
| Outstanding principal | ₹101.85 Cr (open: ₹76.76 Cr active + ₹25.09 Cr defaulted) | Q02 |
| Active / closed / defaulted loans | 10,048 / 8,502 / 1,581 | Q02 |
| Default rate, mature loans | **8.60 %** (891 / 10,364; 95 % CI 8.07 - 9.15 %) | statistics.json |
| PAR30 (by balance) | 27.38 % - *inflated, see limitation L1* | Q06 / Q16 |
| Monthly origination | grew from ~300 to >900 loans/month over 33 months | Q01, Q12 |

### 3.2 Who defaults (mature loans) 
- By employment: Gig Worker 15.1 %, Contract 11.8 %, Self-employed 9.9 %, Business owner 7.6 %, Salaried 5.9 % [Q04]. Gig vs salaried: +9.1 percentage points (95 % CI 7.1 - 11.1), risk ratio 2.54, p < 0.001, Holm-adjusted p < 0.001.
- By credit score: <600: 27.4 %; 600-649: 18.6 %; 650-699: 10.8 %; falling steadily above that [Q17]. Defaulters' median score 681 vs 721 for non-defaulters (Cohen's d = -0.68).
- By affordability (FOIR = (existing EMI + new EMI) / income): <30 %: 3.8 %; 30-45 %: 5.6 %; 45-60 %: 8.1 %; **60 %+: 18.7 %** [Q19]. The 60 %+ band is 22.9 % of mature loans but about half of all defaults (444 of 891; direct count on mature loans with FOIR >= 60 %).
- By acquisition channel: Partner referral 10.0 %, Paid digital 10.0 %, Customer referral 7.6 %, Organic 7.3 % [query on analytics tables, see Q18 for channel x tier]. Within every channel Tier 1 has the lowest default rate; Tier 3 is the highest in three of four channels (Partner Referral is the exception, where Tier 2 is highest) [Q18].
- By tenure: 6-month loans 14.5 %, 9-12 month 8.6 %, 18 month 7.9 %, 24 month 7.0 %, 36 month 7.6 % [Q13].
- New customers 8.9 % vs repeat 6.4 % [Q20].
- **After adjusting for other factors** (logistic regression, n = 10,107): credit score (OR 0.32 per +100 points), FOIR (OR 1.46 per +10 pp), utilisation (OR 1.12 per +10 pp), gig worker (OR 1.56), Tier 3 (OR 1.38), partner referral (OR 1.51), paid digital (OR 1.46) remain associated with default. Gender is not (OR 1.01, 95 % CI 0.86 - 1.19, p = 0.86); the unadjusted female-vs-male difference was also not significant (p = 0.30).

### 3.3 Are things getting worse?
- Share of loans hitting 30+ DPD within their first 6 instalments rose from ~10 % (cohorts Jul 2023 - Jun 2024) to ~12.5 % (Jul 2024 - Sep 2025): difference +1.8 pp (95 % CI 0.7 - 2.9), p = 0.001 (Holm-adjusted 0.003) [Q09, Q28; statistics.json H3].
- Adjusting for customer mix in the logistic model, the later-cohort indicator is still associated with default (OR 1.18, 95 % CI 1.01 - 1.38, p = 0.035). This is borderline: small effect, wide interval, not corrected for multiple testing across all model terms.
- Late-payment share of instalments rises from ~12 % to ~26 % by due month [Q25]; **this trend is partly an artefact**: the book is ageing and recent months contain payments not yet made.

### 3.4 Collections
- Overall recovery rate 65.9 % of ₹68.1 Cr due across 49,751 cases [Q08].
- Recovery falls steeply with how far a case ages: 95.7 % (1-29 DPD), 49.1 % (30-59), 28.4 % (60-89), **2.9 % (90+)** [Q23].
- Of mature loans that ever reached 30+ DPD, 51 % ended defaulted [Q21]. (Reaching 90+ requires passing 30+, so the other direction is trivially ~0 and not informative.)
- Channels: SMS/calls act at ~2-13 days overdue, field visits/legal notices at 76-118 days [Q22]. Channel "success rates" are **not comparable** because of this timing difference.

### 3.5 Predictive models (out-of-time test, n = 3,856)
| Model | ROC-AUC | PR-AUC | Precision | Recall | F1 |
|---|---|---|---|---|---|
| Dummy (prior) | 0.500 | 0.088 | 0.00 | 0.00 | 0.00 |
| Logistic regression | **0.805** | 0.394 | 0.41 | 0.38 | 0.40 |
| Random forest | 0.794 | 0.368 | 0.29 | 0.50 | 0.37 |
| Gradient boosting | 0.787 | 0.355 | 0.36 | 0.37 | 0.36 |
- Scoring at origination ranks risk usefully: the riskiest 20 % of loans by score contain 58 % of test-period defaults (random would give 20 %). Simple logistic regression matched or beat tree models.
- Top drivers (permutation importance): credit score, FOIR, loan-to-income, utilisation.
- Leakage check: giving the model `current_dpd` yields AUC 1.00 - meaningless in production; honest out-of-time AUC is 0.805.
- Repayment regression (share of first six instalments paid): R² 0.09 (ridge), MAE 0.083 vs baseline 0.090. Weak: 92.6 % of loans pay everything, so little variance remains to explain.

## 4. Hypotheses (not proven)
1. **H-A: Weaker underwriting of recent cohorts** (more partner/paid-digital volume, higher FOIR) explains the rise in early delinquency. *Evidence for:* channel and FOIR are associated with default and volume grew. *Missing:* a mix decomposition of cohort change; we only have the adjusted OR of 1.18.
2. **H-B: Short-tenure loans default more because of higher monthly burden** (6-month EMIs are large relative to income). *Evidence:* 6-month loans show the highest default rate; FOIR is a strong predictor. *Missing:* test within FOIR bands.
3. **H-C: Early collections contact causes better recovery.** The 95.7 % vs 2.9 % gradient is consistent with this, but it is also mechanically produced by who ends up at each DPD (borrowers who will pay do so early). This **cannot** be concluded from observational data.
4. **H-D: Channel quality differences** are driven by the mix of customers each channel attracts, not by the channel itself.

## 5. Risks and opportunities
- **Risk:** concentration of defaults in high-FOIR, low-score, gig-worker, Tier-3 and partner-sourced loans; early-delinquency drift in newer cohorts that cannot yet show defaults (right-censoring).
- **Risk:** model decays if applicant mix shifts; score probabilities are not calibrated (class weighting).
- **Opportunity:** a simple scorecard concentrates risk well; early intervention window exists between 1-59 DPD where recovery is still high.

## 6. Recommendations (each tied to evidence)
| # | Recommendation | Evidence | Expected impact (scenario, not forecast) |
|---|---|---|---|
| 1 | **Pilot an affordability cap** (e.g. decline or reduce amounts above FOIR 60 %), tested on a randomised holdout | 60 %+ FOIR: 18.7 % default vs 3.8 - 8.1 % below; 22.9 % of loans, ~50 % of defaults (§3.2) | If the cap removed the 60 %+ band entirely, simulated mature defaults would fall ~50 % at a cost of ~23 % of volume; true effect depends on pricing, margin and borrower behaviour, which this data cannot tell us. |
| 2 | **Use the logistic scorecard for risk-based limits and pricing review**, after recalibration and a fairness audit; exclude gender | AUC 0.805 out-of-time; top 20 % of scores hold 58 % of defaults (§3.5); gender has no effect | Ranking only; no monetary estimate without margin data. |
| 3 | **Move first collection contact earlier and intensify 30-59 DPD treatment**; measure with an A/B test | Recovery 95.7 % -> 49.1 % -> 28.4 % -> 2.9 %; 51 % of 30+ DPD loans default (§3.4). Causality unproven (H-C) | Each 10 pp improvement in 30-59 DPD recovery would add ~₹0.26 Cr on the ₹2.6 Cr due in that bucket (arithmetic on §3.4 data). |
| 4 | **Review partner-referral and paid-digital acquisition criteria** | Channel default 10.0 % vs 7.3 % organic; adjusted ORs 1.5; the effect survived adjustment (§3.2) | Needs cost-per-acquisition data to evaluate. |
| 5 | **Track cohort vintage curves monthly** (Q28) and report PAR on a write-off-adjusted basis | Newer cohorts show higher early delinquency (§3.3) | Early warning before defaults mature. |
| 6 | **Limit short-tenure (6-month) loans for high-FOIR applicants** only if H-B is confirmed within FOIR bands | 14.5 % default at 6 months (§3.2) | Pending follow-up analysis. |

## 7. Limitations and caveats
- **L1 No write-offs.** Defaulted loans stay on the book at full balance, so PAR30 (27.4 %) and the share of "outstanding" in default (24.6 %) are far above what a lender reports after write-offs. Use trends, not levels.
- **L2 Synthetic data.** Effect sizes and model performance reflect the simulator; real data will be noisier, with selection effects (we only see funded loans) and unobserved variables.
- **L3 Right-censoring.** Default rates use loans >= 15 months old, so the newest cohorts are not evaluated for default.
- **L4 Association, not causation.** No recommendation here is proven causal; hence the pilots and A/B tests.
- **L5 Independence.** Repeat borrowers appear more than once; p-values are slightly optimistic.
- **L6 No profitability data.** Interest income, cost of funds and collection costs are not modelled, so no ROI is claimed.

## 8. Follow-up analysis
Mix-versus-rate decomposition of cohort change; FOIR-stratified tenure analysis (H-B); roll-rate matrices (DPD transitions month to month); survival analysis of time-to-default; randomised pilots for recommendations 1 and 3; profitability layer (interest, cost of funds, collections cost); calibration of score to probability of default.
