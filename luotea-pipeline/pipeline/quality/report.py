"""QA report JSON serialization and terminal summary formatting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import polars as pl

from pipeline.config import GOLD_DIR, QA_DIR, SILVER_DIR
from pipeline.quality.checks import CheckResult


@dataclass
class QAResult:
    run_at: str
    ingest_date: str
    overall: Literal["PASS", "FAIL"]
    errors: int
    warnings: int
    duration_seconds: float
    pipeline_steps: dict[str, Any]
    checks: list[CheckResult] = field(default_factory=list)
    samples: dict[str, Any] = field(default_factory=dict)
    report_path: Path | None = None

    @classmethod
    def from_checks(
        cls,
        *,
        ingest_date: str,
        checks: list[CheckResult],
        pipeline_steps: dict[str, Any],
        duration_seconds: float,
        samples: dict[str, Any] | None = None,
    ) -> QAResult:
        errors = sum(
            1 for c in checks if not c.passed and c.severity in ("error",)
        )
        warnings = sum(
            1 for c in checks if not c.passed and c.severity in ("warn", "warning")
        )
        overall: Literal["PASS", "FAIL"] = "PASS" if errors == 0 else "FAIL"
        return cls(
            run_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ingest_date=ingest_date,
            overall=overall,
            errors=errors,
            warnings=warnings,
            duration_seconds=round(duration_seconds, 1),
            pipeline_steps=pipeline_steps,
            checks=checks,
            samples=samples or build_site_samples(),
        )


def build_site_samples() -> dict[str, Any]:
    """Compute sample stats for key sites from Gold output."""
    path = GOLD_DIR / "site_daily_signals.parquet"
    if not path.exists():
        path = GOLD_DIR / "site_daily_signals" / "site_daily_signals.parquet"
    if not path.exists():
        return {}

    df = pl.read_parquet(path)
    samples: dict[str, Any] = {}

    valmet = df.filter(pl.col("site_id") == "site_valmet_l11")
    if valmet.height:
        util_days = valmet.filter(pl.col("avg_room_utilization_pct").is_not_null()).height
        samples["site_valmet_l11"] = {
            "days": valmet.height,
            "alarm_count_sum": int(valmet["alarm_count"].sum() or 0),
            "avg_utilization_non_null_days": util_days,
        }

    aurora = df.filter(pl.col("site_id") == "site_aurora")
    if aurora.height:
        elec_days = aurora.filter(pl.col("electricity_kwh").is_not_null()).height
        alarm_nonzero = aurora.filter(pl.col("alarm_count") > 0).height
        samples["site_aurora"] = {
            "days": aurora.height,
            "electricity_kwh_non_null_days": elec_days,
            "alarm_nonzero_days": alarm_nonzero,
        }

    return samples


def _check_to_dict(c: CheckResult) -> dict[str, Any]:
    return {
        "id": c.check_id,
        "severity": c.severity if c.severity != "warning" else "warn",
        "passed": c.passed,
        "message": c.message,
        "actual": c.actual,
        "expected": c.expected,
        "table": c.table,
        "layer": c.layer,
    }


def qa_result_to_dict(result: QAResult) -> dict[str, Any]:
    return {
        "run_at": result.run_at,
        "ingest_date": result.ingest_date,
        "overall": result.overall,
        "errors": result.errors,
        "warnings": result.warnings,
        "duration_seconds": result.duration_seconds,
        "pipeline_steps": result.pipeline_steps,
        "checks": [_check_to_dict(c) for c in result.checks],
        "samples": result.samples,
    }


def write_qa_report(result: QAResult) -> Path:
    """Write JSON report to data/qa/qa_report_{date}.json."""
    QA_DIR.mkdir(parents=True, exist_ok=True)
    path = QA_DIR / f"qa_report_{result.ingest_date}.json"
    path.write_text(json.dumps(qa_result_to_dict(result), indent=2), encoding="utf-8")
    result.report_path = path
    return path


def print_qa_summary(result: QAResult, *, verbose: bool = False) -> None:
    """Print human-readable QA summary for agents."""
    bar = "═" * 70
    print(f"\n{bar}")
    print(
        f"QA REPORT  {result.ingest_date}  →  {result.overall} "
        f"({result.errors} errors, {result.warnings} warnings)"
    )
    print(bar)

    steps = result.pipeline_steps
    ingest_s = "✓" if steps.get("ingest", {}).get("status") in ("ok", "skipped") else "✗"
    silver_s = "✓" if steps.get("silver", {}).get("status") == "ok" else "✗"
    gold_s = "✓" if steps.get("gold", {}).get("status") == "ok" else "✗"
    print(
        f"PIPELINE   ingest {ingest_s}  silver {silver_s}  gold {gold_s}  "
        f"({result.duration_seconds}s)"
    )

    passed = sum(1 for c in result.checks if c.passed)
    total = len(result.checks)
    print(f"\nCHECKS     {passed}/{total} passed")

    failed = [c for c in result.checks if not c.passed]
    if verbose:
        for c in result.checks:
            _print_check_line(c)
    else:
        for c in failed:
            _print_check_line(c)

    if result.samples:
        print("\nSAMPLES")
        v = result.samples.get("site_valmet_l11", {})
        if v:
            print(
                f"  site_valmet_l11   {v.get('days', 0)} days  "
                f"alarms={v.get('alarm_count_sum', 0)}  "
                f"utilization_days={v.get('avg_utilization_non_null_days', 0)}"
            )
        a = result.samples.get("site_aurora", {})
        if a:
            print(
                f"  site_aurora       {a.get('days', 0)} days  "
                f"electricity_days={a.get('electricity_kwh_non_null_days', 0)}"
            )

    if result.report_path:
        print(f"\nReport: {result.report_path}")
    print(bar)


def _print_check_line(c: CheckResult) -> None:
    if c.passed:
        mark = "✓"
        label = "PASS"
    elif c.severity in ("warn", "warning"):
        mark = "⚠"
        label = "WARN"
    else:
        mark = "✗"
        label = "ERROR"
    cid = c.check_id or c.check_name
    print(f"  {mark} {label:<5}  {cid:<36}  {c.message}")
