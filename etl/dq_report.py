"""Build the data-quality report (Markdown) from a TransformResult + the injection manifest."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from etl.transform import TransformResult

# manifest key prefix (rule id) -> rule ids in the log that should have caught it
def injected_vs_detected(res: TransformResult, manifest: dict) -> pd.DataFrame:
    rows = []
    rr = res.rule_results.set_index("rule_id")["failures"].to_dict()
    for k, injected in manifest.items():
        rule = k.split("_")[0]
        rows.append(dict(defect=k, rule_id=rule, injected=injected, detected=int(rr.get(rule, 0)),
                         caught=int(rr.get(rule, 0)) >= injected))
    return pd.DataFrame(rows)


def _md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(out)


def build_report(res: TransformResult, manifest: dict, run_ts: str) -> str:
    cnt = res.counts.copy()
    cnt["balanced"] = (cnt.raw_rows == cnt.clean_rows + cnt.rejected_rows).map({True: "yes", False: "NO"})
    rules = res.rule_results.sort_values(["table_name", "rule_id"])
    rules = rules[rules.failures > 0]
    parts = [
        "# Data Quality Report",
        f"_Generated {run_ts}. All data is SYNTHETIC; defects were injected deliberately by `src/generation/dirty.py` "
        "so the pipeline has something to catch._\n",
        "## 1. Record counts by table",
        "`balanced` confirms **raw rows = clean rows + rejected rows** (nothing silently dropped). "
        "`fixed`/`flagged` rows are kept in the clean table (value corrected or noted).\n",
        _md_table(cnt), "",
        "## 2. Rule results (rules with at least one failure)",
        _md_table(rules[["table_name", "rule_id", "action", "failures", "description"]]), "",
    ]
    if manifest:
        iv = injected_vs_detected(res, manifest)
        parts += ["## 3. Injected defects vs detected",
                  "Detected >= injected is expected (cascading rejections and natural overlaps add extra detections).\n",
                  _md_table(iv), "",
                  f"**Defect types caught: {int(iv.caught.sum())} / {len(iv)}**", ""]
    x = res.rule_results[res.rule_results.rule_id.str.startswith("X")]
    parts += ["## 4. Cross-table reconciliation (flag-only)", _md_table(x[["table_name", "rule_id", "failures", "description"]]), "",
              "## 5. Where the full detail lives",
              "- `data/rejected/*.csv` and `etl.data_quality_issues` hold every rejected / fixed / flagged record with its raw values.",
              "- `etl.dq_rule_results` and `etl.dq_table_counts` hold the tables above."]
    return "\n".join(parts)


def write_report(res: TransformResult, manifest_path: Path, out_path: Path, run_ts: str) -> None:
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_report(res, manifest, run_ts), encoding="utf-8")
