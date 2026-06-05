"""Shared null/type/timezone/BOM cleaning utilities for Silver transforms."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import polars as pl

from pipeline.config import DEFAULT_TIMEZONE

NULL_LITERALS: frozenset[str] = frozenset({"NULL", "null", "None", "none", ""})

# Common UTF-8 misread as Latin-1/CP1252 (e.g. "MÃ¤Ã¤rÃ¤" instead of "Määrä")
MOJIBAKE_PATTERN = re.compile(r"Ã[\x80-\xBF]|â€|ï¿½")

ERP_DATETIME_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y %H:%M:%S.%f",
    "%d.%m.%Y %H:%M:%S",
)

FINNISH_BOOL_TRUE = frozenset({"TOSI", "true", "True", "1", "yes", "YES"})
FINNISH_BOOL_FALSE = frozenset({"EPÄTOSI", "EPATOSI", "false", "False", "0", "no", "NO"})


class EncodingError(ValueError):
    """Raised when source text cannot be decoded cleanly to UTF-8."""


def strip_bom(text: str) -> str:
    """Remove UTF-8 BOM if present."""
    return text.lstrip("\ufeff")


def normalize_null(value: Any) -> Any:
    """Map null-like literals to Python ``None``."""
    if value is None:
        return None
    if isinstance(value, float) and value != value:  # NaN
        return None
    if isinstance(value, str):
        stripped = strip_bom(value.strip())
        if stripped in NULL_LITERALS:
            return None
        return stripped
    return value


def detect_delimiter(sample: str) -> str:
    """Auto-detect CSV delimiter from a text sample (semicolon vs comma)."""
    header_line = sample.split("\n", 1)[0]
    semicolons = header_line.count(";")
    commas = header_line.count(",")
    return ";" if semicolons > commas else ","


def detect_csv_encoding(path: Path) -> str:
    """Detect CSV encoding; prefer UTF-8 BOM, fall back to cp1252 for ERP exports."""
    raw = path.read_bytes()[:65536]
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if MOJIBAKE_PATTERN.search(text[:4096]):
            continue
        if encoding == "utf-8":
            try:
                path.read_text(encoding="utf-8")
                return "utf-8"
            except UnicodeDecodeError:
                continue
        return encoding
    raise EncodingError(
        f"Cannot decode {path} as UTF-8 or cp1252 without mojibake. "
        "Re-export the file in UTF-8 or Windows-1252."
    )


# UTF-8 misinterpreted as Latin-1/CP1252 (common in mixed ERP exports)
MOJIBAKE_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("Ã¤", "ä"),
    ("Ã„", "Ä"),
    ("Ã¶", "ö"),
    ("Ã–", "Ö"),
    ("Ã¥", "å"),
    ("Ã…", "Å"),
    ("Ã©", "é"),
    ("Ã¼", "ü"),
)


def repair_mojibake(text: str) -> str:
    """Repair common UTF-8-as-Latin-1 sequences without breaking valid cp1252 text."""
    if not text or not MOJIBAKE_PATTERN.search(text):
        return text
    repaired = text
    for bad, good in MOJIBAKE_REPLACEMENTS:
        repaired = repaired.replace(bad, good)
    if MOJIBAKE_PATTERN.search(repaired):
        raise EncodingError(f"Unrecoverable mojibake: {repaired[:80]!r}")
    return repaired


def validate_finnish_text(text: str, *, context: str = "") -> str:
    """Fail loudly on unrecoverable mojibake; repair common double-encoding."""
    if not text:
        return text
    if MOJIBAKE_PATTERN.search(text):
        text = repair_mojibake(text)
    return text


def parse_finnish_bool(value: Any) -> bool | None:
    """Parse Finnish ERP booleans (TOSI/EPÄTOSI) and common variants."""
    normalized = normalize_null(value)
    if normalized is None:
        return None
    token = str(normalized).strip()
    if token in FINNISH_BOOL_TRUE:
        return True
    if token in FINNISH_BOOL_FALSE:
        return False
    raise ValueError(f"Unrecognized boolean value: {value!r}")


def parse_int_nullable(value: Any) -> int | None:
    """Parse integer column, treating null literals as None."""
    normalized = normalize_null(value)
    if normalized is None:
        return None
    return int(float(str(normalized)))


def parse_float_nullable(value: Any) -> float | None:
    """Parse float column, treating null literals as None."""
    normalized = normalize_null(value)
    if normalized is None:
        return None
    token = str(normalized).replace(",", ".")
    return float(token)


def parse_finished_days(value: Any) -> float | None:
    """Parse ERP ``WORK_FINISHED_DAYS`` (e.g. ``2.16.00`` → 2.16 days)."""
    normalized = normalize_null(value)
    if normalized is None:
        return None
    parts = str(normalized).split(".")
    if len(parts) >= 2 and parts[0].isdigit():
        return float(f"{parts[0]}.{parts[1]}")
    return float(str(normalized).replace(",", "."))


def parse_datetime(value: Any, tz_name: str = DEFAULT_TIMEZONE) -> datetime | None:
    """Parse ERP datetime strings (ISO or European ``d.M.yyyy H:mm``)."""
    normalized = normalize_null(value)
    if normalized is None:
        return None
    text = str(normalized).strip()
    for fmt in ERP_DATETIME_FORMATS:
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=ZoneInfo(tz_name))
        except ValueError:
            continue
    raise ValueError(f"Unparseable datetime: {value!r}")


def parse_date(value: Any) -> date | None:
    """Parse date from ISO or European date/datetime string."""
    normalized = normalize_null(value)
    if normalized is None:
        return None
    text = str(normalized).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    dt = parse_datetime(text)
    return dt.date() if dt else None


def local_to_utc(dt: datetime) -> datetime:
    """Convert timezone-aware local datetime to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(DEFAULT_TIMEZONE))
    return dt.astimezone(timezone.utc)


def read_erp_csv(path: Path, *, encoding: str | None = None, delimiter: str | None = None) -> pl.DataFrame:
    """Read an ERP CSV with BOM strip, encoding detection, and delimiter auto-detect."""
    import csv

    encoding = encoding or detect_csv_encoding(path)
    sample = path.read_text(encoding=encoding)[:8192]
    sep = delimiter or detect_delimiter(sample)

    if encoding in ("utf-8", "utf-8-sig"):
        df = pl.read_csv(
            path,
            separator=sep,
            infer_schema_length=10_000,
            null_values=list(NULL_LITERALS),
            try_parse_dates=False,
        )
    else:
        with path.open(encoding=encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=sep)
            header = [strip_bom(h) for h in next(reader)]
            data = list(reader)
        df = pl.DataFrame(data, schema=header, orient="row")

    rename = {c: strip_bom(c) for c in df.columns if c != strip_bom(c)}
    return df.rename(rename) if rename else df


def strip_string_columns(expr: pl.Expr) -> pl.Expr:
    """Strip whitespace from a string expression."""
    return expr.str.strip_chars()


def null_rate(df: pl.DataFrame, column: str) -> float:
    """Fraction of null values in a column (0.0–1.0)."""
    if column not in df.columns or df.height == 0:
        return 0.0
    return df[column].null_count() / df.height


def mapping_hit_rate(df: pl.DataFrame, site_column: str = "site_id") -> float:
    """Fraction of rows with a non-null canonical site_id."""
    if site_column not in df.columns or df.height == 0:
        return 0.0
    return df.filter(pl.col(site_column).is_not_null()).height / df.height
