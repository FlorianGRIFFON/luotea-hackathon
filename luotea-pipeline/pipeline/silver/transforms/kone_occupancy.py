"""Silver transform: KONE occupancy profiles."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

import polars as pl

from pipeline.schemas.enums import OccupancyValueType, SourceSystem
from pipeline.silver.site_mapping import build_kone_building_lookup, enrich_with_building_site_id

logger = logging.getLogger(__name__)

BUILDING_FROM_FILE = re.compile(r"^(Aurora_House|Meridian_Tower|Horizon_Plaza)_")


def building_name_from_filename(filename: str) -> str:
    """Derive KONE building label from export filename."""
    match = BUILDING_FROM_FILE.match(filename)
    if not match:
        raise ValueError(f"Cannot parse KONE building from filename: {filename}")
    return match.group(1).replace("_", " ")


def value_type_from_filename(filename: str) -> str:
    if "-normalized" in filename:
        return OccupancyValueType.NORMALIZED.value
    return OccupancyValueType.RAW_COUNT.value


def kone_year_for_month(month: int) -> int:
    """Map month to calendar year for Dec 2025 – May 2026 export window."""
    return 2025 if month == 12 else 2026


def _occupancy_id(
    building: str,
    year: int,
    month: int,
    weekday: int,
    floor: str,
    hour: int,
    value_type: str,
) -> str:
    raw = f"{building}|{year}|{month}|{weekday}|{floor}|{hour}|{value_type}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def transform_kone_occupancy(bronze_dir: Path) -> pl.DataFrame:
    """Flatten KONE hourly occupancy arrays → ``fact_occupancy``."""
    lookup = build_kone_building_lookup()
    rows: list[dict] = []

    for path in sorted(bronze_dir.glob("*.json")):
        if path.name.endswith(".meta.json") or path.name == "_manifest.json":
            continue
        building = building_name_from_filename(path.name)
        value_type = value_type_from_filename(path.name)

        with path.open(encoding="utf-8") as handle:
            records = json.load(handle)
        if not isinstance(records, list):
            raise ValueError(f"Expected JSON array in {path}")

        for record in records:
            month = int(record["month"])
            year = kone_year_for_month(month)
            weekday = int(record["weekday"])
            floor = str(record["floor"])
            floor_id = int(record["floor_id"])
            connection = record.get("site_connection_ok")
            occupancy = record["occupancy"]
            if len(occupancy) != 24:
                raise ValueError(f"Expected 24 hourly values in {path}, got {len(occupancy)}")

            for hour, value in enumerate(occupancy):
                rows.append(
                    {
                        "occupancy_id": _occupancy_id(
                            building, year, month, weekday, floor, hour, value_type
                        ),
                        "building_name": building,
                        "year": year,
                        "month": month,
                        "weekday": weekday,
                        "floor": floor,
                        "floor_id": floor_id,
                        "hour": hour,
                        "occupancy_value": float(value),
                        "value_type": value_type,
                        "site_connection_ok": connection,
                        "source_system": SourceSystem.KONE_OCCUPANCY.value,
                        "source_file": str(path),
                    }
                )

        logger.info("KONE %s (%s): %d exploded rows", building, value_type, len(records) * 24)

    df = pl.DataFrame(rows, infer_schema_length=max(len(rows), 1))
    df = enrich_with_building_site_id(df, lookup)

    if df["occupancy_id"].n_unique() != df.height:
        raise ValueError("occupancy_id must be unique in fact_occupancy")

    return df
