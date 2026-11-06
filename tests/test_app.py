"""Headless smoke tests of the Streamlit app (streamlit.testing). Skipped if streamlit or the demo data is missing."""
from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from pathlib import Path

from src.app_data import local_data_available

APP = str(Path(__file__).resolve().parents[1] / "app.py")

pytestmark = pytest.mark.skipif(not local_data_available(), reason="demo data not generated (run the ETL first)")


def test_app_renders_all_tabs_without_exceptions():
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.tabs) == 6
    labels = {m.label for m in at.metric}
    for needed in ["Total disbursement", "Outstanding portfolio", "Active loans", "Average loan amount", "Portfolio delinquency rate",
                   "Default rate (mature loans)", "Average DPD (open loans)", "Total overdue amount", "Amount collected", "Recovery rate", "Overdue accounts"]:
        assert needed in labels, needed


def test_app_labels_synthetic_data():
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert any("SYNTHETIC" in m.value for m in at.markdown)


def test_app_upload_mode_without_files_shows_guidance():
    at = AppTest.from_file(APP, default_timeout=180).run()
    at.sidebar.radio[0].set_value("Upload my CSVs").run()
    assert not at.exception
    assert any("Loans CSV" in i.value or "Loans" in i.value for i in at.info)
