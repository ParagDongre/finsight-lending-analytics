"""EXTRACT step: read the source CSV extracts as raw strings (no type inference, no dropping)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src import config

TABLES = ["customers", "customer_financial_profiles", "loans", "repayments", "collections"]


def extract(raw_dir: Path = config.DATA_RAW) -> dict[str, pd.DataFrame]:
    out = {}
    for t in TABLES:
        path = Path(raw_dir) / f"{t}.csv"
        if not path.exists():
            raise FileNotFoundError(f"{path} not found. Generate data first:  python -m src.generation.generate_data")
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        df["_src_row"] = range(2, len(df) + 2)           # CSV line number (header is line 1)
        out[t] = df
    return out
