"""Gold mart: rolling 7-day site context for ML feature joining."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.config import GOLD_DIR

WINDOW = 7


def build_site_rolling_context() -> pl.DataFrame:
    """Compute rolling 7-day site signals from site_daily_signals.

    Produces one row per (site_id, as_of_date). The ML layer joins on
    work_order.site_id + (start_date - 1 day) to get leak-free site context.

    Rolling window (WINDOW=7 calendar days, min_samples=1):
      - Averages for level signals: open WOs, alarms, utilization
      - Sums for event signals: SLA violations, fire alarms, incidents
        (rare events matter cumulatively, not as daily averages)
    """
    path = GOLD_DIR / "site_daily_signals" / "site_daily_signals.parquet"
    if not path.exists():
        raise FileNotFoundError(
            f"site_daily_signals not found at {path}. "
            "Run: python3.11 -m pipeline transform --layer gold first."
        )

    signals = pl.read_parquet(path)

    if signals.is_empty():
        return _empty_schema()

    return (
        signals
        .sort(["site_id", "signal_date"])
        .with_columns([
            pl.col("open_work_orders").cast(pl.Float64)
              .rolling_mean(window_size=WINDOW, min_samples=1)
              .over("site_id")
              .alias("open_wo_7d_avg"),
            pl.col("sla_violations").cast(pl.Float64)
              .rolling_sum(window_size=WINDOW, min_samples=1)
              .over("site_id")
              .alias("sla_violations_7d"),
            pl.col("alarm_count").cast(pl.Float64)
              .rolling_mean(window_size=WINDOW, min_samples=1)
              .over("site_id")
              .alias("alarms_7d_avg"),
            pl.col("fire_alarm_count").cast(pl.Float64)
              .rolling_sum(window_size=WINDOW, min_samples=1)
              .over("site_id")
              .alias("fire_alarms_7d"),
            pl.col("incident_count").cast(pl.Float64)
              .rolling_sum(window_size=WINDOW, min_samples=1)
              .over("site_id")
              .alias("incidents_7d"),
            pl.col("avg_room_utilization_pct")
              .rolling_mean(window_size=WINDOW, min_samples=1)
              .over("site_id")
              .alias("utilization_7d_avg"),
        ])
        .select([
            "site_id",
            pl.col("signal_date").alias("as_of_date"),
            "open_wo_7d_avg",
            "sla_violations_7d",
            "alarms_7d_avg",
            "fire_alarms_7d",
            "incidents_7d",
            "utilization_7d_avg",
        ])
    )


def _empty_schema() -> pl.DataFrame:
    return pl.DataFrame(schema={
        "site_id":           pl.Utf8,
        "as_of_date":        pl.Date,
        "open_wo_7d_avg":    pl.Float64,
        "sla_violations_7d": pl.Float64,
        "alarms_7d_avg":     pl.Float64,
        "fire_alarms_7d":    pl.Float64,
        "incidents_7d":      pl.Float64,
        "utilization_7d_avg": pl.Float64,
    })
