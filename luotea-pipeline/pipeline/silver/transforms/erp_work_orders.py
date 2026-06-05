"""Silver transform: ERP work orders → fact_work_order."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.schemas.enums import SourceSystem
from pipeline.silver.cleaners import (
    local_to_utc,
    normalize_null,
    parse_datetime,
    parse_finished_days,
    parse_float_nullable,
    parse_finnish_bool,
    parse_int_nullable,
    read_erp_csv,
    validate_finnish_text,
)
from pipeline.silver.site_mapping import build_erp_site_lookup, enrich_with_site_id


def transform_work_orders(bronze_path: Path, *, source_file: str | None = None) -> pl.DataFrame:
    """Clean and conform ERP work orders CSV to ``fact_work_order`` schema."""
    raw = read_erp_csv(bronze_path)
    lookup = build_erp_site_lookup()

    rows: list[dict] = []
    for record in raw.iter_rows(named=True):
        for text_col in ("WORK_DESCRIPTION", "WORK_ORDER_DESCRIPTION", "WORK_ORDER_PERFORMED_ACTION"):
            val = normalize_null(record.get(text_col))
            if val:
                val = validate_finnish_text(val, context=text_col)
                record = {**record, text_col: val}

        started = parse_datetime(record.get("WORK_STARTED_DATETIME"))
        finished = parse_datetime(record.get("WORK_FINISHED_DATETIME"))
        if not started or not finished:
            raise ValueError(f"Missing start/finish datetime for WO_NO={record.get('WO_NO')}")

        finished_days = parse_finished_days(record.get("WORK_FINISHED_DAYS"))
        if finished_days is None:
            finished_days = (finished - started).total_seconds() / 86400.0

        sla_start = parse_datetime(record.get("SLA_REQUIRED_START_DATETIME"))
        sla_end = parse_datetime(record.get("SLA_REQUIRED_END_DATETIME"))
        invoicable = parse_finnish_bool(record.get("WORK_INVOICABLE"))
        subcontractor = parse_finnish_bool(record.get("IS_SUBCONTRACTOR_WORK"))
        sla_violation_raw = normalize_null(record.get("IS_SLA_VIOLATION"))

        rows.append(
            {
                "wo_no": int(record["WO_NO"]),
                "customer_no": int(record["CUSTOMER_NO"]),
                "customer_site_no": int(record["CUSTOMER_SITE_NO"]),
                "customer_worksite_no": str(record["CUSTOMER_WORKSITE_NO"]),
                "contract_type": record["CONTRACT"],
                "contract_no": parse_int_nullable(record.get("CONTRACT_NO")),
                "work_order_type": record["WORK_ORDER_TYPE"],
                "wo_parent_id": parse_int_nullable(record.get("WO_PARENT_ID")),
                "assignment_type": normalize_null(record.get("ASSIGNMENT_TYPE")),
                "priority_id": parse_int_nullable(record.get("PRIORITY_ID")),
                "work_description": normalize_null(record.get("WORK_DESCRIPTION")),
                "work_order_description": record["WORK_ORDER_DESCRIPTION"],
                "work_order_performed_action": normalize_null(record.get("WORK_ORDER_PERFORMED_ACTION")),
                "work_type_fin": record["WORK_TYPE_DESCRIPTION_FIN"],
                "work_type_eng": record["WORK_TYPE_DESCRIPTION_ENG"],
                "pm_no": normalize_null(record.get("PM_NO")),
                "pm_action_descr": normalize_null(record.get("PM_ACTION_DESCR")),
                "work_started_at_utc": local_to_utc(started),
                "work_finished_at_utc": local_to_utc(finished),
                "work_finished_days": finished_days,
                "sla_required_start_at_utc": local_to_utc(sla_start) if sla_start else None,
                "sla_required_end_at_utc": local_to_utc(sla_end) if sla_end else None,
                "is_sla_violation": bool(int(sla_violation_raw)) if sla_violation_raw is not None else False,
                "worktime_hours": parse_float_nullable(record.get("WORKTIME_HOURS")),
                "is_invoicable": invoicable if invoicable is not None else False,
                "is_subcontractor_work": subcontractor if subcontractor is not None else False,
                "source_system": SourceSystem.ERP_WORK_ORDERS.value,
                "source_file": source_file or str(bronze_path),
            }
        )

    df = pl.DataFrame(rows, infer_schema_length=max(len(rows), 1))
    df = enrich_with_site_id(df, lookup, customer_col="customer_no", site_col="customer_site_no")

    if df["wo_no"].n_unique() != df.height:
        raise ValueError("WO_NO must be unique in fact_work_order")

    return df
