"""
Luotea Reliability Risk Engine — interactive demo (mobile-responsive).

    streamlit run src/demo/app.py

Reads only precomputed artifacts under outputs/ (build them first with
`python -m src.demo.build_demo_artifacts`). Pitch tab up front, then operations-facing roles,
then the analytics behind them:
  Story        — the pitch: problem → solution → headline metrics
  Manager    — global picture: portfolio reliability, crew load, queue, RRI history
  My tasks     — a maintainer's own list, attributed by predicted risk, with a plain reason
  Data & model — unified schema across customers, then held-out evaluation
"""
from __future__ import annotations

import json
from pathlib import Path

import altair as alt
import pandas as pd
import polars as pl
import streamlit as st

from src.config import SILVER_DIR

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
FIG = OUT / "figures"
PRED = OUT / "predictions"

_dim_site = pl.read_parquet(
    SILVER_DIR / "dim_site/dim_site.parquet"
).select(["site_id", "display_name"])
SITE_DISPLAY: dict[str, str] = dict(zip(
    _dim_site["site_id"].to_list(), _dim_site["display_name"].to_list()
))

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
           "MEDIUM": "background-color:#ffe0b2", "LOW": "background-color:#c8e6c9",
           "Critical": "background-color:#ffcdd2"}
BAND_EMOJI = {"ELEVATED": "⚠️", "NORMAL": "🟡", "CALM": "🟢"}
ACTION_BG = {"Urgent": "background-color:#ffcdd2", "Monitor": "background-color:#fff3cd",
             "Low priority": "background-color:#c8e6c9"}
REC_BG = {"CLEAN": "background-color:#ffcdd2", "MONITOR": "background-color:#fff3cd",
          "SKIP": "background-color:#c8e6c9"}


def gap(height: int = 14):
    """Vertical breathing room between blocks (Streamlit's default spacing is tight)."""
    st.markdown(f"<div style='height: {height}px'></div>", unsafe_allow_html=True)


def render_risk_queue(height: int = 380):
    """The attributed, risk-ranked work-order queue (shared by Story and Manager tabs)."""
    q = load_parquet(PRED / "task_assignments.parquet")[
        ["wo_no", "site_id", "work_type_eng", "assigned_to", "breach_risk_pct",
         "risk_band", "severity", "action"]
    ].copy()
    q["site_id"] = q["site_id"].map(SITE_DISPLAY)
    q = q.rename(columns={"wo_no": "WO #", "site_id": "Site", "work_type_eng": "Work type",
                          "assigned_to": "Assigned to", "breach_risk_pct": "Breach risk %",
                          "risk_band": "Risk", "severity": "Severity", "action": "Action"})
    st.dataframe(q.style.map(lambda v: ACTION_BG.get(v, ""), subset=["Action"])
                 .format({"Breach risk %": "{:.1f}"}),
                 hide_index=True, height=height, width="stretch")


def render_reliability_chart(key: str, default_sites=("site_valmet_l11", "site_aurora")):
    """Interactive Reliability-Risk-Index-over-time chart (shared by Story and Manager tabs)."""
    rri = load_parquet(PRED / "reliability_index.parquet").dropna(subset=["reliability_risk_index"])
    sites = sorted(rri["site_id"].unique())
    default = [s for s in default_sites if s in sites] or sites[:2]
    chosen = st.multiselect("Sites", sites, default=default, format_func=fmt_site, key=f"sites_{key}")
    if not chosen:
        return
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
    st.caption("Orange line = elevated-risk threshold.")


def reason_for(work_type: str, risk: float) -> str:
    if risk >= 80:
        return "Long/complex job that has historically slipped — start now."
    if risk >= 55:
        return "Typical risk for this service line — don't let it sit."
    return "Low risk — safe to schedule later."


# ----------------------------------------------------------------------------- header
st.title("Luotea Reliability Risk Engine")
st.caption("From calendar-based maintenance to **data-driven reliability** · "
           "**data → signals → decisions**")

sla = load_json(OUT / "metrics" / "sla_risk_metrics.json")
summary = load_json(OUT / "metrics" / "demo_summary.json")
h = summary["headline"]

m = st.columns(4)
m[0].metric("Model ROC-AUC", f"{h['model_roc_auc']:.3f}", f"+{h['model_roc_auc']-h['priority_rule_roc_auc']:.3f} vs rule")
m[1].metric("Work orders scored", f"{h['n_work_orders_scored']:,}")
m[2].metric("Top-10% precision", f"{h['dispatch_top10pct_precision']*100:.0f}%", f"base {h['test_base_rate']*100:.0f}%")
m[3].metric("Breaches caught (top-10%)", f"{h['dispatch_top10pct_breaches_caught']:,}")

tabs = st.tabs(["Story", "Manager", "My tasks", "Data & model"])

# ============================================================================= 1. STORY (pitch)
with tabs[0]:
    # ---------- 1. The problem: four worlds that don't join ----------
    st.markdown("### The problem: four worlds that were never built to be joined")
    st.markdown(
        "Luotea's facility data comes from **four different worlds that were never designed to be "
        "joined**. Each one has its own format, its own grain, and its own idea of an *identity*:"
    )
    st.markdown(
        "| World | Format | Identity |\n"
        "|---|---|---|\n"
        "| **ERP** (alarms, work orders, maintenance) | CSV (cp1252, `;`-delimited) | `CUSTOMER_NO`, `CUSTOMER_SITE_NO` |\n"
        "| **Smartti IoT** (energy, CO₂, temperature) | nested JSON | `property.id`, `node.id` |\n"
        "| **KONE** (elevator occupancy) | JSON arrays | building name |\n"
        "| **Cleaning** (room / desk utilization) | wide CSV | asset names (`K2`, `Letto`, ...) |"
    )
    gap()
    st.markdown(
        "On top of that, the raw files are messy: odd text encodings, literal `\"NULL\"` strings, "
        "Finnish dates, free text, mixed time zones."
    )

    st.divider()
    # ---------- 2. What we built FIRST: the unified pipeline ----------
    st.markdown("### What we built first: one canonical model")
    st.markdown(
        "Before any machine learning, we built a **medallion pipeline** (Bronze, Silver, Gold) that "
        "ingests all six source families, cleans them, and **joins every world onto one canonical "
        "`site_id`**, behind an automated QA gate (row counts, key uniqueness, PII scan)."
    )
    gap()
    st.graphviz_chart(
        r"""
        digraph {
          rankdir=LR; bgcolor="transparent";
          node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=11, color="#d0d0d0"];
          edge [color="#9e9e9e"];
          subgraph cluster_src {
            label="Four worlds · four ID systems"; fontname="Helvetica"; fontsize=11;
            style=dashed; color="#bdbdbd";
            erp     [label="ERP\nalarms · work orders\nCUSTOMER_NO", fillcolor="#E3F2FD"];
            smartti [label="Smartti IoT\nenergy · CO₂\nproperty.id", fillcolor="#E8F5E9"];
            kone    [label="KONE\nelevator occupancy\nbuilding name", fillcolor="#FFF3E0"];
            clean   [label="Cleaning\nroom / desk use\nasset names", fillcolor="#F3E5F5"];
          }
          pipe [label="Medallion pipeline\nBronze → Silver → Gold\n+ QA gate", shape=box3d, fillcolor="#ECEFF1"];
          gold [label="site_daily_signals\none row per site_id × day", fillcolor="#1565C0", fontcolor="white"];
          erp -> pipe; smartti -> pipe; kone -> pipe; clean -> pipe; pipe -> gold;
        }
        """
    )
    gap()
    st.markdown("**The result: one Parquet table, `site_daily_signals`, joined on `site_id`:**")
    st.dataframe(load_parquet(PRED / "unified_sample.parquet"), hide_index=True, width="stretch")

    st.divider()
    # ---------- 3 + 4. What this unified data lets us build → SLA use case ----------
    st.markdown("### What this unified data lets us build")
    st.markdown(
        "Once every source shares **one `site_id` and one daily grain**, we can ask *forward-looking* "
        "questions instead of only reporting the past. Our hackathon use case:"
    )
    gap(6)
    with st.container(border=True):
        st.markdown("#### Predicting SLA breaches before they happen")
        st.markdown(
            "At the moment a work order is **created**, we predict its probability of **breaching its "
            "SLA**. It is a machine-learning model trained on "
            f"**{sla['dataset']['n_total']:,} real work orders** and evaluated on a **future hold-out** "
            f"({sla['dataset']['test_period_start'][:10]} to {sla['dataset']['test_period_end'][:10]}) "
            "with **no leakage**, so the score is a genuine forecast, not hindsight."
        )
        gap(6)
        u = st.columns(3)
        u[0].metric("Breach-risk model ROC-AUC", f"{h['model_roc_auc']:.3f}",
                    f"+{h['model_roc_auc']-h['priority_rule_roc_auc']:.3f} vs priority-rule")
        u[1].metric("Riskiest-10% precision", f"{h['dispatch_top10pct_precision']*100:.0f}%",
                    f"{h['dispatch_top10pct_breaches_caught']:,} breaches caught early")
        u[2].metric("Work orders scored", f"{h['n_work_orders_scored']:,}")

    gap()
    st.markdown("**What the model produces: a risk-ranked, attributed queue.**")
    st.caption(
        "Every open work order, scored for SLA-breach risk and assigned to the right crew member, "
        "worst first. This is the live Manager view; drill in there to act on it."
    )
    render_risk_queue(height=320)

    st.divider()
    # ---------- 5. Reliability Risk Index ----------
    st.markdown("### One number per site: the Reliability Risk Index")
    st.markdown(
        "A manager does not want hundreds of probabilities, they want one number. The **Reliability "
        "Risk Index** rolls the breach prediction together with the live signals (alarms, energy, "
        "incidents) into a single **0 to 100 score per site**. It is a *now-cast* of operational risk: "
        "the same scale for an ERP factory and an IoT office tower, so you can tell normal variation "
        "from genuinely elevated risk and watch a whole portfolio at a glance."
    )
    gap()
    render_reliability_chart(key="story")

    st.divider()
    # ---------- 6. What actions can people take? ----------
    st.markdown("### What actions can people take thanks to this?")
    gap(6)
    a1, a2 = st.columns(2)
    a1.markdown(
        "**Managers** *(Manager tab)*\n\n"
        "See the whole portfolio's reliability at a glance, plus a **risk-ranked queue with every job "
        "attributed to the right crew member**. Dispatch by risk, not by calendar."
    )
    a2.markdown(
        "**Maintainers** *(My tasks tab)*\n\n"
        "A personal, risk-ordered task list with a plain reason. **Act on the prediction, before the "
        "fault**, instead of reacting after a complaint."
    )

    st.divider()
    # ---------- 7. How does it scale? ----------
    st.markdown("### How does it scale?")
    st.markdown(
        "- **API-ready**: the trained model is a saved artifact. Wrap it in a scoring endpoint and run "
        "it nightly, right after the pipeline's QA gate passes.\n"
        "- **New customer = one data export plus one `site_id` mapping row, with no new model** "
        "(`site_id` is already a feature, so the model generalises across sites).\n"
        "- **New data source = one Silver table**, and the Reliability Index picks it up automatically, "
        "re-weighting over whatever signals a site has.\n"
        "- Trains in **seconds** and runs on a laptop or a phone. The same 0 to 100 index gives "
        "**cross-customer benchmarking** for free as more sites are onboarded."
    )
    st.markdown(
        "**Walk the demo →** *Manager* (the global queue + reliability index) · *My tasks* "
        "(a maintainer's phone view) · *Data & model* (one schema, honest evaluation)."
    )

# ============================================================================= 2. MANAGER
with tabs[1]:

    port = load_parquet(PRED / "portfolio_today.parquet")
    st.subheader("Site reliability today")
    cols = st.columns(min(len(port), 4))
    for i, r in port.iterrows():
        c = cols[i % len(cols)]
        c.metric(f"{BAND_EMOJI.get(r['band'],'')} {fmt_site(r['site_id'])}",
                 f"{r['rri']:.0f}")

    st.divider()
    left, right = st.columns([1, 1], vertical_alignment="center")
    with left:
        st.subheader("Crew workload")
        wl = load_parquet(PRED / "crew_workload.parquet").rename(columns={
            "assigned_to": "Worker", "role": "Role", "tasks": "Tasks",
            "high_risk": "High-risk", "top_risk_pct": "Top risk %"})
        st.dataframe(wl, hide_index=True, width="stretch")
    with right:
        crew = summary.get("crew", {})
        cc = st.columns(3)
        cc[0].metric("Tasks", crew.get("tasks_assigned", "—"))
        cc[1].metric("High-risk", crew.get("high_risk_tasks", "—"))
        cc[2].metric("Crew", crew.get("workers", "—"))

    st.markdown("**Risk-ranked queue (attributed)** — ordered by recommended action:")
    render_risk_queue(height=380)

    st.divider()
    st.markdown(
        "### Reliability over time\n\n"
        "One score per site, 0–100.<br>"
        "Same scale for every customer; pick sites below to compare.",
        unsafe_allow_html=True,
    )
    render_reliability_chart(key="manager")

# ============================================================================= 3. MY TASKS
with tabs[2]:
    st.subheader("My tasks")
    asn = load_parquet(PRED / "task_assignments.parquet")
    workers = sorted(asn["assigned_to"].unique())
    hi = asn[asn["action"] == "ACT NOW"]["assigned_to"]
    default_idx = workers.index(hi.iloc[0]) if len(hi) else 0
    who = st.selectbox("I am:", workers, index=default_idx)

    mine = asn[asn["assigned_to"] == who].copy()
    k = st.columns(3)
    k[0].metric("Tasks today", len(mine))
    k[1].metric("Urgent", int((mine["action"] == "Urgent").sum()))
    k[2].metric("Monitor", int((mine["action"] == "Monitor").sum()))

    mine["site_id"] = mine["site_id"].map(SITE_DISPLAY)
    view = mine[["wo_no", "site_id", "work_type_eng", "action"]].rename(columns={
        "wo_no": "WO #", "site_id": "Site", "work_type_eng": "Task", "action": "Action"})
    st.dataframe(view.style.map(lambda v: ACTION_BG.get(v, ""), subset=["Action"]),
                 hide_index=True, height=300, width="stretch")

# ============================================================================= 4. DATA & MODEL
with tabs[3]:
    st.subheader("One canonical model spans very different customers")
    st.markdown(
        "Luotea's value is **unifying fragmented facility data**. The same Gold schema and `site_id` "
        "key carry **Valmet ERP** (alarms, work orders, SLA) and **NovaProp IoT** (Smartti energy, "
        "KONE, incidents) with honest nulls where a source is absent.<br>"
        "Onboarding a new customer is a new Bronze export, **not** a new model.",
        unsafe_allow_html=True,
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
    st.subheader("Model evaluation")
    ds = sla["dataset"]
    st.markdown(
        f"- **Target:** `is_sla_violation` on **{ds['n_total']:,}** Valmet work orders (2017→2026).\n"
        f"- **Split:** time-based, train on the past, test on **{ds['test_period_start'][:10]} → "
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

    st.image(
        str(FIG / "sla_roc_pr.png"),
        caption="ROC & Precision-Recall vs baselines",
        use_container_width=True,
    )
    cal_col, imp_col = st.columns(2)
    with cal_col:
        st.image(
            str(FIG / "sla_calibration.png"),
            caption="Calibration: predicted ≈ observed",
            use_container_width=True,
        )
    with imp_col:
        st.image(
            str(FIG / "sla_feature_importance.png"),
            caption="Permutation importance (held-out test)",
            use_container_width=True,
        )
