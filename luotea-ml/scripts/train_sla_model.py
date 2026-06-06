"""
SLA Violation Prediction — model training
==========================================

Trains a Random Forest (default) or HistGradientBoosting classifier on Silver
fact_work_order and saves the fitted pipeline plus evaluation artifacts.

Run this once to train, then use score_orders.py to score new orders without
retraining. Retrain monthly as new work orders accumulate.

Prerequisites:
    python3.11 -m pipeline ingest --source all --date <today>
    python3.11 -m pipeline transform --layer silver --domain erp --date <today>

Run:
    python3.11 train_sla_model.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.feature_selection import VarianceThreshold
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_curve,
    roc_auc_score,
    roc_curve,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

REPO_ROOT   = Path(__file__).resolve().parents[2]
SILVER_PATH = REPO_ROOT / "luotea-pipeline" / "data" / "silver" / "fact_work_order" / "fact_work_order.parquet"
GOLD_PATH   = REPO_ROOT / "luotea-pipeline" / "data" / "gold" / "site_rolling_context" / "site_rolling_context.parquet"
MODELS_DIR  = Path(__file__).parent.parent / "models"
REPORTS_DIR = Path(__file__).parent.parent / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

for _d in [MODELS_DIR, REPORTS_DIR, FIGURES_DIR]:
    _d.mkdir(exist_ok=True, parents=True)

# These lists are imported by score_orders.py and train_segmented_models.py — keep them in sync.
CATEGORICAL_FEATURES = ["site_id", "contract_type", "work_order_type", "work_type_eng"]

# Rolling 7-day site context from Gold, joined on (site_id, start_date - 1 day).
# Rolling smooths daily noise — a site consistently overloaded for a week is a
# stronger signal than a single bad day. Named with "site_" prefix for visibility
# in feature importance reports.
GOLD_FEATURES = [
    "site_open_wo_7d_avg",     # avg open WOs at site over past 7 days (team load trend)
    "site_sla_violations_7d",  # total SLA violations at site over past 7 days (pressure)
    "site_alarms_7d_avg",      # avg daily alarms at site over past 7 days (noise level)
    "site_fire_alarms_7d",     # total fire alarms over past 7 days (safety events)
    "site_incidents_7d",       # total Smartti incidents over past 7 days (cross-source)
    "site_utilization_7d_avg", # avg room utilization % over past 7 days (busyness trend)
]

NUMERIC_FEATURES = [
    "priority_id", "month", "day_of_week", "hour", "year",
    "sla_window_days", "has_pm_no", "has_parent_wo",
    "has_sla_deadline", "is_invoicable", "is_subcontractor_work",
    *GOLD_FEATURES,
]
TARGET = "is_sla_violation"

PRECISION_AT_K = [0.05, 0.10, 0.20, 0.30]
_BLUE, _RED, _GREEN, _GREY = "#1565C0", "#E53935", "#2E7D32", "#9E9E9E"


# ── 1. Load from Silver ────────────────────────────────────────────────────────

def load_silver(path: Path) -> pd.DataFrame:
    if not path.exists():
        sys.exit(
            f"Silver data not found: {path}\n"
            "Run: python3.11 -m pipeline transform --layer silver --domain erp --date <today>"
        )
    df = pd.read_parquet(path)
    print(f"  {len(df):,} work orders loaded  |  SLA violation rate: {df[TARGET].mean():.1%}")
    return df


def load_gold_signals() -> pd.DataFrame | None:
    """Load site_rolling_context from Gold. Returns None if not yet generated."""
    if not GOLD_PATH.exists():
        print(
            f"\n  [gold] site_rolling_context not found at:\n    {GOLD_PATH}\n"
            "  Run: cd luotea-pipeline && python3.11 -m pipeline transform --layer gold\n"
            "  Training without site-context features (gold columns will be null-imputed).\n"
        )
        return None
    df = pd.read_parquet(GOLD_PATH)
    print(f"  [gold] {len(df):,} site-day rows loaded (7-day rolling context)")
    return df


# ── 2. Feature engineering ─────────────────────────────────────────────────────
# Only intake-time features — nothing known only after the order closes.
# Excluded: work_finished_days, worktime_hours, work_order_performed_action.
# Gold features use T-1 (previous day) to avoid leakage from same-day counts.

def engineer_features(df: pd.DataFrame, gold_signals: pd.DataFrame | None = None) -> pd.DataFrame:
    df = df.copy()
    started = pd.to_datetime(df["work_started_at_utc"], utc=True)
    sla_end = pd.to_datetime(df["sla_required_end_at_utc"], utc=True)

    df["month"]       = started.dt.month
    df["day_of_week"] = started.dt.dayofweek
    df["hour"]        = started.dt.hour
    df["year"]        = started.dt.year

    df["sla_window_days"]       = (sla_end - started).dt.total_seconds() / 86400.0
    df["has_pm_no"]             = df["pm_no"].notna().astype(int)
    df["has_parent_wo"]         = df["wo_parent_id"].notna().astype(int)
    df["has_sla_deadline"]      = sla_end.notna().astype(int)
    df["is_invoicable"]         = df["is_invoicable"].astype(int)
    df["is_subcontractor_work"] = df["is_subcontractor_work"].astype(int)

    if gold_signals is not None:
        # T-1: use the previous day's site signals to avoid same-day leakage.
        # Merge only the join keys against gold (not the full df) so there are no
        # column name conflicts — gold feature columns don't exist in keys yet.
        join_keys = df[["site_id"]].copy()
        join_keys["_join_date"] = (started - pd.Timedelta(days=1)).dt.date

        gold_slim = gold_signals[
            ["site_id", "as_of_date",
             "open_wo_7d_avg", "sla_violations_7d", "alarms_7d_avg",
             "fire_alarms_7d", "incidents_7d", "utilization_7d_avg"]
        ].rename(columns={
            "as_of_date":        "_join_date",
            "open_wo_7d_avg":    "site_open_wo_7d_avg",
            "sla_violations_7d": "site_sla_violations_7d",
            "alarms_7d_avg":     "site_alarms_7d_avg",
            "fire_alarms_7d":    "site_fire_alarms_7d",
            "incidents_7d":      "site_incidents_7d",
            "utilization_7d_avg":"site_utilization_7d_avg",
        }).copy()
        gold_slim["_join_date"] = pd.to_datetime(gold_slim["_join_date"]).dt.date

        joined = join_keys.merge(gold_slim, on=["site_id", "_join_date"], how="left")
        for col in GOLD_FEATURES:
            df[col] = joined[col].values

        hit_rate = df[GOLD_FEATURES[0]].notna().mean()
        print(f"  [gold] join hit rate: {hit_rate:.1%} of work orders matched a site-day row")
    else:
        # Gold not available — SimpleImputer will fill nulls with the column median.
        for col in GOLD_FEATURES:
            df[col] = float("nan")

    return df


# ── 3. Time-based train / validation split ─────────────────────────────────────
# Test on the most recent 12 months — never shuffle randomly.

def time_split(df: pd.DataFrame, test_months: int = 12) -> tuple[pd.DataFrame, pd.DataFrame]:
    cutoff = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=test_months)
    started = pd.to_datetime(df["work_started_at_utc"], utc=True)
    train = df[started < cutoff]
    test  = df[started >= cutoff]
    print(f"  Train : {len(train):,} orders (before {cutoff.date()})")
    print(f"  Test  : {len(test):,} orders (last {test_months} months)")
    return train, test


# ── 4. Build sklearn pipelines ─────────────────────────────────────────────────

def build_pipeline() -> Pipeline:
    """Random Forest pipeline — tree importance is interpretable, handles class imbalance."""
    preprocessor = ColumnTransformer([
        (
            "cat",
            OneHotEncoder(handle_unknown="ignore", sparse_output=False),
            CATEGORICAL_FEATURES,
        ),
        (
            "num",
            Pipeline([
                ("impute", SimpleImputer(strategy="median")),
                ("scale",  StandardScaler()),
            ]),
            NUMERIC_FEATURES,
        ),
    ])
    clf = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_leaf=20,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    return Pipeline([("prep", preprocessor), ("clf", clf)])


def build_pipeline_gbt() -> Pipeline:
    """HistGradientBoosting pipeline with imputation and constant-feature removal.

    GBT handles NaN natively but its binning step raises on features with only one
    distinct value. A median imputer plus VarianceThreshold(0) prevents this on
    small per-segment training sets.
    """
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False),
         CATEGORICAL_FEATURES),
        ("num", SimpleImputer(strategy="median"), NUMERIC_FEATURES),
    ])
    clf = HistGradientBoostingClassifier(
        learning_rate=0.08,
        max_iter=400,
        max_depth=6,
        l2_regularization=1.0,
        early_stopping=True,
        validation_fraction=0.1,
        random_state=42,
    )
    return Pipeline([("prep", pre), ("var", VarianceThreshold(threshold=0)), ("clf", clf)])


# ── 5. Baselines ───────────────────────────────────────────────────────────────

def baseline_majority(y_train: np.ndarray, n_test: int) -> np.ndarray:
    """Predict the training-set breach rate for every order — trivial baseline."""
    return np.full(n_test, float(y_train.mean()))


def baseline_priority_rate(
    X_train: pd.DataFrame, y_train: np.ndarray, X_test: pd.DataFrame
) -> np.ndarray:
    """Historical breach rate per priority level — what a spreadsheet could already do."""
    if "priority_id" not in X_train.columns:
        return np.full(len(X_test), float(y_train.mean()))
    tmp = pd.DataFrame({"priority_id": X_train["priority_id"].values, "y": y_train})
    rate = tmp.groupby("priority_id")["y"].mean()
    return X_test["priority_id"].map(rate).fillna(float(y_train.mean())).to_numpy()


def baseline_logreg(
    X_train: pd.DataFrame, y_train: np.ndarray, X_test: pd.DataFrame
) -> np.ndarray:
    """Logistic regression — linear ceiling to sanity-check the non-linear model."""
    pre = ColumnTransformer(
        [("cat", OneHotEncoder(handle_unknown="ignore", min_frequency=10), CATEGORICAL_FEATURES)],
        remainder="passthrough",
    )
    pipe = Pipeline([("pre", pre), ("clf", LogisticRegression(max_iter=1000))])
    Xtr, Xte = X_train.copy(), X_test.copy()
    for c in NUMERIC_FEATURES:
        med = Xtr[c].median()
        fill = float(med) if pd.notna(med) else 0.0
        Xtr[c] = Xtr[c].fillna(fill)
        Xte[c] = Xte[c].fillna(fill)
    pipe.fit(Xtr, y_train)
    return pipe.predict_proba(Xte)[:, 1]


# ── 6. Evaluation helpers ──────────────────────────────────────────────────────

def precision_at_k_metric(y_true: np.ndarray, scores: np.ndarray, k_frac: float) -> dict:
    """Among the top-k% riskiest orders, what fraction actually breached?"""
    k = max(1, int(round(len(scores) * k_frac)))
    order = np.argsort(scores)[::-1][:k]
    flagged = y_true[order]
    total = int(y_true.sum())
    return {
        "k_frac": k_frac,
        "k": k,
        "precision": float(flagged.mean()),
        "recall": float(flagged.sum() / total) if total else 0.0,
        "breaches_caught": int(flagged.sum()),
    }


def calibration_table(y_true: np.ndarray, scores: np.ndarray, n_bins: int = 10) -> list[dict]:
    """Reliability-diagram data: predicted probability vs observed breach rate per bin."""
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


def evaluate_rich(
    pipeline: Pipeline,
    X_train: pd.DataFrame,
    y_train: "pd.Series | np.ndarray",
    X_test: pd.DataFrame,
    y_test: "pd.Series | np.ndarray",
    tag: str = "",
    save_figures: bool = True,
) -> dict:
    """
    Full evaluation: ROC-AUC, PR-AUC, Brier, baselines, precision@k dispatch,
    calibration, permutation importance, and optional figures.

    `tag` is used as a figure filename prefix (e.g. "KH", "KT").
    """
    y_tr = y_train.values if hasattr(y_train, "values") else y_train
    y_te = y_test.values  if hasattr(y_test,  "values") else y_test

    y_prob = pipeline.predict_proba(X_test)[:, 1]

    base_maj  = baseline_majority(y_tr, len(y_te))
    base_prio = baseline_priority_rate(X_train, y_tr, X_test)
    base_lr   = baseline_logreg(X_train, y_tr, X_test)

    def _score(y, sc):
        p = (sc >= 0.5).astype(int)
        return {
            "roc_auc":  float(roc_auc_score(y, sc)),
            "pr_auc":   float(average_precision_score(y, sc)),
            "f1":       float(f1_score(y, p, zero_division=0)),
            "brier":    float(brier_score_loss(y, sc)),
            "base_rate": float(y.mean()),
            "precision_at_k": [precision_at_k_metric(y, sc, kf) for kf in PRECISION_AT_K],
        }

    metrics: dict = {
        "model": _score(y_te, y_prob),
        "baselines": {
            "majority_class":      _score(y_te, base_maj),
            "priority_rate":       _score(y_te, base_prio),
            "logistic_regression": _score(y_te, base_lr),
        },
        "calibration": calibration_table(y_te, y_prob),
        "classification_report": classification_report(y_te, (y_prob >= 0.5).astype(int), output_dict=True),
        "confusion_matrix": confusion_matrix(y_te, (y_prob >= 0.5).astype(int)).tolist(),
        "test_size": int(len(y_te)),
        "violation_rate_test": float(y_te.mean()),
    }

    # Permutation importance: model-agnostic, computed on held-out test set.
    # Measures actual drop in ROC-AUC when each feature is shuffled — more honest
    # than tree impurity importance which inflates high-cardinality features.
    print(f"    Computing permutation importance{' (' + tag + ')' if tag else ''}…")
    perm = permutation_importance(
        pipeline, X_test, y_te,
        scoring="roc_auc", n_repeats=5, random_state=42, n_jobs=-1,
    )
    all_features = CATEGORICAL_FEATURES + NUMERIC_FEATURES
    importance = sorted(
        ({"feature": f, "importance": float(m), "std": float(s)}
         for f, m, s in zip(all_features, perm.importances_mean, perm.importances_std)),
        key=lambda d: d["importance"],
        reverse=True,
    )
    metrics["feature_importance"] = importance

    if save_figures:
        prefix = f"{tag}_" if tag else ""
        _plot_roc_pr(y_te, y_prob, base_prio, base_lr, tag, prefix)
        _plot_calibration(metrics["calibration"], float(y_te.mean()), prefix)
        _plot_feature_importance(importance, tag, prefix)
        _plot_dispatch(metrics["model"]["precision_at_k"], float(y_te.mean()), tag, prefix)

    m = metrics["model"]
    p10 = next(p for p in m["precision_at_k"] if p["k_frac"] == 0.10)
    base_auc = metrics["baselines"]["priority_rate"]["roc_auc"]
    print(f"    ROC-AUC={m['roc_auc']:.3f}  PR-AUC={m['pr_auc']:.3f}  Brier={m['brier']:.3f}")
    print(f"    Priority-rate baseline AUC={base_auc:.3f}  lift=+{m['roc_auc'] - base_auc:.3f}")
    print(f"    Dispatch top-10%: precision={p10['precision']:.3f}, catches {p10['breaches_caught']} breaches")

    return metrics


# ── 7. Tree-based feature importances (fast, RF-only fallback) ─────────────────

def get_feature_importances(pipeline: Pipeline, top_n: int = 20) -> list[dict]:
    ohe_names = (
        pipeline.named_steps["prep"]
        .named_transformers_["cat"]
        .get_feature_names_out(CATEGORICAL_FEATURES)
        .tolist()
    )
    all_names   = ohe_names + NUMERIC_FEATURES
    importances = pipeline.named_steps["clf"].feature_importances_
    ranked = sorted(zip(all_names, importances.tolist()), key=lambda x: x[1], reverse=True)
    return [{"feature": name, "importance": round(imp, 5)} for name, imp in ranked[:top_n]]


# ── 8. Figures ─────────────────────────────────────────────────────────────────

def _plot_roc_pr(y, scores, base_priority, base_logreg, label: str, prefix: str):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
    for sc, name, col in [
        (scores,       "Model",              _BLUE),
        (base_logreg,  "Logistic reg.",      _GREEN),
        (base_priority,"Priority-rate rule", _GREY),
    ]:
        fpr, tpr, _ = roc_curve(y, sc)
        a1.plot(fpr, tpr, color=col, lw=2, label=name)
        prec, rec, _ = precision_recall_curve(y, sc)
        a2.plot(rec, prec, color=col, lw=2, label=name)
    a1.plot([0, 1], [0, 1], "--", color="#bbb")
    a1.set(xlabel="False positive rate", ylabel="True positive rate", title="ROC")
    a2.axhline(y.mean(), ls="--", color="#bbb", label=f"Base rate {y.mean():.2f}")
    a2.set(xlabel="Recall", ylabel="Precision", title="Precision–Recall")
    for a in (a1, a2):
        a.legend(loc="lower left", fontsize=9)
        a.grid(alpha=.3)
    title = f"SLA-breach {label} vs baselines (held-out test)" if label else "SLA-breach model vs baselines"
    fig.suptitle(title, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"{prefix}roc_pr.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_calibration(cal: list[dict], base_rate: float, prefix: str):
    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "--", color="#bbb", label="Perfect calibration")
    ax.plot([c["mean_pred"] for c in cal], [c["observed"] for c in cal],
            "o-", color=_BLUE, lw=2, label="Model")
    ax.set(xlabel="Predicted breach probability", ylabel="Observed breach rate",
           title="Calibration (reliability diagram)", xlim=(0, 1), ylim=(0, 1))
    ax.legend(loc="upper left")
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"{prefix}calibration.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_feature_importance(importance: list[dict], label: str, prefix: str):
    top = importance[:12][::-1]
    fig, ax = plt.subplots(figsize=(9, 5))
    xerr = [d.get("std", 0) for d in top]
    ax.barh(
        [d["feature"] for d in top],
        [d["importance"] for d in top],
        xerr=xerr if any(e > 0 for e in xerr) else None,
        color=_BLUE, alpha=.85,
    )
    ax.set(xlabel="Permutation importance (Δ ROC-AUC on held-out test)",
           title=f"Top features driving SLA-breach risk{' — ' + label if label else ''}")
    ax.grid(alpha=.3, axis="x")
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"{prefix}feature_importance.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def _plot_dispatch(pak: list[dict], base_rate: float, label: str, prefix: str):
    fig, ax = plt.subplots(figsize=(8, 5))
    fracs = [p["k_frac"] * 100 for p in pak]
    ax.plot(fracs, [p["precision"] * 100 for p in pak], "o-", color=_RED, lw=2,
            label="Precision @ top-k%")
    ax.plot(fracs, [p["recall"] * 100 for p in pak], "s-", color=_BLUE, lw=2,
            label="Recall (breaches caught)")
    ax.axhline(base_rate * 100, ls="--", color="#bbb",
               label=f"Random precision = base rate {base_rate*100:.0f}%")
    for p in pak:
        ax.annotate(f"{p['breaches_caught']}", (p["k_frac"]*100, p["recall"]*100),
                    textcoords="offset points", xytext=(0, 8), fontsize=8, color=_BLUE)
    ax.set(xlabel="Dispatch capacity — top-k% riskiest orders acted on first",
           ylabel="%",
           title=f"Risk-ranked dispatch: catching breaches early{' — ' + label if label else ''}")
    ax.legend()
    ax.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / f"{prefix}dispatch_precision_at_k.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 55)
    print("  SLA Violation Model — training (combined)")
    print("=" * 55)

    print("\n[1/5] Loading Gold site context (optional) ...")
    gold = load_gold_signals()

    print("\n[2/5] Loading Silver ...")
    df = load_silver(SILVER_PATH)
    df = engineer_features(df, gold_signals=gold)

    print("\n[3/5] Splitting by time ...")
    train, test = time_split(df, test_months=12)

    X_train = train[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_train = train[TARGET].astype(int)
    X_test  = test[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_test  = test[TARGET].astype(int)

    print(f"\n[4/5] Training on {len(train):,} orders ...")
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    print("\n[5/5] Evaluating on held-out test set ...")
    metrics = evaluate_rich(pipeline, X_train, y_train, X_test, y_test,
                            tag="combined", save_figures=True)
    metrics["trained_on_date"] = date.today().isoformat()

    model_path  = MODELS_DIR  / "sla_violation_model.pkl"
    report_path = REPORTS_DIR / "sla_model_report.json"

    joblib.dump(pipeline, model_path)
    report_path.write_text(json.dumps(metrics, indent=2))

    print(f"\n  Model   → {model_path}")
    print(f"  Report  → {report_path}")
    print(f"  Figures → {FIGURES_DIR}/combined_*.png")
    print("\nDone. Run score_orders.py to score new orders.\n")


if __name__ == "__main__":
    main()
