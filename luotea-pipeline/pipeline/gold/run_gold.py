"""Run Gold layer builds."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import polars as pl

from pipeline.config import GOLD_DIR
from pipeline.gold.event_timeline import build_event_timeline
from pipeline.gold.io import write_gold
from pipeline.gold.site_daily_signals import build_site_daily_signals

logger = logging.getLogger(__name__)

SIGNAL_COLUMNS = [
    "alarm_count",
    "fire_alarm_count",
    "hvac_alarm_count",
    "open_work_orders",
    "sla_violations",
    "avg_co2_ppm",
    "avg_indoor_temp_c",
    "electricity_kwh",
    "heating_mwh",
    "avg_room_utilization_pct",
    "avg_desk_utilization_pct",
    "avg_elevator_occupancy",
    "incident_count",
    "unresolved_incident_count",
]


@dataclass
class GoldTableResult:
    table_name: str
    output_path: Path
    row_count: int


def run_gold(*, as_of_date: date | None = None) -> list[GoldTableResult]:
    """Build all Gold marts from Silver tables."""
    results: list[GoldTableResult] = []

    builds = [
        ("site_daily_signals", lambda: build_site_daily_signals(as_of_date=as_of_date)),
        ("event_timeline", build_event_timeline),
    ]

    for table_name, builder in builds:
        logger.info("Building gold.%s", table_name)
        df = builder()
        out_path = write_gold(df, table_name)
        results.append(GoldTableResult(table_name=table_name, output_path=out_path, row_count=df.height))
        logger.info("Wrote %s (%d rows) → %s", table_name, df.height, out_path)

    return results


def print_gold_summary(results: list[GoldTableResult]) -> None:
    print(f"\n{'=' * 72}")
    print("Gold build summary")
    print(f"{'=' * 72}")
    for r in results:
        print(f"  {r.table_name}: {r.row_count:,} rows → {r.output_path}")
    print(f"{'=' * 72}")


def print_site_samples(site_ids: list[str], *, limit: int = 10) -> None:
    """Print recent sample rows for selected sites (partial nulls expected)."""
    path = GOLD_DIR / "site_daily_signals" / "site_daily_signals.parquet"
    df = pl.read_parquet(path)

    for site_id in site_ids:
        sample = (
            df.filter(pl.col("site_id") == site_id)
            .sort("signal_date", descending=True)
            .head(limit)
        )
        print(f"\n--- site_daily_signals: {site_id} (latest {limit} dates) ---")
        if sample.is_empty():
            print("  (no rows)")
            continue
        with pl.Config(tbl_cols=-1, tbl_width_chars=200, fmt_str_lengths=40):
            print(sample.select(["site_id", "signal_date", *SIGNAL_COLUMNS]))

        non_null = {
            col: sample[col].null_count() < sample.height
            for col in SIGNAL_COLUMNS
            if col in sample.columns
        }
        populated = [c for c, has in non_null.items() if has]
        missing = [c for c in SIGNAL_COLUMNS if c not in populated]
        print(f"  populated metrics: {populated or '(counts only)'}")
        if missing:
            print(f"  null/empty metrics (expected for partial coverage): {missing}")
