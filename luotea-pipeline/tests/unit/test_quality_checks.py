"""Unit tests for Silver/Gold quality validators."""

from __future__ import annotations

import polars as pl
import pytest

from pipeline.quality.checks import (
    check_enum,
    check_mapping_hit_rate,
    check_no_literal_null_strings,
    check_occupancy_value_range,
    check_pii_scan,
    check_primary_key_unique,
    check_range,
    check_referential_integrity,
    check_required_columns,
    check_row_count_tolerance,
    check_unique,
)


def test_unique_pass():
    df = pl.DataFrame({"id": [1, 2, 3]})
    result = check_unique(df, layer="silver", table="t", columns="id")
    assert result.passed
    assert result.quarantine_path is None


def test_unique_fail_quarantines(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"id": [1, 1, 2]})
    result = check_unique(df, layer="silver", table="fact_alarm", columns="id")
    assert not result.passed
    assert result.quarantine_path is not None
    assert result.quarantine_path.exists()


def test_enum_invalid_priority(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"priority": [1, 99, 42]})
    result = check_enum(
        df,
        layer="silver",
        table="fact_alarm",
        column="priority",
        allowed={1, 13, 50, 60, 77, 99},
    )
    assert not result.passed
    assert result.failed_count == 1


def test_range_utilization_pct(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"utilization_pct": [0.0, 50.0, 101.0]})
    result = check_range(
        df,
        layer="silver",
        table="fact_utilization",
        column="utilization_pct",
        low=0.0,
        high=100.0,
    )
    assert not result.passed
    assert result.failed_count == 1


def test_mapping_hit_rate_below_threshold(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"site_id": ["site_a", None, None, "site_b"]})
    result = check_mapping_hit_rate(
        df, layer="silver", table="fact_alarm", min_rate=0.99
    )
    assert not result.passed


def test_referential_integrity_orphans(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"site_id": ["site_a", "site_unknown"]})
    ref = pl.DataFrame({"site_id": ["site_a", "site_b"]})
    result = check_referential_integrity(
        df,
        layer="gold",
        table="site_daily_signals",
        fk_column="site_id",
        ref_table="dim_site",
        ref_df=ref,
    )
    assert not result.passed
    assert result.failed_count == 1


def test_required_columns_nulls(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"site_id": ["a", None], "signal_date": ["2026-01-01", "2026-01-02"]})
    result = check_required_columns(
        df, layer="gold", table="site_daily_signals", columns=["site_id", "signal_date"]
    )
    assert not result.passed


def test_pii_scan_detects_email(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"title": ["Normal event", "Contact user@example.com please"]})
    result = check_pii_scan(df, layer="gold", table="event_timeline")
    assert not result.passed


def test_pii_scan_allows_anonymized_tokens():
    df = pl.DataFrame({"title": ["Work order for [NAME]", "Alarm at building A"]})
    result = check_pii_scan(df, layer="gold", table="event_timeline")
    assert result.passed


def test_occupancy_range_by_value_type():
    df = pl.DataFrame(
        {
            "occupancy_value": [5.0, 11.0, 50.0, -1.0],
            "value_type": ["normalized", "normalized", "raw_count", "raw_count"],
        }
    )
    result = check_occupancy_value_range(df, layer="silver", table="fact_occupancy")
    assert not result.passed
    assert result.failed_count == 2  # normalized 11, raw -1


def test_row_count_within_tolerance():
    df = pl.DataFrame({"id": range(18702)})
    result = check_row_count_tolerance(
        df,
        layer="silver",
        table="fact_alarm",
        expected_rows=18702,
        tolerance_pct=0.005,
    )
    assert result.passed
    assert result.actual == 18702


def test_row_count_outside_tolerance():
    df = pl.DataFrame({"id": range(100)})
    result = check_row_count_tolerance(
        df,
        layer="silver",
        table="fact_alarm",
        expected_rows=18702,
        tolerance_pct=0.005,
    )
    assert not result.passed


def test_primary_key_unique():
    df = pl.DataFrame({"alert_event_id": [1, 2, 3]})
    result = check_primary_key_unique(
        df,
        layer="silver",
        table="fact_alarm",
        column="alert_event_id",
        source_pk="ALERT_EVENT_ID",
    )
    assert result.passed
    assert result.check_id == "pk_unique_fact_alarm_alert_event_id"


def test_no_literal_null_strings_detects(tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.quality.checks.QUARANTINE_DIR", tmp_path)
    df = pl.DataFrame({"pm_no": ["PM1", "NULL", "PM2"], "note": ["ok", "bad", "ok"]})
    result = check_no_literal_null_strings(df, layer="silver", table="fact_work_order")
    assert not result.passed
    assert result.failed_count == 1
