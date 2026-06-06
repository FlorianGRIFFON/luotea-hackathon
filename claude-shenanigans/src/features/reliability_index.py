"""
Reliability Risk Index (RRI) — one comparable 0–100 risk number per site per day.

This is the "single metric for operational reliability" the hackathon README asks for, and
it is what makes the solution *cross-customer*: it is computed from **whatever signals a site
has**, so a Valmet ERP site and a NovaProp IoT site land on the same 0–100 scale.

    0   = calm / reliable day
    100 = high disruption-risk day

Components (each normalised to 0–1 by percentile rank within the site, then blended; weights
re-normalise over whichever components are present so partial coverage never breaks the score):

  maintenance_risk   ERP   daily sum of model-predicted SLA-breach probability (forward-looking)
  alarm_pressure     ERP   weighted alarm load (fire ×3, HVAC ×2, other ×1)
  energy_anomaly     IoT   robust deviation of electricity_kWh from its 28-day rolling median
  incident_pressure  IoT   incidents + 3 × unresolved incidents

`maintenance_risk` is where the SLA-breach model feeds the index, turning a per-work-order
prediction into a site-level operational signal.
"""
from __future__ import annotations

import numpy as np
import polars as pl

COMPONENTS = ["maintenance_risk", "alarm_pressure", "energy_anomaly", "incident_pressure"]


def compute_breach_load(model, wo: pl.DataFrame, daily: pl.DataFrame) -> pl.DataFrame:
    """Daily per-site sum of model-predicted breach probability for work orders created that day."""
    from src.features.work_orders import build_sla_dataset, split_xy

    ds = build_sla_dataset(wo, daily)
    X, _ = split_xy(ds)
    proba = model.predict_proba(X)
    scored = ds.select(["site_id", "work_started_at_utc"]).with_columns(
        pl.Series("p", proba),
        pl.col("work_started_at_utc").dt.date().alias("signal_date"),
    )
    return (
        scored.group_by(["site_id", "signal_date"])
        .agg(pl.col("p").sum().alias("maintenance_risk_raw"),
             pl.len().alias("n_work_orders"))
    )


def _pct_rank(s: pl.Series) -> pl.Series:
    """Percentile rank in [0,1]; nulls stay null."""
    return (s.rank(method="average") - 1) / max(s.drop_nulls().len() - 1, 1)


def compute_reliability_index(
    daily: pl.DataFrame,
    breach_load: pl.DataFrame | None = None,
    weights: dict[str, float] | None = None,
) -> pl.DataFrame:
    """Return daily site rows with component scores and the blended RRI (0–100)."""
    df = daily.sort(["site_id", "signal_date"])

    # raw component signals
    df = df.with_columns(
        (
            pl.col("fire_alarm_count").fill_null(0) * 3
            + pl.col("hvac_alarm_count").fill_null(0) * 2
            + (pl.col("alarm_count").fill_null(0)
               - pl.col("fire_alarm_count").fill_null(0)
               - pl.col("hvac_alarm_count").fill_null(0)).clip(0)
        ).alias("alarm_pressure_raw"),
        (pl.col("incident_count").fill_null(0)
         + 3 * pl.col("unresolved_incident_count").fill_null(0)).alias("incident_pressure_raw"),
    )

    # energy anomaly: |kWh - rolling median(28)| / rolling MAD(28), per site
    df = df.with_columns(
        pl.col("electricity_kwh")
        .rolling_median(window_size=28, min_samples=7)
        .over("site_id").alias("_kwh_med")
    )
    df = df.with_columns(
        (pl.col("electricity_kwh") - pl.col("_kwh_med")).abs().alias("_kwh_dev")
    )
    df = df.with_columns(
        pl.col("_kwh_dev").rolling_median(window_size=28, min_samples=7)
        .over("site_id").alias("_kwh_mad")
    )
    df = df.with_columns(
        pl.when(pl.col("electricity_kwh").is_null())
        .then(None)
        .otherwise(pl.col("_kwh_dev") / (pl.col("_kwh_mad") + 1e-6))
        .alias("energy_anomaly_raw")
    )

    # join model-predicted maintenance risk
    if breach_load is not None:
        df = df.join(breach_load, on=["site_id", "signal_date"], how="left")
    else:
        df = df.with_columns(pl.lit(None, dtype=pl.Float64).alias("maintenance_risk_raw"),
                             pl.lit(None, dtype=pl.UInt32).alias("n_work_orders"))

    # null out components a site structurally lacks (avoid 0 masquerading as "calm")
    df = df.with_columns(
        pl.when(pl.col("maintenance_risk_raw").is_null()).then(None)
        .otherwise(pl.col("alarm_pressure_raw")).alias("alarm_pressure_raw"),
    )

    # normalise each component to 0–1 by within-site percentile rank
    norm = {
        "maintenance_risk": "maintenance_risk_raw",
        "alarm_pressure": "alarm_pressure_raw",
        "energy_anomaly": "energy_anomaly_raw",
        "incident_pressure": "incident_pressure_raw",
    }
    for comp, raw in norm.items():
        df = df.with_columns(
            pl.col(raw).map_batches(_pct_rank, return_dtype=pl.Float64)
            .over("site_id").alias(comp)
        )

    # weighted blend over present components (weights renormalise over non-nulls)
    w = {c: 1.0 for c in COMPONENTS}
    if weights:
        w.update(weights)
    wsum = pl.sum_horizontal(
        [pl.when(pl.col(c).is_not_null()).then(pl.lit(w[c])).otherwise(0.0) for c in COMPONENTS]
    )
    blended = pl.sum_horizontal(
        [pl.when(pl.col(c).is_not_null()).then(pl.col(c) * w[c]).otherwise(0.0) for c in COMPONENTS]
    )
    df = df.with_columns(
        pl.when(wsum > 0).then(100.0 * blended / wsum).otherwise(None).alias("reliability_risk_index")
    )

    keep = ["site_id", "signal_date", "reliability_risk_index", *COMPONENTS,
            "n_work_orders", "alarm_count", "electricity_kwh", "incident_count"]
    return df.select([c for c in keep if c in df.columns]).sort(["site_id", "signal_date"])
