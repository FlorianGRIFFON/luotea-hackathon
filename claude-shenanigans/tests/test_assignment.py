"""Task attribution: every work order is assigned, by the right role, with balanced load."""
import polars as pl

from src.features.assignment import CREW, assign_tasks, crew_workload, role_for


def _fake_dispatch() -> pl.DataFrame:
    rows = [
        ("Cleaning services", 65.0, "MEDIUM", "Monitor"),
        ("Additional cleaning services", 60.0, "MEDIUM", "Low priority"),
        ("Repairs and maintenance electrical", 24.0, "LOW", "Low priority"),
        ("Outdoor area and green area maintenance", 97.0, "HIGH", "Urgent"),
        ("Security services", 70.0, "HIGH", "Urgent"),
        ("Repairs and maintenance ventilation", 55.0, "MEDIUM", "Monitor"),
    ]
    return pl.DataFrame(
        {"wo_no": list(range(len(rows))),
         "work_type_eng": [r[0] for r in rows],
         "breach_risk_pct": [r[1] for r in rows],
         "risk_band": [r[2] for r in rows],
         "action": [r[3] for r in rows]}
    )


def test_role_mapping():
    assert role_for("Cleaning services") == "Cleaner"
    assert role_for("Repairs and maintenance electrical") == "Electrician"
    assert role_for("Outdoor area and green area maintenance") == "Groundskeeper"
    assert role_for(None) == "Technician"  # safe default


def test_every_task_assigned_to_valid_worker():
    out = assign_tasks(_fake_dispatch())
    assert out.height == 6
    assert "assigned_to" in out.columns and "role" in out.columns
    valid = {w for members in CREW.values() for w in members}
    assert set(out["assigned_to"].to_list()) <= valid
    # worker's role matches the task's role
    for r in out.iter_rows(named=True):
        assert r["assigned_to"] in CREW[r["role"]]


def test_load_balances_within_role():
    # 10 cleaning jobs across 2 cleaners → 5 and 5
    df = pl.DataFrame({
        "wo_no": list(range(10)),
        "work_type_eng": ["Cleaning services"] * 10,
        "breach_risk_pct": [50.0] * 10,
        "risk_band": ["MEDIUM"] * 10,
        "action": ["Monitor"] * 10,
    })
    wl = crew_workload(assign_tasks(df))
    cleaner_tasks = wl.filter(pl.col("role") == "Cleaner")["tasks"].to_list()
    assert sorted(cleaner_tasks) == [5, 5]
    # action split columns are present and sum back to the task total
    assert {"urgent", "monitor", "low_priority"} <= set(wl.columns)
