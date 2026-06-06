"""Central config — all paths relative to repo root."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_DATA = REPO_ROOT / "luotea-pipeline" / "data"

GOLD_DAILY = PIPELINE_DATA / "gold" / "site_daily_signals" / "site_daily_signals.parquet"
GOLD_EVENTS = PIPELINE_DATA / "gold" / "event_timeline" / "event_timeline.parquet"
SILVER_DIR = PIPELINE_DATA / "silver"
SILVER_WORK_ORDERS = SILVER_DIR / "fact_work_order" / "fact_work_order.parquet"

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "outputs"
FIGURES_DIR = OUTPUT_DIR / "figures"
METRICS_DIR = OUTPUT_DIR / "metrics"
PREDICTIONS_DIR = OUTPUT_DIR / "predictions"
MODELS_DIR = OUTPUT_DIR / "models"

for d in [FIGURES_DIR, METRICS_DIR, PREDICTIONS_DIR, MODELS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

RANDOM_SEED = 42

SITE_VALMET_L11 = "site_valmet_l11"
SITE_AURORA = "site_aurora"

# Feature columns per site (nulls handled per-site in feature engineering)
VALMET_L11_FEATURES = [
    "alarm_count", "fire_alarm_count", "hvac_alarm_count",
    "open_work_orders", "sla_violations",
    "avg_room_utilization_pct", "avg_desk_utilization_pct",
]
AURORA_FEATURES = [
    "electricity_kwh", "heating_mwh",
    "avg_co2_ppm", "avg_indoor_temp_c",
    "incident_count",
]

# -- SLA-breach model (hero use case) ----------------------------------------
# Target label in fact_work_order.
SLA_TARGET = "is_sla_violation"

# Features known AT WORK-ORDER CREATION TIME (no leakage from completion).
# Categorical features (one-hot encoded; nulls become an explicit category).
SLA_CAT_FEATURES = [
    "work_type_eng",        # 39 service categories (cleaning, HVAC repair, fire, …)
    "work_order_type",      # Tilaustyö (order) vs EH-työ (preventive)
    "contract_type",        # SP / KIPA / KH / KT
    "assignment_type",      # DS-osoitus / Manuaalinen osoitus / null
    "priority_id_str",      # 1–6 or "unknown" (72% null, but informative)
    "site_id",              # cross-site generalization
]
# Numeric / boolean features known at creation time.
SLA_NUM_FEATURES = [
    "is_subcontractor_work",
    "is_invoicable",
    "start_month",          # seasonality
    "start_weekday",        # Mon=1 … Sun=7
    "start_is_weekend",
    "start_year",           # captures (and is robust to) regime drift
    "sla_window_hours",     # contractual allowed duration (mostly 0; long windows matter)
    "site_open_wo_at_start",  # operational backlog/load context on creation day
]

# Columns that MUST NEVER be used as features (only known after completion).
SLA_LEAKAGE_COLS = [
    "work_finished_at_utc", "work_finished_days", "worktime_hours",
    "work_order_performed_action", "is_sla_violation",
]

# Time-based split: fraction of the (chronologically sorted) rows used for the
# held-out test period. No shuffling — the most recent slice is the test set.
SLA_TEST_FRACTION = 0.2

# Dispatch-capacity points for precision@k reporting (share of backlog acted on).
PRECISION_AT_K = [0.05, 0.10, 0.20, 0.30]
