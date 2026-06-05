"""Gold mart: unified event timeline across sources."""

from __future__ import annotations

import polars as pl

from pipeline.gold.io import load_silver
from pipeline.schemas.enums import SourceSystem

ALARM_PRIORITY_SEVERITY = {
    1: "critical",
    13: "high",
    50: "medium",
    60: "standard",
    77: "high",
    99: "informational",
}

SMARTTI_PRIORITY_SEVERITY = {
    "immediate": "critical",
    "significant": "high",
    "according_to_agreement": "standard",
}


def _alarm_events(alarms: pl.DataFrame) -> pl.DataFrame:
    if alarms.is_empty():
        return _empty_timeline()

    return alarms.select(
        pl.concat_str([pl.lit("alarm:"), pl.col("alert_event_id").cast(pl.Utf8)]).alias("event_id"),
        pl.col("site_id"),
        pl.lit(None).cast(pl.Utf8).alias("asset_id"),
        pl.when(pl.col("alert_type").is_not_null())
        .then(pl.concat_str([pl.lit("alarm_"), pl.col("alert_type")]))
        .otherwise(pl.lit("alarm"))
        .alias("event_type"),
        pl.col("priority")
        .replace_strict(ALARM_PRIORITY_SEVERITY, default="standard")
        .alias("severity"),
        pl.col("event_time_utc").alias("timestamp_utc"),
        pl.col("event_description").alias("description"),
        pl.lit(SourceSystem.ERP_ALARMS.value).alias("source_system"),
        pl.col("alert_event_id").cast(pl.Utf8).alias("source_record_id"),
    )


def _work_order_events(work_orders: pl.DataFrame) -> pl.DataFrame:
    if work_orders.is_empty():
        return _empty_timeline()

    started = work_orders.select(
        pl.concat_str([pl.lit("wo:"), pl.col("wo_no").cast(pl.Utf8), pl.lit(":started")]).alias("event_id"),
        pl.col("site_id"),
        pl.lit(None).cast(pl.Utf8).alias("asset_id"),
        pl.lit("work_order_started").alias("event_type"),
        pl.when(pl.col("priority_id").is_not_null())
        .then(pl.concat_str([pl.lit("priority_"), pl.col("priority_id").cast(pl.Utf8)]))
        .otherwise(pl.lit("standard"))
        .alias("severity"),
        pl.col("work_started_at_utc").alias("timestamp_utc"),
        pl.col("work_order_description").alias("description"),
        pl.lit(SourceSystem.ERP_WORK_ORDERS.value).alias("source_system"),
        pl.col("wo_no").cast(pl.Utf8).alias("source_record_id"),
    )

    finished = work_orders.select(
        pl.concat_str([pl.lit("wo:"), pl.col("wo_no").cast(pl.Utf8), pl.lit(":finished")]).alias("event_id"),
        pl.col("site_id"),
        pl.lit(None).cast(pl.Utf8).alias("asset_id"),
        pl.lit("work_order_finished").alias("event_type"),
        pl.when(pl.col("is_sla_violation"))
        .then(pl.lit("sla_violation"))
        .otherwise(pl.lit("completed"))
        .alias("severity"),
        pl.col("work_finished_at_utc").alias("timestamp_utc"),
        pl.coalesce([pl.col("work_order_performed_action"), pl.col("work_order_description")]).alias("description"),
        pl.lit(SourceSystem.ERP_WORK_ORDERS.value).alias("source_system"),
        pl.col("wo_no").cast(pl.Utf8).alias("source_record_id"),
    )

    return pl.concat([started, finished], how="vertical_relaxed")


def _incident_events(incidents: pl.DataFrame) -> pl.DataFrame:
    if incidents.is_empty():
        return _empty_timeline()

    return incidents.select(
        pl.concat_str([pl.lit("incident:"), pl.col("incident_id")]).alias("event_id"),
        pl.col("site_id"),
        pl.col("node_id").alias("asset_id"),
        pl.col("event_type"),
        pl.col("priority").replace_strict(SMARTTI_PRIORITY_SEVERITY, default="standard").alias("severity"),
        pl.col("created_at_utc").alias("timestamp_utc"),
        pl.col("description"),
        pl.lit(SourceSystem.SMARTTI_PULSE.value).alias("source_system"),
        pl.col("incident_id").alias("source_record_id"),
    )


def _empty_timeline() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "event_id": pl.Utf8,
            "site_id": pl.Utf8,
            "asset_id": pl.Utf8,
            "event_type": pl.Utf8,
            "severity": pl.Utf8,
            "timestamp_utc": pl.Datetime(time_unit="us", time_zone="UTC"),
            "description": pl.Utf8,
            "source_system": pl.Utf8,
            "source_record_id": pl.Utf8,
        }
    )


def build_event_timeline() -> pl.DataFrame:
    """Union alarms, work order lifecycle events, and Smartti incidents."""
    frames = [
        _alarm_events(load_silver("fact_alarm")),
        _work_order_events(load_silver("fact_work_order")),
        _incident_events(load_silver("fact_incident")),
    ]
    frames = [f for f in frames if f.height > 0]
    if not frames:
        return _empty_timeline()

    return pl.concat(frames, how="vertical_relaxed").sort("timestamp_utc")
