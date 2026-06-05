"""Data contracts — YAML definitions per source family."""

from pathlib import Path

CONTRACTS_DIR = Path(__file__).resolve().parent

SOURCE_CONTRACTS = {
    "alarms": CONTRACTS_DIR / "alarms.yaml",
    "work_orders": CONTRACTS_DIR / "work_orders.yaml",
    "maintenance_plans": CONTRACTS_DIR / "maintenance_plans.yaml",
    "smartti_pulse": CONTRACTS_DIR / "smartti_pulse.yaml",
    "kone_occupancy": CONTRACTS_DIR / "kone_occupancy.yaml",
    "utilization": CONTRACTS_DIR / "utilization.yaml",
}

__all__ = ["CONTRACTS_DIR", "SOURCE_CONTRACTS", "load_contract"]


def load_contract(source: str) -> dict:
    """Load a source contract YAML by name."""
    import yaml

    path = SOURCE_CONTRACTS.get(source)
    if path is None:
        raise KeyError(f"Unknown source contract: {source!r}. Known: {list(SOURCE_CONTRACTS)}")
    if not path.exists():
        raise FileNotFoundError(f"Contract file not found: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)
