"""
Train anomaly detectors for all sites and save artifacts + figures.

Usage:
    python -m src.models.train
"""
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import polars as pl

from src.config import FIGURES_DIR, METRICS_DIR, PREDICTIONS_DIR, SITE_VALMET_L11, SITE_AURORA
from src.data.loader import load_daily_signals, list_sites
from src.features.signals import build_feature_matrix
from src.models.anomaly import (
    SiteAnomalyDetector,
    baseline_max_zscore,
    evaluate_and_save_metrics,
)

DEMO_SITES = [SITE_VALMET_L11, SITE_AURORA]
TOP_N_ANOMALIES = 10


def train_site(site_id: str, verbose: bool = True) -> dict:
    if verbose:
        print(f"\n{'='*60}")
        print(f"Training anomaly detector: {site_id}")

    df = load_daily_signals(site_id)
    X, dates, feature_names = build_feature_matrix(df, site_id)

    if len(X) < 30:
        print(f"  SKIP: only {len(X)} rows — not enough data")
        return {}

    if verbose:
        print(f"  Rows: {len(X)}, Features: {feature_names}")

    # Train
    detector = SiteAnomalyDetector(site_id)
    detector.fit(X, feature_names)
    scores = detector.score(X)
    predictions = detector.predict(X)
    baseline = baseline_max_zscore(X)

    # Metrics
    metrics = evaluate_and_save_metrics(
        site_id, scores, predictions, baseline, feature_names, len(X)
    )

    # Save model
    model_path = detector.save()
    metrics["model_path"] = str(model_path)

    if verbose:
        print(f"  Anomalies (IF): {metrics['n_anomalies_if']} / {len(X)} ({metrics['anomaly_rate_if']:.1%})")

    # Predictions output
    result_df = pl.DataFrame({
        "site_id": [site_id] * len(X),
        "signal_date": dates,
        "anomaly_score": scores.tolist(),
        "is_anomaly": (predictions == -1).tolist(),
        "baseline_zscore": baseline.tolist(),
    })
    pred_path = PREDICTIONS_DIR / f"anomaly_scores_{site_id}.parquet"
    result_df.write_parquet(pred_path)
    metrics["predictions_path"] = str(pred_path)

    # Plot
    fig_path = plot_anomaly_timeline(site_id, dates, scores, predictions, feature_names, df, X)
    metrics["figure_path"] = str(fig_path)

    return metrics


def plot_anomaly_timeline(
    site_id: str,
    dates: pl.Series,
    scores: np.ndarray,
    predictions: np.ndarray,
    feature_names: list[str],
    df: pl.DataFrame,
    X: np.ndarray,
) -> Path:
    """Multi-panel figure: anomaly score timeline + feature signals."""
    import pandas as pd

    dates_pd = pd.to_datetime(dates.to_list())
    is_anomaly = predictions == -1

    n_panels = min(len(feature_names), 3) + 1
    fig, axes = plt.subplots(n_panels, 1, figsize=(14, 3 * n_panels), sharex=True)
    if n_panels == 1:
        axes = [axes]

    fig.suptitle(f"Anomaly Detection — {site_id.replace('site_', '').replace('_', ' ').title()}", fontsize=14, fontweight="bold")

    # Panel 0: Anomaly score
    ax = axes[0]
    ax.plot(dates_pd, scores, color="#2196F3", linewidth=0.8, alpha=0.8, label="Anomaly score")
    ax.fill_between(dates_pd, scores, scores.min(), alpha=0.15, color="#2196F3")

    # Highlight anomalies
    anom_dates = dates_pd[is_anomaly]
    anom_scores = scores[is_anomaly]
    ax.scatter(anom_dates, anom_scores, color="#F44336", s=25, zorder=5, label=f"Flagged ({is_anomaly.sum()})")

    # Threshold line
    threshold = np.percentile(scores, 5)
    ax.axhline(threshold, color="#F44336", linestyle="--", alpha=0.5, linewidth=0.8)

    ax.set_ylabel("IF Score\n(lower = more anomalous)")
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.3)

    # Feature panels
    for i, col in enumerate(feature_names[:3]):
        ax = axes[i + 1]
        vals = X[:, feature_names.index(col)]
        ax.plot(dates_pd, vals, color="#4CAF50", linewidth=0.7, alpha=0.8)
        ax.fill_between(dates_pd, vals, 0, alpha=0.1, color="#4CAF50")

        # Highlight anomaly days
        ax.scatter(dates_pd[is_anomaly], vals[is_anomaly], color="#F44336", s=20, zorder=5, alpha=0.7)
        ax.set_ylabel(col.replace("_", "\n"), fontsize=8)
        ax.grid(True, alpha=0.3)

    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    axes[-1].xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    path = FIGURES_DIR / f"anomaly_timeline_{site_id}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


def plot_top_anomalies(site_id: str, dates: pl.Series, scores: np.ndarray, df: pl.DataFrame, X: np.ndarray, feature_names: list[str]) -> Path:
    """Bar chart of top anomaly days with feature breakdown."""
    import pandas as pd

    top_idx = np.argsort(scores)[:TOP_N_ANOMALIES]
    dates_list = dates.to_list()
    top_dates = [str(dates_list[int(i)]) for i in top_idx]
    top_scores = scores[top_idx]

    fig, ax = plt.subplots(figsize=(10, 5))
    bars = ax.barh(top_dates, -top_scores, color="#F44336", alpha=0.8)
    ax.set_xlabel("Anomaly Severity (−IF score, higher = more anomalous)")
    ax.set_title(f"Top {TOP_N_ANOMALIES} Most Anomalous Days — {site_id}")
    ax.grid(True, alpha=0.3, axis="x")
    plt.tight_layout()

    path = FIGURES_DIR / f"top_anomalies_{site_id}.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    return path


def main():
    all_metrics = {}
    sites = DEMO_SITES

    for site_id in sites:
        m = train_site(site_id)
        if m:
            all_metrics[site_id] = m

            # Also generate top anomalies plot
            result_df = pl.read_parquet(m["predictions_path"])
            df = load_daily_signals(site_id)
            X, dates, feature_names = build_feature_matrix(df, site_id)
            scores = np.array(result_df["anomaly_score"].to_list())
            fig_path = plot_top_anomalies(site_id, dates, scores, df, X, feature_names)
            all_metrics[site_id]["top_anomalies_figure"] = str(fig_path)

    # Summary metrics
    summary_path = METRICS_DIR / "anomaly_summary.json"
    with open(summary_path, "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)
    print(f"\nSaved summary metrics: {summary_path}")
    print("\nDone. Models, figures, and predictions saved.")
    return all_metrics


if __name__ == "__main__":
    main()
