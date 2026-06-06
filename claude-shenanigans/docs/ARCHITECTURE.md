# Architecture — how the Reliability Risk Engine sits on the pipeline

```
 RAW (unchanged)            luotea-pipeline (read-only)                 claude-shenanigans (this repo)
┌──────────────┐   ingest  ┌────────────┐  transform  ┌──────────┐
│ ERP CSV      │──────────▶│  Bronze    │────────────▶│  Silver  │   fact_work_order ─┐
│ Smartti JSON │           │ (immutable)│             │ (typed)  │   fact_alarm       │
│ KONE JSON    │           └────────────┘             └────┬─────┘   fact_sensor …    │
│ Cleaning CSV │                                            │ gold                     │
└──────────────┘                                       ┌────▼──────────────┐           │
                                                        │  Gold marts       │           │
                                                        │ site_daily_signals│───────────┤
                                                        │ event_timeline    │           │
                                                        └────────┬──────────┘           │
                                                          qa gate │ PASS                 │
                                                                  ▼                      ▼
                                                            (we consume) ───────▶  features ─▶ model ─▶ index ─▶ demo
```

We add **one thin, additive layer** on top of Gold/Silver. We never modify, re-run, or
re-ingest the pipeline — the QA-gated Parquet is our contract.

## Components (this repo)

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Config | `src/config.py` | All paths into `../luotea-pipeline/data`, feature lists, split params, seeds |
| Data | `src/data/loader.py` | Read-only Polars loaders for Gold daily, event timeline, Silver work orders |
| Features | `src/features/work_orders.py` | **Leakage-safe** creation-time features + chronological split |
| Features | `src/features/reliability_index.py` | Cross-site daily **Reliability Risk Index** (0–100) |
| Features | `src/features/assignment.py` | **Task attribution** — assign risk-ranked work orders to the right-skilled, least-loaded crew member |
| Model | `src/models/sla_risk.py` | sklearn pipeline (OHE + HistGradientBoosting), baselines, metrics |
| Model | `src/models/train_sla.py` | Train, evaluate on held-out future, save artifacts + figures |
| Model | `src/models/anomaly.py`, `train.py` | Supporting unsupervised anomaly flag (Isolation Forest) |
| Demo | `src/demo/build_demo_artifacts.py` | Precompute index, dispatch list, summary, cross-site figures |
| Demo | `src/demo/app.py` | Streamlit UI, **mobile-responsive** (5 tabs: Manager, My tasks, Reliability, Model card, Unified data) |

## The ML contract (hero model)

**Question** — *at the moment a work order is created*, how likely is it to **breach its SLA**?

- **Label:** `is_sla_violation` (Silver `fact_work_order`; 44,265 rows, 0 nulls, 53.8 % positive).
- **Features (14, creation-time only):** `work_type_eng`, `work_order_type`, `contract_type`,
  `assignment_type`, `priority_id` (null→"unknown"), `site_id`, `is_subcontractor_work`,
  `is_invoicable`, month / weekday / weekend / year of creation, contractual SLA-window hours,
  and the site's open-WO backlog that day (from Gold).
- **Leakage control:** `worktime_hours`, `work_finished_*`, `work_order_performed_action` and the
  label itself are listed in `SLA_LEAKAGE_COLS` and **asserted absent** from the feature frame
  (`_assert_no_leakage`, covered by `tests/test_features.py`).
- **Split:** time-based — earliest 80 % train, most-recent 20 % test
  (test = 2025-01-24 → 2026-06-01). No shuffling → always evaluated on the future.
- **Model:** `OneHotEncoder(min_frequency=20)` + `HistGradientBoostingClassifier`
  (handles NaN natively, fast, strong on tabular FM data).
- **Baselines:** majority class · **priority-rate rule** (what a team could do by hand) · logistic
  regression. The model must beat them (enforced by `tests/test_model.py`).

### Held-out results (see `outputs/metrics/sla_risk_metrics.json`)

| Model | ROC-AUC | PR-AUC | F1 | Brier | Prec@10 % |
|-------|:------:|:-----:|:--:|:-----:|:---------:|
| Majority class | 0.50 | — | — | — | base rate |
| Priority-rate rule | 0.640 | 0.687 | — | — | — |
| **HistGradientBoosting** | **0.704** | **0.771** | **0.811** | **0.187** | **0.868** |

Acting on the **riskiest 10 %** of work orders catches **768** breaches at **86.8 %** precision
(vs a 61 % base rate); the riskiest **5 %** are **99.5 %** precise.

**Interpretation (top permutation features):** the strongest driver is the **SLA-window
structure** — work orders with no formal deadline breach only ~23 %, same-day deadlines ~62 %,
and longer explicit windows ~81 % — followed by **contract type**, **assignment type**, **work
type**, and **priority**. This is an operational finding, not a leak: the deadline is set at
creation; the breach is decided later by the actual finish time.

## The Reliability Risk Index

`compute_reliability_index` turns per-work-order predictions into a **site-level daily signal** and
fuses it with the other domains, so a single 0–100 number describes any site:

```
RRI(site, day) = 100 × weighted mean over PRESENT components of:
    maintenance_risk   = Σ model breach-probability of WOs created that day   (ERP)
    alarm_pressure     = fire×3 + hvac×2 + other alarms                        (ERP)
    energy_anomaly     = |kWh − 28-day median| / 28-day MAD                     (IoT)
    incident_pressure  = incidents + 3 × unresolved incidents                   (IoT)
```

Each component is percentile-ranked **within the site**, so RRI reads as *"how risky is today
relative to this site's own normal"* — 90 means a top-decile risk day on **any** site, which is
exactly the "distinguish normal variation from elevated risk" the brief asks for. Weights
re-normalise over whichever components a site actually has, so partial coverage never breaks it.

## Reproducibility & ops

- Fixed `RANDOM_SEED = 42`; deterministic time split; artifacts written to `outputs/`.
- One-command flows via `Makefile` (`make demo`, `make app`); pinned `requirements.txt`.
- 12 tests cover loaders, the no-leakage guarantee, split integrity, index bounds, and the
  model-beats-baseline claim.
- See [`SCALING.md`](./SCALING.md) for the production path.
