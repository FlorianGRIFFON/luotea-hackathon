"""
Reliability Risk Index (RRI) — one comparable 0–100 risk number per site per day.

This is the "single metric for operational reliability" the hackathon README asks for, and
it is what makes the solution *cross-customer*: it is computed from **whatever signals a site
has**, so a Valmet ERP site and a NovaProp IoT site land on the same 0–100 scale.

    0   = calm / reliable day
    100 = high disruption-risk day

Components (blended; weights re-normalise over whichever components are present, so partial
coverage never breaks the score):

  maintenance_risk   ERP   mean model-predicted SLA-breach probability of the day's work orders
                           — an ABSOLUTE 0–1 level, so a genuinely high-risk site stays high and
                           does not revert to the middle of its own range (forward-looking)
  alarm_pressure     ERP   weighted alarm load (fire ×3, HVAC ×2, other ×1)
  energy_anomaly     IoT   robust deviation of electricity_kWh from its 28-day rolling median
  incident_pressure  IoT   incidents + 3 × unresolved incidents

The maintenance component is kept on an absolute probability scale; the secondary signals
(alarm / energy / incident), which have no natural 0–1 meaning, are scaled to the site's own
5th–95th percentile. Structurally-absent or zero-variance components are dropped, not pinned to
the middle. The blended daily score is finally smoothed over a trailing 7-day window so the index
reflects *sustained* risk rather than weekday/weekend work-order-volume noise.

`maintenance_risk` is where the SLA-breach model feeds the index, turning per-work-order
predictions into a persistent, comparable site-level operational signal.
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
        .agg(pl.col("p").mean().alias("maintenance_risk_raw"),   # mean intensity (0–1), volume-robust
             pl.col("p").sum().alias("expected_breaches"),       # Σ prob ≈ expected breaches that day
             pl.len().alias("n_work_orders"))
    )


def _robust_unit(s: pl.Series) -> pl.Series:
    """
    Level-preserving normalisation to [0,1] using the site's own 5th–95th percentile
    (winsorised min–max). Unlike a percentile *rank*, this keeps levels: a sustained bad
    stretch stays near 1, a calm stretch stays near 0 — it does NOT force the median to 0.5.

    Returns all-null (→ component excluded from the blend) when the signal is structurally
    absent (all null) or degenerate (no spread, e.g. incidents that are always 0).
    """
    x = s.to_numpy().astype(float)
    mask = ~np.isnan(x)
    if mask.sum() < 5:
        return pl.Series([None] * len(x), dtype=pl.Float64)
    lo, hi = np.percentile(x[mask], 5), np.percentile(x[mask], 95)
    if hi - lo < 1e-9:  # no meaningful variation → not an informative component here
        return pl.Series([None] * len(x), dtype=pl.Float64)
    out = np.clip((x - lo) / (hi - lo), 0.0, 1.0)
    out[~mask] = np.nan
    # NaN must become a real polars null (not a float NaN) so it is excluded downstream
    return pl.Series(out, dtype=pl.Float64).fill_nan(None)


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

    # Maintenance: keep the ABSOLUTE probability level (mean breach prob, already 0–1). On days
    # with no work orders it is genuinely unknown → stays null and is excluded (not read as calm).
    df = df.with_columns(pl.col("maintenance_risk_raw").clip(0.0, 1.0).alias("maintenance_risk"))

    # Secondary signals have no natural 0–1 scale → scale to the site's 5th–95th percentile.
    # Structurally-absent or zero-variance components are dropped (returned null) by _robust_unit.
    for comp, raw in [("alarm_pressure", "alarm_pressure_raw"),
                      ("energy_anomaly", "energy_anomaly_raw"),
                      ("incident_pressure", "incident_pressure_raw")]:
        df = df.with_columns(
            pl.col(raw).map_batches(_robust_unit, return_dtype=pl.Float64)
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
        pl.when(wsum > 0).then(100.0 * blended / wsum).otherwise(None).alias("rri_daily")
    )

    # Persistence: a trailing 7-day mean so the index reflects sustained risk and ignores
    # weekday/weekend work-order-volume noise — a bad week stays elevated instead of snapping back.
    df = df.with_columns(
        pl.col("rri_daily").rolling_mean(window_size=7, min_samples=1)
        .over("site_id").alias("reliability_risk_index")
    )

    keep = ["site_id", "signal_date", "reliability_risk_index", "rri_daily", *COMPONENTS,
            "n_work_orders", "alarm_count", "electricity_kwh", "incident_count"]
    return df.select([c for c in keep if c in df.columns]).sort(["site_id", "signal_date"])
