"""Unit tests for utilization wide CSV unpivot and dedupe."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl

from pipeline.silver.transforms.utilization import (
    parse_utilization_file_end,
    transform_utilization,
)


def test_parse_utilization_file_end():
    assert parse_utilization_file_end("Room_Utilization_010326-270526.csv") == date(2026, 5, 27)


def test_utilization_unpivot_wide_csv(tmp_path: Path):
    bronze = tmp_path / "util"
    bronze.mkdir()
    (bronze / "Room_Utilization_010124-290224.csv").write_text(
        "asset,2024-01-01,2024-01-02\nLetto,10.5,20.0\nKarhu,0,5.5\n",
        encoding="utf-8-sig",
    )

    df = transform_utilization(bronze)
    assert df.height == 4
    assert set(df["asset_name"].unique().to_list()) == {"Letto", "Karhu"}
    letto = df.filter(pl.col("asset_name") == "Letto").sort("utilization_date")
    assert letto.row(0, named=True)["utilization_pct"] == 10.5
    assert letto.row(0, named=True)["site_id"] == "site_valmet_l11"


def test_utilization_dedupe_keeps_latest_export(tmp_path: Path):
    bronze = tmp_path / "util"
    bronze.mkdir()
    (bronze / "Room_Utilization_010124-290224.csv").write_text(
        "asset,2024-01-01\nLetto,10.0\n",
        encoding="utf-8-sig",
    )
    (bronze / "Room_Utilization_010325-310525.csv").write_text(
        "asset,2024-01-01\nLetto,99.0\n",
        encoding="utf-8-sig",
    )

    df = transform_utilization(bronze)
    assert df.height == 1
    assert df.row(0, named=True)["utilization_pct"] == 99.0
