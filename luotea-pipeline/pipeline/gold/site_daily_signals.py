"""Gold mart: site × day unified operational signals."""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone

import polars as pl

from pipeline.gold.io import load_silver

DESK_ASSET_PATTERN = re.compile(r"^K\d+$", re.IGNORECASE)
FIRE_ALERT_TYPES = {"PALO", "PALOVIK"}
HVAC_ALERT_TYPES = {"LVIS", "LVIA", "Lvi-häly", "LINJAVIK"}


def _utc_date(column: str) -> pl.Expr:
    return pl.col(column).dt.date().alias("signal_date")


def _first_weekday_in_month(year: int, month: int, weekday: int) -> date:
    """First calendar date in ``month`` with ISO weekday (1=Mon … 7=Sun)."""
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        candidate = date(year, month, day)
        if candidate.isoweekday() == weekday:
            return candidate
    raise ValueError(f"No weekday {weekday} in {year}-{month:02d}")


def _aggregate_alarms(alarms: pl.DataFrame) -> pl.DataFrame:
    if alarms.is_empty():
        return pl.DataFrame(schema={"site_id": pl.Utf8, "signal_date": pl.Date, "alarm_count": pl.Int64})

    return (
        alarms.filter(pl.col("site_id").is_not_null())
        .with_columns(_utc_date("event_time_utc"))
        .group_by("site_id", "signal_date")
        .agg(
            pl.len().alias("alarm_count"),
            pl.col("alert_type")
            .is_in(list(FIRE_ALERT_TYPES))
            .or_(pl.col("priority") == 1)
            .sum()
            .alias("fire_alarm_count"),
            pl.col("alert_type").is_in(list(HVAC_ALERT_TYPES)).sum().alias("hvac_alarm_count"),
        )
    )


def _aggregate_work_orders(work_orders: pl.DataFrame) -> pl.DataFrame:
    if work_orders.is_empty():
        return pl.DataFrame(
            schema={
                "site_id": pl.Utf8,
                "signal_date": pl.Date,
                "open_work_orders": pl.Int64,
                "sla_violations": pl.Int64,
            }
        )

    base = work_orders.filter(pl.col("site_id").is_not_null()).with_columns(
        pl.col("work_started_at_utc").dt.date().alias("start_date"),
        pl.col("work_finished_at_utc").dt.date().alias("finish_date"),
    )

    sla_daily = (
        base.filter(pl.col("is_sla_violation"))
        .with_columns(_utc_date("work_finished_at_utc"))
        .group_by("site_id", "signal_date")
        .agg(pl.len().alias("sla_violations"))
    )

    open_daily = (
        base.with_columns(
            pl.date_ranges(
                pl.col("start_date"),
                pl.col("finish_date"),
                interval="1d",
                closed="both",
            ).alias("signal_date")
        )
        .explode("signal_date")
        .group_by("site_id", "signal_date")
        .agg(pl.len().alias("open_work_orders"))
    )

    return open_daily.join(sla_daily, on=["site_id", "signal_date"], how="full", coalesce=True)


def _aggregate_sensor_readings(readings: pl.DataFrame) -> pl.DataFrame:
    if readings.is_empty():
        return pl.DataFrame(
            schema={
                "site_id": pl.Utf8,
                "signal_date": pl.Date,
                "avg_co2_ppm": pl.Float64,
                "avg_indoor_temp_c": pl.Float64,
                "electricity_kwh": pl.Float64,
                "heating_mwh": pl.Float64,
            }
        )

    base = readings.filter(pl.col("site_id").is_not_null()).with_columns(
        _utc_date("timestamp_utc")
    )

    def _metric_agg(metric: str, agg: str, alias: str) -> pl.DataFrame:
        subset = base.filter(pl.col("metric") == metric)
        if subset.is_empty():
            return pl.DataFrame(schema={"site_id": pl.Utf8, "signal_date": pl.Date, alias: pl.Float64})
        expr = pl.col("value").mean() if agg == "mean" else pl.col("value").sum()
        return subset.group_by("site_id", "signal_date").agg(expr.alias(alias))

    parts = [
        _metric_agg("interior_co2_ppm", "mean", "avg_co2_ppm"),
        _metric_agg("interior_temperature_C", "mean", "avg_indoor_temp_c"),
        _metric_agg("electricity_kWh", "sum", "electricity_kwh"),
        _metric_agg("district_heating_MWh", "sum", "heating_mwh"),
    ]
    parts = [p for p in parts if p.height > 0]
    if not parts:
        return pl.DataFrame(schema={"site_id": pl.Utf8, "signal_date": pl.Date})

    result = parts[0]
    for part in parts[1:]:
        result = result.join(part, on=["site_id", "signal_date"], how="full", coalesce=True)
    return result


def _is_desk_asset(name: str) -> bool:
    return bool(DESK_ASSET_PATTERN.match(name.strip()))


def _aggregate_utilization(utilization: pl.DataFrame) -> pl.DataFrame:
    if utilization.is_empty():
        return pl.DataFrame(
            schema={
                "site_id": pl.Utf8,
                "signal_date": pl.Date,
                "avg_room_utilization_pct": pl.Float64,
                "avg_desk_utilization_pct": pl.Float64,
            }
        )

    util = utilization.filter(pl.col("site_id").is_not_null()).with_columns(
        pl.col("utilization_date").alias("signal_date"),
        pl.col("asset_name").map_elements(_is_desk_asset, return_dtype=pl.Boolean).alias("is_desk"),
    )

    room = (
        util.filter(~pl.col("is_desk"))
        .group_by("site_id", "signal_date")
        .agg(pl.col("utilization_pct").mean().alias("avg_room_utilization_pct"))
    )
    desk = (
        util.filter(pl.col("is_desk"))
        .group_by("site_id", "signal_date")
        .agg(pl.col("utilization_pct").mean().alias("avg_desk_utilization_pct"))
    )

    return room.join(desk, on=["site_id", "signal_date"], how="full", coalesce=True)


def _aggregate_occupancy(occupancy: pl.DataFrame) -> pl.DataFrame:
    if occupancy.is_empty():
        return pl.DataFrame(
            schema={"site_id": pl.Utf8, "signal_date": pl.Date, "avg_elevator_occupancy": pl.Float64}
        )

    occ = occupancy.filter(
        (pl.col("site_id").is_not_null()) & (pl.col("value_type") == "normalized")
    ).with_columns(
        pl.struct(["year", "month", "weekday"])
        .map_elements(
            lambda row: _first_weekday_in_month(row["year"], row["month"], row["weekday"]),
            return_dtype=pl.Date,
        )
        .alias("signal_date")
    )

    return (
        occ.group_by("site_id", "signal_date")
        .agg(pl.col("occupancy_value").mean().alias("avg_elevator_occupancy"))
    )


def _aggregate_incidents(incidents: pl.DataFrame) -> pl.DataFrame:
    if incidents.is_empty():
        return pl.DataFrame(
            schema={
                "site_id": pl.Utf8,
                "signal_date": pl.Date,
                "incident_count": pl.Int64,
                "unresolved_incident_count": pl.Int64,
            }
        )

    return (
        incidents.filter(pl.col("site_id").is_not_null())
        .with_columns(_utc_date("created_at_utc"))
        .group_by("site_id", "signal_date")
        .agg(
            pl.len().alias("incident_count"),
            pl.col("is_resolved").not_().sum().alias("unresolved_incident_count"),
        )
    )


def _union_spine(parts: list[pl.DataFrame]) -> pl.DataFrame:
    """Distinct ``site_id × signal_date`` keys from all partial aggregates."""
    spine = pl.concat(
        [p.select("site_id", "signal_date") for p in parts if p.height > 0],
        how="vertical_relaxed",
    ).unique()
    return spine


def build_site_daily_signals(*, as_of_date: date | None = None) -> pl.DataFrame:
    """Build Gold ``site_daily_signals`` from Silver fact tables.

    Sites with only partial source coverage retain null metrics (never dropped).
    """
    as_of = as_of_date or datetime.now(timezone.utc).date()

    alarm_agg = _aggregate_alarms(load_silver("fact_alarm"))
    wo_agg = _aggregate_work_orders(load_silver("fact_work_order"))
    sensor_agg = _aggregate_sensor_readings(load_silver("fact_sensor_reading"))
    util_agg = _aggregate_utilization(load_silver("fact_utilization"))
    occ_agg = _aggregate_occupancy(load_silver("fact_occupancy"))
    incident_agg = _aggregate_incidents(load_silver("fact_incident"))

    parts = [alarm_agg, wo_agg, sensor_agg, util_agg, occ_agg, incident_agg]
    spine = _union_spine(parts)

    result = spine
    for part in parts:
        if part.height == 0:
            continue
        result = result.join(part, on=["site_id", "signal_date"], how="left")

    return result.with_columns(
        pl.col("alarm_count").fill_null(0),
        pl.col("fire_alarm_count").fill_null(0),
        pl.col("hvac_alarm_count").fill_null(0),
        pl.col("open_work_orders").fill_null(0),
        pl.col("sla_violations").fill_null(0),
        pl.col("incident_count").fill_null(0),
        pl.col("unresolved_incident_count").fill_null(0),
        pl.lit(as_of).alias("as_of_date"),
    ).sort("site_id", "signal_date")
