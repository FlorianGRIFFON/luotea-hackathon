# Luotea Data Pipeline — Overview

This document explains **what the pipeline is**, **what it does**, **what it enables**, and **why we built it** for the Luotea Hackathon 2026 project.

For run instructions, see [pipeline/README.md](../pipeline/README.md).  
For column-level Gold schema, see [schema.yml](./schema.yml).  
For autonomous QA, see [QA_AGENT_PLAYBOOK.md](./QA_AGENT_PLAYBOOK.md).

---

## What is the pipeline?

The **Luotea data pipeline** (`luotea-pipeline/`) is a local, medallion-style data pipeline that takes heterogeneous facility-management data from the hackathon dataset and produces **clean, joinable, analysis-ready tables**.

It follows the **Bronze → Silver → Gold** pattern:

| Layer | Role | Output location |
|-------|------|-----------------|
| **Bronze** | Immutable copy of raw files + ingest metadata | `data/bronze/{source}/{date}/` |
| **Silver** | Cleaned, typed, conformed tables per domain | `data/silver/{table}/` |
| **Gold** | Business-ready marts for dashboards, analytics, and ML | `data/gold/` |

Raw source files stay in `Luotea-Hackathon-2026/` and are never modified. All pipeline output lives under `luotea-pipeline/data/`.

---

## The problem we started with

Luotea's hackathon data comes from **four different worlds** that were never designed to be joined:

| Source family | Format | Example grain | Identity system |
|---------------|--------|---------------|-----------------|
| ERP (alarms, work orders, maintenance) | CSV | One row per event/plan | `CUSTOMER_NO`, `CUSTOMER_SITE_NO` |
| Smartti Pulse | Nested JSON | Hourly sensor readings + incidents | `property.id`, `node.id` |
| KONE elevator occupancy | JSON arrays | Floor × weekday × hour profiles | Building name |
| Need-based cleaning | Wide CSV | Room/desk × day | Asset names (`Letto`, `K2`, …) |

Additional friction:

- **Different sites, different coverage** — Valmet industrial sites have ERP data; NovaProp buildings have Smartti/KONE but no ERP.
- **Data quality quirks** — UTF-8 BOM, semicolon-delimited work orders (cp1252), literal `"NULL"` strings, duplicate maintenance plan rows, Finnish free text, mixed time zones.
- **Same concept, different shape** — e.g. alarms in ERP CSV vs Smartti incidents.

Without a pipeline, answering a simple question like *"How did alarms, open work orders, and electricity use compare at this site last month?"* requires manual joins across incompatible formats and ID systems.

---

## What the pipeline does

### 1. Ingest (Bronze)

Copies all structured source files into a dated Bronze partition and records row counts, file sizes, and manifests.

**Sources ingested (6 families):**

- ERP alarms, work orders, maintenance plans
- Smartti Pulse JSON (3 buildings)
- KONE occupancy JSON
- Room utilization CSVs

### 2. Transform (Silver)

Cleans and standardizes each source into typed Parquet tables:

| Silver table | Source | Rows (approx.) |
|--------------|--------|----------------|
| `fact_alarm` | Alarms CSV | 18,702 |
| `fact_work_order` | Work orders CSV | 44,265 |
| `fact_maintenance_plan` | Maintenance CSV | 106 (deduped from 316) |
| `fact_sensor_reading` | Smartti JSON | 792,506 |
| `fact_incident` | Smartti JSON | 474 |
| `fact_occupancy` | KONE JSON | 60,480 |
| `fact_utilization` | Utilization CSV | 23,864 |
| `dim_site`, `dim_customer` | Mapping + ERP | 7 sites, 3 customers |

Cleaning includes: BOM stripping, encoding detection, `"NULL"` → null, Finnish date/boolean parsing, timezone normalization to UTC, site ID enrichment via `mappings/sites.yaml`, and deduplication where contracts require it.

### 3. Build marts (Gold)

Joins and aggregates Silver tables into four deliverables. Build order matters: `site_rolling_context` reads from `site_daily_signals` and must be built last.

#### `fact_work_order.parquet`

Silver `fact_work_order` enriched with a `severity` column that classifies each work type into one of four business tiers:

| Severity | Description | Examples |
|----------|-------------|---------|
| `Critical` | Life safety & fire compliance — highest legal/financial penalties | Fire safety, fire alarms, sprinklers, security services |
| `High` | Core habitability & urgent safety — risk of building shutdown or injury | Electrical, heating & water, ventilation, winter maintenance |
| `Medium` | Preventative maintenance & project services — operational backlog risk | Periodic/preventive maintenance, project services, energy management |
| `Low` | Routine & aesthetic maintenance — minor SLA impact | Cleaning, landscaping, workplace & premises services |

Severity lives in Gold (not Silver) because it is a business classification, not a data-cleaning operation — updating the taxonomy requires only a Gold rebuild.

#### `site_daily_signals.parquet`

**One row per `site_id × signal_date`** — a unified daily operational view:

- ERP: `alarm_count`, `fire_alarm_count`, `hvac_alarm_count`, `open_work_orders`, `sla_violations`
- Smartti: `avg_co2_ppm`, `avg_indoor_temp_c`, `electricity_kwh`, `heating_mwh`, `incident_count`
- KONE: `avg_elevator_occupancy`
- Cleaning: `avg_room_utilization_pct`, `avg_desk_utilization_pct`

Sites without a given data source keep **null** for those metrics (never dropped). Used for dashboards, trend analysis, and as the input to `site_rolling_context`.

#### `event_timeline.parquet`

A unified timeline of **alarms, work order lifecycle events, and Smartti incidents** with `event_type`, `severity`, and `timestamp_utc` (~107k rows).

#### `site_rolling_context.parquet`

**One row per `site_id × date`** — rolling 7-day aggregates of site signals, purpose-built as a feature table for ML models.

Built from `site_daily_signals` by computing a 7-day rolling window per site, sorted chronologically:

| Column | Aggregation | What it captures |
|--------|-------------|-----------------|
| `open_wo_7d_avg` | Mean | Average open work orders — team workload trend |
| `sla_violations_7d` | Sum | Total SLA violations — cumulative pressure |
| `alarms_7d_avg` | Mean | Average daily alarms — site noise level |
| `fire_alarms_7d` | Sum | Total fire/priority-1 alarms — safety events |
| `incidents_7d` | Sum | Total Smartti incidents — cross-source signal |
| `utilization_7d_avg` | Mean | Average room utilization — building busyness trend |

Means are used for level signals; sums for rare event signals where the cumulative count matters more than the daily average. The ML layer joins on `work_order.site_id + (start_date − 1 day)` to get pre-computed context with no leakage.

### 4. Validate (Quality / QA)

Automated checks at Silver and Gold boundaries:

- Row counts vs data specs
- Primary key uniqueness
- Site mapping hit rates
- No literal `"NULL"` in cleaned columns
- Gold grain integrity
- PII scan on Gold outputs
- Idempotent reruns

Results are written to `data/qa/qa_report_{date}.json`. Failed rows go to `data/quarantine/`.

---

## Why we built it this way

### One canonical model, not one giant table

Forcing alarms, sensor readings, and utilization into a single wide table would break grain and semantics. Instead, the pipeline produces:

- **Normalized facts** in Silver (one table per entity)
- **Purpose-built marts** in Gold (daily signals + event timeline)
- A shared **`site_id`** join key across sources via `mappings/sites.yaml`

This mirrors how production lakehouses scale when new customers and sources are added.

### Medallion architecture

| Benefit | Explanation |
|---------|-------------|
| **Reproducibility** | Bronze preserves raw inputs; you can replay transforms without re-fetching files |
| **Debuggability** | Quality issues can be traced Bronze → Silver → Gold |
| **Separation of concerns** | Ingest, clean, and aggregate are independent steps |
| **ML-ready path** | Gold tables are feature-ready; Silver holds row-level detail for custom models |

### Explicit handling of real-world messiness

The pipeline was built against **actual files**, not idealized specs:

- Work orders use **semicolon + cp1252**, not comma + UTF-8 as some docs suggest
- Maintenance plans are **deduped by `PM_NO`** (316 bronze → 106 silver)
- Utilization filenames use **DDMMYY** date ranges
- Mojibake in Finnish text is repaired where possible

Contracts in `pipeline/contracts/*.yaml` document what we verified in the files.

### Partial mapping is a feature, not a bug

Not every site has every source. The pipeline **keeps all rows** and uses nulls for missing domains rather than dropping unmapped or incomplete data. That reflects real multi-customer operations where Valmet has ERP + utilization and NovaProp has Smartti + KONE.

---

## What does it allow us to do?

### Cross-source analysis at site level

Query one Gold table to compare operational signals across domains:

```sql
SELECT site_id, signal_date, alarm_count, open_work_orders,
       electricity_kwh, avg_room_utilization_pct
FROM read_parquet('data/gold/site_daily_signals.parquet')
WHERE site_id = 'site_valmet_l11'
ORDER BY signal_date DESC
LIMIT 30;
```

### Event-level investigation

Drill into individual alarms, work orders, and incidents:

```sql
SELECT event_type, severity, timestamp_utc, description
FROM read_parquet('data/gold/event_timeline.parquet')
WHERE site_id = 'site_aurora'
ORDER BY timestamp_utc DESC
LIMIT 50;
```

### Row-level detail in Silver

For custom analytics or ML feature engineering, Silver Parquet tables retain full cleaned granularity (every alarm, every sensor reading, every utilization row).

### Demonstrable unified view for the hackathon

Two sites illustrate the value:

| Site | What Gold shows |
|------|-----------------|
| **`site_valmet_l11`** (Tampere) | ERP alarms + work orders + room/desk utilization |
| **`site_aurora`** (NovaProp) | Smartti energy/climate + KONE elevator + incidents; zero ERP alarms |

Together they prove the pipeline can unify **real ERP data** and **anonymized IoT data** under one model.

### Foundation for ML and BI

The Gold layer provides two complementary feature sources for ML:

- `site_daily_signals` — raw daily metrics per site, suitable for dashboards, anomaly detection, energy/operations reporting, and as a source for derived tables.
- `site_rolling_context` — pre-computed 7-day rolling aggregates, ready to join directly into ML feature pipelines without any additional transformation. Currently used by the SLA violation prediction models (`luotea-ml/`).

Both tables use `site_id + date` as the join key, making them suitable for:

- Anomaly detection (alarm spikes vs utilization trends)
- Predictive maintenance signals
- Energy/operations dashboards
- Cross-customer benchmarking (when more sites are mapped)

### Automated quality gate

`pipeline qa --date 2026-06-05` runs the full flow and produces a pass/fail report — suitable for CI, agent self-checks, or demo confidence before presenting results.

---

## What is *not* in the pipeline

These hackathon assets are **out of scope** for the current MVP:

| Asset | Reason |
|-------|--------|
| Cleaning robot PNGs | Visual assets, not tabular data |
| Marketing / logo files | Not operational data |
| Separate `Valmet_desk_utilization_*.csv` files | Not wired in Bronze ingest; desk metrics come from room utilization files where assets are named `K1`, `K2`, etc. |
| Real-time streaming | Batch export only |
| Finnish → English translation | Text preserved as-is |

---

## How to run it

```bash
cd luotea-pipeline
pip install -e ".[dev]"

# Full run with QA gate (recommended)
python -m pipeline qa --date 2026-06-05

# Or step by step
python -m pipeline ingest --source all --date 2026-06-05
python -m pipeline transform --layer silver --domain all --date 2026-06-05
python -m pipeline transform --layer gold --date 2026-06-05
python -m pipeline validate --date 2026-06-05
```

---

## Where to find outputs

| Need | Path |
|------|------|
| Work orders with severity classification | `data/gold/fact_work_order.parquet` |
| Daily site dashboard data | `data/gold/site_daily_signals.parquet` |
| Event timeline | `data/gold/event_timeline.parquet` |
| ML site context features (7-day rolling) | `data/gold/site_rolling_context.parquet` |
| Cleaned row-level tables | `data/silver/{table}/{table}.parquet` |
| Raw landed copies | `data/bronze/{source}/{date}/` |
| QA pass/fail report | `data/qa/qa_report_{date}.json` |
| Site crosswalk | `mappings/sites.yaml` |
| Source contracts | `pipeline/contracts/*.yaml` |

---

## Architecture diagram

```
Luotea-Hackathon-2026/          Raw CSV & JSON (unchanged)
        │
        ▼ ingest
   data/bronze/                  Immutable copies + manifests
        │
        ├── Silver ERP ──► fact_alarm, fact_work_order, fact_maintenance_plan
        │                  dim_customer, dim_site
        │
        └── Silver IoT ──► fact_sensor_reading, fact_incident,
                           fact_occupancy, fact_utilization
        │
        ▼ gold
   data/gold/                    fact_work_order  (Silver + severity classification)
                                 site_daily_signals, event_timeline
                                 site_rolling_context  (built from site_daily_signals)
        │
        ▼ qa / validate
   data/qa/                      qa_report_{date}.json
   data/quarantine/              rejected rows (if any)
```

**Join key:** `site_id` from `mappings/sites.yaml` links Valmet ERP sites, NovaProp Smartti properties, KONE buildings, and utilization assets.

---

## Related documentation

| Document | Purpose |
|----------|---------|
| [data-pipeline-plan.md](./data-pipeline-plan.md) | Original architecture plan and ML rationale |
| [AGENT_PROMPT.md](./AGENT_PROMPT.md) | Implementation spec for builders |
| [schema.yml](./schema.yml) | Gold column definitions |
| [QA_AGENT_PLAYBOOK.md](./QA_AGENT_PLAYBOOK.md) | How to run and interpret QA |
| [pipeline/README.md](../pipeline/README.md) | Setup and CLI reference |

---

## Summary

The Luotea pipeline turns **six incompatible source families** into a **single canonical model** with shared site keys, clean types, and two Gold marts ready for querying, dashboards, and ML. We built it to solve the real problem of multi-source facility data — uneven coverage, messy encodings, and different ID systems — without pretending every site has every metric. The result is reproducible, testable, and demonstrable on both Valmet ERP sites and anonymized NovaProp IoT sites.
