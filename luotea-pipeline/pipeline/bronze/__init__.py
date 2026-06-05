"""Bronze layer — immutable raw landing."""

from pipeline.bronze.ingest import IngestResult, ingest_file, ingest_paths
from pipeline.bronze.connectors import ALL_SOURCES, ingest_all, ingest_source

__all__ = [
    "ALL_SOURCES",
    "IngestResult",
    "ingest_all",
    "ingest_file",
    "ingest_paths",
    "ingest_source",
]
