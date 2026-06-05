# Luotea Data Pipeline

Medallion-style data pipeline (Bronze → Silver → Gold) for the Luotea Hackathon 2026 project.

See [data-pipeline-plan.md](../docs/data-pipeline-plan.md) and [AGENT_PROMPT.md](../docs/AGENT_PROMPT.md) for architecture, phases, and implementation order.

Raw hackathon source files live in `../Luotea-Hackathon-2026/`; pipeline code and runtime data live in this project folder.

## Setup

```bash
cd luotea-pipeline
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Ensure hackathon data is present at `../Luotea-Hackathon-2026/` (alarms, work orders, Smartti JSON, KONE JSON, utilization CSVs).

## Full pipeline run

Runs the complete DAG: **ingest → Silver ERP → Silver IoT → Gold → quality checks**.

```bash
python -m pipeline run --full --date 2026-06-05
```

Or via Makefile:

```bash
make full DATE=2026-06-05
```

Exit code is **0** when all quality checks pass, **1** otherwise. Rejected rows are written to `data/quarantine/` with a `.meta.json` sidecar explaining the failure.

## Individual commands

```bash
# Bronze — land raw files (one source or all)
python -m pipeline ingest --source alarms --date 2026-06-05
python -m pipeline ingest --source all --date 2026-06-05

# Silver — ERP and/or IoT transforms
python -m pipeline transform --layer silver --domain erp --date 2026-06-05
python -m pipeline transform --layer silver --domain iot --date 2026-06-05
python -m pipeline transform --layer silver --domain all --date 2026-06-05

# Gold — site_daily_signals + event_timeline
python -m pipeline transform --layer gold --date 2026-06-05
```

## Query Gold output (DuckDB)

```bash
duckdb -c "SELECT site_id, signal_date, alarm_count, open_work_orders, avg_room_utilization_pct FROM read_parquet('data/gold/site_daily_signals.parquet') ORDER BY signal_date DESC LIMIT 20"
```

## Architecture

```
Luotea-Hackathon-2026/          (raw source files)
        │
        ▼
   Bronze ingest                data/bronze/{source}/{date}/
        │
        ├── Silver ERP           fact_alarm, fact_work_order, fact_maintenance_plan
        │                        dim_customer, dim_site
        ├── Silver IoT           fact_sensor_reading, fact_incident,
        │                        fact_occupancy, fact_utilization
        ▼
   Gold marts                    site_daily_signals, event_timeline
        │
        ▼
   Quality checks                schema, uniqueness, referential, ranges, PII scan
        │
        └── quarantine           data/quarantine/ (failing rows + reason)
```

**Site join key:** canonical `site_id` from `mappings/sites.yaml` links Valmet ERP sites, NovaProp Smartti properties, KONE buildings, and utilization assets.

## Layout

| Path | Purpose |
|------|---------|
| `bronze/` | Raw file landing + ingest metadata |
| `silver/` | Cleaned, typed, conformed tables |
| `gold/` | Business-ready marts |
| `contracts/` | Per-source data contracts (YAML) |
| `quality/` | Silver/Gold validation checks |
| `mappings/sites.yaml` | Cross-source site mapping |
| `docs/schema.yml` | Gold column definitions |

## Quality checks

At Silver/Gold boundaries the pipeline validates:

- **Schema** — required columns present and non-null
- **Uniqueness** — primary keys (`alert_event_id`, `wo_no`, `pm_no`, `reading_id`, etc.)
- **Referential** — `site_id` mapping hit rate ≥99% (ERP) / ≥95% (IoT)
- **Ranges** — alarm priority enum `{1,13,50,60,77,99}`, utilization 0–100%, occupancy 0–10
- **PII** — no raw email addresses in Gold string columns

## Tests

```bash
pytest tests/unit -q
```

## Known limitations

- **Partial site coverage:** Valmet L11 has ERP + utilization; Aurora has Smartti climate/energy; missing domains stay null in Gold (never dropped).
- **Work orders encoding:** semicolon-delimited, often cp1252; mojibake repair is best-effort.
- **KONE occupancy:** sparse calendar dates; 24h explode produces many rows per building/month.
- **Utilization filenames:** date ranges use DDMMYY (not US MMDDYY).
- **Maintenance plans:** deduped by `pm_no` (316 → 106 rows); Obsolete plans retained.
- **Unmapped ERP rows:** kept with null `site_id` where mapping fails; quality checks enforce hit-rate thresholds on mapped sources.
