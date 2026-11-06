"""End-to-end ETL:  raw CSV -> raw schema -> validate/transform -> analytics schema (+ audit tables).

    python -m etl.run_pipeline                 # full run incl. PostgreSQL
    python -m etl.run_pipeline --no-db         # transform + files only (no database needed)
    python -m etl.run_pipeline --generate      # (re)generate synthetic raw data first
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime

from etl.dq_report import write_report
from etl.extract import extract
from etl.transform import transform_all
from src import config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-db", action="store_true", help="skip PostgreSQL (still writes processed/rejected files + report)")
    ap.add_argument("--generate", action="store_true", help="regenerate the synthetic raw data first")
    ap.add_argument("--seed", type=int, default=config.SEED)
    args = ap.parse_args()

    if args.generate or not (config.DATA_RAW / "loans.csv").exists():
        subprocess.run([sys.executable, "-m", "src.generation.generate_data", "--seed", str(args.seed)], check=True)

    print("[1/5] Extract raw CSVs ...")
    raw = extract()
    print("[2/5] Validate + transform ...")
    res = transform_all(raw, config.SNAPSHOT_DATE)

    print("[3/5] Write processed / rejected files + DQ report ...")
    config.DATA_PROCESSED.mkdir(parents=True, exist_ok=True)
    config.DATA_REJECTED.mkdir(parents=True, exist_ok=True)
    for name, df in res.clean.items():
        df.to_csv(config.DATA_PROCESSED / f"{name}.csv", index=False)
    for name in res.clean:
        sub = res.issues[(res.issues.table_name == name) & (res.issues.action == "REJECTED")]
        sub.to_csv(config.DATA_REJECTED / f"{name}_rejected.csv", index=False)
    res.issues.to_csv(config.DATA_REJECTED / "all_issues.csv", index=False)
    write_report(res, config.DATA_RAW / "_injection_manifest.json", config.REPORTS / "data_quality_report.md",
                 datetime.now().strftime("%Y-%m-%d %H:%M"))

    if not args.no_db:
        from etl import load
        print("[4/5] Load PostgreSQL (schema reset -> raw -> analytics -> audit) ...")
        with load.connect() as conn:
            load.run_sql_file(conn, config.SCHEMA_SQL)
            load.load_raw(conn, raw)
            load.load_analytics(conn, res.clean)
            run_id = load.load_audit(conn, res.issues, res.rule_results, res.counts, args.seed, config.SNAPSHOT_DATE,
                                     "FinSight synthetic data")
            conn.commit()
        print(f"      committed (etl.pipeline_runs.run_id = {run_id})")
    else:
        print("[4/5] --no-db: PostgreSQL load skipped")

    print("[5/5] Summary")
    print(res.counts.to_string(index=False))
    bad = res.counts[res.counts.raw_rows != res.counts.clean_rows + res.counts.rejected_rows]
    if len(bad):
        raise SystemExit("INTEGRITY FAILURE: rows unaccounted for in " + ", ".join(bad.table_name))
    print("OK: every raw row is either in the clean table or in the rejected log.")


if __name__ == "__main__":
    main()
