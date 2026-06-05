"""Smartti Pulse JSON connector."""

from __future__ import annotations

from pathlib import Path

from pipeline.bronze.connectors.base import BaseConnector, count_smartti_property_rows, resolve_hackathon_path
from pipeline.contracts import load_contract


class SmarttiPulseConnector(BaseConnector):
    source_name = "smartti_pulse"

    def discover_files(self) -> list[Path]:
        contract = load_contract(self.source_name)
        return [resolve_hackathon_path(rel) for rel in contract["source_files"]]

    def count_rows(self, path: Path) -> int:
        return count_smartti_property_rows(path)

    @property
    def file_format(self) -> str:
        return "json"
