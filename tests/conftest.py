"""Shared fixtures. A small synthetic dataset (4 origination months) keeps tests fast (~5 s)."""
from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from src import config
from src.generation import generate_data
from src.generation.dirty import inject_defects


@pytest.fixture(scope="session")
def small_clean():
    """Clean ground truth for a small window, generated with the real generator (deterministic)."""
    old = (config.FIRST_DISBURSEMENT_MONTH, config.LAST_DISBURSEMENT_MONTH)
    config.FIRST_DISBURSEMENT_MONTH, config.LAST_DISBURSEMENT_MONTH = date(2025, 10, 1), date(2026, 1, 1)
    try:
        data = generate_data.generate(seed=7)
    finally:
        config.FIRST_DISBURSEMENT_MONTH, config.LAST_DISBURSEMENT_MONTH = old
    data.pop("_stats")
    return data


@pytest.fixture(scope="session")
def small_dirty(small_clean):
    raw, manifest = inject_defects(small_clean, np.random.default_rng(8), config.SNAPSHOT_DATE)
    for df in raw.values():
        df["_src_row"] = range(2, len(df) + 2)
    return raw, manifest


@pytest.fixture(scope="session")
def small_clean_as_raw(small_clean):
    """The clean data pushed through the same 'all strings' door, with NO injected defects."""
    from src.generation.dirty import _to_raw
    out = {k: _to_raw(v) for k, v in small_clean.items()}
    for df in out.values():
        df["_src_row"] = range(2, len(df) + 2)
    return out
