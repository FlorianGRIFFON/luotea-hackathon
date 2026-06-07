"""Gold/Silver data loaders — read-only consumers of luotea-pipeline outputs."""
import polars as pl
from src.config import GOLD_DAILY, GOLD_EVENTS, SILVER_DIR, SILVER_WORK_ORDERS


def load_daily_signals(site_id: str | None = None) -> pl.DataFrame:
    df = pl.read_parquet(GOLD_DAILY)
    if site_id:
        df = df.filter(pl.col("site_id") == site_id)
    return df.sort("signal_date")


def load_event_timeline(site_id: str | None = None) -> pl.DataFrame:
    df = pl.read_parquet(GOLD_EVENTS)
    if site_id:
        df = df.filter(pl.col("site_id") == site_id)
    return df.sort("timestamp_utc")


def load_silver(table: str) -> pl.DataFrame:
    path = SILVER_DIR / table / f"{table}.parquet"
    return pl.read_parquet(path)


def load_work_orders(site_id: str | None = None) -> pl.DataFrame:
    """Silver fact_work_order — one row per work order (SLA-breach model input)."""
    df = pl.read_parquet(SILVER_WORK_ORDERS)
    if site_id:
        df = df.filter(pl.col("site_id") == site_id)
    return df.sort("work_started_at_utc")


def list_sites() -> list[str]:
    df = pl.read_parquet(GOLD_DAILY)
    return sorted(df["site_id"].unique().to_list())
