"""
Luotea Reliability Risk Engine — interactive demo (mobile-responsive).

    streamlit run src/demo/app.py

Reads only precomputed artifacts under outputs/ (build them first with
`python -m src.demo.build_demo_artifacts`). Two operations-facing roles up front, then the
analytics behind them:
  🧑‍💼 Manager    — global picture: portfolio reliability, crew load, the risk-ranked queue
  🧰 My tasks     — a maintainer's own list, attributed by predicted risk, with a plain reason
  📈 Reliability  — the single 0–100 metric per site
  🤖 Model card   — held-out performance vs baselines (the honesty)
  🧩 Unified data — one schema across ERP + IoT customers
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import polars as pl
import streamlit as st

from src.features.cleaning import load_or_train_clusters, load_utilization, score_for_date

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
FIG = OUT / "figures"
PRED = OUT / "predictions"

st.set_page_config(page_title="Luotea Reliability Risk Engine", page_icon="🌿",
                   layout="wide", initial_sidebar_state="collapsed")

# --- mobile-responsive CSS: stack columns, shrink padding/metrics on small screens ----------
st.markdown(
    """
    <style>
      .block-container { padding-top: 2.2rem; padding-bottom: 2rem; max-width: 1300px; }
      @media (max-width: 680px) {
        /* Streamlit lays columns out as a horizontal flex row — let them wrap and go full width */
        div[data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; gap: 0.4rem !important; }
        div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {
            min-width: 100% !important; flex: 1 1 100% !important;
        }
        .block-container { padding: 1rem 0.6rem !important; }
        div[data-testid="stMetricValue"] { font-size: 1.25rem !important; }
        div[data-testid="stMetricLabel"] { font-size: 0.8rem !important; }
        h1 { font-size: 1.5rem !important; }
        button[data-baseweb="tab"] { padding: 0.3rem 0.5rem !important; font-size: 0.85rem !important; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_json(p: Path) -> dict:
    return json.loads(p.read_text())


@st.cache_data
def load_parquet(p: Path) -> pd.DataFrame:
    return pl.read_parquet(p).to_pandas()


def fmt_site(s: str) -> str:
    return s.replace("site_", "").replace("_", " ").title()


BAND_BG = {"ELEVATED": "background-color:#ffcdd2", "NORMAL": "background-color:#fff3cd",
           "CALM": "background-color:#c8e6c9", "HIGH": "background-color:#ffcdd2",
           "MEDIUM": "background-color:#ffe0b2", "LOW": "background-color:#c8e6c9"}
BAND_EMOJI = {"ELEVATED": "⚠️", "NORMAL": "🟡", "CALM": "🟢"}


@st.cache_data
def _util_df() -> pd.DataFrame:
    return load_utilization()


@st.cache_resource
def _clusters():
    return load_or_train_clusters(_util_df())


@st.cache_data
def _score_date(target_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.Timestamp]:
    return score_for_date(_util_df(), target_date, _clusters())


def reason_for(work_type: str, risk: float) -> str:
    if risk >= 80:
        return "Long/complex job that has historically slipped — start now."
    if risk >= 55:
        return "Typical risk for this service line — don't let it sit."
    return "Low risk — safe to schedule later."


# ----------------------------------------------------------------------------- header
st.title("🌿 Luotea Reliability Risk Engine")
st.caption("From calendar-based maintenance to **data-driven reliability** · "
           "**data → signals → decisions** · built on the Luotea pipeline (Gold).")

sla = load_json(OUT / "metrics" / "sla_risk_metrics.json")
summary = load_json(OUT / "metrics" / "demo_summary.json")
h = summary["headline"]

m = st.columns(4)
m[0].metric("Model ROC-AUC", f"{h['model_roc_auc']:.3f}", f"+{h['model_roc_auc']-h['priority_rule_roc_auc']:.3f} vs rule")
m[1].metric("Work orders scored", f"{h['n_work_orders_scored']:,}")
m[2].metric("Top-10% precision", f"{h['dispatch_top10pct_precision']*100:.0f}%", f"base {h['test_base_rate']*100:.0f}%")
m[3].metric("Breaches caught (top-10%)", f"{h['dispatch_top10pct_breaches_caught']:,}")

tabs = st.tabs(["🧑‍💼 Manager", "🧰 My tasks", "📈 Reliability", "🧹 Cleaning", "🤖 Model card", "🧩 Unified data"])

# ============================================================================= 1. MANAGER
with tabs[0]:
    st.subheader("Manager — what's happening across the portfolio, right now")

    port = load_parquet(PRED / "portfolio_today.parquet")
    st.markdown("**Site reliability today** — one 0–100 scale, every site (higher = more risk):")
    cols = st.columns(min(len(port), 4))
    for i, r in port.iterrows():
        c = cols[i % len(cols)]
        c.metric(f"{BAND_EMOJI.get(r['band'],'')} {fmt_site(r['site_id'])}",
                 f"{r['rri']:.0f}", r["band"])

    st.divider()
    left, right = st.columns([1, 1])
    with left:
        st.markdown("**Crew workload** — who is carrying the high-risk work:")
        wl = load_parquet(PRED / "crew_workload.parquet").rename(columns={
            "assigned_to": "Worker", "role": "Role", "tasks": "Tasks",
            "high_risk": "High-risk", "top_risk_pct": "Top risk %"})
        st.dataframe(wl, hide_index=True, width="stretch")
    with right:
        crew = summary.get("crew", {})
        st.markdown("**Today's backlog at Valmet L11**")
        cc = st.columns(3)
        cc[0].metric("Tasks", crew.get("tasks_assigned", "—"))
        cc[1].metric("High-risk", crew.get("high_risk_tasks", "—"))
        cc[2].metric("Crew", crew.get("workers", "—"))
        st.caption("Predictive maintenance ranks the backlog by SLA-breach risk, then attributes "
                   "each job to the right crew member — the riskiest work is spread first.")

    st.markdown("**Risk-ranked queue (attributed)** — the global to-do list, worst first:")
    q = load_parquet(PRED / "task_assignments.parquet")[
        ["wo_no", "work_type_eng", "breach_risk_pct", "risk_band", "assigned_to"]
    ].rename(columns={"wo_no": "WO #", "work_type_eng": "Work type",
                      "breach_risk_pct": "Breach risk %", "risk_band": "Risk",
                      "assigned_to": "Assigned to"})
    st.dataframe(q.style.map(lambda v: BAND_BG.get(v, ""), subset=["Risk"]),
                 hide_index=True, height=380, width="stretch")
    st.image(str(FIG / "reliability_index_cross_site.png"),
             caption="Same 0–100 scale across a Valmet ERP site and a NovaProp IoT site")

# ============================================================================= 2. MY TASKS
with tabs[1]:
    st.subheader("My tasks — your work for today, riskiest first")
    asn = load_parquet(PRED / "task_assignments.parquet")
    workers = sorted(asn["assigned_to"].unique())
    # default to a worker who has high-risk work, so the demo lands
    hi = asn[asn["risk_band"] == "HIGH"]["assigned_to"]
    default_idx = workers.index(hi.iloc[0]) if len(hi) else 0
    who = st.selectbox("I am:", workers, index=default_idx)

    mine = asn[asn["assigned_to"] == who].sort_values("breach_risk_pct", ascending=False)
    k = st.columns(3)
    k[0].metric("Tasks today", len(mine))
    k[1].metric("High-risk", int((mine["risk_band"] == "HIGH").sum()))
    k[2].metric("Top breach risk", f"{mine['breach_risk_pct'].max():.0f}%")
    st.caption("Your list is ordered by the model's predicted SLA-breach risk — do the top ones "
               "first to protect the contract. This is the maintainer-facing side of the same engine.")

    view = mine.copy()
    view["Why"] = [reason_for(wt, r) for wt, r in zip(view["work_type_eng"], view["breach_risk_pct"])]
    view = view[["wo_no", "work_type_eng", "breach_risk_pct", "risk_band", "Why"]].rename(columns={
        "wo_no": "WO #", "work_type_eng": "Task", "breach_risk_pct": "Breach risk %", "risk_band": "Risk"})
    st.dataframe(view.style.map(lambda v: BAND_BG.get(v, ""), subset=["Risk"]),
                 hide_index=True, height=420, width="stretch")

# ============================================================================= 3. RELIABILITY
with tabs[2]:
    st.subheader("Reliability Risk Index — one 0–100 scale, every site")
    st.markdown(
        "**0 = a calm day, 100 = unusually high disruption risk for this site.** It blends whatever "
        "signals a site has — work-order/SLA risk + alarms (Valmet ERP), energy anomaly + incidents "
        "(NovaProp IoT) — so different customers land on the same comparable scale."
    )
    rri = load_parquet(PRED / "reliability_index.parquet").dropna(subset=["reliability_risk_index"])
    sites = sorted(rri["site_id"].unique())
    default = [s for s in ["site_valmet_l11", "site_aurora"] if s in sites] or sites[:2]
    chosen = st.multiselect("Sites", sites, default=default, format_func=fmt_site)
    if chosen:
        d = rri[rri["site_id"].isin(chosen)].copy()
        d["signal_date"] = pd.to_datetime(d["signal_date"])
        d = d[d["signal_date"] >= d["signal_date"].max() - pd.Timedelta(days=730)]
        d["site"] = d["site_id"].map(fmt_site)
        line = alt.Chart(d).mark_line(opacity=0.85).encode(
            x=alt.X("signal_date:T", title="Date"),
            y=alt.Y("reliability_risk_index:Q", title="Reliability Risk Index", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("site:N", title="Site"),
            tooltip=["site", "signal_date:T", alt.Tooltip("reliability_risk_index:Q", format=".0f")],
        )
        band = alt.Chart(pd.DataFrame({"y": [70]})).mark_rule(strokeDash=[6, 4], color="orange").encode(y="y")
        st.altair_chart((line + band).properties(height=360), width="stretch")
        st.caption("Dashed line = elevated-risk band. Days above it are where a dynamic maintenance "
                   "calendar pulls work forward.")

# ============================================================================= 4. CLEANING
with tabs[3]:
    st.subheader("Cleaning priority — Valmet Lentokentänkatu 11")
    st.markdown(
        "Replaces the fixed cleaning calendar with a **utilization-driven priority list**. "
        "Every evening, each of the 38 meeting rooms gets an urgency score (0–100) combining "
        "today's occupancy, the 3-day rolling average, and how many consecutive days the room "
        "has been in use without a rest day."
    )

    util = _util_df()
    date_min = util["utilization_date"].min().date()
    date_max = util["utilization_date"].max().date()

    picked = st.date_input(
        "Score for date", value=date_max,
        min_value=date_min, max_value=date_max,
        help="Defaults to the latest date in the data. Use any working day to review past recommendations."
    )
    scored, scored_date = _score_date(pd.Timestamp(picked))

    n_clean = int((scored["recommendation"] == "CLEAN").sum())
    n_monitor = int((scored["recommendation"] == "MONITOR").sum())
    n_skip = int((scored["recommendation"] == "SKIP").sum())
    n_total = len(scored)

    st.caption(f"Scored for: **{scored_date.date()}**")
    c = st.columns(4)
    c[0].metric("🔴 Clean tonight", n_clean, help="Rooms above urgency threshold 65 — must be cleaned")
    c[1].metric("🟡 Monitor", n_monitor, help="Borderline — clean if capacity allows")
    c[2].metric("🟢 Skip", n_skip, help="No cleaning needed today — save the effort")
    c[3].metric("Effort saved", f"{n_skip/n_total:.0%}", help="Rooms skipped vs cleaning every room on a fixed calendar")

    REC_BG = {"CLEAN": "background-color:#ffcdd2", "MONITOR": "background-color:#fff3cd", "SKIP": "background-color:#c8e6c9"}
    TIER_BG = {"heavy": "background-color:#e3f2fd", "medium": "background-color:#f3e5f5", "light": "background-color:#f1f8e9"}

    view = scored.rename(columns={
        "room": "Room", "usage_tier": "Tier",
        "today_pct": "Today %", "rolling_3d_mean": "3d avg %",
        "accumulation_days": "Accum. days", "urgency_score": "Score",
        "recommendation": "Action",
    })
    st.dataframe(
        view.style
            .map(lambda v: REC_BG.get(v, ""), subset=["Action"])
            .map(lambda v: TIER_BG.get(v, ""), subset=["Tier"]),
        hide_index=True, height=480, width="stretch",
    )

    with st.expander("Room usage tiers (trained on Jan 2024–May 2026 history)"):
        clusters = _clusters()
        profiles = clusters["profiles"]
        for tier, emoji in [("heavy", "🔵"), ("medium", "🟣"), ("light", "🟤")]:
            rooms = sorted(profiles[profiles["usage_tier"] == tier]["asset_name"].tolist())
            mean_u = profiles[profiles["usage_tier"] == tier]["mean_pct"].mean()
            st.markdown(f"**{emoji} {tier.upper()}** (avg {mean_u:.0f}% utilization): {', '.join(rooms)}")
        st.caption("K-Means clustering on mean utilization, std dev, zero-day fraction, and high-day fraction. "
                   "Retrain quarterly or when new rooms are added.")

# ============================================================================= 5. MODEL CARD
with tabs[4]:
    st.subheader("Model card — honest, held-out evaluation")
    ds = sla["dataset"]
    st.markdown(
        f"- **Target:** `is_sla_violation` on **{ds['n_total']:,}** Valmet work orders (2017→2026).\n"
        f"- **Split:** time-based — train on the past, test on **{ds['test_period_start'][:10]} → "
        f"{ds['test_period_end'][:10]}** ({ds['n_test']:,} work orders). No shuffling, no leakage.\n"
        f"- **Features:** {ds['n_features']} creation-time attributes only. Post-completion fields excluded by assertion."
    )
    md = sla["model"]; bl = sla["baselines"]

    def pick(x: dict) -> dict:
        p10 = next(p for p in x["precision_at_k"] if p["k_frac"] == 0.10)
        return {"ROC-AUC": round(x["roc_auc"], 3), "PR-AUC": round(x["pr_auc"], 3),
                "F1": round(x["f1"], 3), "Brier": round(x["brier"], 3), "Prec@10%": round(p10["precision"], 3)}

    comp = pd.DataFrame([
        {"Model": "Majority class", **pick(bl["majority_class"])},
        {"Model": "Priority-rate rule (baseline)", **pick(bl["priority_rate_rule"])},
        {"Model": "Logistic regression", **pick(bl["logistic_regression"])},
        {"Model": "★ HistGradientBoosting", **pick(md)},
    ])
    st.dataframe(comp, hide_index=True, width="stretch")
    g = st.columns(2)
    g[0].image(str(FIG / "sla_roc_pr.png"), caption="ROC & Precision–Recall vs baselines")
    g[1].image(str(FIG / "sla_calibration.png"), caption="Calibration — predicted ≈ observed")
    st.image(str(FIG / "sla_feature_importance.png"), caption="Permutation importance (held-out test)")

# ============================================================================= 6. UNIFIED
with tabs[5]:
    st.subheader("One canonical model spans very different customers")
    st.markdown(
        "Luotea's value is **unifying fragmented facility data**. The same Gold schema and `site_id` "
        "key carry **Valmet ERP** (alarms, work orders, SLA) and **NovaProp IoT** (Smartti energy, "
        "KONE, incidents) — with honest nulls where a source is absent. Onboarding a new customer is "
        "a new Bronze export, **not** a new model."
    )
    cov = pd.DataFrame({
        "Site": ["Valmet L11", "Valmet Venttiilitehdas", "Aurora (NovaProp)", "Horizon (NovaProp)"],
        "Work orders / SLA": ["✅", "✅", "—", "—"],
        "Alarms": ["✅ (2025+)", "✅", "—", "—"],
        "Energy (Smartti)": ["—", "—", "✅", "✅"],
        "Incidents / KONE": ["—", "—", "✅", "✅"],
    })
    st.table(cov)

st.divider()
st.caption("Read-only on `luotea-pipeline` Gold/Silver · QA gate PASS (0 errors) · "
           "see docs/REAL_WORLD.md, docs/ARCHITECTURE.md, docs/SCALING.md.")
