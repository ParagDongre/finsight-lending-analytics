"""Small helpers shared by the analysis notebooks/scripts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from src import config

RESULTS = config.REPORTS / "results"


def setup(seed: int = config.SEED) -> None:
    import seaborn as sns
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 130, "axes.titlesize": 11, "axes.labelsize": 10})
    np.random.seed(seed)
    config.FIGURES.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)


def save_fig(fig, name: str) -> None:
    fig.tight_layout()
    fig.savefig(config.FIGURES / f"{name}.png", bbox_inches="tight")
    if "agg" not in matplotlib.get_backend().lower():
        plt.show()
    plt.close(fig)


def _py(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


def save_results(name: str, payload: dict) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    p = RESULTS / f"{name}.json"
    p.write_text(json.dumps(payload, indent=2, default=_py))
    print(f"[saved] {p.relative_to(config.ROOT)}")
    return p


def banner() -> None:
    print("=" * 78)
    print("ALL DATA IN THIS PROJECT IS SYNTHETIC. Findings describe the simulation, not real lending.")
    print("=" * 78)
