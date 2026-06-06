"""
Leakage-safe feature engineering for the SLA-breach model.

The model answers a question asked **at the moment a work order is created**:
*"How likely is this work order to breach its SLA?"* — so every feature here must be
knowable at creation time. Post-completion fields (duration, worktime, finish date,
the label itself) are explicitly forbidden and asserted against.

Public API:
    build_sla_dataset(wo, daily) -> pl.DataFrame   # features + target + timestamp
    time_split(df, test_fraction) -> (train, test) # chronological, no leakage
    FEATURE_COLUMNS                                  # ordered list used by the model
"""
from __future__ import annotations

import polars as pl

from src.config import (
    SLA_TARGET,
    SLA_CAT_FEATURES,
    SLA_NUM_FEATURES,
    SLA_LEAKAGE_COLS,
    SLA_TEST_FRACTION,
)

FEATURE_COLUMNS = SLA_CAT_FEATURES + SLA_NUM_FEATURES
_TS = "work_started_at_utc"  # work-order creation timestamp (used only for ordering)


def build_sla_dataset(wo: pl.DataFrame, daily: pl.DataFrame | None = None) -> pl.DataFrame:
    """
    Turn raw Silver work orders into a modelling frame.

    Returns one row per work order with: FEATURE_COLUMNS + [SLA_TARGET, _TS, "wo_no"].
    Only creation-time information is used. `daily` (site_daily_signals) is joined to
    add the site's open-work-order backlog on the creation day as operational context.
    """
    df = wo.filter(pl.col(_TS).is_not_null())

    # --- calendar / creation-time features ---
    df = df.with_columns(
        [
            pl.col(_TS).dt.month().alias("start_month"),
            pl.col(_TS).dt.weekday().alias("start_weekday"),
            (pl.col(_TS).dt.weekday() >= 6).cast(pl.Int8).alias("start_is_weekend"),
            pl.col(_TS).dt.year().alias("start_year"),
            pl.col(_TS).dt.date().alias("_start_date"),
            # priority is 72% null but where present is highly predictive → keep null as a level
            pl.col("priority_id").cast(pl.Utf8).fill_null("unknown").alias("priority_id_str"),
            # contractual SLA window length in hours (mostly 0; long windows carry strong signal)
            (
                (pl.col("sla_required_end_at_utc") - pl.col("sla_required_start_at_utc"))
                .dt.total_seconds() / 3600.0
            ).alias("sla_window_hours"),
            # cast booleans to int for the numeric branch
            pl.col("is_subcontractor_work").cast(pl.Int8),
            pl.col("is_invoicable").cast(pl.Int8),
        ]
    )

    # --- operational backlog context from Gold daily signals ---
    if daily is not None:
        backlog = (
            daily.select(
                pl.col("site_id"),
                pl.col("signal_date").alias("_start_date"),
                pl.col("open_work_orders").alias("site_open_wo_at_start"),
            )
        )
        df = df.join(backlog, on=["site_id", "_start_date"], how="left")
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("site_open_wo_at_start"))

    # ensure categoricals are strings with an explicit "unknown" level (no silent NaN drops)
    for c in SLA_CAT_FEATURES:
        if c == "priority_id_str":
            continue
        df = df.with_columns(pl.col(c).cast(pl.Utf8).fill_null("unknown").alias(c))

    keep = FEATURE_COLUMNS + [SLA_TARGET, _TS, "wo_no"]
    out = df.select([c for c in keep if c in df.columns]).sort(_TS)

    _assert_no_leakage(out)
    return out


def _assert_no_leakage(df: pl.DataFrame) -> None:
    """Hard guarantee that no post-completion column leaked into the feature set."""
    leaked = [c for c in SLA_LEAKAGE_COLS if c in FEATURE_COLUMNS]
    if leaked:
        raise AssertionError(f"Leakage columns present in FEATURE_COLUMNS: {leaked}")
    present = [c for c in SLA_LEAKAGE_COLS if c in df.columns and c != SLA_TARGET]
    if present:
        raise AssertionError(f"Leakage columns present in feature frame: {present}")


def time_split(df: pl.DataFrame, test_fraction: float = SLA_TEST_FRACTION):
    """
    Chronological split: earliest rows train, most-recent `test_fraction` test.
    No shuffling → the model is always evaluated on the future, never the past.
    """
    df = df.sort(_TS)
    n = df.height
    cut = int(round(n * (1.0 - test_fraction)))
    train, test = df.head(cut), df.tail(n - cut)
    return train, test


def split_xy(df: pl.DataFrame):
    """Return (X_pandas, y_numpy) for sklearn."""
    X = df.select(FEATURE_COLUMNS).to_pandas()
    y = df.select(pl.col(SLA_TARGET).cast(pl.Int8)).to_series().to_numpy()
    return X, y
