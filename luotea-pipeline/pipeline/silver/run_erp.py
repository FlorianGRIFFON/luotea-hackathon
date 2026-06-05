"""Run Silver ERP transforms and write Parquet outputs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from pipeline.config import BRONZE_DIR, SILVER_DIR
from pipeline.silver.cleaners import mapping_hit_rate, null_rate
from pipeline.silver.transforms.dimensions import build_dim_customer, build_dim_site
from pipeline.silver.transforms.erp_alarms import transform_alarms
from pipeline.silver.transforms.erp_maintenance_plans import transform_maintenance_plans
from pipeline.silver.transforms.erp_work_orders import transform_work_orders

logger = logging.getLogger(__name__)

ERP_BRONZE_SOURCES = {
    "fact_alarm": ("erp_alarms", "alarms.csv", transform_alarms),
    "fact_work_order": ("erp_work_orders", "work_orders_anonymized 1.csv", transform_work_orders),
    "fact_maintenance_plan": (
        "erp_maintenance_plans",
        "Scheduled maitenance plans.csv",
        transform_maintenance_plans,
    ),
}


@dataclass
class SilverTableResult:
    table_name: str
    output_path: Path
    row_count: int
    null_rates: dict[str, float] = field(default_factory=dict)
    mapping_hit_pct: float | None = None


def _bronze_file(source_system: str, filename: str, ingest_date: str) -> Path:
    path = BRONZE_DIR / source_system / ingest_date / filename
    if not path.exists():
        raise FileNotFoundError(f"Bronze file not found: {path}. Run ingest first.")
    return path


def _write_parquet(df: pl.DataFrame, table_name: str) -> Path:
    out_dir = SILVER_DIR / table_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{table_name}.parquet"
    df.write_parquet(out_path)
    return out_path


def _collect_null_rates(df: pl.DataFrame, columns: list[str]) -> dict[str, float]:
    return {col: null_rate(df, col) for col in columns if null_rate(df, col) > 0}


def run_erp_silver(ingest_date: str) -> list[SilverTableResult]:
    """Transform all ERP Bronze sources into Silver Parquet tables."""
    results: list[SilverTableResult] = []

    for table_name, (source_system, filename, transform_fn) in ERP_BRONZE_SOURCES.items():
        bronze_path = _bronze_file(source_system, filename, ingest_date)
        logger.info("Transforming %s from %s", table_name, bronze_path)
        df = transform_fn(bronze_path)
        out_path = _write_parquet(df, table_name)

        key_null_cols = [
            c
            for c in df.columns
            if c
            in {
                "site_id",
                "workorder_no",
                "pm_no",
                "work_description",
                "work_order_performed_action",
                "event_closed_at_utc",
                "assignment_type",
                "priority_id",
                "description",
                "plan_hrs",
                "interval",
            }
        ]
        hit = mapping_hit_rate(df) * 100 if "site_id" in df.columns else None
        results.append(
            SilverTableResult(
                table_name=table_name,
                output_path=out_path,
                row_count=df.height,
                null_rates=_collect_null_rates(df, key_null_cols),
                mapping_hit_pct=hit,
            )
        )

    for table_name, builder in (("dim_customer", build_dim_customer), ("dim_site", build_dim_site)):
        df = builder()
        out_path = _write_parquet(df, table_name)
        results.append(
            SilverTableResult(
                table_name=table_name,
                output_path=out_path,
                row_count=df.height,
                mapping_hit_pct=100.0,
            )
        )

    return results


def print_validation_stats(results: list[SilverTableResult]) -> None:
    """Print null rates and mapping hit percentages."""
    print(f"\n{'=' * 72}")
    print("Silver ERP validation stats")
    print(f"{'=' * 72}")
    for r in results:
        print(f"\n{r.table_name}  ({r.row_count:,} rows)")
        print(f"  path: {r.output_path}")
        if r.mapping_hit_pct is not None:
            print(f"  site mapping hit: {r.mapping_hit_pct:.1f}%")
        if r.null_rates:
            print("  null rates (non-zero):")
            for col, rate in sorted(r.null_rates.items(), key=lambda x: -x[1]):
                print(f"    {col}: {rate * 100:.1f}%")
        else:
            print("  null rates: (no tracked nulls)")

        # Extra fact-specific stats
        if r.table_name == "fact_alarm":
            df = pl.read_parquet(r.output_path)
            wo_link = df.filter(pl.col("has_work_order")).height / df.height * 100
            print(f"  has_work_order link: {wo_link:.1f}%")
        if r.table_name == "fact_work_order":
            df = pl.read_parquet(r.output_path)
            pm_null = df.filter(pl.col("pm_no").is_null()).height / df.height * 100
            print(f"  pm_no null (on-demand): {pm_null:.1f}%")

    print(f"\n{'=' * 72}")
