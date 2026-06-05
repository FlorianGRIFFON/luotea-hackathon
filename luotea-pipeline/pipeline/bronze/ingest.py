"""Generic Bronze landing: immutable file copies with metadata sidecars."""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.config import BRONZE_DIR, SCHEMA_VERSION

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestedFile:
    """One raw file landed in Bronze."""

    source_path: Path
    dest_path: Path
    metadata_path: Path
    row_count: int | None
    byte_size: int
    format: str


@dataclass
class IngestResult:
    """Outcome of ingesting one source family."""

    source_name: str
    source_system: str
    ingest_date: str
    output_dir: Path
    files: list[IngestedFile] = field(default_factory=list)

    @property
    def total_row_count(self) -> int | None:
        counts = [f.row_count for f in self.files if f.row_count is not None]
        return sum(counts) if counts else None


def bronze_partition_dir(source_system: str, ingest_date: date | str) -> Path:
    """Return ``bronze/{source_system}/{ingest_date}/``."""
    if isinstance(ingest_date, date):
        ingest_date = ingest_date.isoformat()
    return BRONZE_DIR / source_system / ingest_date


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _file_export_date(path: Path) -> str | None:
    """Best-effort export date from filename or mtime."""
    stem = path.stem
    for part in stem.split("_"):
        if len(part) == 10 and part[4] == "-" and part[7] == "-":
            return part
    for part in stem.split("_"):
        if len(part) == 8 and part.isdigit():
            # e.g. 20260527
            return f"{part[0:4]}-{part[4:6]}-{part[6:8]}"
    mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return mtime.date().isoformat()


def write_metadata_sidecar(
    metadata_path: Path,
    *,
    source_system: str,
    source_name: str,
    source_path: Path,
    dest_path: Path,
    ingest_date: str,
    schema_version: str,
    row_count: int | None,
    file_format: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write ``{filename}.meta.json`` sidecar next to the landed copy."""
    payload: dict[str, Any] = {
        "ingested_at": _utc_now_iso(),
        "source_system": source_system,
        "source_name": source_name,
        "source_file": str(source_path.resolve()),
        "dest_file": dest_path.name,
        "schema_version": schema_version,
        "export_date": _file_export_date(source_path),
        "ingest_date": ingest_date,
        "byte_size": dest_path.stat().st_size,
        "row_count": row_count,
        "format": file_format,
    }
    if extra:
        payload.update(extra)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def ingest_file(
    source_path: Path,
    output_dir: Path,
    *,
    source_system: str,
    source_name: str,
    ingest_date: str,
    row_count: int | None,
    file_format: str,
    schema_version: str = SCHEMA_VERSION,
    extra_metadata: dict[str, Any] | None = None,
) -> IngestedFile:
    """Copy one source file unchanged and write its metadata sidecar."""
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    dest_path = output_dir / source_path.name
    metadata_path = output_dir / f"{source_path.name}.meta.json"

    shutil.copy2(source_path, dest_path)
    write_metadata_sidecar(
        metadata_path,
        source_system=source_system,
        source_name=source_name,
        source_path=source_path,
        dest_path=dest_path,
        ingest_date=ingest_date,
        schema_version=schema_version,
        row_count=row_count,
        file_format=file_format,
        extra=extra_metadata,
    )
    logger.info(
        "Landed %s → %s (%s rows)",
        source_path.name,
        dest_path,
        row_count if row_count is not None else "n/a",
    )
    return IngestedFile(
        source_path=source_path,
        dest_path=dest_path,
        metadata_path=metadata_path,
        row_count=row_count,
        byte_size=dest_path.stat().st_size,
        format=file_format,
    )


def write_partition_manifest(result: IngestResult) -> Path:
    """Write ``_manifest.json`` summarizing all files in a Bronze partition."""
    manifest_path = result.output_dir / "_manifest.json"
    payload = {
        "ingested_at": _utc_now_iso(),
        "source_name": result.source_name,
        "source_system": result.source_system,
        "ingest_date": result.ingest_date,
        "schema_version": SCHEMA_VERSION,
        "file_count": len(result.files),
        "total_row_count": result.total_row_count,
        "files": [
            {
                "dest_file": f.dest_path.name,
                "metadata_file": f.metadata_path.name,
                "row_count": f.row_count,
                "byte_size": f.byte_size,
                "format": f.format,
                "source_file": str(f.source_path.resolve()),
            }
            for f in result.files
        ],
    }
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest_path


def ingest_paths(
    paths: list[Path],
    *,
    source_system: str,
    source_name: str,
    ingest_date: str,
    count_rows_fn,
    file_format: str,
    schema_version: str = SCHEMA_VERSION,
) -> IngestResult:
    """Land multiple files into one Bronze partition."""
    output_dir = bronze_partition_dir(source_system, ingest_date)
    result = IngestResult(
        source_name=source_name,
        source_system=source_system,
        ingest_date=ingest_date,
        output_dir=output_dir,
    )
    for path in paths:
        row_count = count_rows_fn(path)
        ingested = ingest_file(
            path,
            output_dir,
            source_system=source_system,
            source_name=source_name,
            ingest_date=ingest_date,
            row_count=row_count,
            file_format=file_format,
            schema_version=schema_version,
        )
        result.files.append(ingested)
    write_partition_manifest(result)
    return result
