"""KONE occupancy JSON connector."""

from __future__ import annotations

from pathlib import Path

from pipeline.bronze.connectors.base import BaseConnector, count_json_array_rows
from pipeline.config import HACKATHON_DATA_ROOT


class KoneOccupancyConnector(BaseConnector):
    source_name = "kone_occupancy"

    def discover_files(self) -> list[Path]:
        kone_dir = HACKATHON_DATA_ROOT / "Smartti" / "kone"
        files = sorted(
            p
            for p in kone_dir.glob("*.json")
            if p.is_file() and "Zone.Identifier" not in p.name
        )
        return files

    def count_rows(self, path: Path) -> int:
        return count_json_array_rows(path)

    @property
    def file_format(self) -> str:
        return "json"
