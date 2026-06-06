"""
SLA Violation Prediction — model training
==========================================

Trains a Random Forest classifier on Silver fact_work_order and saves the
fitted pipeline to models/sla_violation_model.pkl.

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
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

REPO_ROOT   = Path(__file__).resolve().parents[2]
SILVER_PATH = REPO_ROOT / "luotea-pipeline" / "data" / "silver" / "fact_work_order" / "fact_work_order.parquet"
MODELS_DIR  = Path(__file__).parent.parent / "models"
REPORTS_DIR = Path(__file__).parent.parent / "reports"

MODELS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# These lists are imported by score_orders.py — keep them in sync.
CATEGORICAL_FEATURES = ["site_id", "contract_type", "work_order_type", "work_type_eng"]
NUMERIC_FEATURES = [
    "priority_id", "month", "day_of_week", "hour", "year",
    "sla_window_days", "has_pm_no", "has_parent_wo",
    "has_sla_deadline", "is_invoicable", "is_subcontractor_work",
]
TARGET = "is_sla_violation"


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


# ── 2. Feature engineering ─────────────────────────────────────────────────────
# Only intake-time features — nothing known only after the order closes.
# Excluded: work_finished_days, worktime_hours, work_order_performed_action.

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
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


# ── 4. Build sklearn pipeline ──────────────────────────────────────────────────

def build_pipeline() -> Pipeline:
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


# ── 5. Evaluate ────────────────────────────────────────────────────────────────

def evaluate(pipeline: Pipeline, X_test: pd.DataFrame, y_test: pd.Series) -> dict:
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]
    auc    = roc_auc_score(y_test, y_prob)
    report = classification_report(y_test, y_pred, output_dict=True)
    cm     = confusion_matrix(y_test, y_pred).tolist()

    print(f"\n  ROC-AUC: {auc:.3f}  (aim for >0.75)")
    print(classification_report(y_test, y_pred, target_names=["No violation", "Violation"]))

    return {
        "roc_auc": round(auc, 4),
        "classification_report": report,
        "confusion_matrix": cm,
        "test_size": int(len(y_test)),
        "violation_rate_test": round(float(y_test.mean()), 4),
        "trained_on_date": date.today().isoformat(),
    }


# ── 6. Feature importances ─────────────────────────────────────────────────────

def get_feature_importances(pipeline: Pipeline) -> list[dict]:
    ohe_names = (
        pipeline.named_steps["prep"]
        .named_transformers_["cat"]
        .get_feature_names_out(CATEGORICAL_FEATURES)
        .tolist()
    )
    all_names   = ohe_names + NUMERIC_FEATURES
    importances = pipeline.named_steps["clf"].feature_importances_
    ranked = sorted(zip(all_names, importances.tolist()), key=lambda x: x[1], reverse=True)
    return [{"feature": name, "importance": round(imp, 5)} for name, imp in ranked[:20]]


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 55)
    print("  SLA Violation Model — training")
    print("=" * 55)

    print("\n[1/4] Loading Silver ...")
    df = load_silver(SILVER_PATH)
    df = engineer_features(df)

    print("\n[2/4] Splitting by time ...")
    train, test = time_split(df, test_months=12)

    X_train = train[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_train = train[TARGET].astype(int)
    X_test  = test[CATEGORICAL_FEATURES + NUMERIC_FEATURES]
    y_test  = test[TARGET].astype(int)

    print(f"\n[3/4] Training on {len(train):,} orders ...")
    pipeline = build_pipeline()
    pipeline.fit(X_train, y_train)

    print("\n[4/4] Evaluating on held-out test set ...")
    metrics = evaluate(pipeline, X_test, y_test)
    metrics["top_features"] = get_feature_importances(pipeline)

    model_path  = MODELS_DIR  / "sla_violation_model.pkl"
    report_path = REPORTS_DIR / "sla_model_report.json"

    joblib.dump(pipeline, model_path)
    report_path.write_text(json.dumps(metrics, indent=2))

    print(f"\n  Model  → {model_path}")
    print(f"  Report → {report_path}")
    print("\nDone. Run score_orders.py to score new orders.\n")


if __name__ == "__main__":
    main()
