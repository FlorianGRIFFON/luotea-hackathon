"""The leakage guarantee and time-split integrity are the credibility of the whole model."""
import numpy as np
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
from src.features.reliability_index import compute_breach_load, compute_reliability_index
from src.models.sla_risk import build_model


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


def test_reliability_index_bounded_and_cross_site(dataset):
    daily = load_daily_signals()
    # ERP sites get their maintenance component from the model → train + score (realistic path)
    train, _ = time_split(dataset)
    X, y = split_xy(train)
    model = type("M", (), {"pipeline": build_model().fit(X, y)})()
    model.predict_proba = lambda Xp, p=model.pipeline: p.predict_proba(Xp)[:, 1]
    breach_load = compute_breach_load(model, load_work_orders(), daily)

    rri = compute_reliability_index(daily, breach_load)
    vals = rri["reliability_risk_index"].drop_nulls().to_numpy()
    assert vals.min() >= 0 and vals.max() <= 100
    assert not np.isnan(vals).any(), "index must use real nulls, never float NaN"
    # produced for both an ERP site (model-driven) and an IoT site (energy-driven)
    scored = rri.filter(pl.col("reliability_risk_index").is_not_null())["site_id"].unique().to_list()
    assert "site_valmet_l11" in scored
    assert "site_aurora" in scored


def test_reliability_index_persists_not_mean_reverting(dataset):
    """The index must reflect a site's true level, not snap back to 50 every day."""
    train, _ = time_split(dataset)
    X, y = split_xy(train)
    pipe = build_model().fit(X, y)
    model = type("M", (), {"predict_proba": lambda self, Xp: pipe.predict_proba(Xp)[:, 1]})()
    rri = compute_reliability_index(load_daily_signals(),
                                    compute_breach_load(model, load_work_orders(), load_daily_signals()))
    means = (rri.filter(pl.col("reliability_risk_index").is_not_null())
             .group_by("site_id").agg(pl.col("reliability_risk_index").mean()))
    site_means = means["reliability_risk_index"].to_list()
    # sites must NOT all collapse to ~50 — calm IoT sites should sit clearly below busy ERP sites
    assert max(site_means) - min(site_means) > 15
