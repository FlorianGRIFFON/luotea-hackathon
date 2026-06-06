"""
Precompute every artifact the Streamlit demo and the slides consume, in one shot.

    python -m src.demo.build_demo_artifacts

Produces (under outputs/):
    predictions/reliability_index.parquet         daily RRI per site (cross-source)
    predictions/dispatch_today_site_valmet_l11.parquet   risk-ranked backlog sample
    metrics/demo_summary.json                     headline numbers for the pitch
    figures/reliability_index_cross_site.png      Valmet vs Aurora on one 0–100 scale
    figures/dispatch_list_site_valmet_l11.png     the "do these first" table
Assumes the SLA model is trained (runs training if the pickle is missing).
"""
from __future__ import annotations

import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl

from src.config import FIGURES_DIR, METRICS_DIR, MODELS_DIR, PREDICTIONS_DIR, SITE_AURORA, SITE_VALMET_L11
from src.data.loader import load_daily_signals, load_work_orders
from src.features.assignment import assign_tasks, crew_workload
from src.features.cleaning import load_or_train_clusters, load_utilization, score_for_date
from src.features.reliability_index import compute_breach_load, compute_reliability_index
from src.models.sla_risk import SLARiskModel

BLUE, RED, ORANGE, GREEN = "#1565C0", "#E53935", "#FB8C00", "#2E7D32"


def ensure_model() -> SLARiskModel:
    path = MODELS_DIR / "sla_risk_model.pkl"
    if not path.exists():
        from src.models.train_sla import run
        run()
    return SLARiskModel.load()


def build_reliability_index(model) -> pl.DataFrame:
    daily = load_daily_signals()
    wo = load_work_orders()
    breach_load = compute_breach_load(model, wo, daily)
    rri = compute_reliability_index(daily, breach_load)
    rri.write_parquet(PREDICTIONS_DIR / "reliability_index.parquet")
    return rri


def build_dispatch_sample(site_id: str = SITE_VALMET_L11, window: int = 40) -> pl.DataFrame:
    """
    A realistic 'current open backlog' view: take the most recent `window` work orders in the
    held-out test period at this site and rank them by predicted breach risk. This is exactly
    the queue a facility manager faces — the model re-orders it so the riskiest jobs rise to
    the top instead of being worked in calendar/arrival order.
    """
    preds = pl.read_parquet(PREDICTIONS_DIR / "sla_risk_test_predictions.parquet").filter(
        pl.col("site_id") == site_id
    )
    recent = preds.sort("work_started_at_utc", descending=True).head(window)
    day = f"{recent['work_started_at_utc'].min().date()} → {recent['work_started_at_utc'].max().date()}"
    ranked = (
        recent.sort("breach_probability", descending=True)
        .with_columns(
            (pl.col("breach_probability") * 100).round(1).alias("breach_risk_pct"),
            pl.when(pl.col("breach_probability") >= 0.66).then(pl.lit("HIGH"))
            .when(pl.col("breach_probability") >= 0.45).then(pl.lit("MEDIUM"))
            .otherwise(pl.lit("LOW")).alias("risk_band"),
        )
        .select(["wo_no", "work_type_eng", "priority_id_str", "breach_risk_pct",
                 "risk_band", "is_sla_violation"])
    )
    ranked.write_parquet(PREDICTIONS_DIR / f"dispatch_today_{site_id}.parquet")
    return ranked.with_columns(pl.lit(day).alias("day"))


def plot_reliability_cross_site(rri: pl.DataFrame):
    fig, axes = plt.subplots(2, 1, figsize=(13, 8), sharex=False)
    cfg = [(SITE_VALMET_L11, "Valmet Lentokentänkatu 11  ·  ERP work-order / SLA risk", BLUE),
           (SITE_AURORA, "Aurora House (NovaProp)  ·  IoT energy / incident risk", GREEN)]
    for ax, (site, title, col) in zip(axes, cfg):
        sub = rri.filter((pl.col("site_id") == site)
                         & pl.col("reliability_risk_index").is_not_null())
        # show last ~2 years for readability
        sub = sub.tail(730)
        d = pd.to_datetime(sub["signal_date"].to_list())
        y = sub["reliability_risk_index"].to_numpy()
        ax.plot(d, y, color=col, lw=0.9)
        ax.fill_between(d, y, 0, color=col, alpha=0.12)
        roll = pd.Series(y).rolling(14, min_periods=3).mean()
        ax.plot(d, roll, color=RED, lw=1.6, label="14-day trend")
        ax.axhline(70, ls="--", color=ORANGE, alpha=.7, label="elevated-risk band (70)")
        ax.set(title=title, ylabel="Reliability Risk Index\n(0 calm → 100 high risk)", ylim=(0, 100))
        ax.legend(loc="upper left", fontsize=8); ax.grid(alpha=.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.suptitle("One 0–100 reliability scale across two very different customers (same Gold schema)",
                 fontweight="bold")
    fig.tight_layout(); fig.savefig(FIGURES_DIR / "reliability_index_cross_site.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_dispatch_table(day_df: pl.DataFrame, site_id: str):
    day = day_df["day"][0] if "day" in day_df.columns else ""
    # show the contrast: top-10 "do first" and bottom-3 "can wait", with a divider
    top = day_df.head(10)
    bottom = day_df.tail(3)
    sep = bottom.head(1).with_columns(
        pl.lit(None).alias("wo_no"), pl.lit("⋯  lower-risk backlog  ⋯").alias("work_type_eng"),
        pl.lit("").alias("priority_id_str"), pl.lit(None).alias("breach_risk_pct"),
        pl.lit("SEP").alias("risk_band"), pl.lit(None).alias("is_sla_violation"),
    )
    rows = pl.concat([top, sep, bottom])
    fig, ax = plt.subplots(figsize=(11, 6)); ax.axis("off")
    cols = ["WO #", "Work type", "Prio", "Breach risk", "Band", "Actual"]
    band_color = {"HIGH": "#FFCDD2", "MEDIUM": "#FFE0B2", "LOW": "#C8E6C9", "SEP": "#ECEFF1"}
    cells, colors = [], []
    for r in rows.iter_rows(named=True):
        if r["risk_band"] == "SEP":
            cells.append(["", r["work_type_eng"], "", "", "", ""])
            colors.append(["#ECEFF1"] * 6)
            continue
        cells.append([str(r["wo_no"]), (r["work_type_eng"] or "")[:34], r["priority_id_str"],
                      f"{r['breach_risk_pct']:.0f}%", r["risk_band"],
                      "BREACHED" if r["is_sla_violation"] else "on time"])
        colors.append(["white", "white", "white", "white", band_color[r["risk_band"]],
                       "#FFCDD2" if r["is_sla_violation"] else "#E8F5E9"])
    t = ax.table(cellText=cells, colLabels=cols, cellColours=colors, loc="center", cellLoc="left")
    t.auto_set_font_size(False); t.set_fontsize(9); t.scale(1, 1.5)
    for j in range(len(cols)):
        t[0, j].set_facecolor("#1565C0"); t[0, j].set_text_props(color="white", fontweight="bold")
    ax.set_title(f"Risk-ranked maintenance dispatch — {site_id}  ·  {day}\n"
                 f"\"Do the red ones first\": top of the list = most likely to breach SLA",
                 fontweight="bold", fontsize=11)
    fig.tight_layout(); fig.savefig(FIGURES_DIR / f"dispatch_list_{site_id}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def build_task_assignments(dispatch: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Attribute the risk-ranked backlog to the crew (manager + maintainer views)."""
    assigned = assign_tasks(dispatch.drop("day") if "day" in dispatch.columns else dispatch)
    assigned.write_parquet(PREDICTIONS_DIR / "task_assignments.parquet")
    workload = crew_workload(assigned)
    workload.write_parquet(PREDICTIONS_DIR / "crew_workload.parquet")
    return assigned, workload


def _band(rri_value: float) -> tuple[str, str]:
    if rri_value >= 70:
        return "ELEVATED", "⚠️ Elevated risk — act today"
    if rri_value >= 40:
        return "NORMAL", "🟡 Normal — watch the queue"
    return "CALM", "🟢 Calm — routine cadence is fine"


def _wo_reason(work_type: str, risk_pct: float) -> str:
    wt = (work_type or "work").lower()
    if risk_pct >= 80:
        return f"{work_type}: {risk_pct:.0f}% breach risk — long/complex job that has historically slipped; start now."
    if risk_pct >= 55:
        return f"{work_type}: {risk_pct:.0f}% breach risk — typical for this service line; don't let it sit."
    return f"{work_type}: {risk_pct:.0f}% breach risk — low; safe to schedule later."


def build_operations_briefing(rri: pl.DataFrame, dispatch: pl.DataFrame) -> dict:
    """
    A plain-language 'facility manager's morning briefing' — the user/operations-facing artifact.
    No ML jargon: a reliability status per site + the concrete work to do first + why.
    """
    daily = load_daily_signals()
    out = {"title": "Facility Operations — Morning Reliability Briefing", "sites": []}

    # --- Valmet L11 (ERP / work-order site): Sari's view ---
    l11_rri = (rri.filter((pl.col("site_id") == SITE_VALMET_L11)
                          & pl.col("reliability_risk_index").is_not_null())
               .sort("signal_date").tail(1))
    rri_val = float(l11_rri["reliability_risk_index"][0]) if l11_rri.height else 50.0
    band, label = _band(rri_val)
    top = dispatch.head(3)
    high = dispatch.filter(pl.col("risk_band") == "HIGH").height
    out["sites"].append({
        "site_id": SITE_VALMET_L11,
        "display_name": "Valmet · Lentokentänkatu 11 (Tampere)",
        "persona": "Sari — Facility & Service Manager",
        "reliability_index": round(rri_val, 0),
        "band": band, "band_label": label,
        "headline": (f"{high} of your open work orders are high-risk for an SLA breach. "
                     f"Work them before the routine queue."),
        "do_first": [
            {"wo_no": int(r["wo_no"]), "work_type": r["work_type_eng"],
             "risk_pct": float(r["breach_risk_pct"]),
             "reason": _wo_reason(r["work_type_eng"], float(r["breach_risk_pct"]))}
            for r in top.iter_rows(named=True)
        ],
        "recommended_actions": [
            "Dispatch the high-risk work orders above first — not in arrival/calendar order.",
            "Confirm subcontractor capacity for the flagged service lines today.",
            "If the reliability index stays elevated for 3+ days, pull forward preventive maintenance.",
        ],
    })

    # --- Aurora (IoT site, no ERP): Mikko's view ---
    a_rri = (rri.filter((pl.col("site_id") == SITE_AURORA)
                        & pl.col("reliability_risk_index").is_not_null())
             .sort("signal_date").tail(1))
    a_val = float(a_rri["reliability_risk_index"][0]) if a_rri.height else 50.0
    a_band, a_label = _band(a_val)
    recent = daily.filter(pl.col("site_id") == SITE_AURORA).sort("signal_date").tail(30)
    inc = int(recent["incident_count"].fill_null(0).sum())
    out["sites"].append({
        "site_id": SITE_AURORA,
        "display_name": "NovaProp · Aurora House",
        "persona": "Mikko — Property Operations Lead (IoT only, no ERP)",
        "reliability_index": round(a_val, 0),
        "band": a_band, "band_label": a_label,
        "headline": (f"No ERP work orders here — reliability comes from energy & incidents. "
                     f"{inc} incident(s) in the last 30 days."),
        "do_first": [],
        "recommended_actions": [
            "Review days where the energy signal deviates from the building's 28-day normal (possible HVAC fault or waste).",
            "Triage any unresolved incidents before they escalate to tenant complaints.",
            "Same 0–100 reliability scale as the Valmet sites — compare across the portfolio.",
        ],
    })

    (METRICS_DIR / "operations_briefing.json").write_text(json.dumps(out, indent=2))
    _write_briefing_markdown(out)
    return out


def _write_briefing_markdown(brief: dict):
    lines = [f"# {brief['title']}", "", "*Plain-language, operations-first view — the screen a "
             "facility manager actually uses. No model jargon.*", ""]
    for s in brief["sites"]:
        lines += [f"## {s['display_name']}", f"**{s['persona']}**", "",
                  f"- **Reliability index: {s['reliability_index']:.0f}/100 — {s['band_label']}**",
                  f"- {s['headline']}", ""]
        if s["do_first"]:
            lines.append("**Do these first:**")
            for w in s["do_first"]:
                lines.append(f"  1. WO #{w['wo_no']} — {w['reason']}")
            lines.append("")
        lines.append("**Recommended actions:**")
        for a in s["recommended_actions"]:
            lines.append(f"- {a}")
        lines.append("")
    (OUTPUTS_MD := METRICS_DIR.parent / "operations_briefing.md").write_text("\n".join(lines))


def build_summary(rri: pl.DataFrame, dispatch: pl.DataFrame):
    sla = json.loads((METRICS_DIR / "sla_risk_metrics.json").read_text())
    p10 = next(p for p in sla["model"]["precision_at_k"] if p["k_frac"] == 0.10)
    # dispatch payoff: of the day's WOs, how many breaches sit in the top third
    n = dispatch.height
    topk = max(1, n // 3)
    top = dispatch.head(topk)
    summary = {
        "headline": {
            "model_roc_auc": round(sla["model"]["roc_auc"], 3),
            "priority_rule_roc_auc": round(sla["baselines"]["priority_rate_rule"]["roc_auc"], 3),
            "dispatch_top10pct_precision": round(p10["precision"], 3),
            "dispatch_top10pct_breaches_caught": p10["breaches_caught"],
            "test_base_rate": round(sla["model"]["base_rate"], 3),
            "n_work_orders_scored": sla["dataset"]["n_total"],
        },
        "reliability_index": {
            "sites_scored": rri.filter(pl.col("reliability_risk_index").is_not_null())["site_id"].n_unique(),
            "site_means": rri.group_by("site_id").agg(
                pl.col("reliability_risk_index").mean().round(1).alias("mean_rri")
            ).sort("mean_rri", descending=True).to_dicts(),
        },
        "dispatch_example": {
            "site": "site_valmet_l11",
            "n_work_orders": n,
            "top_third_size": topk,
            "breaches_in_top_third": int(top["is_sla_violation"].sum()),
            "breaches_total_that_day": int(dispatch["is_sla_violation"].sum()),
        },
    }
    (METRICS_DIR / "demo_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def build_portfolio_today(rri: pl.DataFrame) -> pl.DataFrame:
    """Each site's latest reliability index + band — the manager's portfolio glance."""
    latest = (rri.filter(pl.col("reliability_risk_index").is_not_null())
              .sort("signal_date").group_by("site_id").last()
              .select(["site_id", "signal_date", "reliability_risk_index"])
              .sort("reliability_risk_index", descending=True))
    bands = [_band(v)[0] for v in latest["reliability_risk_index"].to_list()]
    out = latest.with_columns(pl.Series("band", bands),
                              pl.col("reliability_risk_index").round(0).alias("rri"))
    out.write_parquet(PREDICTIONS_DIR / "portfolio_today.parquet")
    return out


def build_cleaning_priority() -> pd.DataFrame:
    """Score every room at Valmet L11 for the latest available date and save to predictions/."""
    util = load_utilization()
    clusters = load_or_train_clusters(util)
    latest = util["utilization_date"].max()
    scored, scored_date = score_for_date(util, latest, clusters)
    scored["scored_date"] = scored_date
    scored.to_parquet(PREDICTIONS_DIR / "cleaning_priority.parquet", index=False)
    return scored


def run():
    model = ensure_model()
    print("Computing cross-site Reliability Index…")
    rri = build_reliability_index(model)
    print("Building dispatch sample…")
    dispatch = build_dispatch_sample()
    print("Attributing tasks to the crew…")
    assigned, workload = build_task_assignments(dispatch)
    build_portfolio_today(rri)
    print("Writing operations briefing…")
    build_operations_briefing(rri, dispatch)
    print("Scoring cleaning priority (Valmet L11)…")
    build_cleaning_priority()
    plot_reliability_cross_site(rri)
    plot_dispatch_table(dispatch, SITE_VALMET_L11)
    summary = build_summary(rri, dispatch)
    summary["crew"] = {
        "workers": workload.height,
        "tasks_assigned": assigned.height,
        "high_risk_tasks": int((assigned["risk_band"] == "HIGH").sum()),
    }
    (METRICS_DIR / "demo_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["crew"], indent=2))
    print("\nDemo artifacts written to outputs/.")


if __name__ == "__main__":
    run()
