"""Orchestrate QA checks from criteria.yaml."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import polars as pl
import yaml

from pipeline.config import BRONZE_DIR, GOLD_DIR, SILVER_DIR
from pipeline.quality.checks import CheckResult, check_row_count_tolerance
from pipeline.quality.report import build_site_samples

logger = logging.getLogger(__name__)

CRITERIA_PATH = Path(__file__).resolve().parent / "criteria.yaml"


def silver_table_path(table_name: str) -> Path:
    return SILVER_DIR / table_name / f"{table_name}.parquet"


def gold_table_path(table_name: str) -> Path:
    flat = GOLD_DIR / f"{table_name}.parquet"
    nested = GOLD_DIR / table_name / f"{table_name}.parquet"
    if flat.exists():
        return flat
    if nested.exists():
        return nested
    raise FileNotFoundError(f"Gold table not found: {table_name}. Run Gold transforms first.")


SILVER_TABLE_NAMES = [
    "fact_alarm",
    "fact_work_order",
    "fact_maintenance_plan",
    "fact_sensor_reading",
    "fact_incident",
    "fact_occupancy",
    "fact_utilization",
    "dim_customer",
    "dim_site",
]

GOLD_TABLE_NAMES = ["site_daily_signals", "event_timeline"]

# Map criteria alias `date` → actual Gold column name
GOLD_KEY_ALIASES = {"date": "signal_date"}


def load_criteria(path: Path | None = None) -> dict[str, Any]:
    criteria_path = path or CRITERIA_PATH
    with criteria_path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def snapshot_row_counts() -> dict[str, int]:
    """Capture row counts for all Silver/Gold tables (fast aggregate)."""
    counts: dict[str, int] = {}
    for table in SILVER_TABLE_NAMES:
        path = silver_table_path(table)
        if path.exists():
            counts[f"silver.{table}"] = pl.scan_parquet(path).select(pl.len()).collect().item()
    for table in GOLD_TABLE_NAMES:
        try:
            path = gold_table_path(table)
            counts[f"gold.{table}"] = pl.scan_parquet(path).select(pl.len()).collect().item()
        except FileNotFoundError:
            pass
    return counts


def _load_table(layer: str, table: str) -> pl.DataFrame:
    if layer == "silver":
        path = silver_table_path(table)
    else:
        path = gold_table_path(table)
    if not path.exists():
        raise FileNotFoundError(f"Missing {layer} table: {path}")
    return pl.read_parquet(path)


def _make_result(
    spec: dict[str, Any],
    *,
    layer: str,
    passed: bool,
    message: str,
    actual: Any = None,
    expected: Any = None,
    table: str = "",
) -> CheckResult:
    severity = spec.get("severity", "error")
    return CheckResult(
        check_id=spec["id"],
        check_name=spec["id"],
        layer=layer,
        table=table or spec.get("table", ""),
        passed=passed,
        severity=severity,
        message=message,
        actual=actual,
        expected=expected,
    )


def _check_bronze_sources(spec: dict[str, Any], ingest_date: str) -> CheckResult:
    expected = spec["expected_sources"]
    missing: list[str] = []
    for source in expected:
        manifest = BRONZE_DIR / source / ingest_date / "_manifest.json"
        if not manifest.exists():
            missing.append(source)
    passed = not missing
    return _make_result(
        spec,
        layer="bronze",
        passed=passed,
        message=(
            f"all {len(expected)} sources present"
            if passed
            else f"missing bronze partitions: {missing}"
        ),
        actual=len(expected) - len(missing),
        expected=len(expected),
    )


def _check_row_count(spec: dict[str, Any]) -> CheckResult:
    table = spec["table"]
    try:
        df = _load_table("silver", table)
    except FileNotFoundError as exc:
        return _make_result(
            spec, layer="silver", passed=False, message=str(exc), table=table
        )
    result = check_row_count_tolerance(
        df,
        layer="silver",
        table=table,
        expected_rows=spec["expected_rows"],
        tolerance_pct=spec["tolerance_pct"] / 100.0,
        spec_note=spec.get("description", ""),
    )
    result.check_id = spec["id"]
    result.severity = spec.get("severity", "error")
    return result


def _check_pk_unique(spec: dict[str, Any]) -> CheckResult:
    table = spec["table"]
    column = spec["column"]
    try:
        df = _load_table("silver", table)
    except FileNotFoundError as exc:
        return _make_result(
            spec, layer="silver", passed=False, message=str(exc), table=table
        )
    distinct = df[column].n_unique() if column in df.columns else 0
    passed = distinct == df.height
    return _make_result(
        spec,
        layer="silver",
        passed=passed,
        message=(
            f"{column} unique ({df.height:,} rows, {distinct:,} distinct)"
            if passed
            else f"{df.height - distinct:,} duplicate(s) on {column}"
        ),
        actual=distinct,
        expected=df.height,
        table=table,
    )


def _check_forbidden_values(spec: dict[str, Any]) -> CheckResult:
    table = spec["table"]
    columns = spec["columns"]
    forbidden = set(spec["forbidden_values"])
    try:
        df = _load_table("silver", table)
    except FileNotFoundError as exc:
        return _make_result(
            spec, layer="silver", passed=False, message=str(exc), table=table
        )

    bad_count = 0
    for col in columns:
        if col not in df.columns:
            continue
        dtype = df.schema[col]
        if dtype not in (pl.Utf8, pl.String):
            continue  # typed column — NULL literals already cleaned
        bad_count += df.filter(pl.col(col).is_in(list(forbidden))).height

    passed = bad_count == 0
    return _make_result(
        spec,
        layer="silver",
        passed=passed,
        message=(
            f"no forbidden NULL literals in {columns}"
            if passed
            else f"{bad_count} row(s) with forbidden values in {columns}"
        ),
        actual=bad_count,
        expected=0,
        table=table,
    )


def _check_min_mapped_pct(spec: dict[str, Any]) -> CheckResult:
    table = spec["table"]
    column = spec["column"]
    min_pct = spec["min_mapped_pct"]
    try:
        df = _load_table("silver", table)
    except FileNotFoundError as exc:
        return _make_result(
            spec, layer="silver", passed=False, message=str(exc), table=table
        )
    if column not in df.columns or df.height == 0:
        return _make_result(
            spec,
            layer="silver",
            passed=False,
            message=f"{column} missing or empty",
            table=table,
        )
    mapped = df.filter(pl.col(column).is_not_null()).height
    rate = mapped / df.height * 100
    passed = rate >= min_pct
    return _make_result(
        spec,
        layer="silver",
        passed=passed,
        message=f"{rate:.1f}% mapped ({mapped:,}/{df.height:,}, min {min_pct:.0f}%)",
        actual=round(rate, 2),
        expected=min_pct,
        table=table,
    )


def _check_min_rows(spec: dict[str, Any], *, layer: str) -> CheckResult:
    table = spec["table"]
    min_rows = spec["min_rows"]
    try:
        df = _load_table(layer, table)
    except FileNotFoundError as exc:
        return _make_result(spec, layer=layer, passed=False, message=str(exc), table=table)
    passed = df.height >= min_rows
    return _make_result(
        spec,
        layer=layer,
        passed=passed,
        message=f"{df.height:,} rows (min {min_rows:,})",
        actual=df.height,
        expected=min_rows,
        table=table,
    )


def _check_grain_unique(spec: dict[str, Any]) -> CheckResult:
    table = spec["table"]
    keys = [GOLD_KEY_ALIASES.get(k, k) for k in spec["unique_keys"]]
    try:
        df = _load_table("gold", table)
    except FileNotFoundError as exc:
        return _make_result(spec, layer="gold", passed=False, message=str(exc), table=table)

    missing = [k for k in keys if k not in df.columns]
    if missing:
        return _make_result(
            spec,
            layer="gold",
            passed=False,
            message=f"missing grain columns: {missing}",
            table=table,
        )

    unique_rows = df.select(keys).unique().height
    passed = unique_rows == df.height
    return _make_result(
        spec,
        layer="gold",
        passed=passed,
        message=(
            f"grain OK: {df.height:,} rows = {' × '.join(keys)}"
            if passed
            else f"grain violation: {df.height - unique_rows:,} duplicate key(s)"
        ),
        actual=df.height,
        expected=unique_rows,
        table=table,
    )


def _check_site_alarm_total(spec: dict[str, Any]) -> CheckResult:
    table = spec["table"]
    site_id = spec["site_id"]
    min_total = spec["min_alarm_count_total"]
    try:
        df = _load_table("gold", table)
    except FileNotFoundError as exc:
        return _make_result(spec, layer="gold", passed=False, message=str(exc), table=table)

    subset = df.filter(pl.col("site_id") == site_id)
    total = int(subset["alarm_count"].sum() or 0) if subset.height else 0
    passed = total >= min_total
    return _make_result(
        spec,
        layer="gold",
        passed=passed,
        message=f"{site_id} alarm_count sum={total:,} (min {min_total:,})",
        actual=total,
        expected=min_total,
        table=table,
    )


def _check_site_column_pct(spec: dict[str, Any]) -> CheckResult:
    table = spec["table"]
    site_id = spec["site_id"]
    column = spec["column"]
    try:
        df = _load_table("gold", table)
    except FileNotFoundError as exc:
        return _make_result(spec, layer="gold", passed=False, message=str(exc), table=table)

    subset = df.filter(pl.col("site_id") == site_id)
    if subset.height == 0:
        return _make_result(
            spec,
            layer="gold",
            passed=False,
            message=f"no rows for {site_id}",
            table=table,
        )

    if "min_non_null_pct" in spec:
        threshold = spec["min_non_null_pct"]
        non_null = subset.filter(pl.col(column).is_not_null()).height
        pct = non_null / subset.height * 100
        passed = pct >= threshold
        return _make_result(
            spec,
            layer="gold",
            passed=passed,
            message=f"{site_id}.{column} {pct:.1f}% non-null (min {threshold:.0f}%)",
            actual=round(pct, 2),
            expected=threshold,
            table=table,
        )

    if "max_non_zero_pct" in spec:
        threshold = spec["max_non_zero_pct"]
        non_zero = subset.filter(pl.col(column).fill_null(0) > 0).height
        pct = non_zero / subset.height * 100
        passed = pct <= threshold
        return _make_result(
            spec,
            layer="gold",
            passed=passed,
            message=f"{site_id}.{column} {pct:.1f}% non-zero (max {threshold:.0f}%)",
            actual=round(pct, 2),
            expected=threshold,
            table=table,
        )

    return _make_result(
        spec, layer="gold", passed=False, message="unknown site column check", table=table
    )


def _check_pii_leak(spec: dict[str, Any]) -> CheckResult:
    pattern = re.compile(spec["pattern"])
    tables = spec.get("tables", GOLD_TABLE_NAMES)
    total_bad = 0
    for table in tables:
        try:
            df = _load_table("gold", table)
        except FileNotFoundError:
            return _make_result(
                spec, layer="gold", passed=False, message=f"missing gold.{table}", table=table
            )
        str_cols = [c for c, dt in df.schema.items() if dt in (pl.Utf8, pl.String)]
        for col in str_cols:
            total_bad += df.filter(
                pl.col(col).str.contains(pattern.pattern).fill_null(False)
            ).height

    passed = total_bad == 0
    return _make_result(
        spec,
        layer="integrity",
        passed=passed,
        message="no raw email patterns in Gold" if passed else f"{total_bad} PII match(es)",
        actual=total_bad,
        expected=0,
    )


def _check_idempotent_rerun(
    spec: dict[str, Any],
    *,
    before: dict[str, int] | None,
    after: dict[str, int] | None,
) -> CheckResult:
    if before is None or after is None:
        return _make_result(
            spec,
            layer="integrity",
            passed=False,
            message="idempotent counts not captured (skipped rerun)",
        )
    passed = before == after
    diff = {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if before.get(k) != after.get(k)}
    return _make_result(
        spec,
        layer="integrity",
        passed=passed,
        message="row counts identical on rerun" if passed else f"count drift: {diff}",
        actual=after,
        expected=before,
    )


def dispatch_check(
    spec: dict[str, Any],
    *,
    layer: str,
    ingest_date: str,
    idempotent_before: dict[str, int] | None = None,
    idempotent_after: dict[str, int] | None = None,
) -> CheckResult:
    check_id = spec["id"]

    if layer == "bronze":
        return _check_bronze_sources(spec, ingest_date)

    if layer == "integrity":
        if check_id == "idempotent_rerun":
            return _check_idempotent_rerun(
                spec, before=idempotent_before, after=idempotent_after
            )
        if check_id == "no_pii_leak":
            return _check_pii_leak(spec)

    if "expected_rows" in spec:
        return _check_row_count(spec)
    if "columns" in spec and "forbidden_values" in spec:
        return _check_forbidden_values(spec)
    if "column" in spec and "min_mapped_pct" in spec:
        return _check_min_mapped_pct(spec)
    if "column" in spec and "site_id" in spec:
        return _check_site_column_pct(spec)
    if "min_alarm_count_total" in spec:
        return _check_site_alarm_total(spec)
    if "unique_keys" in spec:
        return _check_grain_unique(spec)
    if "min_rows" in spec:
        return _check_min_rows(spec, layer=layer)
    if "column" in spec:
        return _check_pk_unique(spec)

    return _make_result(
        spec, layer=layer, passed=False, message=f"unknown check type: {check_id}"
    )


def run_qa_checks(
    ingest_date: str,
    *,
    criteria: dict[str, Any] | None = None,
    idempotent_before: dict[str, int] | None = None,
    idempotent_after: dict[str, int] | None = None,
    verbose: bool = False,
) -> list[CheckResult]:
    """Execute all checks from criteria.yaml."""
    criteria = criteria or load_criteria()
    results: list[CheckResult] = []

    for layer in ("bronze", "silver", "gold", "integrity"):
        for spec in criteria.get(layer, []):
            if spec["id"] == "idempotent_rerun" and (
                idempotent_before is None or idempotent_after is None
            ):
                continue
            logger.info("Running check %s", spec["id"])
            result = dispatch_check(
                spec,
                layer=layer,
                ingest_date=ingest_date,
                idempotent_before=idempotent_before,
                idempotent_after=idempotent_after,
            )
            results.append(result)
            if verbose:
                status = "PASS" if result.passed else result.severity.upper()
                logger.info("  [%s] %s: %s", status, result.check_id, result.message)

    return results
