"""Base connector and shared row-count helpers."""

from __future__ import annotations

import csv
import json
from abc import ABC, abstractmethod
from pathlib import Path

from pipeline.bronze.ingest import IngestResult, ingest_paths
from pipeline.config import HACKATHON_DATA_ROOT, REPO_ROOT, SCHEMA_VERSION
from pipeline.contracts import load_contract


def resolve_hackathon_path(relative: str) -> Path:
    """Resolve a path relative to repo root (``Luotea-Hackathon-2026/...``)."""
    return REPO_ROOT / relative


def _detect_csv_encoding(path: Path) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with path.open(encoding=encoding) as f:
                f.read(65536)
            return encoding
        except UnicodeDecodeError:
            continue
    return "utf-8-sig"


def count_csv_data_rows(path: Path, *, delimiter: str | None = None) -> int:
    """Count CSV data rows (excluding header)."""
    encoding = _detect_csv_encoding(path)
    with path.open("rb") as raw:
        sample = raw.read(8192)
    text_sample = sample.decode(encoding, errors="replace")
    if delimiter is None:
        delimiter = ";" if text_sample.count(";") > text_sample.count(",") else ","
    count = 0
    with path.open(encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        next(reader, None)  # header
        for _ in reader:
            count += 1
    return count


def count_json_array_rows(path: Path) -> int:
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array in {path}, got {type(data).__name__}")
    return len(data)


def count_smartti_property_rows(path: Path) -> int:
    """Count logical records: reading data points + incidents (+ nodes)."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if path.name == "metadata.json":
        return len(data.get("properties", []))

    prop = data.get("property", {})
    reading_rows = 0
    for block in prop.get("readings", {}).values():
        reading_rows += len(block.get("data", []))
    incident_rows = len(prop.get("incidents", []))
    node_rows = len(prop.get("nodes", []))
    child_rows = 0
    for child in prop.get("children", []):
        for block in child.get("readings", {}).values():
            child_rows += len(block.get("data", []))
        child_rows += len(child.get("incidents", []))
    return reading_rows + incident_rows + node_rows + child_rows


class BaseConnector(ABC):
    """One connector per source family."""

    source_name: str

    @abstractmethod
    def discover_files(self) -> list[Path]:
        ...

    @abstractmethod
    def count_rows(self, path: Path) -> int | None:
        ...

    @property
    @abstractmethod
    def file_format(self) -> str:
        ...

    def source_system(self) -> str:
        contract = load_contract(self.source_name)
        return contract["source_system"]

    def ingest(self, ingest_date: str) -> IngestResult:
        paths = self.discover_files()
        if not paths:
            raise FileNotFoundError(f"No source files found for {self.source_name}")
        return ingest_paths(
            paths,
            source_system=self.source_system(),
            source_name=self.source_name,
            ingest_date=ingest_date,
            count_rows_fn=self.count_rows,
            file_format=self.file_format,
            schema_version=SCHEMA_VERSION,
        )


class SingleCsvConnector(BaseConnector):
    """ERP CSV export with a single file defined in the contract."""

    def discover_files(self) -> list[Path]:
        contract = load_contract(self.source_name)
        return [resolve_hackathon_path(contract["source_file"])]

    def count_rows(self, path: Path) -> int:
        return count_csv_data_rows(path)

    @property
    def file_format(self) -> str:
        return "csv"
