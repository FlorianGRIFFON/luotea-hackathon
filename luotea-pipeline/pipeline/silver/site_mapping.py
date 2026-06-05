"""Site mapping loader and ERP key enrichment."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl
import yaml

from pipeline.config import MAPPINGS_DIR
from pipeline.schemas.enums import MappingStatus


@dataclass(frozen=True)
class ErpSiteMapping:
    site_id: str
    customer_no: int
    customer_site_no: int
    customer_name: str
    display_name: str
    timezone: str


@dataclass(frozen=True)
class CustomerMapping:
    customer_id: str
    customer_name: str
    erp_customer_no: int | None


def _erp_key(customer_no: int | str, customer_site_no: int | str) -> str:
    return f"{customer_no}:{customer_site_no}"


def load_sites_yaml(path: Path | None = None) -> dict:
    path = path or MAPPINGS_DIR / "sites.yaml"
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_erp_site_lookup(sites_doc: dict | None = None) -> dict[str, ErpSiteMapping]:
    """Build ``customer_no:customer_site_no`` → ErpSiteMapping."""
    doc = sites_doc or load_sites_yaml()
    lookup: dict[str, ErpSiteMapping] = {}
    for site in doc["sites"]:
        erp = site.get("erp") or {}
        customer_no = erp.get("customer_no")
        customer_site_no = erp.get("customer_site_no")
        if customer_no is None or customer_site_no is None:
            continue
        key = _erp_key(customer_no, customer_site_no)
        lookup[key] = ErpSiteMapping(
            site_id=site["canonical_site_id"],
            customer_no=int(customer_no),
            customer_site_no=int(customer_site_no),
            customer_name=site["customer_name"],
            display_name=site["display_name"],
            timezone=site.get("timezone", doc.get("default_timezone", "Europe/Helsinki")),
        )
    return lookup


def build_customer_mappings(sites_doc: dict | None = None) -> list[CustomerMapping]:
    """Derive canonical customers from site mappings."""
    doc = sites_doc or load_sites_yaml()
    seen: dict[str, CustomerMapping] = {}
    slug_map = {
        "Valmet Technologies Oy": "cust_valmet_technologies",
        "Valmet Flow Control Oy": "cust_valmet_flow_control",
        "NovaProp": "cust_novaprop",
    }
    for site in doc["sites"]:
        name = site["customer_name"]
        erp_no = (site.get("erp") or {}).get("customer_no")
        cid = slug_map.get(name, f"cust_{name.lower().replace(' ', '_')}")
        if cid not in seen:
            seen[cid] = CustomerMapping(
                customer_id=cid,
                customer_name=name,
                erp_customer_no=int(erp_no) if erp_no is not None else None,
            )
    return list(seen.values())


def build_smartti_property_lookup(sites_doc: dict | None = None) -> dict[str, str]:
    """Map Smartti ``property_id`` → canonical ``site_id``."""
    doc = sites_doc or load_sites_yaml()
    lookup: dict[str, str] = {}
    for site in doc["sites"]:
        smartti = site.get("smartti") or {}
        property_id = smartti.get("property_id")
        if property_id:
            lookup[property_id] = site["canonical_site_id"]
        for child_id in smartti.get("child_property_ids") or []:
            lookup[child_id] = site["canonical_site_id"]
    return lookup


def build_kone_building_lookup(sites_doc: dict | None = None) -> dict[str, str]:
    """Map KONE building display name → canonical ``site_id``."""
    doc = sites_doc or load_sites_yaml()
    lookup: dict[str, str] = {}
    for site in doc["sites"]:
        kone = site.get("kone") or {}
        building = kone.get("building_name")
        if building:
            lookup[building] = site["canonical_site_id"]
    return lookup


def enrich_with_property_site_id(
    df: pl.DataFrame,
    lookup: dict[str, str],
    *,
    property_col: str = "property_id",
) -> pl.DataFrame:
    """Add ``site_id`` and ``mapping_status`` via Smartti property id."""
    mapping_df = pl.DataFrame(
        {"property_id": list(lookup.keys()), "site_id": list(lookup.values())}
    )
    return (
        df.join(mapping_df, on=property_col, how="left")
        .with_columns(
            pl.when(pl.col("site_id").is_not_null())
            .then(pl.lit(MappingStatus.MAPPED.value))
            .otherwise(pl.lit(MappingStatus.UNMAPPED.value))
            .alias("mapping_status")
        )
    )


def enrich_with_building_site_id(
    df: pl.DataFrame,
    lookup: dict[str, str],
    *,
    building_col: str = "building_name",
) -> pl.DataFrame:
    """Add ``site_id`` and ``mapping_status`` via KONE building name."""
    mapping_df = pl.DataFrame(
        {"building_name": list(lookup.keys()), "site_id": list(lookup.values())}
    )
    return (
        df.join(mapping_df, on=building_col, how="left")
        .with_columns(
            pl.when(pl.col("site_id").is_not_null())
            .then(pl.lit(MappingStatus.MAPPED.value))
            .otherwise(pl.lit(MappingStatus.UNMAPPED.value))
            .alias("mapping_status")
        )
    )


def enrich_with_site_id(
    df: pl.DataFrame,
    lookup: dict[str, ErpSiteMapping],
    *,
    customer_col: str = "customer_no",
    site_col: str = "customer_site_no",
) -> pl.DataFrame:
    """Add ``site_id`` and ``mapping_status`` via ERP composite key join."""
    mapping_df = pl.DataFrame(
        {
            "erp_key": [_erp_key(m.customer_no, m.customer_site_no) for m in lookup.values()],
            "site_id": [m.site_id for m in lookup.values()],
        }
    )
    return (
        df.with_columns(
            pl.concat_str(
                pl.col(customer_col).cast(pl.Utf8),
                pl.lit(":"),
                pl.col(site_col).cast(pl.Utf8),
            ).alias("_erp_key")
        )
        .join(mapping_df, left_on="_erp_key", right_on="erp_key", how="left")
        .with_columns(
            pl.when(pl.col("site_id").is_not_null())
            .then(pl.lit(MappingStatus.MAPPED.value))
            .otherwise(pl.lit(MappingStatus.UNMAPPED.value))
            .alias("mapping_status")
        )
        .drop("_erp_key")
    )
