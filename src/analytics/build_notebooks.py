"""Convert the `# %%` percent-format scripts into executed Jupyter notebooks.

    python -m src.analytics.build_notebooks            # build + execute (needs nbformat, nbconvert, ipykernel)
    python -m src.analytics.build_notebooks --no-exec  # build only

Notebooks are executed from the repository root so `import src...` works; outputs are stored in the .ipynb.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import nbformat
from nbconvert.preprocessors import ExecutePreprocessor

from src import config

NOTEBOOKS = {
    "01_exploratory_data_analysis": "src/analytics/eda.py",
    "02_statistical_analysis": "src/analytics/statistics_analysis.py",
    "03_default_classification": "src/modelling/default_model.py",
    "04_repayment_regression": "src/modelling/repayment_model.py",
}


def script_to_notebook(path: Path) -> nbformat.NotebookNode:
    text = path.read_text(encoding="utf-8")
    chunks = re.split(r"(?m)^# %%(?: \[markdown\])?\s*$", text)
    headers = re.findall(r"(?m)^# %%( \[markdown\])?\s*$", text)
    nb = nbformat.v4.new_notebook()
    cells = []
    for kind, chunk in zip(headers, chunks[1:]):
        body = chunk.strip("\n")
        if not body.strip():
            continue
        if kind:
            md = "\n".join(re.sub(r"^# ?", "", ln) for ln in body.splitlines())
            cells.append(nbformat.v4.new_markdown_cell(md))
        else:
            cells.append(nbformat.v4.new_code_cell(body))
    nb.cells = cells
    nb.metadata["kernelspec"] = {"display_name": "Python 3", "language": "python", "name": "python3"}
    return nb


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-exec", action="store_true")
    args = ap.parse_args()
    out = config.ROOT / "notebooks"
    out.mkdir(exist_ok=True)
    for name, rel in NOTEBOOKS.items():
        nb = script_to_notebook(config.ROOT / rel)
        if not args.no_exec:
            print(f"executing {name} ...")
            ExecutePreprocessor(timeout=900, kernel_name="python3").preprocess(nb, {"metadata": {"path": str(config.ROOT)}})
        nbformat.write(nb, out / f"{name}.ipynb")
        print(f"wrote notebooks/{name}.ipynb ({len(nb.cells)} cells)")


if __name__ == "__main__":
    main()
