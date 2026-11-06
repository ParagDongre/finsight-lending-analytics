"""Central configuration. No credentials live here - DB settings come from environment / .env."""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_REJECTED = ROOT / "data" / "rejected"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"
SCHEMA_SQL = ROOT / "database" / "schema.sql"
QUERIES_DIR = ROOT / "database" / "queries"

# ---- Simulation parameters (ALL DATA IS SYNTHETIC) ----
SEED = 42
SNAPSHOT_DATE = date(2026, 6, 30)          # "as-of" date of the simulated loan-management extract
FIRST_DISBURSEMENT_MONTH = date(2023, 7, 1)
LAST_DISBURSEMENT_MONTH = date(2026, 3, 1)
DRIFT_START_MONTH = date(2024, 7, 1)       # designed risk deterioration starts here (see docs/simulation_design.md)
MATURE_CUTOFF_DATE = date(2025, 3, 31)     # loans disbursed on/before this have >= 15 months on book

CURRENCY = "INR"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def db_params() -> dict:
    """Connection parameters from environment variables (PGHOST, PGPORT, ...) or .env."""
    _load_dotenv()
    return dict(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5432")),
        dbname=os.environ.get("PGDATABASE", "finsight"),
        user=os.environ.get("PGUSER", "finsight"),
        password=os.environ.get("PGPASSWORD", ""),
    )
