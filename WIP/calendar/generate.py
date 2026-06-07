"""
Luotea Predictive Maintenance Calendar Generator

Reads pre-built Gold-derived Parquet artifacts and emits an RFC 5545 .ics file
that facility managers can subscribe to in Outlook, Google Calendar, or iOS Calendar.

Two kinds of events:

  1. Work-order events  — one event per HIGH/MEDIUM work order in today's dispatch queue,
     scheduled for the next 1-5 business days in priority order.

  2. Projected risk windows  — 30-day forward view: any calendar week where the
     historical average Reliability Risk Index exceeds the ELEVATED threshold (70)
     for a given site generates a "Maintenance window recommended" all-day event.

No network calls, no new dependencies — stdlib + Polars (already in the pipeline venv).
"""
from __future__ import annotations

import os
import textwrap
import uuid
from datetime import date, timedelta
from pathlib import Path

import polars as pl

# Path resolution — works whether called from project root or creative-extensions/
_DEFAULT_PREDS = Path(__file__).resolve().parents[2] / "outputs" / "predictions"
PREDICTIONS_DIR = Path(os.getenv("LUOTEA_PREDICTIONS", str(_DEFAULT_PREDS)))

ELEVATED_THRESHOLD = 70.0  # RRI above this → generate a risk-window event
DISPATCH_SITES = ["site_valmet_l11"]  # sites with work-order dispatch files

SITE_LABELS = {
    "site_valmet_l11": "Valmet L11 (Tampere)",
    "site_valmet_venttiilitehdas": "Valmet Venttiilitehdas",
    "site_valmet_toimistotalo": "Valmet Toimistotalo",
    "site_valmet_std": "Valmet STD Factory",
    "site_aurora": "Aurora House",
    "site_meridian": "Meridian Tower",
    "site_horizon": "Horizon Plaza",
}

RISK_ACTIONS = {
    "HIGH": "Start today — model predicts SLA breach with high confidence.",
    "MEDIUM": "Schedule within 3 days to protect SLA.",
    "LOW": "Monitor; schedule within the week.",
}


# ─────────────────────────────────────────────────────────────────────────────
# ICS building blocks
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _fold(line: str) -> str:
    """RFC 5545 §3.1 line folding at 75 octets — byte-aware to handle multi-byte chars."""
    out: list[str] = []
    encoded = line.encode("utf-8")
    while len(encoded) > 75:
        pos = 75
        # Back up to a byte boundary so we don't split a multi-byte sequence
        while pos > 0 and (encoded[pos] & 0xC0) == 0x80:
            pos -= 1
        out.append(encoded[:pos].decode("utf-8"))
        encoded = b" " + encoded[pos:]
    out.append(encoded.decode("utf-8"))
    return "\r\n".join(out)


def _escape(text: str) -> str:
    """RFC 5545 TEXT escaping."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _vevent(
    uid: str,
    dtstart: date,
    dtend: date,
    summary: str,
    description: str,
    categories: list[str],
    priority: int = 5,
) -> str:
    cats = ",".join(categories)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTART;VALUE=DATE:{_fmt_date(dtstart)}",
        f"DTEND;VALUE=DATE:{_fmt_date(dtend)}",
        _fold(f"SUMMARY:{_escape(summary)}"),
        _fold(f"DESCRIPTION:{_escape(description)}"),
        f"CATEGORIES:{cats}",
        f"PRIORITY:{priority}",
        "STATUS:CONFIRMED",
        "END:VEVENT",
    ]
    return "\r\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Event generators
# ─────────────────────────────────────────────────────────────────────────────

def _next_business_day(d: date, offset: int = 1) -> date:
    """Return d + offset business days (skip Sat/Sun)."""
    current = d
    steps = 0
    while steps < offset:
        current += timedelta(days=1)
        if current.weekday() < 5:
            steps += 1
    return current


def _work_order_events(today: date) -> list[str]:
    events = []
    slot = 0  # business-day slots from today
    for site_id in DISPATCH_SITES:
        path = PREDICTIONS_DIR / f"dispatch_today_{site_id}.parquet"
        if not path.exists():
            continue
        label = SITE_LABELS.get(site_id, site_id)
        df = pl.read_parquet(path).sort("breach_risk_pct", descending=True)

        for i, row in enumerate(df.iter_rows(named=True)):
            band = row["risk_band"]
            if band not in ("HIGH", "MEDIUM"):
                continue
            risk_pct = row["breach_risk_pct"]
            work_type = row["work_type_eng"]
            wo_no = row["wo_no"]
            slot += 1
            # spread work across the next few business days
            event_date = _next_business_day(today, slot)
            summary = (
                f"{'⚠️' if band == 'HIGH' else '🟡'} {band} – {work_type} · {label}"
            )
            description = (
                f"Predicted SLA breach risk: {risk_pct:.0f}%\n"
                f"Work order: {wo_no}\n"
                f"Priority: {row['priority_id_str']}\n"
                f"Site: {label}\n"
                f"Action: {RISK_ACTIONS[band]}"
            )
            prio = 1 if band == "HIGH" else 5
            events.append(
                _vevent(
                    uid=f"luotea-wo-{wo_no}@luotea.com",
                    dtstart=event_date,
                    dtend=event_date + timedelta(days=1),
                    summary=summary,
                    description=description,
                    categories=[band, "WORK-ORDER", "MAINTENANCE"],
                    priority=prio,
                )
            )
    return events


def _projected_risk_events(today: date, horizon_days: int = 30) -> list[str]:
    """
    For each (site, ISO-week) in the next `horizon_days` days, look up the
    historical average RRI for that ISO-week across all past years.
    If the mean RRI > ELEVATED_THRESHOLD, emit an all-day 'maintenance window' event.
    """
    df = pl.read_parquet(PREDICTIONS_DIR / "reliability_index.parquet")
    df = df.with_columns([
        pl.col("signal_date").dt.iso_year().alias("iso_year"),
        pl.col("signal_date").dt.week().alias("iso_week"),
    ])

    # Historical mean RRI per (site, iso_week), excluding the current year
    current_year = today.year
    hist = (
        df.filter(pl.col("iso_year") < current_year)
        .group_by(["site_id", "iso_week"])
        .agg(pl.col("reliability_risk_index").mean().alias("hist_mean_rri"))
    )

    events = []
    # Walk the next 30 days; emit at most one event per (site, week)
    emitted: set[tuple[str, int]] = set()
    for offset in range(1, horizon_days + 1):
        future_date = today + timedelta(days=offset)
        # Only suggest on Mondays (start of work week)
        if future_date.weekday() != 0:
            continue
        iso_week = future_date.isocalendar()[1]
        for row in hist.iter_rows(named=True):
            site_id = row["site_id"]
            if row["iso_week"] != iso_week:
                continue
            key = (site_id, iso_week)
            if key in emitted:
                continue
            if row["hist_mean_rri"] < ELEVATED_THRESHOLD:
                continue
            emitted.add(key)
            label = SITE_LABELS.get(site_id, site_id)
            hist_rri = row["hist_mean_rri"]
            summary = f"📅 Projected risk window — {label}"
            description = (
                f"Historical average Reliability Risk Index for week {iso_week}: "
                f"{hist_rri:.0f}/100 (threshold: {ELEVATED_THRESHOLD:.0f}).\n"
                f"Site: {label}\n"
                f"Recommendation: schedule a maintenance inspection this week.\n"
                f"Generated by the Luotea Reliability Risk Engine."
            )
            events.append(
                _vevent(
                    uid=f"luotea-proj-{site_id}-w{iso_week}-{future_date.year}@luotea.com",
                    dtstart=future_date,
                    dtend=future_date + timedelta(days=5),
                    summary=summary,
                    description=description,
                    categories=["PROJECTED", "RISK-WINDOW", "MAINTENANCE"],
                    priority=7,
                )
            )
    return events


def _elevated_site_events(today: date) -> list[str]:
    """Immediate inspection events for sites currently in ELEVATED band."""
    port = pl.read_parquet(PREDICTIONS_DIR / "portfolio_today.parquet")
    elevated = port.filter(pl.col("band") == "ELEVATED")
    events = []
    for row in elevated.iter_rows(named=True):
        site_id = row["site_id"]
        label = SITE_LABELS.get(site_id, site_id)
        rri = row["rri"]
        event_date = today + timedelta(days=1)
        summary = f"🔴 ELEVATED RISK – Urgent inspection · {label}"
        description = (
            f"Current Reliability Risk Index: {rri:.0f}/100 (ELEVATED band, threshold 70).\n"
            f"Site: {label}\n"
            f"Action: Schedule an unplanned inspection within 48 hours.\n"
            f"Source: Luotea Reliability Risk Engine · live portfolio snapshot."
        )
        events.append(
            _vevent(
                uid=f"luotea-elevated-{site_id}-{today}@luotea.com",
                dtstart=event_date,
                dtend=event_date + timedelta(days=1),
                summary=summary,
                description=description,
                categories=["ELEVATED", "URGENT", "MAINTENANCE"],
                priority=1,
            )
        )
    return events


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def generate_ics(today: date | None = None, horizon_days: int = 30) -> str:
    """
    Build and return a complete ICS calendar string.

    Parameters
    ----------
    today:
        Reference date (defaults to the latest date in portfolio_today.parquet so the
        demo works without a live run — reproducible from committed artifacts).
    horizon_days:
        How many days forward to project risk windows (default 30).
    """
    if today is None:
        port = pl.read_parquet(PREDICTIONS_DIR / "portfolio_today.parquet")
        today = port["signal_date"].max()

    vevent_blocks = (
        _elevated_site_events(today)
        + _work_order_events(today)
        + _projected_risk_events(today, horizon_days)
    )

    header = "\r\n".join([
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Luotea//Reliability Risk Engine//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Luotea Maintenance Calendar",
        _fold("X-WR-CALDESC:Risk-driven maintenance events powered by the Luotea Reliability Risk Engine"),
        "X-WR-TIMEZONE:Europe/Helsinki",
    ])

    footer = "END:VCALENDAR"

    return header + "\r\n" + "\r\n".join(vevent_blocks) + "\r\n" + footer + "\r\n"


def write_ics(output_path: Path | str | None = None, **kwargs) -> Path:
    """Write the calendar to disk and return the path."""
    if output_path is None:
        output_path = Path(__file__).parent / "sample_luotea_maintenance.ics"
    output_path = Path(output_path)
    output_path.write_text(generate_ics(**kwargs), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    path = write_ics()
    cal = path.read_text()
    n_events = cal.count("BEGIN:VEVENT")
    print(f"Written {n_events} events to {path}")
    print(f"File size: {path.stat().st_size:,} bytes")
    print("\nFirst event preview:")
    start = cal.index("BEGIN:VEVENT")
    end = cal.index("END:VEVENT") + len("END:VEVENT")
    print(cal[start:end])
