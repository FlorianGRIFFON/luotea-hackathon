"""
SLA Violation Prediction — score current orders
================================================

Loads the segmented models (one per contract type) and scores recent work
orders, routing each order to the correct model based on its contract type.

SP (cleaning) orders are flagged separately — no model is available for them
because the current features cannot predict cleaning SLA compliance.

Run:
    python3.11 score_orders.py
    python3.11 score_orders.py --cutoff 2026-05-01
    python3.11 score_orders.py --top 30
"""

from __future__ import annotations

import argparse
from pathlib import Path

import joblib
import pandas as pd

from train_sla_model import CATEGORICAL_FEATURES, NUMERIC_FEATURES, engineer_features, load_gold_signals

REPO_ROOT   = Path(__file__).resolve().parents[2]
SILVER_PATH = REPO_ROOT / "luotea-pipeline" / "data" / "silver" / "fact_work_order" / "fact_work_order.parquet"
MODELS_DIR  = Path(__file__).parent.parent / "models"

RISK_HIGH = 0.65
RISK_LOW  = 0.35

# Active contract types with trained models (KIPA discontinued — absorbed into KH/KT)
MODELLED_CONTRACTS = ["KH", "KT"]


# ── Load models ────────────────────────────────────────────────────────────────

def load_models() -> dict[str, object]:
    """Load all available segmented models. Warn if any are missing."""
    models = {}
    for ct in MODELLED_CONTRACTS:
        path = MODELS_DIR / f"model_{ct}.pkl"
        if path.exists():
            models[ct] = joblib.load(path)
        else:
            print(f"  Warning: model_{ct}.pkl not found — run train_segmented_models.py first")
    return models


# ── Score ──────────────────────────────────────────────────────────────────────

def score_orders(df: pd.DataFrame, models: dict[str, object]) -> pd.DataFrame:
    """
    Route each order to its contract-type model and return a scored DataFrame.
    Orders for contract types without a model get risk_prob=NaN and a note.
    """
    df = df.copy()
    df["risk_prob"]  = float("nan")
    df["risk_label"] = "no model"
    df["model_used"] = "—"

    for ct, model in models.items():
        mask = df["contract_type"] == ct
        if mask.sum() == 0:
            continue
        X = df.loc[mask, CATEGORICAL_FEATURES + NUMERIC_FEATURES]
        df.loc[mask, "risk_prob"]  = model.predict_proba(X)[:, 1]
        df.loc[mask, "model_used"] = f"model_{ct}"

    df["risk_label"] = df["risk_prob"].apply(_risk_label)
    return df.sort_values("risk_prob", ascending=False)


def _risk_label(p: float) -> str:
    if pd.isna(p):    return "no model"
    if p >= RISK_HIGH: return f"HIGH   ({p:.0%})"
    if p >= RISK_LOW:  return f"MEDIUM ({p:.0%})"
    return                    f"LOW    ({p:.0%})"


# ── Print ──────────────────────────────────────────────────────────────────────

def print_table(df: pd.DataFrame, top_n: int) -> None:
    modelled = df[df["risk_prob"].notna()].head(top_n)
    print(f"\n  Top {top_n} highest-risk orders (modelled contracts only):\n")
    print(f"  {'WO #':<12} {'Site':<26} {'CT':<5} {'Work type':<26} {'Risk'}")
    print(f"  {'─'*12} {'─'*26} {'─'*5} {'─'*26} {'─'*20}")
    for _, row in modelled.iterrows():
        site  = str(row["site_id"]).replace("site_valmet_", "")[:24]
        wtype = str(row["work_type_eng"])[:24]
        print(
            f"  {int(row['wo_no']):<12} {site:<26} {row['contract_type']:<5} "
            f"{wtype:<26} {row['risk_label']}"
        )


def print_summary(df: pd.DataFrame) -> None:
    modelled = df[df["risk_prob"].notna()]
    sp_count = (df["contract_type"] == "SP").sum()
    other_no_model = df[df["risk_prob"].isna() & (df["contract_type"] != "SP")]

    high   = (modelled["risk_prob"] >= RISK_HIGH).sum()
    medium = ((modelled["risk_prob"] >= RISK_LOW) & (modelled["risk_prob"] < RISK_HIGH)).sum()
    low    = (modelled["risk_prob"] <  RISK_LOW).sum()

    print(f"\n  {'─'*55}")
    print(f"  Scored orders: {len(modelled):,}  (of {len(df):,} total in this period)")
    print(f"\n  🔴 HIGH   risk (≥65%):  {high:>4}  → escalate or reassign")
    print(f"  🟡 MEDIUM risk (35–65%): {medium:>4}  → monitor")
    print(f"  🟢 LOW    risk (<35%):  {low:>4}  → no action")

    if sp_count:
        print(f"\n  ⚪ SP (cleaning): {sp_count:>4} orders — no model available.")
        print(f"     68% of cleaning orders miss SLA by default (systemic issue).")
        print(f"     Use room utilization data for a cleaning-specific model.")

    if len(other_no_model):
        contracts = other_no_model["contract_type"].unique().tolist()
        print(f"\n  ⚪ Other unmodelled contracts {contracts}: {len(other_no_model)} orders")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Score work orders for SLA risk")
    parser.add_argument("--cutoff", default="2026-05-01",
                        help="Score orders started on or after this date (YYYY-MM-DD)")
    parser.add_argument("--top", type=int, default=20,
                        help="Number of top-risk orders to display")
    args = parser.parse_args()

    cutoff = pd.Timestamp(args.cutoff, tz="UTC")

    print("=" * 55)
    print("  SLA Risk Scoring — segmented models")
    print("=" * 55)

    print("\n[1/3] Loading segmented models ...")
    models = load_models()
    for ct, m in models.items():
        print(f"  model_{ct}.pkl loaded")

    print("\n[2/3] Loading Gold site context + Silver orders ...")
    gold = load_gold_signals()
    df = pd.read_parquet(SILVER_PATH)
    df = engineer_features(df, gold_signals=gold)
    started = pd.to_datetime(df["work_started_at_utc"], utc=True)
    df = df[started >= cutoff].copy()
    print(f"  {len(df):,} orders since {cutoff.date()}")
    for ct, g in df.groupby("contract_type"):
        print(f"    {ct}: {len(g):,}")

    print(f"\n[3/3] Scoring ...")
    scored = score_orders(df, models)

    print_table(scored, args.top)
    print_summary(scored)
    print()


if __name__ == "__main__":
    main()
