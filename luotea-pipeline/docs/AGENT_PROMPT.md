# Task: Build the Luotea Hackathon Data Pipeline (Medallion Architecture)

You are a senior data engineer. Implement a **scalable, production-minded** data pipeline for the Luotea Hackathon 2026 project. Follow the architecture and phases defined in:

`Luotea-Hackathon-2026/data-pipeline-plan.md`

Treat that document as the source of truth for layers, entities, and implementation order. Do not skip phases — implement incrementally with tests and documentation at each boundary.

---

## Mission

Build a pipeline that standardizes four heterogeneous source families into **one canonical domain model** with consistent keys, types, and semantics — not one giant table, but a unified lakehouse that ML and BI can consume.

**Success criteria:**

1. Bronze → Silver → Gold runs end-to-end idempotently
2. Cross-source joins work via canonical `site_id` (even if mapping is partial)
3. Gold `site_daily_signals` is demonstrable for the jury
4. Edge cases are handled explicitly (not silently dropped)
5. Code is modular enough to add customers/sources without rewriting transforms

---

## Source Inventory (read specs before coding)

| Source | Path | Spec | Grain | Keys |
|--------|------|------|-------|------|
| Alarms | `Luotea-Hackathon-2026/Alarms/alarms.csv` | `alarms_data_spec.md` | Event | `ALERT_EVENT_ID`, `CUSTOMER_SITE_NO`, `WORKORDER_NO` |
| Work orders | `Luotea-Hackathon-2026/Work orders/work_orders_anonymized 1.csv` | `work_orders_data_spec 1.md` | Event | `WO_NO`, `PM_NO`, `CUSTOMER_SITE_NO` |
| Maintenance plans | `Luotea-Hackathon-2026/Maintenance schedule (EH-työt)/` | `scheduled_maintenance_plans_data_spec.md` | Plan | `PM_NO` |
| Smartti Pulse | `Luotea-Hackathon-2026/Smartti/*.json` | `Smartti/SPEC.md` | Hourly readings + incidents | `property.id`, `node.id` |
| KONE occupancy | `Luotea-Hackathon-2026/Smartti/kone/*-normalized.json` | `Smartti/kone/README.md` | Floor × weekday × hour | Building name only |
| Room/desk utilization | `Luotea-Hackathon-2026/need-based cleaning/` | (wide CSV) | Asset × day | Room names (`Letto`, `K2`, etc.) |

**Before writing transforms:** Read every `*_data_spec.md` and `SPEC.md`. Derive data contracts from them.

---

## Target Repository Layout

```
pipeline/
  __init__.py
  config.py                 # paths, timezone defaults, schema versions
  contracts/                # YAML/JSON data contracts per source
    alarms.yaml
    work_orders.yaml
    ...
  bronze/
    ingest.py               # generic file landing + metadata
    connectors/             # one module per source family
  silver/
    cleaners.py             # shared null/type/tz/BOM utilities
    transforms/             # one module per entity
      erp_work_orders.py
      erp_alarms.py
      smartti_readings.py
      kone_occupancy.py
      utilization.py
  gold/
    site_daily_signals.py
    event_timeline.py
  quality/
    checks.py               # Great Expectations or lightweight validators
  cli.py                    # `python -m pipeline run --layer silver`
mappings/
  sites.yaml                # canonical_site_id ↔ external IDs
  assets.yaml               # optional room/floor mappings
data/
  bronze/{source}/{ingest_date}/
  silver/{table}/
  gold/{table}/
tests/
  unit/                     # per-transform edge cases
  integration/              # bronze→gold on sample fixtures
docs/
  schema.yml                # dbt-style column docs for Gold tables
```

Use **Python 3.11+**, **Polars** (preferred) or pandas, **PyArrow/Parquet**, **DuckDB** for local queries. Keep dependencies minimal.

---

## Architecture Rules (non-negotiable)

### Bronze

- Store raw files **unchanged** (immutable)
- Attach metadata: `ingested_at`, `source_file`, `schema_version`, `source_system`, `export_date`
- Partition: `bronze/{source_system}/{ingest_date}/`
- Never mutate Bronze

### Silver

- Apply shared cleaning rules uniformly:
  - Parse types (datetime, bool, int, float)
  - Normalize nulls: `"NULL"`, `""`, `"null"`, `"None"` → `NULL`
  - Strip UTF-8 BOM from ERP CSVs
  - Convert all timestamps to **UTC**; retain `site_timezone` on dimensions
  - Deduplicate (e.g. maintenance plans on `PM_NO`)
  - Preserve Finnish text; do not corrupt encoding
  - Preserve anonymization tokens `[NAME]`, `[PHONE]`, `[EMAIL]` — never attempt re-identification

### Gold

- Idempotent: re-running produces identical output for same inputs
- Versioned partitions: `as_of_date` or snapshot date
- Document grain, PK, and column semantics in `docs/schema.yml`

### Dimensions (the glue)

- `dim_site` with canonical `site_id`
- `bridge_source_asset_map` with `confidence`, `effective_from`, `effective_to`
- Without mapping, emit rows with `site_id = NULL` and `mapping_status = 'unmapped'` — do not drop

---

## Edge Cases You MUST Handle

### Encoding & parsing

- [ ] UTF-8 BOM on ERP CSVs (alarms spec confirms this)
- [ ] Work orders file may use **semicolon delimiter** despite spec saying comma — auto-detect delimiter
- [ ] Mojibake / mixed encodings in Finnish text (ä, ö, å) — detect and fail loudly or normalize to UTF-8
- [ ] European date formats (`2.12.2019 10:00`, `d.M.yyyy H:mm`) in work orders
- [ ] Literal string `"NULL"` in alarms `WORKORDER_NO` (not SQL null)

### Schema & grain mismatches

- [ ] Same `ALERT_ID` → multiple `ALERT_EVENT_ID` rows (location fan-out) — preserve grain, document it
- [ ] Alarms and Smartti incidents are the same concept, different shape — unify in `fact_incident` with `source_system`
- [ ] KONE: normalized (0–10) vs raw counts — store `value_type` column; prefer normalized for cross-building comparison
- [ ] KONE `occupancy` array = 24 hourly values — explode to `(building, floor, month, weekday, hour, occupancy)`
- [ ] Smartti nested `readings.{metric}.data[]` — explode with `metric`, `meter_key`, `timestamp_utc`, `value`
- [ ] Meridian Tower has `children[]` sub-properties — flatten hierarchy without losing parent link
- [ ] Wide utilization CSVs: asset row × date columns → unpivot to `(asset_name, date, utilization_pct)`
- [ ] Utilization files overlap date ranges across exports — dedupe on `(asset, date)` keeping latest file

### Join & coverage gaps

- [ ] Valmet sites have ERP data; anonymized NovaProp sites have Smartti/KONE but **no ERP**
- [ ] Partial site mapping is expected — Gold aggregates must work with nullable `site_id` and per-source fallbacks
- [ ] `WORKORDER_NO` ↔ `WO_NO` linkage is sparse — left join, track `has_work_order` flag
- [ ] Work orders ↔ maintenance plans via `PM_NO` — handle null `PM_NO` on on-demand work
- [ ] Room names (`Letto`, `Karhu`) have no ERP key — map via `mappings/assets.yaml` or leave unmapped

### Data quality

- [ ] Duplicate maintenance plan rows — dedupe on `PM_NO`, log count removed
- [ ] Priority enum validation: `{1, 50, 60, 77, 99}` for alarms
- [ ] `ALERT_EVENT_ID` uniqueness
- [ ] Referential: `% rows with valid site_id` tracked, alert if < 99% for mapped sources
- [ ] Freshness: warn if source file older than expected
- [ ] PII scan on Gold: no raw emails/names outside `[NAME]` tokens

### Time zones

- [ ] Smartti readings: UTC (per SPEC)
- [ ] ERP events: local Finland time — convert using `Europe/Helsinki` unless site timezone known
- [ ] KONE profiles: no absolute timestamp — synthetic `(year, month, weekday, hour)` for joining to daily grain

---

## Implementation Phases (strict order)

### Phase 1 — Contracts & config (no transforms yet)

1. Catalog all sources with refresh cadence, PII rules, PK, nullable columns
2. Write `pipeline/contracts/*.yaml` per source
3. Create `mappings/sites.yaml` with at least:
   - `site_valmet_l11` ↔ ERP `998389833` (Lentokentänkatu 11)
   - `site_aurora` ↔ Smartti `aurora_house` ↔ KONE `Aurora House`
   - (add Meridian, Horizon similarly)
4. Define canonical domain model types (dataclasses or Pandera/Pydantic schemas)

### Phase 2 — Bronze ingestion

1. Generic ingest: copy file + write sidecar metadata JSON
2. One connector per source family
3. CLI: `pipeline ingest --source alarms --date 2026-06-05`

### Phase 3 — Silver ERP (highest ROI first)

1. `silver.fact_work_order`, `silver.fact_alarm`, `silver.fact_maintenance_plan`
2. `silver.dim_customer`, `silver.dim_site` (from ERP + mapping enrichment)
3. Unit tests for: BOM, `"NULL"`, delimiter detection, Finnish dates, dedup

### Phase 4 — Silver IoT / third-party

1. Smartti reading explosion → `silver.fact_sensor_reading`
2. Smartti incidents → `silver.fact_incident`
3. KONE flatten → `silver.fact_occupancy`
4. Utilization unpivot → `silver.fact_utilization`

### Phase 5 — Gold

1. **`gold.site_daily_signals`** — one row per `site_id × date`:
   - `alarm_count`, `fire_alarm_count`, `hvac_alarm_count`
   - `open_work_orders`, `sla_violations`
   - `avg_co2_ppm`, `avg_indoor_temp_c`, `electricity_kwh`, `heating_mwh` (where available)
   - `avg_room_utilization_pct`, `avg_desk_utilization_pct`
   - `avg_elevator_occupancy`
   - `incident_count`, `unresolved_incident_count`
2. `gold.event_timeline` — union alarms, WO events, incidents with `event_type`, `severity`, `timestamp_utc`
3. Write `docs/schema.yml` with column definitions and grain

### Phase 6 — Quality & orchestration

1. Run checks at Silver/Gold boundaries (schema drift, uniqueness, referential, ranges)
2. DAG via simple Makefile or Prefect flow:

   ```
   ingest_* → silver_* → build_dims → build_gold → quality_checks
   ```

3. Log all quarantined/rejected rows to `data/quarantine/` with reason

---

## Code Quality Requirements

- **Single responsibility:** one transform module per source entity
- **Pure functions:** transforms take DataFrame in, return DataFrame out; no hidden globals
- **Explicit over clever:** no magic string column names scattered — use constants or contracts
- **Fail loud:** invalid enum, unparseable date, schema drift → raise with file/row context
- **Observability:** log row counts in/out, null rates, mapping hit rate per run
- **No premature Spark:** design interfaces so Spark/dbt can replace Polars later, but keep MVP local
- **Tests required:** every edge case listed above gets at least one unit test with a minimal fixture

---

## Deliverables Checklist

- [ ] `pipeline/` package runnable via CLI
- [ ] `mappings/sites.yaml` with cross-source site links
- [ ] Bronze landing for all 6 source families
- [ ] Silver tables per domain entity (10 tables from plan)
- [ ] `data/gold/site_daily_signals.parquet` joinable in DuckDB
- [ ] `docs/schema.yml` documenting Gold
- [ ] `tests/` with ≥80% coverage on cleaning utilities and ERP transforms
- [ ] `README.md` in `pipeline/` with: how to run, architecture diagram, known limitations

---

## How to Work

1. **Read** `data-pipeline-plan.md` and all `*_data_spec.md` files fully
2. **Inspect** actual data samples (first 100 rows + random sample) before assuming schema
3. **Implement Phase 1** and pause for contract review if ambiguous
4. **Implement incrementally** — each phase should run and produce queryable Parquet before moving on
5. **Do not** force all sources into one table; build the canonical model with bridge tables
6. **Do not** drop unmapped rows; quarantine only truly invalid rows
7. When a spec contradicts the file (delimiter, encoding), **trust the file** and update the contract

---

## Out of Scope (for MVP)

- Real-time streaming ingestion
- Translation of Finnish text to English
- ML model training (only feature-ready Gold tables)
- Cloud deployment (local Parquet + DuckDB is fine)

---

## Definition of Done

I can run:

```bash
pip install -e .
python -m pipeline run --full
duckdb -c "SELECT site_id, date, alarm_count, open_work_orders, avg_room_utilization_pct FROM read_parquet('data/gold/site_daily_signals.parquet') ORDER BY date DESC LIMIT 20"
```

…and see sensible, documented, partially-null-but-not-broken results across Valmet ERP sites and anonymized Smartti/KONE sites.
