"""Pipeline configuration: paths, timezone defaults, schema versions."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent
HACKATHON_DATA_ROOT = REPO_ROOT / "Luotea-Hackathon-2026"
DATA_DIR = PROJECT_ROOT / "data"
BRONZE_DIR = DATA_DIR / "bronze"
SILVER_DIR = DATA_DIR / "silver"
GOLD_DIR = DATA_DIR / "gold"
QUARANTINE_DIR = DATA_DIR / "quarantine"
QA_DIR = DATA_DIR / "qa"
MAPPINGS_DIR = PROJECT_ROOT / "mappings"
CONTRACTS_DIR = Path(__file__).resolve().parent / "contracts"
DOCS_DIR = PROJECT_ROOT / "docs"

DEFAULT_TIMEZONE = "Europe/Helsinki"
SCHEMA_VERSION = "0.1.0"
