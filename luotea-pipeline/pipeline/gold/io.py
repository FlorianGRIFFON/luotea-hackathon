"""Gold layer I/O helpers."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.config import GOLD_DIR, SILVER_DIR


def load_silver(table_name: str) -> pl.DataFrame:
    path = SILVER_DIR / table_name / f"{table_name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Silver table not found: {path}. Run Silver transforms first.")
    return pl.read_parquet(path)


def write_gold(df: pl.DataFrame, table_name: str) -> Path:
    out_dir = GOLD_DIR / table_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{table_name}.parquet"
    df.write_parquet(out_path)
    # Flat path for DuckDB one-liner: data/gold/{table}.parquet
    flat_path = GOLD_DIR / f"{table_name}.parquet"
    df.write_parquet(flat_path)
    return out_path
