"""Schema, uniqueness, referential, and range validators at Silver/Gold boundaries."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import polars as pl

from pipeline.config import GOLD_DIR, QUARANTINE_DIR, SILVER_DIR
from pipeline.gold.io import load_silver
from pipeline.schemas.enums import AlarmPriority

logger = logging.getLogger(__name__)

VALID_ALARM_PRIORITIES = {p.value for p in AlarmPriority}
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
QUARANTINE_SAMPLE_LIMIT = 1000

SILVER_SPECS: dict[str, dict[str, Any]] = {
    "fact_alarm": {
        "required": ["alert_event_id", "site_id", "priority", "event_time_utc"],
        "unique": ["alert_event_id"],
        "enum": {"priority": VALID_ALARM_PRIORITIES},
        "mapping_min": 0.99,
    },
    "fact_work_order": {
        "required": ["wo_no", "site_id", "work_order_description"],
        "unique": ["wo_no"],
        "mapping_min": 0.99,
    },
    "fact_maintenance_plan": {
        "required": ["pm_no", "site_id"],
        "unique": ["pm_no"],
        "mapping_min": 0.99,
    },
    "fact_sensor_reading": {
        "required": ["reading_id", "site_id", "metric", "timestamp_utc"],
        "unique": ["reading_id"],
        "mapping_min": 0.95,
    },
    "fact_incident": {
        "required": ["incident_id", "site_id", "created_at_utc"],
        "unique": ["incident_id"],
        "mapping_min": 0.95,
    },
    "fact_occupancy": {
        "required": ["occupancy_id", "site_id", "occupancy_value", "value_type"],
        "unique": ["occupancy_id"],
        "custom": ["occupancy_value_range"],
        "mapping_min": 0.95,
    },
    "fact_utilization": {
        "required": ["utilization_id", "site_id", "utilization_pct", "utilization_date"],
        "unique": ["utilization_id"],
        "range": {"utilization_pct": (0.0, 100.0)},
        "mapping_min": 0.99,
    },
    "dim_site": {
        "required": ["site_id", "display_name", "customer_id"],
        "unique": ["site_id"],
    },
    "dim_customer": {
        "required": ["customer_id", "customer_name"],
        "unique": ["customer_id"],
    },
}

GOLD_SPECS: dict[str, dict[str, Any]] = {
    "site_daily_signals": {
        "required": ["site_id", "signal_date"],
        "unique": [["site_id", "signal_date"]],
        "referential": {"site_id": "dim_site"},
    },
    "event_timeline": {
        "required": ["event_id", "event_type", "timestamp_utc"],
        "unique": ["event_id"],
        "referential": {"site_id": "dim_site"},
        "pii_scan": True,
    },
}


@dataclass
class CheckResult:
    check_name: str
    layer: str
    table: str
    passed: bool
    severity: str = "error"
    message: str = ""
    failed_count: int = 0
    total_count: int = 0
    quarantine_path: Path | None = None
    check_id: str = ""
    actual: Any = None
    expected: Any = None


@dataclass
class QualityReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(
            r.passed or r.severity in ("warning", "warn") for r in self.results
        )

    @property
    def error_count(self) -> int:
        return sum(
            1 for r in self.results if not r.passed and r.severity == "error"
        )

    @property
    def warning_count(self) -> int:
        return sum(
            1
            for r in self.results
            if not r.passed and r.severity in ("warning", "warn")
        )


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


def _silver_path(table_name: str) -> Path:
    return silver_table_path(table_name)


def _gold_path(table_name: str) -> Path:
    return gold_table_path(table_name)


def _write_quarantine(
    *,
    layer: str,
    table: str,
    check_name: str,
    df: pl.DataFrame,
    reason: str,
) -> Path:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    stem = f"{layer}_{table}_{check_name}_{ts}"
    meta_path = QUARANTINE_DIR / f"{stem}.meta.json"
    meta = {
        "layer": layer,
        "table": table,
        "check": check_name,
        "reason": reason,
        "row_count": df.height,
        "quarantined_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

    if df.height == 0:
        return meta_path

    sample = df.head(QUARANTINE_SAMPLE_LIMIT)
    parquet_path = QUARANTINE_DIR / f"{stem}.parquet"
    sample.write_parquet(parquet_path)
    logger.warning(
        "Quarantined %d row(s) for %s.%s (%s) → %s",
        df.height,
        layer,
        table,
        check_name,
        parquet_path,
    )
    return parquet_path


def check_required_columns(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    columns: list[str],
) -> CheckResult:
    missing = [c for c in columns if c not in df.columns]
    name = "schema_required_columns"
    if missing:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=False,
            message=f"Missing columns: {missing}",
            failed_count=len(missing),
            total_count=len(columns),
        )
    null_cols = [c for c in columns if df[c].null_count() > 0]
    if null_cols:
        bad = df.filter(pl.any_horizontal([pl.col(c).is_null() for c in null_cols]))
        qpath = _write_quarantine(
            layer=layer,
            table=table,
            check_name=name,
            df=bad,
            reason=f"Null values in required columns: {null_cols}",
        )
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=False,
            message=f"Nulls in required columns {null_cols}: {bad.height} row(s)",
            failed_count=bad.height,
            total_count=df.height,
            quarantine_path=qpath,
        )
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=True,
        message="All required columns present and non-null",
        total_count=df.height,
    )


def check_unique(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    columns: list[str] | str,
) -> CheckResult:
    cols = [columns] if isinstance(columns, str) else columns
    name = f"unique_{'_'.join(cols)}"
    if df.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="Empty table (skipped)",
        )
    dupes = (
        df.group_by(cols)
        .agg(pl.len().alias("_n"))
        .filter(pl.col("_n") > 1)
        .join(df, on=cols, how="inner")
    )
    if dupes.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message=f"Unique on {cols}",
            total_count=df.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name=name,
        df=dupes.unique(subset=cols),
        reason=f"Duplicate key on {cols}",
    )
    dupe_keys = dupes.select(cols).unique().height
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=False,
        message=f"{dupe_keys} duplicate key(s) on {cols} ({dupes.height} row(s))",
        failed_count=dupes.height,
        total_count=df.height,
        quarantine_path=qpath,
    )


def check_enum(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    column: str,
    allowed: set[Any],
) -> CheckResult:
    name = f"enum_{column}"
    if column not in df.columns or df.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="Column missing or empty (skipped)",
        )
    bad = df.filter(~pl.col(column).is_in(list(allowed)))
    if bad.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message=f"All {column} values in allowed set",
            total_count=df.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name=name,
        df=bad,
        reason=f"{column} not in {sorted(allowed)}",
    )
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=False,
        message=f"{bad.height} row(s) with invalid {column}",
        failed_count=bad.height,
        total_count=df.height,
        quarantine_path=qpath,
    )


def check_range(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    column: str,
    low: float,
    high: float,
) -> CheckResult:
    name = f"range_{column}"
    if column not in df.columns or df.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="Column missing or empty (skipped)",
        )
    bad = df.filter(
        pl.col(column).is_not_null()
        & ((pl.col(column) < low) | (pl.col(column) > high))
    )
    if bad.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message=f"{column} within [{low}, {high}]",
            total_count=df.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name=name,
        df=bad,
        reason=f"{column} outside [{low}, {high}]",
    )
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=False,
        message=f"{bad.height} row(s) with {column} outside [{low}, {high}]",
        failed_count=bad.height,
        total_count=df.height,
        quarantine_path=qpath,
    )


def check_mapping_hit_rate(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    min_rate: float,
    column: str = "site_id",
) -> CheckResult:
    name = "referential_site_mapping"
    if column not in df.columns or df.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="No site_id column or empty (skipped)",
        )
    hit = df.filter(pl.col(column).is_not_null()).height / df.height
    unmapped = df.filter(pl.col(column).is_null())
    if hit >= min_rate:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message=f"site_id mapping hit {hit * 100:.1f}% (min {min_rate * 100:.0f}%)",
            total_count=df.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name=name,
        df=unmapped,
        reason=f"site_id null — mapping hit {hit * 100:.1f}% below {min_rate * 100:.0f}%",
    )
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=False,
        message=f"site_id mapping hit {hit * 100:.1f}% < {min_rate * 100:.0f}% ({unmapped.height} unmapped)",
        failed_count=unmapped.height,
        total_count=df.height,
        quarantine_path=qpath,
    )


def check_referential_integrity(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    fk_column: str,
    ref_table: str,
    ref_df: pl.DataFrame | None = None,
    ref_column: str = "site_id",
    min_hit: float = 0.99,
) -> CheckResult:
    name = f"referential_{fk_column}_to_{ref_table}"
    if fk_column not in df.columns or df.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="FK column missing or empty (skipped)",
        )
    ref = ref_df if ref_df is not None else load_silver(ref_table)
    valid_keys = set(ref[ref_column].drop_nulls().to_list())
    non_null = df.filter(pl.col(fk_column).is_not_null())
    if non_null.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            severity="warning",
            message=f"All {fk_column} values null (partial coverage expected)",
        )
    bad = non_null.filter(~pl.col(fk_column).is_in(list(valid_keys)))
    hit = (non_null.height - bad.height) / non_null.height
    if hit >= min_hit:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message=f"{hit * 100:.1f}% of non-null {fk_column} match {ref_table}.{ref_column}",
            total_count=non_null.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name=name,
        df=bad,
        reason=f"{fk_column} not in {ref_table}.{ref_column}",
    )
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=False,
        message=f"{bad.height} orphan {fk_column} value(s) ({hit * 100:.1f}% hit rate)",
        failed_count=bad.height,
        total_count=non_null.height,
        quarantine_path=qpath,
    )


def check_occupancy_value_range(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
) -> CheckResult:
    """Normalized KONE values are 0–10; raw counts must be non-negative."""
    name = "range_occupancy_value"
    if df.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="Empty table (skipped)",
        )

    normalized = df.filter(pl.col("value_type") == "normalized")
    norm_bad = normalized.filter(
        pl.col("occupancy_value").is_not_null()
        & ((pl.col("occupancy_value") < 0.0) | (pl.col("occupancy_value") > 10.0))
    )
    raw = df.filter(pl.col("value_type") == "raw_count")
    raw_bad = raw.filter(
        pl.col("occupancy_value").is_not_null() & (pl.col("occupancy_value") < 0.0)
    )
    bad = pl.concat([norm_bad, raw_bad], how="vertical_relaxed")

    if bad.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="occupancy_value valid (normalized 0–10, raw_count ≥ 0)",
            total_count=df.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name=name,
        df=bad,
        reason="occupancy_value out of allowed range for value_type",
    )
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=False,
        message=f"{bad.height} row(s) with invalid occupancy_value for value_type",
        failed_count=bad.height,
        total_count=df.height,
        quarantine_path=qpath,
    )


CUSTOM_CHECKS: dict[str, Callable[..., CheckResult]] = {
    "occupancy_value_range": check_occupancy_value_range,
}


def check_pii_scan(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
) -> CheckResult:
    """Flag raw email addresses in string columns (anonymized data should use [NAME] tokens)."""
    name = "pii_email_scan"
    if df.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="Empty table (skipped)",
        )
    str_cols = [c for c, dt in df.schema.items() if dt == pl.Utf8 or dt == pl.String]
    if not str_cols:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="No string columns to scan",
        )

    exprs = [
        pl.col(c).str.contains(EMAIL_PATTERN.pattern).fill_null(False).alias(f"_pii_{c}")
        for c in str_cols
    ]
    flagged = df.with_columns(exprs).filter(pl.any_horizontal(exprs))
    if flagged.height == 0:
        return CheckResult(
            check_name=name,
            layer=layer,
            table=table,
            passed=True,
            message="No raw email addresses detected",
            total_count=df.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name=name,
        df=flagged.drop([c for c in flagged.columns if c.startswith("_pii_")]),
        reason="Raw email address detected in Gold output",
    )
    return CheckResult(
        check_name=name,
        layer=layer,
        table=table,
        passed=False,
        message=f"{flagged.height} row(s) contain raw email addresses",
        failed_count=flagged.height,
        total_count=df.height,
        quarantine_path=qpath,
    )


def _run_table_checks(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    spec: dict[str, Any],
    ref_loader: Callable[[str], pl.DataFrame] | None = None,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    loader = ref_loader or load_silver

    if "required" in spec:
        results.append(
            check_required_columns(df, layer=layer, table=table, columns=spec["required"])
        )

    for col_spec in spec.get("unique", []):
        results.append(check_unique(df, layer=layer, table=table, columns=col_spec))

    for col, allowed in spec.get("enum", {}).items():
        results.append(
            check_enum(df, layer=layer, table=table, column=col, allowed=set(allowed))
        )

    for col, (low, high) in spec.get("range", {}).items():
        results.append(
            check_range(df, layer=layer, table=table, column=col, low=low, high=high)
        )

    if "mapping_min" in spec:
        results.append(
            check_mapping_hit_rate(
                df, layer=layer, table=table, min_rate=spec["mapping_min"]
            )
        )

    for fk, ref_table in spec.get("referential", {}).items():
        ref_df = loader(ref_table)
        results.append(
            check_referential_integrity(
                df,
                layer=layer,
                table=table,
                fk_column=fk,
                ref_table=ref_table,
                ref_df=ref_df,
            )
        )

    if spec.get("pii_scan"):
        results.append(check_pii_scan(df, layer=layer, table=table))

    for custom_name in spec.get("custom", []):
        fn = CUSTOM_CHECKS[custom_name]
        results.append(fn(df, layer=layer, table=table))

    return results


def run_silver_checks() -> list[CheckResult]:
    """Validate all Silver Parquet tables."""
    results: list[CheckResult] = []
    for table, spec in SILVER_SPECS.items():
        path = _silver_path(table)
        if not path.exists():
            results.append(
                CheckResult(
                    check_name="table_exists",
                    layer="silver",
                    table=table,
                    passed=False,
                    message=f"Missing Silver table: {path}",
                )
            )
            continue
        logger.info("Running Silver checks on %s", table)
        df = pl.read_parquet(path)
        results.extend(_run_table_checks(df, layer="silver", table=table, spec=spec))
    return results


def run_gold_checks(*, dim_site: pl.DataFrame | None = None) -> list[CheckResult]:
    """Validate Gold marts and referential links to dim_site."""
    results: list[CheckResult] = []
    site_df = dim_site
    if site_df is None:
        site_path = _silver_path("dim_site")
        site_df = pl.read_parquet(site_path) if site_path.exists() else pl.DataFrame()

    def ref_loader(table: str) -> pl.DataFrame:
        if table == "dim_site":
            return site_df
        return load_silver(table)

    for table, spec in GOLD_SPECS.items():
        try:
            path = _gold_path(table)
        except FileNotFoundError as exc:
            results.append(
                CheckResult(
                    check_name="table_exists",
                    layer="gold",
                    table=table,
                    passed=False,
                    message=str(exc),
                )
            )
            continue
        logger.info("Running Gold checks on %s", table)
        df = pl.read_parquet(path)
        results.extend(
            _run_table_checks(
                df,
                layer="gold",
                table=table,
                spec=spec,
                ref_loader=ref_loader,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Final validation (spec-driven checks for `pipeline validate`)
# ---------------------------------------------------------------------------

FORBIDDEN_NULL_LITERALS = frozenset({"NULL", "null", "None", "none", ""})


def _row_count_specs() -> list[tuple[str, int, float, str]]:
    """Expected Silver row counts from data specs / contracts."""
    from pipeline.contracts import load_contract

    alarms = load_contract("alarms")["format"]["row_count_expected"]
    work_orders = load_contract("work_orders")["format"]["row_count_expected"]
    return [
        ("fact_alarm", alarms, 0.005, "alarms_data_spec.md (18,702 events)"),
        ("fact_work_order", work_orders, 0.005, "work_orders_data_spec.md (44,265 rows)"),
        # Bronze spec is 316 rows; Silver dedupes by PM_NO → 106 unique plans
        ("fact_maintenance_plan", 106, 0.01, "deduped PM_NO (316 bronze → 106 silver)"),
    ]


PRIMARY_KEY_CHECKS: list[tuple[str, str, str]] = [
    ("fact_alarm", "alert_event_id", "ALERT_EVENT_ID"),
    ("fact_work_order", "wo_no", "WO_NO"),
    ("fact_maintenance_plan", "pm_no", "PM_NO"),
]

SOURCE_MAPPING_RULES: list[tuple[str, str, float]] = [
    ("fact_alarm", "erp_alarms", 0.99),
    ("fact_work_order", "erp_work_orders", 0.99),
    ("fact_maintenance_plan", "erp_maintenance_plans", 0.99),
    ("fact_sensor_reading", "smartti_pulse", 0.95),
    ("fact_incident", "smartti_pulse", 0.95),
    ("fact_occupancy", "kone_occupancy", 0.95),
    ("fact_utilization", "cleaning_utilization", 0.99),
]

ERP_NULL_LITERAL_TABLES = ("fact_alarm", "fact_work_order", "fact_maintenance_plan")


def check_row_count_tolerance(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    expected_rows: int,
    tolerance_pct: float,
    spec_note: str = "",
) -> CheckResult:
    check_id = f"row_count_{table}"
    actual = df.height
    if expected_rows == 0:
        passed = actual == 0
        delta_pct = 0.0
    else:
        delta_pct = abs(actual - expected_rows) / expected_rows * 100
        passed = delta_pct <= tolerance_pct * 100
    note = f" ({spec_note})" if spec_note else ""
    return CheckResult(
        check_id=check_id,
        check_name="row_count",
        layer=layer,
        table=table,
        passed=passed,
        message=f"{actual:,} rows (expected {expected_rows:,} ±{tolerance_pct * 100:.1f}%){note}",
        actual=actual,
        expected=expected_rows,
        total_count=actual,
        failed_count=0 if passed else abs(actual - expected_rows),
    )


def check_primary_key_unique(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    column: str,
    source_pk: str,
) -> CheckResult:
    check_id = f"pk_unique_{table}_{column}"
    result = check_unique(df, layer=layer, table=table, columns=column)
    result.check_id = check_id
    result.check_name = "pk_unique"
    result.message = (
        f"{source_pk} unique ({df.height:,} rows, {df[column].n_unique():,} distinct)"
        if result.passed
        else result.message
    )
    result.actual = df[column].n_unique() if column in df.columns else 0
    result.expected = df.height
    return result


def check_site_mapping_by_source(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
    source_system: str,
    min_rate: float,
) -> CheckResult:
    check_id = f"site_mapping_{source_system}"
    if "site_id" not in df.columns:
        return CheckResult(
            check_id=check_id,
            check_name="site_mapping",
            layer=layer,
            table=table,
            passed=False,
            message="site_id column missing",
        )
    subset = df
    if "source_system" in df.columns:
        subset = df.filter(pl.col("source_system") == source_system)
    if subset.height == 0:
        return CheckResult(
            check_id=check_id,
            check_name="site_mapping",
            layer=layer,
            table=table,
            passed=True,
            severity="warning",
            message=f"no rows for source {source_system} (skipped)",
        )
    mapped = subset.filter(pl.col("site_id").is_not_null()).height
    rate = mapped / subset.height
    passed = rate >= min_rate
    return CheckResult(
        check_id=check_id,
        check_name="site_mapping",
        layer=layer,
        table=table,
        passed=passed,
        severity="error" if passed else "error",
        message=(
            f"{source_system}: {rate * 100:.1f}% mapped ({mapped:,}/{subset.height:,}, min {min_rate * 100:.0f}%)"
        ),
        actual=round(rate * 100, 2),
        expected=min_rate * 100,
        total_count=subset.height,
        failed_count=subset.height - mapped if not passed else 0,
    )


def check_no_literal_null_strings(
    df: pl.DataFrame,
    *,
    layer: str,
    table: str,
) -> CheckResult:
    check_id = f"no_literal_null_{table}"
    str_cols = [c for c, dt in df.schema.items() if dt in (pl.Utf8, pl.String)]
    if not str_cols:
        return CheckResult(
            check_id=check_id,
            check_name="no_literal_null",
            layer=layer,
            table=table,
            passed=True,
            message="no string columns to scan",
        )
    exprs = [
        pl.col(c).is_in(list(FORBIDDEN_NULL_LITERALS)).fill_null(False).alias(f"_bad_{c}")
        for c in str_cols
    ]
    flagged = df.with_columns(exprs).filter(pl.any_horizontal(exprs))
    if flagged.height == 0:
        return CheckResult(
            check_id=check_id,
            check_name="no_literal_null",
            layer=layer,
            table=table,
            passed=True,
            message=f"no literal NULL strings in {len(str_cols)} string column(s)",
            total_count=df.height,
        )
    qpath = _write_quarantine(
        layer=layer,
        table=table,
        check_name="no_literal_null",
        df=flagged.drop([c for c in flagged.columns if c.startswith("_bad_")]),
        reason='Literal "NULL" (or empty) in typed string columns',
    )
    return CheckResult(
        check_id=check_id,
        check_name="no_literal_null",
        layer=layer,
        table=table,
        passed=False,
        message=f"{flagged.height} row(s) with literal NULL/empty in string columns",
        failed_count=flagged.height,
        total_count=df.height,
        quarantine_path=qpath,
        actual=flagged.height,
        expected=0,
    )


def check_gold_site_daily_grain(df: pl.DataFrame) -> CheckResult:
    """Gold site_daily_signals: one row per site_id × signal_date."""
    check_id = "gold_grain_site_daily_signals"
    result = check_unique(
        df,
        layer="gold",
        table="site_daily_signals",
        columns=["site_id", "signal_date"],
    )
    result.check_id = check_id
    result.check_name = "gold_grain"
    if result.passed:
        result.message = f"grain OK: {df.height:,} rows = site_id × signal_date"
    else:
        result.message = f"grain violation: duplicate site_id × signal_date ({result.message})"
    result.actual = df.height
    result.expected = df.select(["site_id", "signal_date"]).unique().height
    return result


def run_validation(*, ingest_date: str | None = None) -> QualityReport:
    """Run spec-driven validation checks on existing Silver/Gold outputs."""
    from pipeline.quality.runner import run_qa_checks

    results = run_qa_checks(ingest_date or "unknown")
    report = QualityReport(results=results)
    logger.info(
        "Validation complete (date=%s): %d passed, %d errors, %d warnings",
        ingest_date or "n/a",
        sum(1 for r in results if r.passed),
        report.error_count,
        report.warning_count,
    )
    return report


def print_validation_summary_table(report: QualityReport) -> None:
    """Print a compact validation summary table."""
    print(f"\n{'=' * 100}")
    print("Validation summary")
    print(f"{'=' * 100}")
    header = f"{'Check ID':<36} {'Status':<7} {'Actual':<12} {'Expected':<12} Message"
    print(header)
    print("-" * 100)
    for r in report.results:
        check_id = r.check_id or f"{r.table}.{r.check_name}"
        status = "PASS" if r.passed else ("WARN" if r.severity == "warning" else "FAIL")
        actual = "" if r.actual is None else str(r.actual)
        expected = "" if r.expected is None else str(r.expected)
        print(f"{check_id:<36} {status:<7} {actual:<12} {expected:<12} {r.message}")
    print("-" * 100)
    passed = sum(1 for r in report.results if r.passed)
    print(f"Total: {passed}/{len(report.results)} passed")
    if report.passed:
        print("Result: ALL CHECKS PASSED")
    else:
        print(f"Result: FAILED ({report.error_count} error(s), {report.warning_count} warning(s))")


def run_all_checks() -> QualityReport:
    """Run Silver and Gold quality checks; quarantine failing rows."""
    results = run_silver_checks() + run_gold_checks()
    report = QualityReport(results=results)
    logger.info(
        "Quality checks complete: %d passed, %d errors, %d warnings",
        sum(1 for r in results if r.passed),
        report.error_count,
        report.warning_count,
    )
    return report


def print_quality_report(report: QualityReport) -> None:
    """Print human-readable quality check summary."""
    print(f"\n{'=' * 72}")
    print("Quality check report")
    print(f"{'=' * 72}")
    for layer in ("silver", "gold"):
        layer_results = [r for r in report.results if r.layer == layer]
        if not layer_results:
            continue
        print(f"\n[{layer.upper()}]")
        for r in layer_results:
            status = "PASS" if r.passed else r.severity.upper()
            print(f"  [{status}] {r.table}.{r.check_name}: {r.message}")
            if r.quarantine_path:
                print(f"         quarantine → {r.quarantine_path}")
    print(f"\n{'=' * 72}")
    if report.passed:
        print("All quality checks passed.")
    else:
        print(f"Quality checks FAILED: {report.error_count} error(s), {report.warning_count} warning(s)")
