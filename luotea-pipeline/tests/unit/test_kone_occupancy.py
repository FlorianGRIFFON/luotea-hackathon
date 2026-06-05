"""Unit tests for KONE occupancy flattening."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from pipeline.silver.transforms.kone_occupancy import (
    building_name_from_filename,
    kone_year_for_month,
    transform_kone_occupancy,
    value_type_from_filename,
)


def test_building_and_value_type_from_filename():
    assert building_name_from_filename("Aurora_House_2026-05-27_123944-normalized.json") == "Aurora House"
    assert value_type_from_filename("Aurora_House_2026-05-27_123944-normalized.json") == "normalized"
    assert value_type_from_filename("Aurora_House_2026-05-27_124513.json") == "raw_count"


def test_kone_year_for_month():
    assert kone_year_for_month(12) == 2025
    assert kone_year_for_month(1) == 2026
    assert kone_year_for_month(5) == 2026


def test_kone_occupancy_explode_24_hours(tmp_path: Path):
    bronze = tmp_path / "kone"
    bronze.mkdir()
    records = [
        {
            "month": 12,
            "weekday": 1,
            "site_connection_ok": True,
            "floor": "2",
            "floor_id": 4,
            "occupancy": list(range(24)),
        }
    ]
    (bronze / "Aurora_House_2026-05-27_123944-normalized.json").write_text(
        json.dumps(records), encoding="utf-8"
    )

    df = transform_kone_occupancy(bronze)
    assert df.height == 24
    assert df["hour"].min() == 0 and df["hour"].max() == 23
    assert df.row(0, named=True)["occupancy_value"] == 0.0
    assert df.row(23, named=True)["occupancy_value"] == 23.0
    assert df.row(0, named=True)["year"] == 2025
    assert df.row(0, named=True)["site_id"] == "site_aurora"
    assert df.row(0, named=True)["value_type"] == "normalized"


def test_kone_normalized_and_raw_both_kept(tmp_path: Path):
    bronze = tmp_path / "kone"
    bronze.mkdir()
    record = [
        {
            "month": 3,
            "weekday": 2,
            "site_connection_ok": None,
            "floor": "P",
            "floor_id": 1,
            "occupancy": [0] * 24,
        }
    ]
    (bronze / "Horizon_Plaza_2026-05-27_124034-normalized.json").write_text(json.dumps(record))
    (bronze / "Horizon_Plaza_2026-05-27_124445.json").write_text(json.dumps(record))

    df = transform_kone_occupancy(bronze)
    assert df.height == 48
    types = set(df["value_type"].unique().to_list())
    assert types == {"normalized", "raw_count"}
    assert df.filter(pl.col("site_id") == "site_horizon").height == 48
