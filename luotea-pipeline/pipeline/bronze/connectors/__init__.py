"""Bronze connectors — one module per source family."""

from __future__ import annotations

from pipeline.bronze.connectors.alarms import AlarmsConnector
from pipeline.bronze.connectors.kone_occupancy import KoneOccupancyConnector
from pipeline.bronze.connectors.maintenance_plans import MaintenancePlansConnector
from pipeline.bronze.connectors.smartti_pulse import SmarttiPulseConnector
from pipeline.bronze.connectors.utilization import UtilizationConnector
from pipeline.bronze.connectors.work_orders import WorkOrdersConnector
from pipeline.bronze.ingest import IngestResult

SOURCE_ALIASES: dict[str, str] = {
    "smartti": "smartti_pulse",
    "kone": "kone_occupancy",
    "maintenance": "maintenance_plans",
}

CONNECTORS: dict[str, type] = {
    "alarms": AlarmsConnector,
    "work_orders": WorkOrdersConnector,
    "maintenance_plans": MaintenancePlansConnector,
    "smartti_pulse": SmarttiPulseConnector,
    "kone_occupancy": KoneOccupancyConnector,
    "utilization": UtilizationConnector,
}

ALL_SOURCES = list(CONNECTORS.keys())


def resolve_source_name(source: str) -> str:
    key = source.strip().lower()
    return SOURCE_ALIASES.get(key, key)


def get_connector(source: str):
    name = resolve_source_name(source)
    cls = CONNECTORS.get(name)
    if cls is None:
        known = sorted(set(ALL_SOURCES) | set(SOURCE_ALIASES))
        raise KeyError(f"Unknown source {source!r}. Known: {known}")
    return cls()


def ingest_source(source: str, ingest_date: str) -> IngestResult:
    """Run Bronze ingest for one source family."""
    return get_connector(source).ingest(ingest_date)


def ingest_all(ingest_date: str) -> list[IngestResult]:
    """Run Bronze ingest for every source family."""
    return [ingest_source(name, ingest_date) for name in ALL_SOURCES]


__all__ = [
    "ALL_SOURCES",
    "CONNECTORS",
    "SOURCE_ALIASES",
    "get_connector",
    "ingest_all",
    "ingest_source",
]
