"""Silver transform: Smartti Pulse sensor readings and incidents."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from pipeline.schemas.enums import SourceSystem
from pipeline.silver.site_mapping import (
    build_smartti_property_lookup,
    enrich_with_property_site_id,
)

logger = logging.getLogger(__name__)

SMARTTI_PROPERTY_FILES = ("aurora_house.json", "meridian_tower.json", "horizon_plaza.json")

METRIC_UNITS: dict[str, str] = {
    "electricity_kWh": "kWh",
    "district_heating_MWh": "MWh",
    "district_cooling_MWh": "MWh",
    "water_m3": "m3",
    "interior_temperature_C": "C",
    "interior_temperature_target_C": "C",
    "interior_temperature_tolerance_C": "C",
    "interior_co2_ppm": "ppm",
}


def parse_smartti_timestamp(value: str) -> datetime:
    """Parse Smartti ISO timestamps (space or T separator, +00 offset)."""
    text = value.strip().replace(" ", "T", 1)
    if text.endswith("+00"):
        text = text[:-3] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _reading_id(property_id: str, metric: str, meter_key: str, timestamp: str) -> str:
    raw = f"{property_id}|{metric}|{meter_key}|{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _incident_id(incident_id: str) -> str:
    return incident_id


def _explode_property_readings(
    prop: dict,
    *,
    parent_property_id: str | None,
    source_file: str,
) -> list[dict]:
    property_id = prop["id"]
    rows: list[dict] = []
    for metric, block in (prop.get("readings") or {}).items():
        unit = METRIC_UNITS.get(metric, "unknown")
        for point in block.get("data") or []:
            rows.append(
                {
                    "reading_id": _reading_id(property_id, metric, point["key"], point["t"]),
                    "property_id": property_id,
                    "parent_property_id": parent_property_id,
                    "metric": metric,
                    "meter_key": point["key"],
                    "timestamp_utc": parse_smartti_timestamp(point["t"]),
                    "value": float(point["v"]),
                    "unit": unit,
                    "source": point["src"],
                    "source_system": SourceSystem.SMARTTI_PULSE.value,
                    "source_file": source_file,
                }
            )
    return rows


def _extract_incidents(prop: dict, *, source_file: str) -> list[dict]:
    property_id = prop["id"]
    rows: list[dict] = []
    for inc in prop.get("incidents") or []:
        status = inc["status"]
        rows.append(
            {
                "incident_id": _incident_id(inc["id"]),
                "property_id": property_id,
                "node_id": inc.get("node_id"),
                "created_at_utc": parse_smartti_timestamp(inc["created_at"]),
                "updated_at_utc": parse_smartti_timestamp(inc["updated_at"]),
                "event_type": inc["event_type"],
                "priority": inc["priority"],
                "status": status,
                "category": inc["category"],
                "points": float(inc["points"]),
                "description": inc["description"],
                "is_internal": bool(inc.get("internal", False)),
                "include_in_report": bool(inc.get("include_in_report", True)),
                "is_resolved": status == "resolved",
                "source_system": SourceSystem.SMARTTI_PULSE.value,
                "source_file": source_file,
            }
        )
    return rows


def _process_smartti_file(path: Path) -> tuple[list[dict], list[dict]]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    prop = payload["property"]
    source_file = str(path)

    readings = _explode_property_readings(prop, parent_property_id=None, source_file=source_file)
    incidents = _extract_incidents(prop, source_file=source_file)

    for child in prop.get("children") or []:
        readings.extend(
            _explode_property_readings(child, parent_property_id=prop["id"], source_file=source_file)
        )
        incidents.extend(_extract_incidents(child, source_file=source_file))

    return readings, incidents


def transform_sensor_readings(bronze_dir: Path) -> pl.DataFrame:
    """Explode Smartti nested readings → ``fact_sensor_reading``."""
    lookup = build_smartti_property_lookup()
    all_rows: list[dict] = []

    for filename in SMARTTI_PROPERTY_FILES:
        path = bronze_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Smartti bronze file missing: {path}")
        rows, _ = _process_smartti_file(path)
        logger.info("Smartti readings from %s: %d rows", filename, len(rows))
        all_rows.extend(rows)

    df = pl.DataFrame(all_rows, infer_schema_length=max(len(all_rows), 1))
    df = enrich_with_property_site_id(df, lookup)

    if df["reading_id"].n_unique() != df.height:
        raise ValueError("reading_id must be unique in fact_sensor_reading")

    return df


def transform_incidents(bronze_dir: Path) -> pl.DataFrame:
    """Extract Smartti incidents → ``fact_incident``."""
    lookup = build_smartti_property_lookup()
    all_rows: list[dict] = []

    for filename in SMARTTI_PROPERTY_FILES:
        path = bronze_dir / filename
        _, rows = _process_smartti_file(path)
        logger.info("Smartti incidents from %s: %d rows", filename, len(rows))
        all_rows.extend(rows)

    df = pl.DataFrame(all_rows, infer_schema_length=max(len(all_rows), 1))
    df = enrich_with_property_site_id(df, lookup)

    if df["incident_id"].n_unique() != df.height:
        raise ValueError("incident_id must be unique in fact_incident")

    return df
