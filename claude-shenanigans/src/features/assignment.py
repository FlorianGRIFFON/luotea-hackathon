"""
Task attribution — turn risk-ranked work orders into per-worker assignments.

This is the operations bridge: predictive maintenance ranks the backlog by SLA-breach risk,
and we *attribute* each task to the right crew member by skill, balancing load so the riskiest
jobs are spread across the team first. It powers two user-facing views:

  * Manager  — global picture: who is loaded, where the high-risk work sits.
  * Maintainer (cleaner / technician / …) — "my tasks today", risk-ordered, with a plain reason.

Pure functions over a Polars frame; no I/O, so it is unit-testable.
"""
from __future__ import annotations

import polars as pl

# Map the ERP work-type (English) to a maintenance role.
ROLE_RULES: list[tuple[str, str]] = [
    ("clean", "Cleaner"),
    ("security", "Security"),
    ("outdoor", "Groundskeeper"),
    ("green", "Groundskeeper"),
    ("winter", "Groundskeeper"),
    ("ventil", "HVAC technician"),
    ("heating", "HVAC technician"),
    ("electr", "Electrician"),
    ("technical", "Technician"),
    ("repair", "Technician"),
    ("periodic", "Technician"),
    ("workplace", "Facility services"),
    ("premises", "Facility services"),
]

# A small synthetic crew (2 per common role) — stands in for the customer's real roster.
CREW: dict[str, list[str]] = {
    "Cleaner": ["Aino (Cleaner)", "Eero (Cleaner)"],
    "Technician": ["Mika (Technician)", "Jukka (Technician)"],
    "HVAC technician": ["Sanna (HVAC)"],
    "Electrician": ["Petri (Electrician)"],
    "Security": ["Liisa (Security)"],
    "Groundskeeper": ["Ville (Grounds)"],
    "Facility services": ["Outi (Facility)"],
}


def role_for(work_type: str | None) -> str:
    wt = (work_type or "").lower()
    for needle, role in ROLE_RULES:
        if needle in wt:
            return role
    return "Technician"  # safe default — general maintenance


def assign_tasks(dispatch: pl.DataFrame) -> pl.DataFrame:
    """
    Attribute each work order (rows already carry `breach_risk_pct`, `risk_band`,
    `work_type_eng`) to a crew member of the matching role, balancing count within the role.
    Processing in risk-descending order means the riskiest jobs are dealt out first.

    Returns the input columns + `role` and `assigned_to`.
    """
    df = dispatch.sort("breach_risk_pct", descending=True)
    loads: dict[str, int] = {w: 0 for members in CREW.values() for w in members}
    roles, workers = [], []
    for r in df.iter_rows(named=True):
        role = role_for(r["work_type_eng"])
        members = CREW.get(role) or CREW["Technician"]
        # least-loaded member in this role (ties broken by roster order)
        worker = min(members, key=lambda m: loads[m])
        loads[worker] += 1
        roles.append(role)
        workers.append(worker)
    return df.with_columns(pl.Series("role", roles), pl.Series("assigned_to", workers))


def crew_workload(assigned: pl.DataFrame) -> pl.DataFrame:
    """Per-worker summary for the manager view."""
    return (
        assigned.group_by("assigned_to", "role")
        .agg(
            pl.len().alias("tasks"),
            (pl.col("risk_band") == "HIGH").sum().alias("high_risk"),
            pl.col("breach_risk_pct").max().round(0).alias("top_risk_pct"),
        )
        .sort(["high_risk", "tasks"], descending=True)
    )
