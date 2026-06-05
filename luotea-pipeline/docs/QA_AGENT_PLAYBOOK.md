# QA Agent Playbook

How to autonomously verify the Luotea pipeline without human intervention.

## 1. Run QA

```bash
cd luotea-pipeline
source .venv/bin/activate
pip install -e ".[dev]"
pipeline qa --date 2026-06-05 --verbose
```

For fix loops when bronze is unchanged:

```bash
pipeline qa --date 2026-06-05 --skip-ingest
```

## 2. Read the report

```bash
cat data/qa/qa_report_2026-06-05.json
```

Check `pipeline_steps` first — if ingest/silver/gold failed, fix the pipeline before interpreting check failures.

## 3. Evaluate results

| Result | Action |
|--------|--------|
| `overall: PASS`, `errors: 0` | Report success with sample stats |
| `overall: FAIL`, row count / PK errors | Data loss or transform bug — inspect `data/quarantine/`, fix transform |
| `overall: FAIL`, mapping below threshold | Check `mappings/sites.yaml` and join logic |
| Warnings only (NovaProp ERP gaps) | Expected partial coverage — still PASS if `errors: 0` |
| `idempotent_rerun` failed | Non-deterministic transform — fix sort/order/dedup |

**Never mark PASS if any `severity: error` check failed.**

## 4. Spot-check (if ambiguous)

```bash
duckdb -c "
  SELECT site_id, COUNT(*) days, SUM(alarm_count)
  FROM read_parquet('data/gold/site_daily_signals.parquet')
  GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
"
```

## 5. Fix loop

```
while overall != PASS or errors > 0:
    identify single root cause from failed check messages
    apply minimal fix (no refactors)
    rerun: pipeline qa --date 2026-06-05 --skip-ingest
```

Max 3 iterations before escalating with the JSON report attached.

## 6. Expected partial coverage

| Site | Expected behavior |
|------|-------------------|
| `site_valmet_l11` | ERP alarms, work orders, room/desk utilization |
| `site_aurora` | Smartti electricity/CO₂, KONE occupancy; **no ERP alarms** |
| Maintenance plans | Bronze 316 rows → Silver **106** deduped by `PM_NO` |

Warnings on `gold_aurora_no_erp_alarms` or `silver_utilization_mapped` may appear when thresholds are conservative — confirm against known gaps, not bugs.

## 7. Tuning thresholds

Edit `pipeline/quality/criteria.yaml` — no code changes needed for threshold adjustments.

## 8. Tests

```bash
pytest tests/unit -q
pytest tests/integration/test_qa_workflow.py -q -m integration
```
