"""Tests for maintenance plan deduplication."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.silver.transforms.erp_maintenance_plans import transform_maintenance_plans


def test_maintenance_dedup_on_pm_no(tmp_path: Path):
    csv_path = tmp_path / "plans.csv"
    csv_path.write_text(
        "LAST_UPDATED,PM_NO,MCH_CODE_CONTRACT,CUSTOMER_WORKSITE_NO,CUSTOMER_NO,"
        "customer_name,CUSTOMER_SITE_NO,customer_site_name,site_address,"
        "ACTION_DESCR,ACTION_DESCR_ENG,PRIORITY_ID,INTERVAL,PM_INTERVAL_UNIT,"
        "LAST_CHANGED,PLAN_HRS,DESCRIPTION,DESCRIPTION_ENG,START_DATE,"
        "REV_CRE_DATE,VALID_FROM,OBJSTATE\n"
        "2026-01-01 10:00:00.000,430388,KH,100,100000413,Valmet Technologies Oy,"
        "998389833,Site,Addr,Act,Act EN,3,1,Month,2026-01-01 10:00:00.000,1.0,,,"
        ",2026-01-01 10:00:00.000,,Active\n"
        "2026-06-01 10:00:00.000,430388,KH,100,100000413,Valmet Technologies Oy,"
        "998389833,Site,Addr,Act New,Act EN,3,1,Month,2026-06-01 10:00:00.000,2.0,,,"
        ",2026-06-01 10:00:00.000,,Active\n",
        encoding="utf-8-sig",
    )
    df = transform_maintenance_plans(csv_path)
    assert df.height == 1
    assert df.row(0, named=True)["action_descr"] == "Act New"
    assert df.row(0, named=True)["site_id"] == "site_valmet_l11"
