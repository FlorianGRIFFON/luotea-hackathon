"""Silver dimension tables: dim_customer, dim_site."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from pipeline.schemas.enums import MappingStatus, SourceSystem
from pipeline.silver.site_mapping import build_customer_mappings, load_sites_yaml


def build_dim_customer() -> pl.DataFrame:
    """Build customer dimension from mappings/sites.yaml."""
    customers = build_customer_mappings()
    rows = [
        {
            "customer_id": c.customer_id,
            "customer_name": c.customer_name,
            "erp_customer_no": c.erp_customer_no,
            "region_code": "FI",
            "currency": None,
            "timezone": "Europe/Helsinki",
            "source_system": SourceSystem.ERP_WORK_ORDERS.value,
        }
        for c in customers
    ]
    return pl.DataFrame(rows)


def build_dim_site() -> pl.DataFrame:
    """Build site dimension from mappings/sites.yaml (all canonical sites)."""
    doc = load_sites_yaml()
    slug_map = {
        "Valmet Technologies Oy": "cust_valmet_technologies",
        "Valmet Flow Control Oy": "cust_valmet_flow_control",
        "NovaProp": "cust_novaprop",
    }
    rows = []
    for site in doc["sites"]:
        erp = site.get("erp") or {}
        smartti = site.get("smartti") or {}
        kone = site.get("kone") or {}
        rows.append(
            {
                "site_id": site["canonical_site_id"],
                "display_name": site["display_name"],
                "customer_id": slug_map.get(site["customer_name"], site["customer_name"]),
                "address": site.get("address"),
                "city": site.get("city"),
                "country": site.get("country", "FI"),
                "timezone": site.get("timezone", doc.get("default_timezone", "Europe/Helsinki")),
                "erp_customer_no": erp.get("customer_no"),
                "erp_customer_site_no": erp.get("customer_site_no"),
                "smartti_property_id": smartti.get("property_id"),
                "smartti_file_slug": smartti.get("file_slug"),
                "kone_building_name": kone.get("building_name"),
                "mapping_status": MappingStatus.MAPPED.value,
                "gross_area_m2": None,
            }
        )
    return pl.DataFrame(rows)
