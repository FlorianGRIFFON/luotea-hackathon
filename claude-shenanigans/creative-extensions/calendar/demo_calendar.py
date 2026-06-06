"""
Luotea Predictive Maintenance Calendar — Streamlit demo page.

Run standalone:
    streamlit run creative-extensions/calendar/demo_calendar.py

Or drop the `calendar_tab(st)` function into the main app.py's tab list.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import polars as pl
import streamlit as st

from generate import (
    ELEVATED_THRESHOLD,
    PREDICTIONS_DIR,
    SITE_LABELS,
    generate_ics,
)

st.set_page_config(
    page_title="Luotea — Maintenance Calendar",
    page_icon="📅",
    layout="wide",
)


def fmt_site(s: str) -> str:
    return SITE_LABELS.get(s, s.replace("site_", "").replace("_", " ").title())


def calendar_tab() -> None:
    st.subheader("📅 Predictive Maintenance Calendar")
    st.markdown(
        "The Reliability Risk Engine turns SLA-breach predictions and historical risk patterns "
        "into a **subscribable calendar** — a dynamic maintenance schedule that updates as new "
        "data flows in. Download the `.ics` file and drag it into Outlook, Google Calendar, "
        "or iOS Calendar."
    )

    # ── Controls ──────────────────────────────────────────────────────────────
    col_a, col_b = st.columns([2, 1])
    with col_a:
        horizon = st.slider(
            "Forecast horizon (days)",
            min_value=7,
            max_value=90,
            value=30,
            step=7,
            help="How many days forward to project risk windows from historical patterns.",
        )
    with col_b:
        ics_bytes = generate_ics(horizon_days=horizon).encode("utf-8")
        st.download_button(
            label="⬇️ Download .ics calendar",
            data=ics_bytes,
            file_name="luotea_maintenance.ics",
            mime="text/calendar",
            type="primary",
            use_container_width=True,
        )

    st.divider()

    # ── Portfolio status ──────────────────────────────────────────────────────
    port = pl.read_parquet(PREDICTIONS_DIR / "portfolio_today.parquet")
    elevated = port.filter(pl.col("band") == "ELEVATED")
    st.markdown(f"**Sites in ELEVATED band right now:** {len(elevated)} / {len(port)}")
    emoji_map = {"ELEVATED": "🔴", "NORMAL": "🟡", "CALM": "🟢"}
    cols = st.columns(min(len(port), 4))
    for i, row in enumerate(port.iter_rows(named=True)):
        em = emoji_map.get(row["band"], "")
        cols[i % len(cols)].metric(
            f"{em} {fmt_site(row['site_id'])}",
            f"{row['rri']:.0f}",
        )

    st.divider()

    # ── Work order events preview ─────────────────────────────────────────────
    st.markdown("**Immediate: risk-ranked work orders → scheduled this week**")
    dispatch_path = PREDICTIONS_DIR / "dispatch_today_site_valmet_l11.parquet"
    if dispatch_path.exists():
        df = pl.read_parquet(dispatch_path).sort("breach_risk_pct", descending=True)
        hi_med = df.filter(pl.col("risk_band").is_in(["HIGH", "MEDIUM"])).head(10)
        from generate import _next_business_day
        from datetime import date as _date
        today = port["signal_date"].max()
        rows = []
        slot = 0
        for row in hi_med.iter_rows(named=True):
            slot += 1
            event_date = _next_business_day(today, slot)
            rows.append({
                "Date": str(event_date),
                "Risk": row["risk_band"],
                "Work type": row["work_type_eng"],
                "Breach risk %": f"{row['breach_risk_pct']:.0f}%",
                "WO #": row["wo_no"],
            })
        band_bg = {
            "HIGH": "background-color:#ffcdd2",
            "MEDIUM": "background-color:#ffe0b2",
        }
        preview_df = pd.DataFrame(rows)
        st.dataframe(
            preview_df.style.map(lambda v: band_bg.get(v, ""), subset=["Risk"]),
            hide_index=True,
            use_container_width=True,
        )

    st.divider()

    # ── Projected risk windows chart ──────────────────────────────────────────
    st.markdown("**30-day forward view: projected risk windows from historical patterns**")
    rri_df = pl.read_parquet(PREDICTIONS_DIR / "reliability_index.parquet")
    today = port["signal_date"].max()
    last_year_start = today - timedelta(days=365)
    hist_view = (
        rri_df.filter(pl.col("signal_date") >= last_year_start)
        .filter(pl.col("signal_date") <= today)
    ).to_pandas()
    hist_view["signal_date"] = pd.to_datetime(hist_view["signal_date"])
    hist_view["site"] = hist_view["site_id"].map(fmt_site)

    line = (
        alt.Chart(hist_view)
        .mark_line(opacity=0.7)
        .encode(
            x=alt.X("signal_date:T", title="Date"),
            y=alt.Y(
                "reliability_risk_index:Q",
                title="Reliability Risk Index",
                scale=alt.Scale(domain=[0, 100]),
            ),
            color=alt.Color("site:N", title="Site"),
            tooltip=[
                "site",
                alt.Tooltip("signal_date:T", title="Date"),
                alt.Tooltip("reliability_risk_index:Q", format=".0f", title="RRI"),
            ],
        )
    )
    threshold_line = (
        alt.Chart(pd.DataFrame({"y": [ELEVATED_THRESHOLD]}))
        .mark_rule(strokeDash=[6, 4], color="crimson", strokeWidth=2)
        .encode(y="y")
    )
    st.altair_chart(
        (line + threshold_line).properties(height=300, title="Past year — red dashes = ELEVATED threshold"),
        use_container_width=True,
    )

    st.caption(
        f"Dashed red line = elevated-risk threshold ({ELEVATED_THRESHOLD:.0f}). "
        "Calendar events are generated for any week where historical average RRI exceeds this threshold. "
        "Source: Luotea Reliability Risk Engine · Gold pipeline artifacts."
    )

    # ── Cross-customer anomaly bonus ──────────────────────────────────────────
    with st.expander("🔍 Cross-customer anomaly correlation (bonus)", expanded=False):
        st.markdown(
            "Do anomaly spikes happen simultaneously across different customers? "
            "Platform-wide correlated anomalies are an early-warning signal only "
            "Luotea — sitting across multiple sites — can detect."
        )
        frames = []
        for fname, site_id in [
            ("anomaly_scores_site_aurora.parquet", "site_aurora"),
            ("anomaly_scores_site_valmet_l11.parquet", "site_valmet_l11"),
        ]:
            apath = PREDICTIONS_DIR / fname
            if apath.exists():
                a = pl.read_parquet(apath).to_pandas()
                a["site"] = fmt_site(site_id)
                frames.append(a)

        if len(frames) >= 2:
            anom = pd.concat(frames)
            anom["signal_date"] = pd.to_datetime(anom["signal_date"])
            anom = anom[anom["signal_date"] >= pd.Timestamp("2024-01-01")]

            score_chart = (
                alt.Chart(anom)
                .mark_line(opacity=0.8)
                .encode(
                    x=alt.X("signal_date:T", title="Date"),
                    y=alt.Y("anomaly_score:Q", title="Anomaly score (IF)"),
                    color=alt.Color("site:N"),
                    tooltip=["site", "signal_date:T",
                             alt.Tooltip("anomaly_score:Q", format=".2f")],
                )
            )
            anomaly_flags = (
                alt.Chart(anom[anom["is_anomaly"]])
                .mark_point(shape="triangle-up", size=80, opacity=0.9)
                .encode(
                    x="signal_date:T",
                    y="anomaly_score:Q",
                    color="site:N",
                    tooltip=["site", "signal_date:T"],
                )
            )
            st.altair_chart(
                (score_chart + anomaly_flags).properties(
                    height=250,
                    title="Anomaly scores — triangles = flagged anomalies",
                ),
                use_container_width=True,
            )
            # Pearson correlation
            pivot = anom.pivot_table(
                index="signal_date", columns="site", values="anomaly_score"
            ).dropna()
            if not pivot.empty and len(pivot.columns) >= 2:
                cols_list = pivot.columns.tolist()
                corr = pivot.corr().iloc[0, 1]
                st.metric(
                    "Cross-site anomaly correlation (Pearson)",
                    f"{corr:.2f}",
                    help="Positive correlation → anomaly spikes tend to co-occur across sites.",
                )
                if corr > 0.3:
                    st.info(
                        f"Moderate positive correlation ({corr:.2f}) between "
                        f"{cols_list[0]} and {cols_list[1]} anomaly scores. "
                        "Platform-wide early-warning pattern detected."
                    )


if __name__ == "__main__":
    calendar_tab()
