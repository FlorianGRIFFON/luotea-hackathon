"""Silver transform: ERP maintenance plans → fact_maintenance_plan."""

from __future__ import annotations

import logging
from pathlib import Path

import polars as pl

from pipeline.schemas.enums import SourceSystem
from pipeline.silver.cleaners import (
    local_to_utc,
    normalize_null,
    parse_date,
    parse_datetime,
    parse_float_nullable,
    parse_int_nullable,
    read_erp_csv,
)
from pipeline.silver.site_mapping import build_erp_site_lookup, enrich_with_site_id

logger = logging.getLogger(__name__)


def transform_maintenance_plans(bronze_path: Path, *, source_file: str | None = None) -> pl.DataFrame:
    """Clean, dedupe, and conform maintenance plans to ``fact_maintenance_plan``."""
    raw = read_erp_csv(bronze_path)
    lookup = build_erp_site_lookup()

    rows: list[dict] = []
    for record in raw.iter_rows(named=True):
        last_updated = parse_datetime(record.get("LAST_UPDATED"))
        if not last_updated:
            raise ValueError(f"Missing LAST_UPDATED for PM_NO={record.get('PM_NO')}")

        rows.append(
            {
                "pm_no": str(record["PM_NO"]),
                "contract_type": record["MCH_CODE_CONTRACT"],
                "customer_no": int(record["CUSTOMER_NO"]),
                "customer_site_no": int(record["CUSTOMER_SITE_NO"]),
                "customer_worksite_no": str(record["CUSTOMER_WORKSITE_NO"]),
                "action_descr": record["ACTION_DESCR"],
                "action_descr_eng": record["ACTION_DESCR_ENG"],
                "description": normalize_null(record.get("DESCRIPTION")),
                "description_eng": normalize_null(record.get("DESCRIPTION_ENG")),
                "priority_id": int(record["PRIORITY_ID"]),
                "interval": parse_int_nullable(record.get("INTERVAL")),
                "interval_unit": normalize_null(record.get("PM_INTERVAL_UNIT")),
                "plan_hrs": parse_float_nullable(record.get("PLAN_HRS")),
                "start_date": parse_date(record.get("START_DATE")),
                "valid_from": parse_date(record.get("VALID_FROM")),
                "objstate": record["OBJSTATE"],
                "last_updated_utc": local_to_utc(last_updated),
                "_last_updated_sort": last_updated,
                "source_system": SourceSystem.ERP_MAINTENANCE_PLANS.value,
                "source_file": source_file or str(bronze_path),
            }
        )

    df = pl.DataFrame(rows, infer_schema_length=max(len(rows), 1))
    before = df.height
    df = (
        df.sort("_last_updated_sort", descending=True)
        .unique(subset=["pm_no"], keep="first")
        .drop("_last_updated_sort")
    )
    removed = before - df.height
    if removed:
        logger.info("Deduped maintenance plans: removed %d duplicate PM_NO rows", removed)

    df = enrich_with_site_id(df, lookup, customer_col="customer_no", site_col="customer_site_no")

    if df["pm_no"].n_unique() != df.height:
        raise ValueError("PM_NO must be unique after dedupe in fact_maintenance_plan")

    return df
