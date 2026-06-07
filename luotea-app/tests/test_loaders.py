"""Smoke tests: the read-only Gold/Silver loaders return the data we expect."""
import polars as pl
import pytest

from src.data.loader import (
    list_sites,
    load_daily_signals,
    load_event_timeline,
    load_work_orders,
)


def test_daily_signals_grain_and_columns():
    df = load_daily_signals()
    assert df.height == 10_350, "Gold daily grain changed — expected 10,350 site×day rows"
    for c in ("site_id", "signal_date", "open_work_orders", "alarm_count", "electricity_kwh"):
        assert c in df.columns
    # primary key is unique
    assert df.select(["site_id", "signal_date"]).n_unique() == df.height


def test_demo_sites_present():
    sites = list_sites()
    assert "site_valmet_l11" in sites
    assert "site_aurora" in sites


def test_work_orders_have_label_and_features():
    wo = load_work_orders()
    assert wo.height == 44_265
    assert wo["is_sla_violation"].null_count() == 0
    # creation-time fields we rely on exist
    for c in ("work_started_at_utc", "work_type_eng", "contract_type", "work_order_type"):
        assert c in wo.columns


def test_event_timeline_loads():
    ev = load_event_timeline("site_aurora")
    assert ev.height > 0
    assert ev["timestamp_utc"].is_sorted()
