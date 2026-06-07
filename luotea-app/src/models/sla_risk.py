"""
SLA-breach risk model — the hero ML component.

Task: binary classification of `is_sla_violation` for a maintenance work order,
using only creation-time features (see src/features/work_orders.py).

Model:    OneHotEncoder(categoricals) + HistGradientBoostingClassifier
          (gradient-boosted trees; handles NaN natively, fast, strong on tabular FM data).
Baselines: (1) majority class, (2) historical breach-rate by priority (a "rules" baseline
          a facility team could run in a spreadsheet), (3) logistic regression.

Everything is evaluated on a **chronological hold-out** (future period), never on shuffled data.
"""
from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from src.config import MODELS_DIR, RANDOM_SEED, SLA_CAT_FEATURES, SLA_NUM_FEATURES


def build_model() -> Pipeline:
    """OHE + gradient-boosted trees."""
    pre = ColumnTransformer(
        transformers=[
            ("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20, sparse_output=False),
             SLA_CAT_FEATURES),
        ],
        remainder="passthrough",  # numeric features pass straight through (HistGBT handles NaN)
    )
    clf = HistGradientBoostingClassifier(
        learning_rate=0.08,
        max_iter=400,
        max_depth=6,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=RANDOM_SEED,
    )
    return Pipeline([("pre", pre), ("clf", clf)])


# --------------------------------------------------------------------------- baselines
def baseline_majority(y_train: np.ndarray, n_test: int) -> np.ndarray:
    """Predict the training-set majority class probability for everyone."""
    p = float(y_train.mean())
    return np.full(n_test, p)


def baseline_priority_rate(X_train: pd.DataFrame, y_train: np.ndarray, X_test: pd.DataFrame) -> np.ndarray:
    """
    Rules baseline: probability = historical breach rate for this work order's priority.
    This is what a competent ops team could already do by hand — the model must beat it.
    """
    df = pd.DataFrame({"priority_id_str": X_train["priority_id_str"].values, "y": y_train})
    rate = df.groupby("priority_id_str")["y"].mean()
    global_rate = float(y_train.mean())
    return X_test["priority_id_str"].map(rate).fillna(global_rate).to_numpy()


def baseline_logreg(X_train: pd.DataFrame, y_train: np.ndarray, X_test: pd.DataFrame) -> np.ndarray:
    pre = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=20), SLA_CAT_FEATURES)],
        remainder="passthrough",
    )
    pipe = Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=1000))])
    # logreg cannot ingest NaN → fill numeric NaNs with train medians
    Xtr, Xte = X_train.copy(), X_test.copy()
    for c in SLA_NUM_FEATURES:
        med = Xtr[c].median()
        Xtr[c] = Xtr[c].fillna(med)
        Xte[c] = Xte[c].fillna(med)
    pipe.fit(Xtr, y_train)
    return pipe.predict_proba(Xte)[:, 1]


# --------------------------------------------------------------------------- evaluation
def precision_at_k(y_true: np.ndarray, scores: np.ndarray, k_frac: float) -> dict:
    """
    Among the top-k_frac highest-risk work orders, what share actually breached?
    Mirrors a capacity-limited dispatch team that can only act on the riskiest slice.
    """
    n = len(scores)
    k = max(1, int(round(n * k_frac)))
    order = np.argsort(scores)[::-1][:k]
    flagged = y_true[order]
    total_breaches = int(y_true.sum())
    return {
        "k_frac": k_frac,
        "k": k,
        "precision": float(flagged.mean()),
        "recall": float(flagged.sum() / total_breaches) if total_breaches else 0.0,
        "breaches_caught": int(flagged.sum()),
    }


def evaluate(y_true: np.ndarray, scores: np.ndarray, k_fracs: list[float]) -> dict:
    preds = (scores >= 0.5).astype(int)
    return {
        "roc_auc": float(roc_auc_score(y_true, scores)),
        "pr_auc": float(average_precision_score(y_true, scores)),
        "f1": float(f1_score(y_true, preds)),
        "precision": float(precision_score(y_true, preds, zero_division=0)),
        "recall": float(recall_score(y_true, preds, zero_division=0)),
        "brier": float(brier_score_loss(y_true, scores)),
        "base_rate": float(y_true.mean()),
        "precision_at_k": [precision_at_k(y_true, scores, kf) for kf in k_fracs],
    }


def calibration_table(y_true: np.ndarray, scores: np.ndarray, n_bins: int = 10) -> list[dict]:
    """Reliability-diagram data: predicted prob vs observed breach rate per bin."""
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(scores, bins) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if m.sum() == 0:
            continue
        rows.append({
            "bin_mid": float((bins[b] + bins[b + 1]) / 2),
            "mean_pred": float(scores[m].mean()),
            "observed": float(y_true[m].mean()),
            "count": int(m.sum()),
        })
    return rows


# --------------------------------------------------------------------------- persistence
@dataclass
class SLARiskModel:
    pipeline: Pipeline
    feature_columns: list[str] = field(default_factory=list)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        return self.pipeline.predict_proba(X)[:, 1]

    def save(self, path: Path | None = None) -> Path:
        path = path or (MODELS_DIR / "sla_risk_model.pkl")
        with open(path, "wb") as f:
            pickle.dump(self, f)
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "SLARiskModel":
        path = path or (MODELS_DIR / "sla_risk_model.pkl")
        with open(path, "rb") as f:
            return pickle.load(f)
