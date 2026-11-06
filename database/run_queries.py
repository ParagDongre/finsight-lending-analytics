"""Parse database/queries/business_queries.sql and run each query against PostgreSQL.

    python -m database.run_queries                 # run all, print first rows of each
    python -m database.run_queries --id Q04        # run one
    python -m database.run_queries --export        # also write each result to reports/sql_results/Qxx.csv
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd
import psycopg

from src import config

QUERY_FILE = config.QUERIES_DIR / "business_queries.sql"


def parse_queries(path: Path = QUERY_FILE) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^-- @id:\s*", text)[1:]
    out = []
    for b in blocks:
        lines = b.splitlines()
        meta = {"id": lines[0].strip()}
        sql_lines = []
        for ln in lines[1:]:
            m = re.match(r"-- @(\w+):\s*(.*)", ln)
            if m:
                meta[m.group(1)] = m.group(2).strip()
            elif not ln.startswith("-- ====="):
                sql_lines.append(ln)
        meta["sql"] = "\n".join(sql_lines).strip()
        out.append(meta)
    return out


def run_query(conn, sql: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d.name for d in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--rows", type=int, default=6)
    args = ap.parse_args()
    qs = [q for q in parse_queries() if not args.id or q["id"] == args.id]
    out_dir = config.REPORTS / "sql_results"
    if args.export:
        out_dir.mkdir(parents=True, exist_ok=True)
    with psycopg.connect(**config.db_params()) as conn:
        for q in qs:
            df = run_query(conn, q["sql"])
            print(f"\n=== {q['id']}  {q['title']}  ({len(df)} rows) ===")
            print(df.head(args.rows).to_string(index=False))
            if args.export:
                df.to_csv(out_dir / f"{q['id']}.csv", index=False)


if __name__ == "__main__":
    main()
