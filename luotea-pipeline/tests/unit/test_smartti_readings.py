"""Unit tests for Smartti nested JSON transforms."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from pipeline.silver.transforms.smartti_readings import (
    parse_smartti_timestamp,
    transform_incidents,
    transform_sensor_readings,
)


def _write_smartti_fixture(path: Path, *, property_id: str = "property_test", with_children: bool = False) -> None:
    payload = {
        "property": {
            "id": property_id,
            "readings": {
                "electricity_kWh": {
                    "data": [
                        {
                            "t": "2021-02-10 12:00:00+00",
                            "v": 1.5,
                            "key": "meter/1",
                            "src": "enerkey",
                        }
                    ]
                },
                "interior_co2_ppm": {
                    "data": [
                        {
                            "t": "2021-02-10T12:05:00+00:00",
                            "v": 420.0,
                            "key": "node/1",
                            "src": "smartti_automation",
                        }
                    ]
                },
            },
            "incidents": [
                {
                    "id": f"inc-{property_id}",
                    "node_id": "node-a",
                    "created_at": "2024-01-01 08:00:00+00",
                    "updated_at": "2024-01-02 09:00:00+00",
                    "event_type": "Vikailmoitus",
                    "priority": "immediate",
                    "status": "resolved",
                    "category": "fault",
                    "points": 1.0,
                    "description": "Testivika",
                    "internal": False,
                    "include_in_report": True,
                    "comments": [],
                }
            ],
            "children": [],
        }
    }
    if with_children:
        payload["property"]["children"] = [
            {
                "id": "property_test_child",
                "readings": {
                    "electricity_kWh": {
                        "data": [
                            {
                                "t": "2022-03-01 10:00:00+00",
                                "v": 9.9,
                                "key": "child/1",
                                "src": "enerkey",
                            }
                        ]
                    }
                },
                "incidents": [],
            }
        ]
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_parse_smartti_timestamp_space_and_t_separators():
    dt1 = parse_smartti_timestamp("2021-02-10 12:00:00+00")
    dt2 = parse_smartti_timestamp("2021-02-10T12:05:00+00:00")
    assert dt1.year == 2021 and dt1.hour == 12
    assert dt2.minute == 5
    assert str(dt1.tzinfo) in ("UTC", "UTC+00:00")


def test_smartti_readings_explode_metrics(tmp_path: Path):
    bronze = tmp_path / "smartti"
    bronze.mkdir()
    for name, pid in (
        ("aurora_house.json", "property_aurora"),
        ("meridian_tower.json", "property_meridian"),
        ("horizon_plaza.json", "property_horizon"),
    ):
        _write_smartti_fixture(bronze / name, property_id=pid)

    df = transform_sensor_readings(bronze)
    assert df.height == 6  # 2 metrics × 3 property files
    assert set(df["metric"].unique().to_list()) == {"electricity_kWh", "interior_co2_ppm"}
    assert df["reading_id"].n_unique() == df.height


def test_smartti_meridian_children_parent_link(tmp_path: Path):
    bronze = tmp_path / "smartti"
    bronze.mkdir()
    _write_smartti_fixture(bronze / "aurora_house.json", property_id="property_aurora")
    _write_smartti_fixture(bronze / "horizon_plaza.json", property_id="property_horizon")
    _write_smartti_fixture(
        bronze / "meridian_tower.json",
        property_id="property_meridian_parent",
        with_children=True,
    )

    df = transform_sensor_readings(bronze)
    child_rows = df.filter(pl.col("parent_property_id").is_not_null())
    assert child_rows.height == 1
    assert child_rows.row(0, named=True)["parent_property_id"] == "property_meridian_parent"
    assert child_rows.row(0, named=True)["meter_key"] == "child/1"


def test_smartti_incidents_and_site_mapping(tmp_path: Path):
    bronze = tmp_path / "smartti"
    bronze.mkdir()
    for name, pid in (
        ("aurora_house.json", "property_aurora"),
        ("meridian_tower.json", "property_meridian"),
        ("horizon_plaza.json", "property_horizon"),
    ):
        _write_smartti_fixture(bronze / name, property_id=pid)

    df = transform_incidents(bronze)
    assert df.height == 3
    assert df.filter(pl.col("is_resolved")).height == 3
    # property_test_parent is not in sites.yaml — unmapped in fixture
    assert df.filter(pl.col("mapping_status") == "unmapped").height == 3
