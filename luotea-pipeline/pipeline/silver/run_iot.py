"""Run Silver IoT / third-party transforms and write Parquet outputs."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import polars as pl

from pipeline.silver.cleaners import mapping_hit_rate, null_rate
from pipeline.silver.io import bronze_partition, write_parquet
from pipeline.silver.run_erp import SilverTableResult, print_validation_stats
from pipeline.silver.transforms.kone_occupancy import transform_kone_occupancy
from pipeline.silver.transforms.smartti_readings import transform_incidents, transform_sensor_readings
from pipeline.silver.transforms.utilization import transform_utilization

logger = logging.getLogger(__name__)


def _collect_null_rates(df: pl.DataFrame, columns: list[str]) -> dict[str, float]:
    return {col: null_rate(df, col) for col in columns if col in df.columns and null_rate(df, col) > 0}


def run_iot_silver(ingest_date: str) -> list[SilverTableResult]:
    """Transform Smartti, KONE, and utilization Bronze sources into Silver tables."""
    results: list[SilverTableResult] = []

    smartti_dir = bronze_partition("smartti_pulse", ingest_date)
    kone_dir = bronze_partition("kone_occupancy", ingest_date)
    util_dir = bronze_partition("cleaning_utilization", ingest_date)

    transforms = [
        (
            "fact_sensor_reading",
            lambda: transform_sensor_readings(smartti_dir),
            ["site_id", "parent_property_id"],
        ),
        (
            "fact_incident",
            lambda: transform_incidents(smartti_dir),
            ["site_id", "node_id"],
        ),
        (
            "fact_occupancy",
            lambda: transform_kone_occupancy(kone_dir),
            ["site_id", "site_connection_ok"],
        ),
        (
            "fact_utilization",
            lambda: transform_utilization(util_dir),
            ["site_id", "asset_id"],
        ),
    ]

    for table_name, transform_fn, null_cols in transforms:
        logger.info("Transforming %s", table_name)
        df = transform_fn()
        out_path = write_parquet(df, table_name)
        hit = mapping_hit_rate(df) * 100 if "site_id" in df.columns else None
        results.append(
            SilverTableResult(
                table_name=table_name,
                output_path=out_path,
                row_count=df.height,
                null_rates=_collect_null_rates(df, null_cols),
                mapping_hit_pct=hit,
            )
        )

    return results


def print_iot_validation_stats(results: list[SilverTableResult]) -> None:
    """Print IoT Silver validation stats with domain-specific extras."""
    print(f"\n{'=' * 72}")
    print("Silver IoT validation stats")
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

        if r.table_name == "fact_sensor_reading":
            df = pl.read_parquet(r.output_path)
            child_rows = df.filter(pl.col("parent_property_id").is_not_null()).height
            print(f"  child property readings: {child_rows:,} ({child_rows / df.height * 100:.1f}%)")
        if r.table_name == "fact_incident":
            df = pl.read_parquet(r.output_path)
            resolved = df.filter(pl.col("is_resolved")).height / df.height * 100
            print(f"  resolved incidents: {resolved:.1f}%")
        if r.table_name == "fact_occupancy":
            df = pl.read_parquet(r.output_path)
            normalized = df.filter(pl.col("value_type") == "normalized").height
            print(f"  normalized rows: {normalized:,} ({normalized / df.height * 100:.1f}%)")
        if r.table_name == "fact_utilization":
            df = pl.read_parquet(r.output_path)
            assets = df["asset_name"].n_unique()
            print(f"  unique assets: {assets}")

    print(f"\n{'=' * 72}")
