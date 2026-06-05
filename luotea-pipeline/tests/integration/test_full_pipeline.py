"""End-to-end pipeline test: ingest → silver → gold → validate."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from pipeline.bronze.connectors import ingest_all
from pipeline.config import HACKATHON_DATA_ROOT
from pipeline.gold.run_gold import run_gold
from pipeline.quality.checks import run_validation
from pipeline.silver.run_erp import run_erp_silver
from pipeline.silver.run_iot import run_iot_silver

FIXED_DATE = "2026-06-05"


@pytest.fixture(scope="module")
def require_hackathon_data() -> Path:
    if not HACKATHON_DATA_ROOT.exists():
        pytest.skip(f"Hackathon data not found at {HACKATHON_DATA_ROOT}")
    alarms = HACKATHON_DATA_ROOT / "Alarms" / "alarms.csv"
    if not alarms.exists():
        pytest.skip(f"Alarms source file not found: {alarms}")
    return HACKATHON_DATA_ROOT


def test_full_pipeline_ingest_silver_gold_validate(require_hackathon_data: Path) -> None:
    ingest_all(FIXED_DATE)
    run_erp_silver(FIXED_DATE)
    run_iot_silver(FIXED_DATE)
    run_gold(as_of_date=date.fromisoformat(FIXED_DATE))

    report = run_validation(ingest_date=FIXED_DATE)
    failures = [r for r in report.results if not r.passed and r.severity == "error"]
    assert not failures, "\n".join(
        f"  {r.check_id or r.check_name}: {r.message}" for r in failures
    )
