"""Silver transform: ERP alarms → fact_alarm."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.schemas.enums import AlarmPriority, MappingStatus, SourceSystem
from pipeline.silver.cleaners import (
    local_to_utc,
    normalize_null,
    parse_datetime,
    parse_int_nullable,
    read_erp_csv,
)
from pipeline.silver.site_mapping import build_erp_site_lookup, enrich_with_site_id

ALLOWED_PRIORITIES = {p.value for p in AlarmPriority}


def transform_alarms(bronze_path: Path, *, source_file: str | None = None) -> pl.DataFrame:
    """Clean and conform ERP alarms CSV to ``fact_alarm`` schema."""
    raw = read_erp_csv(bronze_path)
    lookup = build_erp_site_lookup()

    rows: list[dict] = []
    for record in raw.iter_rows(named=True):
        priority_raw = normalize_null(record.get("Priority"))
        if priority_raw is not None:
            priority = int(priority_raw)
            if priority not in ALLOWED_PRIORITIES:
                raise ValueError(
                    f"Invalid alarm Priority {priority} for ALERT_EVENT_ID={record.get('ALERT_EVENT_ID')}"
                )

        workorder_no = parse_int_nullable(record.get("WORKORDER_NO"))
        loop_raw = normalize_null(record.get("LOOP"))
        loop = loop_raw.strip() if isinstance(loop_raw, str) else loop_raw
        alert_type_raw = normalize_null(record.get("ALERT_TYPE"))
        log_only = normalize_null(record.get("LOG_ONLY"))

        event_time = parse_datetime(record.get("EVENT_TIME"))
        event_closed = parse_datetime(record.get("EVENT_CLOSED_TIME"))

        rows.append(
            {
                "alert_event_id": int(record["ALERT_EVENT_ID"]),
                "alert_id": int(record["ALERT_ID"]),
                "customer_no": int(record["CUSTOMER_NO"]),
                "customer_site_no": int(record["CUSTOMER_SITE_NO"]),
                "contract_no": int(record["CONTRACT_NO"]),
                "event_time_utc": local_to_utc(event_time) if event_time else None,
                "event_type": record["EVENT_TYPE"],
                "hwid": record["HWID"],
                "hwid_type": record["HWID_TYPE"],
                "loop": loop,
                "alert_type": alert_type_raw if alert_type_raw else None,
                "priority": priority,
                "is_log_only": log_only == "L",
                "event_description": record["EVENT_DESCRIPTION"],
                "workorder_no": workorder_no,
                "has_work_order": workorder_no is not None,
                "event_closed_at_utc": local_to_utc(event_closed) if event_closed else None,
                "location_id": int(record["LOCATION_ID"]),
                "location_table_id": int(record["LOCATION_TABLE_ID"]),
                "iva_no": record["IVA_NO"],
                "status": record["STATUS"],
                "source_system": SourceSystem.ERP_ALARMS.value,
                "source_file": source_file or str(bronze_path),
            }
        )

    df = pl.DataFrame(rows, infer_schema_length=max(len(rows), 1))
    df = enrich_with_site_id(df, lookup, customer_col="customer_no", site_col="customer_site_no")

    # Validate uniqueness
    if df["alert_event_id"].n_unique() != df.height:
        raise ValueError("ALERT_EVENT_ID must be unique in fact_alarm")

    return df
