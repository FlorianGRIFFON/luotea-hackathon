"""Silver transform: room/desk utilization wide CSVs."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import date
from pathlib import Path

import polars as pl

from pipeline.schemas.enums import MappingStatus, SourceSystem
from pipeline.silver.cleaners import read_erp_csv

logger = logging.getLogger(__name__)

UTILIZATION_SITE_ID = "site_valmet_l11"
FILE_END_PATTERN = re.compile(r"Room_Utilization_(\d{6})-(\d{6})\.csv$")


def parse_utilization_file_end(filename: str) -> date:
    """Parse export end date from ``Room_Utilization_DDMMYY-DDMMYY.csv``."""
    match = FILE_END_PATTERN.search(filename)
    if not match:
        raise ValueError(f"Cannot parse utilization date range from: {filename}")
    end = match.group(2)
    day, month, year_suffix = int(end[:2]), int(end[2:4]), int(end[4:6])
    return date(2000 + year_suffix, month, day)


def _utilization_id(asset_name: str, utilization_date: date) -> str:
    raw = f"{asset_name}|{utilization_date.isoformat()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _unpivot_utilization_file(path: Path) -> pl.DataFrame:
    """Unpivot one wide utilization CSV to long format."""
    raw = read_erp_csv(path)
    if "asset" not in raw.columns:
        raise ValueError(f"Expected 'asset' column in {path}")

    date_columns = [c for c in raw.columns if c != "asset"]
    file_end = parse_utilization_file_end(path.name)

    long_df = raw.unpivot(
        index="asset",
        on=date_columns,
        variable_name="utilization_date",
        value_name="utilization_pct_raw",
    ).rename({"asset": "asset_name"})

    return long_df.with_columns(
        pl.col("utilization_date").str.strptime(pl.Date, "%Y-%m-%d"),
        pl.col("utilization_pct_raw").cast(pl.Float64, strict=False).alias("utilization_pct"),
        pl.lit(str(path)).alias("source_file"),
        pl.lit(file_end).alias("_file_end_date"),
    ).drop("utilization_pct_raw")


def transform_utilization(bronze_dir: Path) -> pl.DataFrame:
    """Unpivot and dedupe utilization exports → ``fact_utilization``."""
    csv_files = sorted(p for p in bronze_dir.glob("Room_Utilization_*.csv") if p.is_file())
    if not csv_files:
        raise FileNotFoundError(f"No utilization CSV files in {bronze_dir}")

    parts = [_unpivot_utilization_file(path) for path in csv_files]
    combined = pl.concat(parts, how="vertical_relaxed")

    before = combined.height
    deduped = (
        combined.sort("_file_end_date", descending=True)
        .unique(subset=["asset_name", "utilization_date"], keep="first")
        .drop("_file_end_date")
    )
    removed = before - deduped.height
    if removed:
        logger.info("Utilization dedupe removed %d overlapping (asset, date) rows", removed)

    df = deduped.with_columns(
        pl.concat_str(
            [
                pl.col("asset_name"),
                pl.lit("|"),
                pl.col("utilization_date").cast(pl.Utf8),
            ]
        )
        .map_elements(
            lambda s: hashlib.sha256(s.encode()).hexdigest()[:16],
            return_dtype=pl.Utf8,
        )
        .alias("utilization_id"),
        pl.lit(UTILIZATION_SITE_ID).alias("site_id"),
        pl.lit(MappingStatus.MAPPED.value).alias("mapping_status"),
        pl.lit(None).cast(pl.Utf8).alias("asset_id"),
        pl.lit(SourceSystem.CLEANING_UTILIZATION.value).alias("source_system"),
    )

    if df["utilization_id"].n_unique() != df.height:
        raise ValueError("utilization_id must be unique in fact_utilization")

    return df
