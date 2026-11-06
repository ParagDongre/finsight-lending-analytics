"""Deterministic SYNTHETIC data generator for FinSight.

Everything produced here is simulated. Nothing is real lending data and no statistic derived
from it should be quoted as a real-world lending benchmark.

Design (see docs/simulation_design.md for the full list of planted effects):
  * ~33 monthly origination cohorts (2023-07 .. 2026-03), growing volume, festive-season bump.
  * One financial-profile row per loan application (profile as at application date).
  * Latent default probability = logistic(credit score, FOIR, employment, channel, ...).
  * Installments are simulated one by one; collections actions are generated for overdue ones.
  * A CLEAN ground-truth set is produced first; src/generation/dirty.py then injects known
    defects so the ETL has real work to do.

Run:  python -m src.generation.generate_data
"""
from __future__ import annotations

import argparse
import calendar
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src import config

# ----------------------------------------------------------------------------------------------
# Simulation parameters
# ----------------------------------------------------------------------------------------------
EMP = {  # share, median income (INR/month), mean credit score, default-logit shift
    "Salaried":        dict(p=0.48, inc=42000, credit=735, risk=0.00),
    "Self-Employed":   dict(p=0.20, inc=38000, credit=710, risk=0.25),
    "Gig Worker":      dict(p=0.14, inc=24000, credit=675, risk=0.55),
    "Business Owner":  dict(p=0.10, inc=60000, credit=720, risk=0.10),
    "Contract Worker": dict(p=0.08, inc=30000, credit=695, risk=0.30),
}
TIER = {"Tier 1": (0.40, 0.00), "Tier 2": (0.35, 0.10), "Tier 3": (0.25, 0.25)}
CHANNEL = {"Organic": (0.38, 0.00), "Paid Digital": (0.26, 0.15),
           "Partner Referral": (0.20, 0.35), "Customer Referral": (0.16, -0.15)}
GENDER = {"Male": 0.62, "Female": 0.37, "Other": 0.01}     # NO effect on default (designed null)
PURPOSES = ["Debt Consolidation", "Medical", "Education", "Travel", "Home Improvement",
            "Wedding", "Business Working Capital", "Other"]
PURPOSE_P = [0.22, 0.12, 0.12, 0.10, 0.14, 0.08, 0.10, 0.12]
HOME = {"Rented": 0.55, "Owned": 0.30, "Family": 0.15}
TENURES = [6, 9, 12, 18, 24, 36]
TENURE_P = [0.10, 0.12, 0.30, 0.15, 0.20, 0.13]

INTERCEPT = -3.55         # calibrated so that overall latent default rate is ~9-11 %
DRIFT_MAX = 0.50          # extra default logit for the most recent cohorts
OFFSETS = [1, 3, 7, 15, 30, 45, 60, 90, 120, 150, 180]
OFFSET_CHANNEL = {1: ["SMS", "APP_PUSH"], 3: ["SMS", "CALL"], 7: ["CALL"], 15: ["CALL"],
                  30: ["CALL", "FIELD_VISIT"], 45: ["CALL", "FIELD_VISIT"], 60: ["LEGAL_NOTICE"],
                  90: ["LEGAL_NOTICE", "FIELD_VISIT"], 120: ["FIELD_VISIT"],
                  150: ["LEGAL_NOTICE"], 180: ["LEGAL_NOTICE"]}


def add_months(d: date, n: int) -> date:
    y = d.year + (d.month - 1 + n) // 12
    m = (d.month - 1 + n) % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_starts(first: date, last: date) -> list[date]:
    out, cur = [], first
    while cur <= last:
        out.append(cur)
        cur = add_months(cur, 1)
    return out


def _choice(rng: np.random.Generator, mapping: dict, idx: int = 0):
    keys = list(mapping.keys())
    p = np.array([v if np.isscalar(v) else v[idx] for v in mapping.values()], dtype=float)
    return keys[rng.choice(len(keys), p=p / p.sum())]


def emi_formula(principal: float, annual_rate_pct: float, n: int) -> float:
    r = annual_rate_pct / 1200.0
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def _new_customer(rng, cid: str, first_app_date: date) -> dict:
    emp = _choice(rng, {k: v["p"] for k, v in EMP.items()})
    age = int(np.clip(rng.normal(33, 8), 21, 60))
    income = EMP[emp]["inc"] * rng.lognormal(0, 0.45)
    income = float(np.clip(round(income, -2), 12000, 400000))
    credit = EMP[emp]["credit"] + 0.8 * (age - 33) + rng.normal(0, 55)
    return dict(
        customer_id=cid, age=age, gender=_choice(rng, GENDER),
        city_tier=_choice(rng, TIER), employment_type=emp,
        acquisition_channel=_choice(rng, CHANNEL, 0),
        signup_date=first_app_date - timedelta(days=int(rng.integers(0, 61))),
        _income=income, _credit=float(np.clip(credit, 300, 900)),
        _years_emp=float(round(rng.exponential(4.0) + 0.3, 1)),
        _home=_choice(rng, HOME),
    )


def generate(seed: int = config.SEED, snapshot: date = config.SNAPSHOT_DATE) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    months = month_starts(config.FIRST_DISBURSEMENT_MONTH, config.LAST_DISBURSEMENT_MONTH)
    n_m = len(months)

    customers: dict[str, dict] = {}
    cust_state: dict[str, list] = {}    # cid -> [ready_date, blocked, n_prev_loans]
    profiles, loans, repays, colls = [], [], [], []
    cust_seq = prof_seq = loan_seq = rep_seq = col_seq = 0
    stats = dict(latent_default=0, n_loans=0)

    for mi, mstart in enumerate(months):
        base = 300 + 600 * mi / (n_m - 1)
        festive = 1.15 if mstart.month in (10, 11) else 1.0
        n_apps = int(base * festive * rng.uniform(0.93, 1.07))
        drift_frac = float(np.clip(
            ((mstart.year - config.DRIFT_START_MONTH.year) * 12 + mstart.month - config.DRIFT_START_MONTH.month) / 12, 0, 1))
        eligible = [c for c, (rd, blocked, _) in cust_state.items() if rd <= mstart and not blocked]
        ndays = calendar.monthrange(mstart.year, mstart.month)[1]

        for _ in range(n_apps):
            disb = date(mstart.year, mstart.month, int(rng.integers(1, ndays + 1)))
            is_repeat = bool(eligible) and rng.random() < 0.22
            if is_repeat:
                k = int(rng.integers(0, len(eligible)))
                cid = eligible.pop(k)
                cu = customers[cid]
                cu["_income"] = float(np.clip(round(cu["_income"] * rng.lognormal(0.04, 0.06), -2), 12000, 400000))
                cu["_credit"] = float(np.clip(cu["_credit"] + rng.normal(5, 15), 300, 900))
                cu["_years_emp"] = round(cu["_years_emp"] + 0.5, 1)
            else:
                cust_seq += 1
                cid = f"C{cust_seq:06d}"
                cu = _new_customer(rng, cid, disb)
                customers[cid] = cu
                cust_state[cid] = [date(1900, 1, 1), False, 0]
            prev_loans = cust_state[cid][2]

            # ---- financial profile (as at application date) ----
            income = cu["_income"]
            credit = int(round(np.clip(cu["_credit"] + rng.normal(0, 8), 300, 900)))
            existing_emi = 0.0 if rng.random() < 0.25 else round(income * float(rng.beta(2, 6)) * 0.9, 2)
            util = float(round(rng.beta(2, 3) * 100, 2))
            deps = int(np.clip(rng.poisson(1.2), 0, 5))
            prof_seq += 1
            pid = f"FP{prof_seq:07d}"
            profiles.append(dict(
                profile_id=pid, customer_id=cid, profile_date=disb, monthly_income=income,
                existing_monthly_emi=existing_emi, credit_score=credit, credit_utilization_pct=util,
                dependents=deps, home_ownership=cu["_home"], years_in_employment=cu["_years_emp"],
                previous_loans_count=prev_loans))

            # ---- loan terms ----
            tenure = int(rng.choice(TENURES, p=TENURE_P))
            mult = float(np.clip(rng.lognormal(np.log(3.0), 0.5), 0.8, 10))
            amount = float(np.clip(round(income * mult, -3), 10000, 1000000))
            rate = float(np.clip(11 + (800 - credit) / 16 + 0.04 * tenure + rng.normal(0, 1.0), 10, 36))
            rate = round(rate, 2)
            emi = round(emi_formula(amount, rate, tenure), 2)
            foir = (existing_emi + emi) / income
            purpose = PURPOSES[int(rng.choice(len(PURPOSES), p=PURPOSE_P))]

            # ---- latent default probability (designed ground truth) ----
            z = (INTERCEPT
                 - 0.011 * (credit - 700)
                 + 2.2 * (foir - 0.35)
                 + EMP[cu["employment_type"]]["risk"]
                 + 0.012 * (util - 40)
                 + TIER[cu["city_tier"]][1]
                 + CHANNEL[cu["acquisition_channel"]][1]
                 + (0.02 * (30 - cu["age"]) if cu["age"] < 30 else 0.0)
                 + 0.25 * (mult - 3)
                 + 0.015 * (tenure - 12)
                 - (0.35 if prev_loans > 0 else 0.0)
                 + DRIFT_MAX * drift_frac)
            p_def = float(1 / (1 + np.exp(-z)))
            is_def = bool(rng.random() < p_def)

            loan_seq += 1
            lid = f"L{loan_seq:06d}"
            maturity = add_months(disb, tenure)
            cust_state[cid][0] = maturity
            cust_state[cid][2] = prev_loans + 1
            if is_def:
                cust_state[cid][1] = True
            stats["n_loans"] += 1
            stats["latent_default"] += int(is_def)

            # ---- installment simulation ----
            onset = int(min(rng.geometric(0.25), tenure)) if is_def else None
            stress_inst = int(rng.integers(1, tenure + 1)) if (not is_def and rng.random() < 0.07) else None
            late_prob = float(np.clip((0.04 + 1.0 * p_def) * (1 + 0.7 * drift_frac), 0.02, 0.55))
            r_m = rate / 1200.0
            bal = amount
            principal_repaid = 0.0
            n_due = 0
            all_paid_full = True
            max_unpaid_dpd = 0
            for j in range(1, tenure + 1):
                due = add_months(disb, j)
                interest_j = bal * r_m
                princ_j = emi - interest_j
                bal -= princ_j
                if due >= snapshot:
                    continue      # future installment: not part of the extract (loan cannot be CLOSED)
                n_due += 1
                paid_amt, paid_date, delay, status = 0.0, None, None, "UNPAID"
                if is_def and j >= onset:
                    if j == onset and rng.random() < 0.30:
                        delay = int(rng.integers(8, 60))
                        pd_ = due + timedelta(days=delay)
                        if pd_ <= snapshot:
                            paid_amt = round(emi * float(rng.uniform(0.3, 0.8)), 2)
                            paid_date, status = pd_, "PARTIAL"
                else:
                    if stress_inst == j:
                        delay = int(rng.integers(35, 86))
                    elif rng.random() < late_prob:
                        delay = 1 + min(int(rng.exponential(7)), 44)
                    else:
                        delay = int(rng.choice([-2, -1, 0, 0, 0, 0]))
                    pd_ = due + timedelta(days=delay)
                    if pd_ <= snapshot:
                        paid_amt, paid_date = emi, pd_
                        status = "PAID_LATE" if delay > 0 else "PAID_ON_TIME"
                dpd_snap = (snapshot - due).days
                if status in ("PAID_ON_TIME", "PAID_LATE"):
                    dpd = max(delay, 0)
                    principal_repaid += princ_j
                else:
                    dpd = dpd_snap
                    all_paid_full = False
                    max_unpaid_dpd = max(max_unpaid_dpd, dpd_snap)
                    if status == "PARTIAL":
                        principal_repaid += princ_j * paid_amt / emi
                rep_seq += 1
                repays.append(dict(
                    repayment_id=f"R{rep_seq:08d}", loan_id=lid, installment_no=j, due_date=due,
                    due_amount=emi, paid_amount=round(paid_amt, 2), paid_date=paid_date, dpd=dpd,
                    repayment_status=status))

                # ---- collections actions for overdue installments ----
                if status in ("PAID_LATE",) and delay >= 1:
                    offs = [o for o in OFFSETS if o <= delay]
                elif status in ("UNPAID", "PARTIAL"):
                    offs = [o for o in OFFSETS if o <= dpd_snap]
                else:
                    offs = []
                for oi, o in enumerate(offs):
                    last = oi == len(offs) - 1
                    col_seq += 1
                    chan = OFFSET_CHANNEL[o][int(rng.integers(0, len(OFFSET_CHANNEL[o])))]
                    recovered, outcome = 0.0, None
                    if status == "PAID_LATE" and last:
                        outcome, recovered, cstat = "PAID_IN_FULL", emi, "RESOLVED"
                    elif status == "PARTIAL" and delay is not None and o <= delay and (
                            oi == len(offs) - 1 or offs[oi + 1] > delay):
                        outcome, recovered, cstat = "PARTIAL_PAYMENT", paid_amt, "OPEN"
                    else:
                        outcome = ["PROMISE_TO_PAY", "NO_RESPONSE", "REFUSED_TO_PAY"][
                            int(rng.choice(3, p=[0.35, 0.50, 0.15]))]
                        cstat = ("WRITTEN_OFF" if o >= 180 else "ESCALATED" if o >= 60
                                 else "PROMISE_TO_PAY" if outcome == "PROMISE_TO_PAY" else "OPEN")
                    colls.append(dict(
                        collection_id=f"COL{col_seq:08d}", loan_id=lid, installment_no=j,
                        action_date=due + timedelta(days=o), dpd_at_action=o, channel=chan,
                        outcome=outcome, amount_due=emi, amount_recovered=round(recovered, 2),
                        collection_status=cstat))

            closed = (n_due == tenure) and all_paid_full and max_unpaid_dpd == 0
            if closed:
                outstanding, status_l, cur_dpd = 0.0, "CLOSED", 0
            else:
                outstanding = round(max(amount - principal_repaid, 0.0), 2)
                cur_dpd = int(max_unpaid_dpd)
                status_l = "DEFAULTED" if cur_dpd >= 90 else "ACTIVE"
            loans.append(dict(
                loan_id=lid, customer_id=cid, profile_id=pid, loan_purpose=purpose, loan_amount=amount,
                interest_rate=rate, tenure_months=tenure, emi_amount=emi, disbursement_date=disb,
                first_due_date=add_months(disb, 1), maturity_date=maturity,
                outstanding_balance=outstanding, current_dpd=cur_dpd, loan_status=status_l,
                snapshot_date=snapshot))

    cust_cols = ["customer_id", "age", "gender", "city_tier", "employment_type",
                 "acquisition_channel", "signup_date"]
    out = {
        "customers": pd.DataFrame([{k: c[k] for k in cust_cols} for c in customers.values()]),
        "customer_financial_profiles": pd.DataFrame(profiles),
        "loans": pd.DataFrame(loans),
        "repayments": pd.DataFrame(repays),
        "collections": pd.DataFrame(colls),
    }
    out["_stats"] = pd.DataFrame([dict(latent_default_rate=stats["latent_default"] / stats["n_loans"],
                                       n_loans=stats["n_loans"])])
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate SYNTHETIC FinSight source extracts (raw CSVs).")
    ap.add_argument("--seed", type=int, default=config.SEED)
    ap.add_argument("--out", default=str(config.DATA_RAW))
    ap.add_argument("--no-dirt", action="store_true", help="write the clean ground truth without injected defects")
    args = ap.parse_args()

    from src.generation.dirty import inject_defects  # local import keeps module import light

    clean = generate(seed=args.seed)
    stats = clean.pop("_stats").iloc[0]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if args.no_dirt:
        for name, df in clean.items():
            df.to_csv(out / f"{name}.csv", index=False)
        manifest = {}
    else:
        raw, manifest = inject_defects(clean, np.random.default_rng(args.seed + 1), config.SNAPSHOT_DATE)
        for name, df in raw.items():
            df.to_csv(out / f"{name}.csv", index=False, na_rep="")
    (out / "_injection_manifest.json").write_text(json.dumps(manifest, indent=2))
    # a copy of the clean ground truth is kept for tests / ETL reconciliation
    gt = out.parent / "processed" / "_ground_truth"
    gt.mkdir(parents=True, exist_ok=True)
    for name, df in clean.items():
        df.to_csv(gt / f"{name}.csv", index=False)

    print("SYNTHETIC data generated (seed=%d). Rows:" % args.seed)
    for name, df in clean.items():
        print(f"  {name:30s} {len(df):>9,d}")
    print(f"  latent default rate (simulation parameter, not an observed statistic): {stats['latent_default_rate']:.3%}")
    print(f"  injected defects: {sum(manifest.values()) if manifest else 0}")


if __name__ == "__main__":
    main()
