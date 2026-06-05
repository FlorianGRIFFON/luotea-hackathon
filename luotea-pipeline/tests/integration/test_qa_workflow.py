"""Run pipeline qa on real hackathon data via CLI subprocess."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from pipeline.config import HACKATHON_DATA_ROOT, QA_DIR

FIXED_DATE = "2026-06-05"


@pytest.fixture(scope="module")
def require_hackathon_data() -> Path:
    if not HACKATHON_DATA_ROOT.exists():
        pytest.skip(f"Hackathon data not found at {HACKATHON_DATA_ROOT}")
    alarms = HACKATHON_DATA_ROOT / "Alarms" / "alarms.csv"
    if not alarms.exists():
        pytest.skip(f"Alarms source file not found: {alarms}")
    return HACKATHON_DATA_ROOT


@pytest.mark.integration
def test_qa_full_pipeline_passes(require_hackathon_data: Path) -> None:
    """Run `pipeline qa` on real hackathon data; assert exit 0 and report PASS."""
    result = subprocess.run(
        [sys.executable, "-m", "pipeline", "qa", "--date", FIXED_DATE],
        capture_output=True,
        text=True,
        check=False,
    )
    report_path = QA_DIR / f"qa_report_{FIXED_DATE}.json"
    assert report_path.exists(), (
        f"QA report missing at {report_path}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert result.returncode == 0, (
        f"pipeline qa exited {result.returncode}\n"
        f"overall={report.get('overall')} errors={report.get('errors')}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert report["overall"] == "PASS"
    assert report["errors"] == 0
    assert report["ingest_date"] == FIXED_DATE
    assert report["pipeline_steps"]["ingest"]["status"] == "ok"
    assert report["pipeline_steps"]["silver"]["status"] == "ok"
    assert report["pipeline_steps"]["gold"]["status"] == "ok"
