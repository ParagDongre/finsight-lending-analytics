"""Reusable validation helpers + the issue log.

Principles
  * Every rule is evaluated independently on EVERY row (a bad row is never hidden by an earlier rule).
  * Each outcome is one of  REJECTED (row quarantined) | FIXED (value corrected/nulled, logged) | FLAGGED (kept as-is, logged).
  * Nothing is ever dropped without a log entry:  raw_rows == clean_rows + rejected_rows.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DPD_BINS = [-np.inf, 0, 29, 59, 89, np.inf]
DPD_LABELS = ["Current", "1-29", "30-59", "60-89", "90+"]


def to_num(s: pd.Series) -> pd.Series:
    """Parse to float; anything non-numeric becomes NaN."""
    return pd.to_numeric(s.astype("string").str.strip(), errors="coerce").astype("float64")


def to_date(s: pd.Series) -> pd.Series:
    """Strict ISO (YYYY-MM-DD) parse; invalid calendar dates (e.g. 2024-02-30) become NaT."""
    return pd.to_datetime(s.astype("string").str.strip(), format="%Y-%m-%d", errors="coerce")


def is_blank(s: pd.Series) -> pd.Series:
    return s.isna() | (s.astype("string").str.strip() == "")


def dpd_bucket(dpd: pd.Series) -> pd.Series:
    return pd.cut(dpd.astype(float), bins=DPD_BINS, labels=DPD_LABELS).astype(str)


@dataclass
class IssueLog:
    rows: list = field(default_factory=list)
    rules: dict = field(default_factory=dict)       # (table, rule_id) -> dict

    def check(self, table: str, df: pd.DataFrame, mask: pd.Series, rule_id: str, action: str,
              description: str, key_col: str) -> pd.Series:
        """Register a rule, log every failing row, return the (aligned) boolean mask."""
        mask = mask.fillna(False).astype(bool)
        n = int(mask.sum())
        self.rules[(table, rule_id)] = dict(table_name=table, rule_id=rule_id, description=description,
                                            action=action, failures=n)
        if n:
            sub = df.loc[mask]
            for _, row in sub.iterrows():
                key = row[key_col]
                self.rows.append(dict(
                    table_name=table, src_row=int(row["_src_row"]),
                    record_key=None if pd.isna(key) else str(key), rule_id=rule_id, action=action,
                    reason=description,
                    raw_record=json.dumps({k: v for k, v in row.items() if not pd.isna(v) and k != "_src_row"}, default=str)))
        return mask

    def issues_df(self) -> pd.DataFrame:
        cols = ["table_name", "src_row", "record_key", "rule_id", "action", "reason", "raw_record"]
        return pd.DataFrame(self.rows, columns=cols)

    def rules_df(self) -> pd.DataFrame:
        return pd.DataFrame(list(self.rules.values()))


def table_counts(table: str, raw_rows: int, clean_rows: int, issues: pd.DataFrame) -> dict:
    t = issues[(issues.table_name == table) & ~issues.rule_id.str.startswith("X")]   # X* = cross-table reconciliation flags
    def n(act): return int(t.loc[t.action == act, "src_row"].nunique())
    return dict(table_name=table, raw_rows=raw_rows, clean_rows=clean_rows,
                rejected_rows=n("REJECTED"), fixed_rows=n("FIXED"), flagged_rows=n("FLAGGED"))
