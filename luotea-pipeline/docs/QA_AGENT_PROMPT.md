# Task: Build Self-QA Workflow for the Luotea Data Pipeline

You are a senior data engineer building an **autonomous QA gate** for the Luotea pipeline. The goal is that **you (the agent) can run the full pipeline on real CSV/JSON inputs, wait for completion, inspect outputs, and decide pass/fail** — without human intervention.

Read first:

- `luotea-pipeline/docs/AGENT_PROMPT.md` — pipeline architecture
- `luotea-pipeline/pipeline/contracts/*.yaml` — expected row counts, keys, enums
- `luotea-pipeline/mappings/sites.yaml` — site coverage expectations

**Do not implement new transforms.** Only build the QA orchestration, checks, report, and tests.

---

## Mission

Create a repeatable workflow:

```
RUN pipeline on hackathon data  →  WAIT  →  INSPECT outputs  →  PASS or FAIL with evidence
```

An agent (or CI) runs one command and gets a structured report it can reason about.

**Success criteria for this task:**

1. `pipeline qa --date YYYY-MM-DD` runs ingest → silver → gold → validate end-to-end
2. Exit code `0` = pass, `1` = fail (any hard check failed)
3. Report written to `data/qa/qa_report_{date}.json` and printed as a human-readable summary
4. Agent can read the report and explain what passed, what failed, and what is expected partial coverage
5. `pytest tests/integration/test_qa_workflow.py` passes locally

---

## Inputs (real hackathon files — do not mock)

All inputs live in `Luotea-Hackathon-2026/` (sibling folder). The pipeline already resolves this via `pipeline/config.py` → `HACKATHON_DATA_ROOT`.

| Source | Input path | Format |
|--------|------------|--------|
| Alarms | `Alarms/alarms.csv` | CSV |
| Work orders | `Work orders/work_orders_anonymized 1.csv` | CSV (semicolon delimiter) |
| Maintenance plans | `Maintenance schedule (EH-työt)/Scheduled maitenance plans.csv` | CSV |
| Smartti Pulse | `Smartti/aurora_house.json`, `meridian_tower.json`, `horizon_plaza.json` | JSON |
| KONE occupancy | `Smartti/kone/*-normalized.json` | JSON arrays |
| Utilization | `need-based cleaning/**/Room_Utilization_*.csv`, `Valmet_desk_utilization_*.csv` | Wide CSV |

**QA must use these real files**, not synthetic fixtures, for the integration test. Use a fixed `--date` (e.g. `2026-06-05`) so partitions are deterministic.

---

## Deliverables

### 1. `pipeline qa` CLI command

Add to `pipeline/cli.py`:

```bash
pipeline qa --date 2026-06-05           # full run + validate
pipeline qa --date 2026-06-05 --skip-ingest   # validate existing outputs only
pipeline qa --date 2026-06-05 --verbose       # print every check
```

**Steps executed (in order):**

1. `ingest --source all` (unless `--skip-ingest`)
2. `transform --layer silver --domain all`
3. `transform --layer gold`
4. `validate` (new — see below)
5. Write report + print summary

On failure: exit `1`, still write the report (partial results are valuable).

### 2. `pipeline/quality/` module

```
pipeline/quality/
  __init__.py
  criteria.yaml      # success thresholds (agent-editable, not hardcoded magic numbers)
  checks.py          # individual check functions
  runner.py          # orchestrates checks, returns QAResult
  report.py            # JSON + terminal summary formatting
```

#### `criteria.yaml` structure

Define checks with `severity: error | warn` and explicit thresholds sourced from contracts:

```yaml
schema_version: "0.1.0"
ingest_date: "2026-06-05"  # default for QA runs

bronze:
  - id: bronze_all_sources_present
    severity: error
    description: All 6 source families landed in bronze partition
    expected_sources: [erp_alarms, erp_work_orders, erp_maintenance_plans, smartti_pulse, kone_occupancy, cleaning_utilization]

silver:
  - id: silver_row_count_alarms
    severity: error
    table: fact_alarm
    expected_rows: 18702
    tolerance_pct: 0.5        # allow tiny drift from quarantine

  - id: silver_row_count_work_orders
    severity: error
    table: fact_work_order
    expected_rows: 44265
    tolerance_pct: 0.5

  - id: silver_row_count_maintenance
    severity: error
    table: fact_maintenance_plan
    expected_rows: 316
    tolerance_pct: 1.0        # dedup may change count slightly — document actual

  - id: silver_pk_unique_alarms
    severity: error
    table: fact_alarm
    column: alert_event_id

  - id: silver_pk_unique_work_orders
    severity: error
    table: fact_work_order
    column: wo_no

  - id: silver_no_literal_null_strings
    severity: error
    table: fact_alarm
    columns: [workorder_no]
    forbidden_values: ["NULL", "null", ""]

  - id: silver_erp_site_mapping
    severity: error
    table: fact_alarm
    column: site_id
    min_mapped_pct: 99.0      # ERP sites must map

  - id: silver_smartti_site_mapping
    severity: warn
    table: fact_sensor_reading
    column: site_id
    min_mapped_pct: 90.0

  - id: silver_sensor_readings_nonempty
    severity: error
    table: fact_sensor_reading
    min_rows: 100000

  - id: silver_utilization_mapped
    severity: warn
    table: fact_utilization
    column: site_id
    min_mapped_pct: 50.0      # only Valmet L11 has utilization + mapping

gold:
  - id: gold_site_daily_signals_grain
    severity: error
    table: site_daily_signals
    unique_keys: [site_id, date]

  - id: gold_site_daily_signals_nonempty
    severity: error
    table: site_daily_signals
    min_rows: 100

  - id: gold_valmet_l11_has_erp_signals
    severity: error
    table: site_daily_signals
    site_id: site_valmet_l11
    min_alarm_count_total: 100    # sanity: ERP alarms rolled up

  - id: gold_valmet_l11_has_utilization
    severity: warn
    table: site_daily_signals
    site_id: site_valmet_l11
    column: avg_room_utilization_pct
    min_non_null_pct: 10.0

  - id: gold_aurora_has_smartti_signals
    severity: error
    table: site_daily_signals
    site_id: site_aurora
    column: electricity_kwh
    min_non_null_pct: 5.0

  - id: gold_aurora_no_erp_alarms
    severity: warn
    table: site_daily_signals
    site_id: site_aurora
    column: alarm_count
    max_non_null_pct: 5.0       # NovaProp has no ERP — alarms should be null/zero

  - id: gold_event_timeline_nonempty
    severity: error
    table: event_timeline
    min_rows: 1000

integrity:
  - id: idempotent_rerun
    severity: error
    description: Two QA runs on same date produce identical silver/gold row counts

  - id: no_pii_leak
    severity: error
    description: Gold tables must not contain raw email patterns
    pattern: '@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}'
```

**Important:** After first QA run, adjust `expected_rows` for maintenance if dedup produces a different stable count — document the actual number in the check and in the report.

### 3. Check implementations (`checks.py`)

Each check returns:

```python
@dataclass
class CheckResult:
    check_id: str
    severity: Literal["error", "warn"]
    passed: bool
    message: str
    actual: Any = None
    expected: Any = None
```

**Implement these check types:**

| Type | Logic |
|------|-------|
| `row_count` | `abs(actual - expected) / expected <= tolerance_pct` |
| `pk_unique` | `count == count_distinct(column)` |
| `min_mapped_pct` | non-null `site_id` / total × 100 |
| `forbidden_values` | no rows where column in forbidden set |
| `grain_unique` | unique on composite keys |
| `site_column_non_null_pct` | filter `site_id = X`, compute non-null % for column |
| `sources_present` | bronze partition dirs exist with `_manifest.json` |
| `pii_scan` | regex scan on string columns in Gold |
| `idempotent_rerun` | compare row counts from two consecutive runs (optional flag to avoid double runtime in CI) |

Use **Polars** or **DuckDB** to query Parquet. Prefer reading only metadata + aggregates (fast).

### 4. Report format (`report.py`)

Write `data/qa/qa_report_{date}.json`:

```json
{
  "run_at": "2026-06-05T14:30:00Z",
  "ingest_date": "2026-06-05",
  "overall": "PASS",
  "errors": 0,
  "warnings": 2,
  "duration_seconds": 45.2,
  "pipeline_steps": {
    "ingest": {"status": "ok", "sources": 6},
    "silver": {"status": "ok", "tables": 10},
    "gold": {"status": "ok", "tables": 2}
  },
  "checks": [
    {
      "id": "silver_row_count_alarms",
      "severity": "error",
      "passed": true,
      "message": "18702 rows (expected 18702 ±0.5%)",
      "actual": 18702,
      "expected": 18702
    }
  ],
  "samples": {
    "site_valmet_l11": {"days": 120, "alarm_count_sum": 1536, "avg_utilization_non_null_days": 45},
    "site_aurora": {"days": 90, "electricity_kwh_non_null_days": 88}
  }
}
```

Print a terminal summary the agent can read directly:

```
══════════════════════════════════════════════════════════════════════
QA REPORT  2026-06-05  →  PASS (0 errors, 2 warnings)
══════════════════════════════════════════════════════════════════════
PIPELINE   ingest ✓  silver ✓  gold ✓  (45.2s)

CHECKS     18/20 passed
  ✗ ERROR  silver_row_count_maintenance   310 rows (expected 316)
  ⚠ WARN   gold_aurora_no_erp_alarms      2.1% non-null alarm_count (expected ≤5%)

SAMPLES
  site_valmet_l11   120 days  alarms=1536  utilization_days=45
  site_aurora        90 days  electricity_days=88

Report: data/qa/qa_report_2026-06-05.json
══════════════════════════════════════════════════════════════════════
```

### 5. Integration test

`tests/integration/test_qa_workflow.py`:

```python
def test_qa_full_pipeline_passes():
    """Run pipeline qa on real hackathon data; assert exit 0 and report PASS."""
    # Use subprocess to invoke CLI (tests the real entry point)
    # Fixed date: 2026-06-05
    # Assert qa_report JSON exists, overall == "PASS", errors == 0
```

Mark with `@pytest.mark.integration` so unit tests stay fast:

```bash
pytest tests/unit -q                    # fast
pytest tests/integration -q -m integration   # full QA (~1-2 min)
```

### 6. Agent playbook (`docs/QA_AGENT_PLAYBOOK.md`)

Short doc (you write this as part of the task) telling future agents:

1. Run `pipeline qa --date 2026-06-05`
2. Read `data/qa/qa_report_2026-06-05.json`
3. If FAIL → read failed checks → fix minimal bug → rerun QA (do not refactor)
4. If WARN only → confirm warnings match known data gaps (partial mapping, no ERP on NovaProp)
5. Never mark PASS if any `severity: error` check failed

---

## Agent Self-QA Workflow (how YOU use this after building it)

When asked to verify the pipeline, follow this loop **without asking the user**:

### Step 1 — Run

```bash
cd luotea-pipeline
source .venv/bin/activate
pip install -e ".[dev]"
pipeline qa --date 2026-06-05 --verbose
```

Wait for the command to finish. Do not assume success from partial output.

### Step 2 — Read report

```bash
cat data/qa/qa_report_2026-06-05.json
```

If JSON is missing or `pipeline_steps` shows a failed step, the pipeline itself broke — fix that before checks.

### Step 3 — Evaluate against criteria

| Result | Agent action |
|--------|--------------|
| `overall: PASS`, `errors: 0` | Report success with sample stats from report |
| `overall: FAIL`, errors on row counts / PK | Data loss or transform bug — inspect quarantine, fix transform |
| `overall: FAIL`, mapping < threshold | Check `mappings/sites.yaml` and transform join logic |
| Warnings only on NovaProp ERP gaps | Expected — document as known limitation, still PASS if errors=0 |
| `idempotent_rerun` failed | Non-deterministic transform — fix sort/order/dedup logic |

### Step 4 — Spot-check (if any doubt)

Run DuckDB queries only when report is ambiguous:

```sql
SELECT site_id, COUNT(*) days, SUM(alarm_count)
FROM read_parquet('data/gold/site_daily_signals/site_daily_signals.parquet')
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
```

### Step 5 — Fix loop

```
while report.overall != "PASS" or report.errors > 0:
    identify single root cause from failed check messages
    apply minimal fix
    rerun: pipeline qa --date 2026-06-05 --skip-ingest  # if bronze unchanged
```

Max 3 fix iterations before escalating to user with the report attached.

### Step 6 — Final response to user

Always include:

- Overall PASS/FAIL
- Row counts for key tables vs expected
- Mapping hit rates
- Sample stats for `site_valmet_l11` and `site_aurora`
- List of warnings with "expected" vs "bug" classification

---

## Implementation Rules

- **Criteria in YAML, not scattered** — agent and humans tune thresholds without code changes
- **Fail loud** — error checks block PASS; warnings are informational
- **Never skip reading outputs** — running the command is not enough; always parse the report
- **Real data only** for integration test — catches encoding, delimiter, and path bugs fixtures miss
- **Fast validate path** — `--skip-ingest` reruns checks in seconds during fix loops
- **No silent passes** — if a Parquet is missing, that's an error, not a skip
- **Document expected partial coverage** — NovaProp sites without ERP is correct behavior

---

## Definition of Done

```bash
cd luotea-pipeline
pytest tests/unit -q
pytest tests/integration/test_qa_workflow.py -q
pipeline qa --date 2026-06-05
echo $?   # must be 0
```

And the agent can paste the terminal summary showing PASS with evidence for both Valmet (ERP + utilization) and Aurora (Smartti/KONE, no ERP).

---

## Out of Scope

- Great Expectations / external DQ platforms
- CI/CD wiring (GitHub Actions) — but design so `pipeline qa` is CI-ready
- ML model validation
- Performance benchmarking
