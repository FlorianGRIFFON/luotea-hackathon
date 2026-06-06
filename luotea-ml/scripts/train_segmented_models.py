"""
SLA Violation Prediction — segmented models (one per contract type)
====================================================================

Trains a separate Random Forest for each contract type: KH, KT, KIPA.
SP (cleaning) is skipped — the current features cannot predict SP SLA
compliance. Use room utilization data instead for a cleaning-specific model.

Why segment?
  The combined model scored AUC 0.69. When broken down by contract type:
    KH   AUC 0.949  (property maintenance)
    KT   AUC 0.836  (technical maintenance)
    SP   AUC 0.496  (cleaning — worse than random, drags down the whole model)
  Training separate models eliminates SP noise and lets each model learn
  the right patterns for its own contract type.

Output:
  models/model_KH.pkl        models/model_KT.pkl        models/model_KIPA.pkl
  reports/report_KH.json     reports/report_KT.json     reports/report_KIPA.json

Run:
    python3.11 train_segmented_models.py
"""

from __future__ import annotations

import json
import warnings
warnings.filterwarnings("ignore")

from datetime import date
from pathlib import Path

import joblib
import pandas as pd
from sklearn.model_selection import cross_val_score
from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix

from train_sla_model import (
    SILVER_PATH,
    MODELS_DIR,
    REPORTS_DIR,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET,
    build_pipeline,
    engineer_features,
    load_silver,
)

# ── Contract type config ───────────────────────────────────────────────────────
# Each entry defines how to train and evaluate the model for that contract type.
#
# KH and KT: standard time-based split — enough recent orders to evaluate properly.
# KIPA: discontinued in 2021 — no recent test data. Use cross-validation instead.
# SP:   skipped — features don't discriminate (see module docstring).

SEGMENTS = {
    "KH": {
        "description": "Property maintenance (KH)",
        "test_cutoff": pd.Timestamp("2025-06-06", tz="UTC"),
        "eval_method": "time_split",
    },
    "KT": {
        "description": "Technical maintenance (KT)",
        "test_cutoff": pd.Timestamp("2024-01-01", tz="UTC"),  # wider window — only 544 test orders
        "eval_method": "time_split",
    },
    "KIPA": {
        "description": "Facility services (KIPA) — discontinued 2021",
        "test_cutoff": None,
        "eval_method": "cross_val",   # no recent data; use 5-fold CV
    },
}


# ── Train helpers ──────────────────────────────────────────────────────────────

def train_time_split(
    df_ct: pd.DataFrame,
    cutoff: pd.Timestamp,
    ct: str,
) -> tuple[object, dict]:
    """Standard time-based train/test split for active contract types."""
    started = pd.to_datetime(df_ct["work_started_at_utc"], utc=True)
    train   = df_ct[started <  cutoff]
    test    = df_ct[started >= cutoff]

    print(f"    Train: {len(train):,}  |  Test: {len(test):,}  "
          f"(violation rate — train: {train[TARGET].mean():.1%}, test: {test[TARGET].mean():.1%})")

    X_train = train[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_train = train[TARGET].astype(int)
    X_test  = test[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_test  = test[TARGET].astype(int)

    model = build_pipeline()
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_prob = model.predict_proba(X_test)[:, 1]
    auc    = roc_auc_score(y_test, y_prob)
    report = classification_report(y_test, y_pred, output_dict=True)
    cm     = confusion_matrix(y_test, y_pred).tolist()
    fa     = cm[0][1]  # false alarms

    print(f"    ROC-AUC: {auc:.3f}  |  False alarms: {fa}  |  Recall(violation): {report['1']['recall']:.1%}")

    metrics = {
        "contract_type": ct,
        "eval_method": "time_split",
        "test_cutoff": str(cutoff.date()),
        "roc_auc": round(auc, 4),
        "false_alarms": fa,
        "classification_report": report,
        "confusion_matrix": cm,
        "train_size": len(train),
        "test_size": len(test),
        "trained_on_date": date.today().isoformat(),
    }
    return model, metrics


def train_cross_val(df_ct: pd.DataFrame, ct: str) -> tuple[object, dict]:
    """5-fold cross-validation for contract types with no recent test data (KIPA)."""
    X = df_ct[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y = df_ct[TARGET].astype(int)

    print(f"    Full dataset: {len(df_ct):,} orders  |  violation rate: {y.mean():.1%}")
    print(f"    No recent test data — using 5-fold cross-validation")

    model = build_pipeline()
    cv_aucs = cross_val_score(model, X, y, cv=5, scoring="roc_auc", n_jobs=-1)
    print(f"    CV AUC: {cv_aucs.mean():.3f} ± {cv_aucs.std():.3f}")

    # Fit on full dataset for the saved model
    model.fit(X, y)

    metrics = {
        "contract_type": ct,
        "eval_method": "cross_val_5fold",
        "roc_auc_mean": round(cv_aucs.mean(), 4),
        "roc_auc_std": round(cv_aucs.std(), 4),
        "note": "KIPA discontinued 2021 — no recent orders. Model trained on full 2017-2021 history.",
        "train_size": len(df_ct),
        "trained_on_date": date.today().isoformat(),
    }
    return model, metrics


def get_top_features(model: object, top_n: int = 10) -> list[dict]:
    ohe_names = (
        model.named_steps["prep"]
        .named_transformers_["cat"]
        .get_feature_names_out(CATEGORICAL_FEATURES)
        .tolist()
    )
    all_names   = ohe_names + NUMERIC_FEATURES
    importances = model.named_steps["clf"].feature_importances_
    ranked = sorted(zip(all_names, importances.tolist()), key=lambda x: x[1], reverse=True)
    return [{"feature": name, "importance": round(imp, 5)} for name, imp in ranked[:top_n]]


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  SLA Segmented Models — training per contract type")
    print("=" * 60)

    print("\nLoading Silver fact_work_order.parquet ...")
    df = load_silver(SILVER_PATH)
    df = engineer_features(df)

    # Show what we're skipping and why
    sp = df[df["contract_type"] == "SP"]
    print(f"\n  SP (cleaning) — SKIPPED")
    print(f"    {len(sp):,} orders  |  violation rate: {sp[TARGET].mean():.1%}")
    print(f"    Reason: AUC 0.496 with available features (worse than random).")
    print(f"    Fix: build a separate utilization-based cleaning scheduler.")

    results = {}

    for ct, cfg in SEGMENTS.items():
        print(f"\n{'─'*60}")
        print(f"  {cfg['description']}")
        print(f"{'─'*60}")

        df_ct = df[df["contract_type"] == ct].copy()
        print(f"  Total: {len(df_ct):,} orders")

        if cfg["eval_method"] == "time_split":
            model, metrics = train_time_split(df_ct, cfg["test_cutoff"], ct)
        else:
            model, metrics = train_cross_val(df_ct, ct)

        metrics["top_features"] = get_top_features(model)

        model_path  = MODELS_DIR  / f"model_{ct}.pkl"
        report_path = REPORTS_DIR / f"report_{ct}.json"

        joblib.dump(model, model_path)
        report_path.write_text(json.dumps(metrics, indent=2))

        print(f"  Saved: {model_path.name}  |  {report_path.name}")
        results[ct] = metrics

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Summary")
    print(f"{'='*60}")
    print(f"  {'Contract':<8} {'AUC':<8} {'False alarms':<15} {'Notes'}")
    print(f"  {'─'*8} {'─'*8} {'─'*15} {'─'*25}")

    for ct, m in results.items():
        if m["eval_method"] == "time_split":
            auc = m["roc_auc"]
            fa  = m.get("false_alarms", "n/a")
            note = ""
        else:
            auc = m["roc_auc_mean"]
            fa  = "n/a (CV)"
            note = "historical only"
        print(f"  {ct:<8} {auc:<8.3f} {str(fa):<15} {note}")

    print(f"  {'SP':<8} {'skipped':<8} {'n/a':<15} needs utilization data")
    print(f"\n  Use score_orders.py to score new orders with these models.\n")


if __name__ == "__main__":
    main()
