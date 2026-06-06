"""
Multivariate anomaly detection on site_daily_signals.

Model: Isolation Forest (sklearn) — chosen for:
- No assumption of distribution shape (good for bursty alarm data)
- Handles partial coverage via per-site feature selection
- Fast training (<1s on 2500 rows)
- Anomaly score is interpretable (more negative = more anomalous)

Baseline comparison: robust z-score per signal (univariate), then max z.
"""
import json
import pickle
from pathlib import Path

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import RobustScaler

from src.config import MODELS_DIR, METRICS_DIR, RANDOM_SEED


class SiteAnomalyDetector:
    """Isolation Forest + RobustScaler for one site."""

    def __init__(self, site_id: str, contamination: float = 0.05):
        self.site_id = site_id
        self.contamination = contamination
        self.scaler = RobustScaler()
        self.model = IsolationForest(
            n_estimators=200,
            contamination=contamination,
            random_state=RANDOM_SEED,
            n_jobs=-1,
        )
        self.feature_names: list[str] = []
        self.fitted = False

    def fit(self, X: np.ndarray, feature_names: list[str]) -> "SiteAnomalyDetector":
        self.feature_names = feature_names
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled)
        self.fitted = True
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        """Return anomaly scores: more negative = more anomalous (range -1 to 0)."""
        X_scaled = self.scaler.transform(X)
        return self.model.score_samples(X_scaled)

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return -1 (anomaly) or +1 (normal)."""
        X_scaled = self.scaler.transform(X)
        return self.model.predict(X_scaled)

    def save(self) -> Path:
        path = MODELS_DIR / f"anomaly_{self.site_id}.pkl"
        with open(path, "wb") as f:
            pickle.dump(self, f)
        return path

    @classmethod
    def load(cls, site_id: str) -> "SiteAnomalyDetector":
        path = MODELS_DIR / f"anomaly_{site_id}.pkl"
        with open(path, "rb") as f:
            return pickle.load(f)


def baseline_max_zscore(X: np.ndarray) -> np.ndarray:
    """
    Univariate baseline: for each row, compute robust z-score per feature,
    return the max absolute z-score across features.
    Higher = more anomalous (opposite sign convention from IsolationForest.score_samples).
    """
    median = np.median(X, axis=0)
    mad = np.median(np.abs(X - median), axis=0)
    mad = np.where(mad == 0, 1e-6, mad)
    z = np.abs((X - median) / (1.4826 * mad))  # 1.4826 makes MAD consistent with std
    return z.max(axis=1)


def evaluate_and_save_metrics(
    site_id: str,
    scores: np.ndarray,
    predictions: np.ndarray,
    baseline_scores: np.ndarray,
    feature_names: list[str],
    n_rows: int,
) -> dict:
    n_anomalies = int((predictions == -1).sum())
    metrics = {
        "site_id": site_id,
        "n_rows": n_rows,
        "n_anomalies_if": n_anomalies,
        "anomaly_rate_if": round(n_anomalies / n_rows, 4),
        "score_min": float(scores.min()),
        "score_max": float(scores.max()),
        "score_mean": float(scores.mean()),
        "baseline_max_zscore_p95": float(np.percentile(baseline_scores, 95)),
        "feature_names": feature_names,
    }
    out = METRICS_DIR / f"anomaly_metrics_{site_id}.json"
    with open(out, "w") as f:
        json.dump(metrics, f, indent=2)
    return metrics
