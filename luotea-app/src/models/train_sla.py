"""
Train the SLA-breach risk model and produce all artifacts for the demo + slides.

    python -m src.models.train_sla

Outputs:
    outputs/models/sla_risk_model.pkl
    outputs/metrics/sla_risk_metrics.json
    outputs/predictions/sla_risk_test_predictions.parquet
    outputs/figures/sla_roc_pr.png
    outputs/figures/sla_calibration.png
    outputs/figures/sla_feature_importance.png
    outputs/figures/sla_dispatch_precision_at_k.png
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from sklearn.inspection import permutation_importance
from sklearn.metrics import precision_recall_curve, roc_curve

from src.config import FIGURES_DIR, METRICS_DIR, PREDICTIONS_DIR, PRECISION_AT_K, RANDOM_SEED
from src.data.loader import load_daily_signals, load_work_orders
from src.features.work_orders import FEATURE_COLUMNS, build_sla_dataset, split_xy, time_split
from src.models.sla_risk import (
    SLARiskModel,
    baseline_logreg,
    baseline_majority,
    baseline_priority_rate,
    build_model,
    calibration_table,
    evaluate,
)

BLUE, RED, GREEN, GREY = "#1565C0", "#E53935", "#2E7D32", "#9E9E9E"


def run() -> dict:
    np.random.seed(RANDOM_SEED)
    print("Loading Silver work orders + Gold daily signals (read-only)…")
    wo = load_work_orders()                 # all Valmet sites → cross-site model
    daily = load_daily_signals()
    ds = build_sla_dataset(wo, daily)
    print(f"  dataset: {ds.height:,} work orders · {len(FEATURE_COLUMNS)} features")

    train_df, test_df = time_split(ds)
    cut_date = str(test_df["work_started_at_utc"].min())
    print(f"  time split: train={train_df.height:,}  test={test_df.height:,}  test starts {cut_date}")

    X_train, y_train = split_xy(train_df)
    X_test, y_test = split_xy(test_df)

    # --- train model ---
    print("Training HistGradientBoosting…")
    pipe = build_model()
    pipe.fit(X_train, y_train)
    model = SLARiskModel(pipeline=pipe, feature_columns=FEATURE_COLUMNS)
    model_path = model.save()
    scores = model.predict_proba(X_test)

    # --- baselines ---
    print("Scoring baselines…")
    base_majority = baseline_majority(y_train, len(y_test))
    base_priority = baseline_priority_rate(X_train, y_train, X_test)
    base_logreg = baseline_logreg(X_train, y_train, X_test)

    metrics = {
        "dataset": {
            "n_total": ds.height,
            "n_train": train_df.height,
            "n_test": test_df.height,
            "test_period_start": cut_date,
            "test_period_end": str(test_df["work_started_at_utc"].max()),
            "n_features": len(FEATURE_COLUMNS),
            "features": FEATURE_COLUMNS,
            "test_base_rate": float(y_test.mean()),
        },
        "model": {"name": "HistGradientBoostingClassifier", **evaluate(y_test, scores, PRECISION_AT_K)},
        "baselines": {
            "majority_class": evaluate(y_test, base_majority, PRECISION_AT_K),
            "priority_rate_rule": evaluate(y_test, base_priority, PRECISION_AT_K),
            "logistic_regression": evaluate(y_test, base_logreg, PRECISION_AT_K),
        },
        "calibration": calibration_table(y_test, scores),
        "model_path": str(model_path),
    }

    # --- permutation importance (model-agnostic, on held-out test) ---
    print("Computing permutation importance…")
    perm = permutation_importance(
        pipe, X_test, y_test, scoring="roc_auc", n_repeats=8, random_state=RANDOM_SEED, n_jobs=-1
    )
    importance = sorted(
        ({"feature": f, "importance": float(m), "std": float(s)}
         for f, m, s in zip(FEATURE_COLUMNS, perm.importances_mean, perm.importances_std)),
        key=lambda d: d["importance"], reverse=True,
    )
    metrics["feature_importance"] = importance

    # --- persist metrics + predictions ---
    (METRICS_DIR / "sla_risk_metrics.json").write_text(json.dumps(metrics, indent=2))
    pl.DataFrame({
        "wo_no": test_df["wo_no"],
        "site_id": test_df["site_id"],
        "work_started_at_utc": test_df["work_started_at_utc"],
        "work_type_eng": test_df["work_type_eng"],
        "priority_id_str": test_df["priority_id_str"],
        "breach_probability": scores.tolist(),
        "is_sla_violation": y_test.tolist(),
    }).write_parquet(PREDICTIONS_DIR / "sla_risk_test_predictions.parquet")

    # --- figures ---
    plot_roc_pr(y_test, scores, base_priority, base_logreg)
    plot_calibration(metrics["calibration"], metrics["model"]["base_rate"])
    plot_feature_importance(importance)
    plot_dispatch(metrics["model"]["precision_at_k"], metrics["model"]["base_rate"])

    _print_summary(metrics)
    return metrics


# ------------------------------------------------------------------------------- figures
def plot_roc_pr(y, scores, base_priority, base_logreg):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
    for sc, name, col in [(scores, "Model (GBT)", BLUE), (base_logreg, "Logistic reg.", GREEN),
                          (base_priority, "Priority-rate rule", GREY)]:
        fpr, tpr, _ = roc_curve(y, sc)
        a1.plot(fpr, tpr, color=col, lw=2, label=name)
        prec, rec, _ = precision_recall_curve(y, sc)
        a2.plot(rec, prec, color=col, lw=2, label=name)
    a1.plot([0, 1], [0, 1], "--", color="#bbb")
    a1.set(xlabel="False positive rate", ylabel="True positive rate", title="ROC")
    a2.axhline(y.mean(), ls="--", color="#bbb", label=f"Base rate {y.mean():.2f}")
    a2.set(xlabel="Recall", ylabel="Precision", title="Precision–Recall")
    for a in (a1, a2):
        a.legend(loc="lower left", fontsize=9); a.grid(alpha=.3)
    fig.suptitle("SLA-breach model vs baselines (held-out future period)", fontweight="bold")
    fig.tight_layout(); fig.savefig(FIGURES_DIR / "sla_roc_pr.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_calibration(cal, base_rate):
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "--", color="#bbb", label="Perfect calibration")
    ax.plot([c["mean_pred"] for c in cal], [c["observed"] for c in cal],
            "o-", color=BLUE, lw=2, label="Model")
    ax.set(xlabel="Predicted breach probability", ylabel="Observed breach rate",
           title="Calibration (reliability diagram)", xlim=(0, 1), ylim=(0, 1))
    ax.legend(loc="upper left"); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(FIGURES_DIR / "sla_calibration.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_feature_importance(importance):
    top = importance[:12][::-1]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh([d["feature"] for d in top], [d["importance"] for d in top],
            xerr=[d["std"] for d in top], color=BLUE, alpha=.85)
    ax.set(xlabel="Permutation importance (Δ ROC-AUC)",
           title="What drives SLA-breach risk (held-out test)")
    ax.grid(alpha=.3, axis="x")
    fig.tight_layout(); fig.savefig(FIGURES_DIR / "sla_feature_importance.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_dispatch(pak, base_rate):
    fig, ax = plt.subplots(figsize=(8, 5))
    fracs = [p["k_frac"] * 100 for p in pak]
    ax.plot(fracs, [p["precision"] * 100 for p in pak], "o-", color=RED, lw=2, label="Precision @ top-k%")
    ax.plot(fracs, [p["recall"] * 100 for p in pak], "s-", color=BLUE, lw=2, label="Recall (breaches caught)")
    ax.axhline(base_rate * 100, ls="--", color="#bbb", label=f"Random precision = base rate {base_rate*100:.0f}%")
    for p in pak:
        ax.annotate(f"{p['breaches_caught']}", (p["k_frac"]*100, p["recall"]*100),
                    textcoords="offset points", xytext=(0, 8), fontsize=8, color=BLUE)
    ax.set(xlabel="Dispatch capacity — top-k% riskiest work orders acted on first",
           ylabel="%", title="Risk-ranked dispatch: catching breaches early")
    ax.legend(); ax.grid(alpha=.3)
    fig.tight_layout(); fig.savefig(FIGURES_DIR / "sla_dispatch_precision_at_k.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _print_summary(m):
    md, bp = m["model"], m["baselines"]["priority_rate_rule"]
    print("\n" + "=" * 64)
    print(f"  Test period: {m['dataset']['test_period_start'][:10]} → "
          f"{m['dataset']['test_period_end'][:10]}  ({m['dataset']['n_test']:,} work orders)")
    print(f"  Base breach rate (test):   {md['base_rate']:.3f}")
    print(f"  Model     ROC-AUC={md['roc_auc']:.3f}  PR-AUC={md['pr_auc']:.3f}  F1={md['f1']:.3f}  Brier={md['brier']:.3f}")
    print(f"  Priority  ROC-AUC={bp['roc_auc']:.3f}  PR-AUC={bp['pr_auc']:.3f}  (rules baseline)")
    p10 = next(p for p in md["precision_at_k"] if p["k_frac"] == 0.10)
    print(f"  Dispatch top-10%: precision={p10['precision']:.3f}  catches {p10['breaches_caught']} breaches")
    print("  Top features: " + ", ".join(d["feature"] for d in m["feature_importance"][:4]))
    print("=" * 64)


if __name__ == "__main__":
    run()
