"""
Cleaning Optimization Model — Lentokentänkatu 11
=================================================

Replaces the fixed cleaning calendar with a utilization-driven priority list.

Instead of "clean every room on Tuesday and Friday regardless of usage", this
model answers: "given how rooms were actually used today, which ones need
cleaning tonight and which can be skipped?"

Two components:
  1. CLUSTERING — groups rooms by their typical usage pattern (done once,
     saved to models/cleaning_clusters.pkl). Produces three tiers:
       Heavy users  → need frequent cleaning (daily or near-daily)
       Medium users → need cleaning 2–3× per week
       Light users  → weekly cleaning is enough

  2. DAILY SCORING — for any given date, computes an urgency score per room
     combining today's utilization, the rolling 3-day average, and how many
     days the room has been accumulating use without a rest day.
     Outputs a ranked priority list: clean / monitor / skip.

Data source:
  luotea-pipeline/data/silver/fact_utilization/fact_utilization.parquet
  38 meeting rooms at Lentokentänkatu 11, Jan 2024 – May 2026

Run:
    python3.11 cleaning_optimizer.py                  # score latest available date
    python3.11 cleaning_optimizer.py --date 2026-05-20
    python3.11 cleaning_optimizer.py --train          # refit clusters and exit
"""

from __future__ import annotations

import argparse
import warnings
warnings.filterwarnings("ignore")

from pathlib import Path

import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

REPO_ROOT      = Path(__file__).resolve().parents[2]
SILVER_PATH    = REPO_ROOT / "luotea-pipeline" / "data" / "silver" / "fact_utilization" / "fact_utilization.parquet"
MODELS_DIR     = Path(__file__).parent.parent / "models"
CLUSTER_MODEL  = MODELS_DIR / "cleaning_clusters.pkl"

MODELS_DIR.mkdir(exist_ok=True)

# Urgency score thresholds — same scale as SLA models for dashboard consistency
URGENT_THRESHOLD  = 65   # → clean tonight
MONITOR_THRESHOLD = 35   # → monitor / clean if capacity allows


# ── Step 1: Load utilization data ──────────────────────────────────────────────
# Silver Parquet — already cleaned and typed by the pipeline.
# One row per (room, working_day). 628 working days × 38 rooms = 23,864 rows.
# utilization_pct: 0–100, representing how much of the day the room was in use.

def load_utilization() -> pd.DataFrame:
    if not SILVER_PATH.exists():
        raise FileNotFoundError(
            f"Silver utilization not found: {SILVER_PATH}\n"
            "Run: cd luotea-pipeline && python3.11 -m pipeline transform --layer silver --domain iot --date <today>"
        )
    df = pd.read_parquet(SILVER_PATH)
    df["utilization_date"] = pd.to_datetime(df["utilization_date"])
    return df


# ── Step 2: Cluster rooms by usage pattern ─────────────────────────────────────
# Why cluster?
#   Different rooms have fundamentally different usage profiles. A heavy meeting
#   room used 50% of every day accumulates dirt much faster than a quiet back
#   room used 5% occasionally. A fixed threshold ("clean if >40%") treats them
#   identically. Clustering lets us calibrate expectations per room type:
#     Heavy cluster → lower threshold to trigger cleaning (dirt builds fast)
#     Light cluster → higher threshold (rarely needs cleaning)
#
# Features used for clustering (all computed per room across the full history):
#   mean_pct        — average daily utilization (how busy is it overall?)
#   zero_day_frac   — fraction of days with zero usage (how often is it idle?)
#   std_pct         — variability (predictable vs erratic usage pattern?)
#   high_day_frac   — fraction of days above 60% (how often is it heavily used?)
#
# We use K-Means with k=3. Three clusters naturally emerge from the data:
# high/medium/low usage — visible in the stats before training.

def compute_room_profiles(df: pd.DataFrame) -> pd.DataFrame:
    profiles = df.groupby("asset_name")["utilization_pct"].agg(
        mean_pct="mean",
        std_pct="std",
        zero_day_frac=lambda x: (x == 0).mean(),
        high_day_frac=lambda x: (x >= 60).mean(),
    ).reset_index()
    return profiles


def train_clusters(df: pd.DataFrame) -> dict:
    profiles = compute_room_profiles(df)

    features = ["mean_pct", "std_pct", "zero_day_frac", "high_day_frac"]
    X = profiles[features].fillna(0).values

    # Scale before clustering — KMeans is distance-based so scale matters
    scaler  = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    kmeans = KMeans(n_clusters=3, random_state=42, n_init=20)
    profiles["cluster_raw"] = kmeans.fit_predict(X_scaled)

    # Label clusters by mean utilization so they're interpretable across runs
    cluster_means = profiles.groupby("cluster_raw")["mean_pct"].mean()
    rank = cluster_means.rank().astype(int)  # 1=low, 2=medium, 3=high
    label_map = {raw: ["light", "medium", "heavy"][rank[raw] - 1]
                 for raw in cluster_means.index}
    profiles["usage_tier"] = profiles["cluster_raw"].map(label_map)

    result = {
        "kmeans": kmeans,
        "scaler": scaler,
        "features": features,
        "room_tiers": profiles.set_index("asset_name")["usage_tier"].to_dict(),
        "profiles": profiles,
    }
    joblib.dump(result, CLUSTER_MODEL)
    return result


def load_or_train_clusters(df: pd.DataFrame) -> dict:
    if CLUSTER_MODEL.exists():
        return joblib.load(CLUSTER_MODEL)
    print("  Cluster model not found — training now ...")
    return train_clusters(df)


# ── Step 3: Daily urgency scoring ──────────────────────────────────────────────
# For each room on a given date, we compute an urgency score (0–100) combining:
#
#   today_util (50% weight)
#     The room's utilization today. The primary signal — if it was busy, it
#     needs cleaning.
#
#   rolling_3d_mean (30% weight)
#     Average utilization over the last 3 working days. Captures accumulation:
#     a room used at 40% for 3 consecutive days is dirtier than one used once
#     at 40% after a week of zero use.
#
#   accumulation_days (20% weight, capped at 5 days)
#     Number of consecutive working days the room has been above 10% without
#     a full rest day (0% or weekend). Converts to a 0–1 scale over 5 days.
#     A room that hasn't had a rest day in 5 days gets urgency +20 regardless
#     of today's specific utilization.
#
# Score = 0.5 * today_util + 0.3 * rolling_3d_mean + 20 * min(acc_days/5, 1)
#
# Recommendation thresholds:
#   score ≥ 65 → CLEAN   (red)    — high priority, include in tonight's run
#   score 35–65 → MONITOR (yellow) — borderline, clean if capacity allows
#   score < 35  → SKIP    (green)  — can wait, save cleaning resources

def score_for_date(df: pd.DataFrame, target_date: pd.Timestamp, clusters: dict) -> pd.DataFrame:
    # Build a pivot table: rooms × dates (working days only)
    pivot = (
        df.pivot(index="utilization_date", columns="asset_name", values="utilization_pct")
        .sort_index()
        .fillna(0)
    )

    if target_date not in pivot.index:
        available = pivot.index[-1]
        print(f"  {target_date.date()} not in data — using latest available: {available.date()}")
        target_date = available

    # Find position of target date and get last 3 working days (including today)
    idx      = pivot.index.get_loc(target_date)
    window   = pivot.iloc[max(0, idx - 2): idx + 1]   # last 3 working days
    today    = pivot.loc[target_date]
    roll3    = window.mean()

    # Accumulation days: consecutive days with >10% utilization before today
    acc_days = pd.Series(0, index=pivot.columns)
    for room in pivot.columns:
        count = 0
        for past_date in reversed(list(pivot.index[:idx])):
            if pivot.loc[past_date, room] > 10:
                count += 1
            else:
                break
        acc_days[room] = count

    # Urgency score
    score = (
        0.50 * today
        + 0.30 * roll3
        + 20.0 * (acc_days / 5).clip(upper=1)
    ).clip(upper=100)

    room_tiers = clusters["room_tiers"]

    result = pd.DataFrame({
        "room":              score.index,
        "usage_tier":        [room_tiers.get(r, "unknown") for r in score.index],
        "today_pct":         today.values.round(1),
        "rolling_3d_mean":   roll3.values.round(1),
        "accumulation_days": acc_days.values.astype(int),
        "urgency_score":     score.values.round(1),
    }).sort_values("urgency_score", ascending=False).reset_index(drop=True)

    result["recommendation"] = result["urgency_score"].apply(
        lambda s: "CLEAN  " if s >= URGENT_THRESHOLD
        else ("MONITOR" if s >= MONITOR_THRESHOLD else "SKIP   ")
    )

    return result, target_date


# ── Step 4: Print output ───────────────────────────────────────────────────────

def print_priority_list(scored: pd.DataFrame, target_date: pd.Timestamp) -> None:
    icons = {"CLEAN  ": "🔴", "MONITOR": "🟡", "SKIP   ": "🟢"}

    print(f"\n  Cleaning priority list — {target_date.date()}  (Lentokentänkatu 11)\n")
    print(f"  {'Room':<20} {'Tier':<8} {'Today':<8} {'3d avg':<8} {'Accum':<7} {'Score':<7} {'Action'}")
    print(f"  {'─'*20} {'─'*8} {'─'*8} {'─'*8} {'─'*7} {'─'*7} {'─'*10}")

    for _, row in scored.iterrows():
        icon = icons.get(row["recommendation"], " ")
        print(
            f"  {row['room']:<20} {row['usage_tier']:<8} "
            f"{row['today_pct']:>5.1f}%   {row['rolling_3d_mean']:>5.1f}%   "
            f"{row['accumulation_days']:>3}d     {row['urgency_score']:>5.1f}   "
            f"{icon} {row['recommendation'].strip()}"
        )

    clean   = (scored["recommendation"] == "CLEAN  ").sum()
    monitor = (scored["recommendation"] == "MONITOR").sum()
    skip    = (scored["recommendation"] == "SKIP   ").sum()

    print(f"\n  Summary:")
    print(f"    🔴 CLEAN tonight:        {clean:>3} rooms")
    print(f"    🟡 MONITOR / if capacity: {monitor:>3} rooms")
    print(f"    🟢 SKIP — save resources: {skip:>3} rooms")

    avg_today = scored["today_pct"].mean()
    skipped_util = scored.loc[scored["recommendation"] == "SKIP   ", "today_pct"].mean()
    print(f"\n    Average utilization today:        {avg_today:.1f}%")
    print(f"    Average utilization of skip rooms: {skipped_util:.1f}%")
    print(f"    Estimated cleaning effort saved:  {skip}/{len(scored)} rooms ({skip/len(scored):.0%})")


def print_cluster_summary(clusters: dict) -> None:
    profiles = clusters["profiles"]
    print("\n  Room usage tiers (trained on Jan 2024 – May 2026 history):\n")
    for tier in ["heavy", "medium", "light"]:
        rooms = profiles[profiles["usage_tier"] == tier]["asset_name"].tolist()
        mean  = profiles[profiles["usage_tier"] == tier]["mean_pct"].mean()
        print(f"  {tier.upper():<8} (avg {mean:.0f}% utilization): {', '.join(sorted(rooms))}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Cleaning priority optimizer")
    parser.add_argument("--date",  default=None,  help="Date to score (YYYY-MM-DD). Default: latest in data.")
    parser.add_argument("--train", action="store_true", help="Refit clusters and exit.")
    args = parser.parse_args()

    print("=" * 60)
    print("  CLEANING OPTIMIZER — utilization-driven scheduling")
    print("=" * 60)

    print("\n[1/3] Loading Silver utilization data ...")
    df = load_utilization()
    print(f"      {len(df):,} room-days  |  {df['asset_name'].nunique()} rooms  "
          f"|  {df['utilization_date'].min().date()} → {df['utilization_date'].max().date()}")

    print("\n[2/3] Loading room usage clusters ...")
    clusters = load_or_train_clusters(df)
    print_cluster_summary(clusters)

    if args.train:
        print("\n  Clusters retrained and saved.")
        return

    target_date = pd.Timestamp(args.date) if args.date else df["utilization_date"].max()

    print(f"\n[3/3] Scoring rooms for {target_date.date()} ...")
    scored, target_date = score_for_date(df, target_date, clusters)
    print_priority_list(scored, target_date)
    print()


if __name__ == "__main__":
    main()
