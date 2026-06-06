"""
SLA Violation Prediction — segmented models (one per contract type)
====================================================================

Trains a separate model for each active contract type: KH, KT.
SP (cleaning) is skipped — the current features cannot predict SP SLA
compliance. Use room utilization data instead for a cleaning-specific model.
KIPA is skipped — discontinued in 2021, work absorbed into KH and KT.

Why segment?
  The combined model scored AUC 0.69. When broken down by contract type:
    KH   AUC 0.954  (property maintenance)
    KT   AUC 0.793  (technical maintenance)
    SP   AUC 0.496  (cleaning — worse than random, drags down the whole model)
  Training separate models eliminates SP noise and lets each model learn
  the right patterns for its own contract type.

GBT benchmark:
  Set BENCHMARK_GBT = True (default) to also train HistGradientBoosting for each
  segment. The winner (by ROC-AUC) is saved as the production model. GBT handles
  NaN natively and often outperforms Random Forest on tabular data.

Output:
  models/model_KH.pkl        models/model_KT.pkl
  reports/report_KH.json     reports/report_KT.json
  reports/figures/KH_*.png   reports/figures/KT_*.png

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
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from train_sla_model import (
    SILVER_PATH,
    MODELS_DIR,
    REPORTS_DIR,
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET,
    build_pipeline,
    build_pipeline_gbt,
    engineer_features,
    evaluate_rich,
    load_gold_signals,
    load_silver,
)

# Set to True to benchmark HistGradientBoosting against Random Forest per segment.
# The classifier with higher ROC-AUC on the held-out test set is saved as the
# production model. Adds ~30s per segment but gives an honest algorithm comparison.
BENCHMARK_GBT = True

# ── Contract type config ───────────────────────────────────────────────────────
# KH and KT: standard time-based split — enough recent orders to evaluate properly.
# SP and KIPA are skipped (see module docstring).

SEGMENTS = {
    "KH": {
        "description": "Property maintenance (KH)",
        "test_cutoff": pd.Timestamp("2025-06-06", tz="UTC"),
    },
    "KT": {
        "description": "Technical maintenance (KT)",
        "test_cutoff": pd.Timestamp("2024-01-01", tz="UTC"),  # wider window — only ~544 test orders
    },
}


# ── Train helpers ──────────────────────────────────────────────────────────────

def train_segment(
    df_ct: pd.DataFrame,
    cutoff: pd.Timestamp,
    ct: str,
) -> tuple[object, dict]:
    """
    Train and evaluate one contract-type segment.

    If BENCHMARK_GBT is True, trains both Random Forest and HistGradientBoosting,
    compares AUC, and runs full evaluation (baselines, precision@k, figures) for
    the winner. The winner is returned for saving.
    """
    started = pd.to_datetime(df_ct["work_started_at_utc"], utc=True)
    train   = df_ct[started <  cutoff]
    test    = df_ct[started >= cutoff]

    print(f"    Train: {len(train):,}  |  Test: {len(test):,}  "
          f"(violation rate — train: {train[TARGET].mean():.1%}, test: {test[TARGET].mean():.1%})")

    X_train = train[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_train = train[TARGET].astype(int)
    X_test  = test[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_test  = test[TARGET].astype(int)
    y_arr   = y_test.values

    # ── Train Random Forest ────────────────────────────────────────────────────
    print(f"\n    Training Random Forest ({ct})…")
    rf = build_pipeline()
    rf.fit(X_train, y_train)
    rf_auc = roc_auc_score(y_arr, rf.predict_proba(X_test)[:, 1])
    print(f"    RF  AUC = {rf_auc:.3f}")

    winner_name, winner_model, winner_auc = "RF", rf, rf_auc
    benchmark_row: dict = {"RF": round(rf_auc, 4)}

    # ── Optionally benchmark GBT ───────────────────────────────────────────────
    if BENCHMARK_GBT:
        print(f"    Training HistGradientBoosting ({ct})…")
        gbt = build_pipeline_gbt()
        gbt.fit(X_train, y_train)
        gbt_auc = roc_auc_score(y_arr, gbt.predict_proba(X_test)[:, 1])
        print(f"    GBT AUC = {gbt_auc:.3f}")
        benchmark_row["GBT"] = round(gbt_auc, 4)

        if gbt_auc > rf_auc:
            winner_name, winner_model, winner_auc = "GBT", gbt, gbt_auc
        delta = abs(gbt_auc - rf_auc)
        print(f"    Winner: {winner_name}  (Δ AUC = {delta:.3f})")

    # ── Full evaluation for winner: baselines, calibration, precision@k, figures ──
    print(f"\n    Full evaluation of {winner_name} ({ct})…")
    metrics = evaluate_rich(
        winner_model, X_train, y_train, X_test, y_test,
        tag=ct, save_figures=True,
    )
    metrics.update({
        "contract_type": ct,
        "classifier": winner_name,
        "eval_method": "time_split",
        "test_cutoff": str(cutoff.date()),
        "train_size": len(train),
        "trained_on_date": date.today().isoformat(),
    })
    if BENCHMARK_GBT:
        metrics["benchmark_auc"] = benchmark_row

    return winner_model, metrics


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  SLA Segmented Models — training per contract type")
    if BENCHMARK_GBT:
        print("  (GBT benchmark enabled — winner by AUC will be saved)")
    print("=" * 60)

    print("\n[1/2] Loading Gold site context (optional) ...")
    gold = load_gold_signals()

    print("\n[2/2] Loading Silver fact_work_order.parquet ...")
    df = load_silver(SILVER_PATH)
    df = engineer_features(df, gold_signals=gold)

    # Show what we're skipping and why
    sp   = df[df["contract_type"] == "SP"]
    kipa = df[df["contract_type"] == "KIPA"]
    print(f"\n  SP (cleaning) — SKIPPED")
    print(f"    {len(sp):,} orders  |  violation rate: {sp[TARGET].mean():.1%}")
    print(f"    Reason: AUC 0.496 with available features (worse than random).")
    print(f"\n  KIPA (facility services) — SKIPPED")
    print(f"    {len(kipa):,} historical orders (2017–2021), now absorbed into KH/KT.")

    results = {}

    for ct, cfg in SEGMENTS.items():
        print(f"\n{'─'*60}")
        print(f"  {cfg['description']}")
        print(f"{'─'*60}")

        df_ct = df[df["contract_type"] == ct].copy()
        print(f"  Total: {len(df_ct):,} orders")

        model, metrics = train_segment(df_ct, cfg["test_cutoff"], ct)

        model_path  = MODELS_DIR  / f"model_{ct}.pkl"
        report_path = REPORTS_DIR / f"report_{ct}.json"

        joblib.dump(model, model_path)
        report_path.write_text(json.dumps(metrics, indent=2))

        print(f"\n  Saved: {model_path.name}  |  {report_path.name}")
        results[ct] = metrics

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  Summary")
    print(f"{'='*60}")

    if BENCHMARK_GBT:
        print(f"  {'Contract':<8} {'Winner':<6} {'AUC':<8} {'RF AUC':<10} {'GBT AUC':<10}")
        print(f"  {'─'*8} {'─'*6} {'─'*8} {'─'*10} {'─'*10}")
        for ct, m in results.items():
            bm = m.get("benchmark_auc", {})
            auc = m["model"]["roc_auc"]
            print(f"  {ct:<8} {m['classifier']:<6} {auc:<8.3f} "
                  f"{bm.get('RF', 'n/a'):<10} {bm.get('GBT', 'n/a'):<10}")
    else:
        print(f"  {'Contract':<8} {'Classifier':<6} {'AUC':<8} {'PR-AUC':<10} {'Brier':<8}")
        print(f"  {'─'*8} {'─'*6} {'─'*8} {'─'*10} {'─'*8}")
        for ct, m in results.items():
            mm = m["model"]
            print(f"  {ct:<8} {m['classifier']:<6} {mm['roc_auc']:<8.3f} "
                  f"{mm['pr_auc']:<10.3f} {mm['brier']:<8.3f}")

    print(f"  {'SP':<8} {'—':<6} skipped (AUC 0.496 — use cleaning optimizer instead)")
    print(f"  {'KIPA':<8} {'—':<6} skipped (discontinued 2021)")

    FIGURES_DIR = REPORTS_DIR / "figures"
    print(f"\n  Figures → {FIGURES_DIR}/KH_*.png  {FIGURES_DIR}/KT_*.png")
    print(f"\n  Use score_orders.py to score new orders with these models.\n")


if __name__ == "__main__":
    main()
