"""
Cleaning optimizer — ported from luotea-ml for dashboard integration.

Replaces the fixed cleaning calendar with a utilization-driven priority list.
For any given date, scores each room 0–100 and recommends CLEAN / MONITOR / SKIP.

Data: Silver fact_utilization (38 rooms at Valmet L11, Jan 2024–May 2026).
"""
from __future__ import annotations

import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from src.config import MODELS_DIR, SILVER_DIR

CLUSTER_MODEL = MODELS_DIR / "cleaning_clusters.pkl"
SILVER_UTILIZATION = SILVER_DIR / "fact_utilization" / "fact_utilization.parquet"

URGENT_THRESHOLD = 65
MONITOR_THRESHOLD = 35


def load_utilization() -> pd.DataFrame:
    df = pd.read_parquet(SILVER_UTILIZATION)
    df["utilization_date"] = pd.to_datetime(df["utilization_date"])
    return df


def _compute_room_profiles(df: pd.DataFrame) -> pd.DataFrame:
    return df.groupby("asset_name")["utilization_pct"].agg(
        mean_pct="mean",
        std_pct="std",
        zero_day_frac=lambda x: (x == 0).mean(),
        high_day_frac=lambda x: (x >= 60).mean(),
    ).reset_index()


def train_clusters(df: pd.DataFrame) -> dict:
    profiles = _compute_room_profiles(df)
    features = ["mean_pct", "std_pct", "zero_day_frac", "high_day_frac"]
    X = profiles[features].fillna(0).values
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)
    kmeans = KMeans(n_clusters=3, random_state=42, n_init=20)
    profiles["cluster_raw"] = kmeans.fit_predict(X_scaled)
    cluster_means = profiles.groupby("cluster_raw")["mean_pct"].mean()
    rank = cluster_means.rank().astype(int)
    label_map = {raw: ["light", "medium", "heavy"][rank[raw] - 1] for raw in cluster_means.index}
    profiles["usage_tier"] = profiles["cluster_raw"].map(label_map)
    result = {
        "kmeans": kmeans, "scaler": scaler, "features": features,
        "room_tiers": profiles.set_index("asset_name")["usage_tier"].to_dict(),
        "profiles": profiles,
    }
    joblib.dump(result, CLUSTER_MODEL)
    return result


def load_or_train_clusters(df: pd.DataFrame) -> dict:
    if CLUSTER_MODEL.exists():
        return joblib.load(CLUSTER_MODEL)
    return train_clusters(df)


def score_for_date(df: pd.DataFrame, target_date: pd.Timestamp, clusters: dict) -> tuple[pd.DataFrame, pd.Timestamp]:
    pivot = (
        df.pivot(index="utilization_date", columns="asset_name", values="utilization_pct")
        .sort_index()
        .fillna(0)
    )
    if target_date not in pivot.index:
        target_date = pivot.index[-1]

    idx = pivot.index.get_loc(target_date)
    window = pivot.iloc[max(0, idx - 2): idx + 1]
    today = pivot.loc[target_date]
    roll3 = window.mean()

    acc_days = pd.Series(0, index=pivot.columns)
    for room in pivot.columns:
        count = 0
        for past_date in reversed(list(pivot.index[:idx])):
            if pivot.loc[past_date, room] > 10:
                count += 1
            else:
                break
        acc_days[room] = count

    score = (0.50 * today + 0.30 * roll3 + 20.0 * (acc_days / 5).clip(upper=1)).clip(upper=100)

    result = pd.DataFrame({
        "room": score.index,
        "usage_tier": [clusters["room_tiers"].get(r, "unknown") for r in score.index],
        "today_pct": today.values.round(1),
        "rolling_3d_mean": roll3.values.round(1),
        "accumulation_days": acc_days.values.astype(int),
        "urgency_score": score.values.round(1),
    }).sort_values("urgency_score", ascending=False).reset_index(drop=True)

    result["recommendation"] = result["urgency_score"].apply(
        lambda s: "CLEAN" if s >= URGENT_THRESHOLD else ("MONITOR" if s >= MONITOR_THRESHOLD else "SKIP")
    )
    return result, target_date
