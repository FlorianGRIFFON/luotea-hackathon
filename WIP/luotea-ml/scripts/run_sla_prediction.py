"""
SLA Violation Prediction — end-to-end demo
===========================================

Demo script that runs train → score in sequence to show the full flow.
In production these two steps run independently:
  - train_sla_model.py  runs once (or monthly) to fit and save the model
  - score_orders.py     runs on demand to score new orders from the saved model

This script is useful for demos and for verifying that predictions match
reality on known-outcome data.

Run:
    python3.11 run_sla_prediction.py
"""

from __future__ import annotations

import warnings
warnings.filterwarnings("ignore")

import subprocess
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import roc_auc_score, classification_report, confusion_matrix

from train_sla_model import (
    CATEGORICAL_FEATURES,
    NUMERIC_FEATURES,
    TARGET,
    SILVER_PATH,
    MODELS_DIR,
    build_pipeline,
    engineer_features,
    load_silver,
    time_split,
)
from score_orders import RISK_HIGH, RISK_LOW, risk_label, score

CUTOFF_CURRENT = pd.Timestamp("2026-05-01", tz="UTC")
CUTOFF_TRAIN   = pd.Timestamp("2025-05-01", tz="UTC")


def main() -> None:
    print("=" * 62)
    print("  SLA VIOLATION PREDICTION  —  end-to-end demo")
    print("  Pipeline: Silver Parquet → train → evaluate → score")
    print("=" * 62)

    # ── Step 1: load Silver (pipeline output) ──────────────────────────────
    print("\n[1/4] Loading Silver fact_work_order.parquet ...")
    print("      (produced by the data pipeline — already clean, typed, site-mapped)")
    df = load_silver(SILVER_PATH)
    df = engineer_features(df)

    # ── Step 2: train on historical data ───────────────────────────────────
    print(f"\n[2/4] Training on orders before {CUTOFF_TRAIN.date()} ...")
    started = pd.to_datetime(df["work_started_at_utc"], utc=True)
    train   = df[started < CUTOFF_TRAIN]
    val     = df[(started >= CUTOFF_TRAIN) & (started < CUTOFF_CURRENT)]
    current = df[started >= CUTOFF_CURRENT].copy()

    print(f"      Train   : {len(train):>6,} orders  (8 years of history)")
    print(f"      Validate: {len(val):>6,} orders  (May 2025 – Apr 2026)")
    print(f"      Current : {len(current):>6,} orders  (May 2026 onwards)  ← we predict these")

    model = build_pipeline()
    model.fit(
        train[CATEGORICAL_FEATURES + NUMERIC_FEATURES],
        train[TARGET].astype(int),
    )
    joblib.dump(model, MODELS_DIR / "sla_violation_model.pkl")
    print("      Model trained and saved.")

    # ── Step 3: evaluate on validation set ────────────────────────────────
    print(f"\n[3/4] Evaluating on {len(val):,} validation orders ...")
    X_val  = val[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_val  = val[TARGET].astype(int)
    y_pred = model.predict(X_val)
    y_prob = model.predict_proba(X_val)[:, 1]
    auc    = roc_auc_score(y_val, y_prob)
    cm     = confusion_matrix(y_val, y_pred)

    print(f"\n      ROC-AUC: {auc:.3f}   (1.0 = perfect, 0.5 = random guess)\n")
    for line in classification_report(y_val, y_pred, target_names=["No violation", "Violation"]).splitlines():
        print(f"      {line}")
    print(f"\n      Confusion matrix:")
    print(f"                         Predicted NO    Predicted YES")
    print(f"        Actual NO            {cm[0][0]:<8}        {cm[0][1]}")
    print(f"        Actual YES           {cm[1][0]:<8}        {cm[1][1]}")

    # ── Step 4: score current orders (blind) then reveal truth ────────────
    print(f"\n[4/4] Scoring {len(current):,} current orders (May–Jun 2026) ...")
    print("      Model saw none of these during training — revealing actual outcomes:\n")

    scored = score(model, current)
    scored["actual"]  = scored[TARGET].map({True: "VIOLATION ✗", False: "ok"})
    scored["correct"] = (
        (scored["risk_prob"] >= RISK_HIGH) == scored[TARGET].astype(bool)
    ).map({True: "✓", False: "·"})

    print(f"  {'WO #':<12} {'Site':<26} {'CT':<5} {'Risk':<20} {'Actual':<14} {'Match'}")
    print(f"  {'─'*12} {'─'*26} {'─'*5} {'─'*20} {'─'*14} {'─'*5}")
    for _, row in scored.head(20).iterrows():
        site = str(row["site_id"]).replace("site_valmet_", "")[:24]
        print(
            f"  {int(row['wo_no']):<12} {site:<26} {row['contract_type']:<5} "
            f"{row['risk_label']:<20} {row['actual']:<14} {row['correct']}"
        )

    high   = (scored["risk_prob"] >= RISK_HIGH).sum()
    medium = ((scored["risk_prob"] >= RISK_LOW) & (scored["risk_prob"] < RISK_HIGH)).sum()
    low    = (scored["risk_prob"] <  RISK_LOW).sum()
    actual = scored[TARGET].sum()

    print(f"\n  ... top 20 of {len(scored)} current orders ranked by risk\n")
    print(f"  Breakdown:")
    print(f"    HIGH   risk (≥65%):  {high:>4} orders  → escalate")
    print(f"    MEDIUM risk (35–65%): {medium:>4} orders  → monitor")
    print(f"    LOW    risk (<35%):  {low:>4} orders  → no action")
    print(f"    Actual violations:   {actual:>4} of {len(scored)}")
    print(f"\n  To score future orders without retraining, run: python3.11 score_orders.py\n")


if __name__ == "__main__":
    main()
