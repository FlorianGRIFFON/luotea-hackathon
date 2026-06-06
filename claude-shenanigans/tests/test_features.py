"""The leakage guarantee and time-split integrity are the credibility of the whole model."""
import polars as pl
import pytest

from src.config import SLA_LEAKAGE_COLS, SLA_TARGET
from src.data.loader import load_daily_signals, load_work_orders
from src.features.work_orders import (
    FEATURE_COLUMNS,
    build_sla_dataset,
    split_xy,
    time_split,
)
from src.features.reliability_index import compute_reliability_index


@pytest.fixture(scope="module")
def dataset():
    return build_sla_dataset(load_work_orders(), load_daily_signals())


def test_no_post_completion_feature_leaks(dataset):
    for col in SLA_LEAKAGE_COLS:
        if col == SLA_TARGET:
            continue
        assert col not in FEATURE_COLUMNS, f"{col} is a leakage column"
        assert col not in dataset.columns, f"{col} leaked into the feature frame"


def test_dataset_has_all_features_and_target(dataset):
    for c in FEATURE_COLUMNS + [SLA_TARGET]:
        assert c in dataset.columns


def test_time_split_is_chronological_and_disjoint(dataset):
    train, test = time_split(dataset, test_fraction=0.2)
    assert train.height + test.height == dataset.height
    # every training row is strictly before every test row in time
    assert train["work_started_at_utc"].max() <= test["work_started_at_utc"].min()
    # no work-order appears in both splits
    overlap = set(train["wo_no"].to_list()) & set(test["wo_no"].to_list())
    assert not overlap


def test_split_xy_shapes(dataset):
    train, _ = time_split(dataset)
    X, y = split_xy(train)
    assert X.shape[0] == len(y) == train.height
    assert list(X.columns) == FEATURE_COLUMNS


def test_reliability_index_bounded_and_cross_site():
    rri = compute_reliability_index(load_daily_signals())
    vals = rri["reliability_risk_index"].drop_nulls()
    assert vals.min() >= 0 and vals.max() <= 100
    # index is produced for both an ERP site and an IoT site
    scored = rri.filter(pl.col("reliability_risk_index").is_not_null())["site_id"].unique().to_list()
    assert "site_valmet_l11" in scored
    assert "site_aurora" in scored
