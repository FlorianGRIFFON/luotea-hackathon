"""Shared Silver I/O helpers."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.config import BRONZE_DIR, SILVER_DIR


def bronze_partition(source_system: str, ingest_date: str) -> Path:
    path = BRONZE_DIR / source_system / ingest_date
    if not path.exists():
        raise FileNotFoundError(f"Bronze partition not found: {path}. Run ingest first.")
    return path


def bronze_file(source_system: str, filename: str, ingest_date: str) -> Path:
    path = BRONZE_DIR / source_system / ingest_date / filename
    if not path.exists():
        raise FileNotFoundError(f"Bronze file not found: {path}. Run ingest first.")
    return path


def write_parquet(df: pl.DataFrame, table_name: str) -> Path:
    out_dir = SILVER_DIR / table_name
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{table_name}.parquet"
    df.write_parquet(out_path)
    return out_path
