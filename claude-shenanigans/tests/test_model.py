"""End-to-end: the model must beat the rules baseline on a held-out future period."""
import numpy as np
import pytest

from src.config import PRECISION_AT_K
from src.data.loader import load_daily_signals, load_work_orders
from src.features.work_orders import build_sla_dataset, split_xy, time_split
from src.models.sla_risk import baseline_priority_rate, build_model, evaluate


@pytest.fixture(scope="module")
def trained():
    ds = build_sla_dataset(load_work_orders(), load_daily_signals())
    train, test = time_split(ds)
    X_train, y_train = split_xy(train)
    X_test, y_test = split_xy(test)
    pipe = build_model().fit(X_train, y_train)
    scores = pipe.predict_proba(X_test)[:, 1]
    base = baseline_priority_rate(X_train, y_train, X_test)
    return dict(y_test=y_test, scores=scores, base=base, X_train=X_train, y_train=y_train)


def test_model_beats_random_and_baseline(trained):
    m = evaluate(trained["y_test"], trained["scores"], PRECISION_AT_K)
    b = evaluate(trained["y_test"], trained["base"], PRECISION_AT_K)
    assert m["roc_auc"] > 0.62, f"model AUC too low: {m['roc_auc']:.3f}"
    assert m["roc_auc"] > b["roc_auc"], "model must beat the priority-rate rules baseline"


def test_top_decile_precision_strong(trained):
    m = evaluate(trained["y_test"], trained["scores"], PRECISION_AT_K)
    p10 = next(p for p in m["precision_at_k"] if p["k_frac"] == 0.10)
    # acting on the riskiest 10% should be far better than the base rate
    assert p10["precision"] > m["base_rate"] + 0.15


def test_scores_are_probabilities(trained):
    s = trained["scores"]
    assert s.min() >= 0.0 and s.max() <= 1.0
