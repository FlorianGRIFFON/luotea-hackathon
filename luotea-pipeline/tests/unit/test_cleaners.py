"""Unit tests for Silver cleaning utilities (Encoding & parsing edge cases)."""

from __future__ import annotations

from datetime import timezone
from pathlib import Path

import pytest

from pipeline.silver.cleaners import (
    EncodingError,
    detect_csv_encoding,
    detect_delimiter,
    normalize_null,
    parse_datetime,
    parse_finnish_bool,
    parse_int_nullable,
    read_erp_csv,
    strip_bom,
    validate_finnish_text,
)


class TestUtf8Bom:
    def test_strip_bom_from_text(self):
        assert strip_bom("\ufeffALERT_EVENT_ID") == "ALERT_EVENT_ID"

    def test_read_erp_csv_strips_bom_from_column_names(self, tmp_path: Path):
        csv_path = tmp_path / "alarms.csv"
        csv_path.write_bytes(b"\xef\xbb\xbfALERT_EVENT_ID,Priority\n5701,60\n")
        df = read_erp_csv(csv_path)
        assert "ALERT_EVENT_ID" in df.columns
        assert "\ufeffALERT_EVENT_ID" not in df.columns
        assert df.height == 1


class TestDelimiterDetection:
    def test_detect_semicolon(self):
        sample = "A;B;C\n1;2;3"
        assert detect_delimiter(sample) == ";"

    def test_detect_comma(self):
        sample = "A,B,C\n1,2,3"
        assert detect_delimiter(sample) == ","

    def test_read_work_orders_uses_semicolon(self, tmp_path: Path):
        csv_path = tmp_path / "work_orders.csv"
        csv_path.write_text(
            "WO_NO;WORK_INVOICABLE;WORK_ORDER_DESCRIPTION\n"
            "123;EPÄTOSI;Testi\n",
            encoding="cp1252",
        )
        df = read_erp_csv(csv_path)
        assert df.columns == ["WO_NO", "WORK_INVOICABLE", "WORK_ORDER_DESCRIPTION"]
        assert df.row(0, named=True)["WO_NO"] == "123"


class TestMojibakeDetection:
    def test_repair_double_encoded_utf8(self):
        repaired = validate_finnish_text("LentokentÃ¤nkatu")
        assert repaired == "Lentokentänkatu"

    def test_validate_finnish_text_accepts_proper_utf8(self):
        assert validate_finnish_text("Määräaikaishuollot") == "Määräaikaishuollot"

    def test_detect_encoding_prefers_cp1252_for_windows_file(self, tmp_path: Path):
        csv_path = tmp_path / "wo.csv"
        csv_path.write_text("desc\nMäärä\n", encoding="cp1252")
        assert detect_csv_encoding(csv_path) == "cp1252"


class TestEuropeanDates:
    def test_parse_european_datetime(self):
        dt = parse_datetime("2.12.2019 10:00")
        assert dt is not None
        assert dt.year == 2019 and dt.month == 12 and dt.day == 2
        assert dt.hour == 10 and dt.minute == 0

    def test_parse_iso_datetime_with_millis(self):
        dt = parse_datetime("2025-04-13 13:45:12.000")
        assert dt is not None
        assert dt.year == 2025 and dt.month == 4 and dt.day == 13

    def test_parse_datetime_returns_utc_convertible(self):
        dt = parse_datetime("2.12.2019 10:00")
        from pipeline.silver.cleaners import local_to_utc

        utc = local_to_utc(dt)
        assert utc.tzinfo == timezone.utc


class TestNullLiterals:
    def test_normalize_null_string(self):
        assert normalize_null("NULL") is None
        assert normalize_null("") is None
        assert normalize_null("null") is None
        assert normalize_null("None") is None

    def test_parse_int_nullable_treats_null_literal_as_none(self):
        assert parse_int_nullable("NULL") is None
        assert parse_int_nullable("5701") == 5701

    def test_workorder_no_null_literal_in_alarms_fixture(self, tmp_path: Path):
        csv_path = tmp_path / "alarms.csv"
        csv_path.write_text(
            "ALERT_EVENT_ID,WORKORDER_NO,Priority\n"
            "1,NULL,60\n"
            "2,12345,60\n",
            encoding="utf-8",
        )
        df = read_erp_csv(csv_path)
        assert normalize_null(df.row(0, named=True)["WORKORDER_NO"]) is None
        assert parse_int_nullable(df.row(0, named=True)["WORKORDER_NO"]) is None
        assert parse_int_nullable(df.row(1, named=True)["WORKORDER_NO"]) == 12345


class TestFinnishBooleans:
    def test_tosi_epatosi(self):
        assert parse_finnish_bool("TOSI") is True
        assert parse_finnish_bool("EPÄTOSI") is False

    def test_null_bool(self):
        assert parse_finnish_bool("NULL") is None
        assert parse_finnish_bool(None) is None

    def test_invalid_bool_raises(self):
        with pytest.raises(ValueError):
            parse_finnish_bool("maybe")
