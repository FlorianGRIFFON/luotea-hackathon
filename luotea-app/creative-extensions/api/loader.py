"""
Data loader for the API — single responsibility: find and read prediction Parquet files.
All path resolution is here; routes stay clean.
"""
from __future__ import annotations

import os
from pathlib import Path

import polars as pl

# Configurable via env so the API can be run from any directory.
_DEFAULT = Path(__file__).resolve().parents[2] / "outputs" / "predictions"
PREDICTIONS_DIR: Path = Path(os.getenv("LUOTEA_PREDICTIONS", str(_DEFAULT)))


def _pred(name: str) -> Path:
    return PREDICTIONS_DIR / name


def sites() -> pl.DataFrame:
    """One row per site: site_id, last_seen date, latest RRI, band."""
    df = pl.read_parquet(_pred("portfolio_today.parquet"))
    return df.select(["site_id", "signal_date", "reliability_risk_index", "band"]).rename(
        {"signal_date": "last_seen"}
    )


def reliability(site_id: str, days: int = 30) -> pl.DataFrame:
    """Daily Reliability Risk Index for one site, most-recent `days` rows."""
    df = pl.read_parquet(_pred("reliability_index.parquet"))
    df = df.filter(pl.col("site_id") == site_id)
    if df.is_empty():
        return df
    cutoff = df["signal_date"].max() - pl.duration(days=days)
    return (
        df.filter(pl.col("signal_date") >= cutoff)
        .select(["signal_date", "reliability_risk_index", "maintenance_risk",
                 "alarm_pressure", "energy_anomaly", "incident_pressure"])
        .sort("signal_date")
    )


def dispatch(site_id: str) -> pl.DataFrame:
    """Risk-ranked work-order queue for one site (today's snapshot)."""
    fname = f"dispatch_today_{site_id}.parquet"
    path = _pred(fname)
    if not path.exists():
        return pl.DataFrame()
    return (
        pl.read_parquet(path)
        .sort("breach_risk_pct", descending=True)
        .select(["wo_no", "work_type_eng", "priority_id_str",
                 "breach_risk_pct", "risk_band"])
    )


def known_sites() -> list[str]:
    """All site_ids present in the portfolio snapshot."""
    return sites()["site_id"].to_list()
