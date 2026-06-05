"""Room/desk utilization wide CSV connector."""

from __future__ import annotations

from pathlib import Path

from pipeline.bronze.connectors.base import BaseConnector, count_csv_data_rows
from pipeline.config import HACKATHON_DATA_ROOT


class UtilizationConnector(BaseConnector):
    source_name = "utilization"

    def discover_files(self) -> list[Path]:
        pattern = "**/Room_Utilization_*.csv"
        return sorted(HACKATHON_DATA_ROOT.glob(pattern))

    def count_rows(self, path: Path) -> int:
        return count_csv_data_rows(path)

    @property
    def file_format(self) -> str:
        return "csv"
