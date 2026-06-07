# Hackathon sprint TODO

Status values: `pending` | `in_progress` | `done` | `cancelled`
Hero use case: **Reliability Risk Engine** (SLA-breach prediction → daily Reliability Index → risk-ranked dispatch).

## Phase 0 — Context

- [x] Read `../Luotea-Hackathon-2026/README.md` (challenge + judging criteria) — **done**
- [x] Read `../luotea-pipeline/docs/PIPELINE_OVERVIEW.md` — **done**
- [x] Read `schema.yml`, `sites.yaml`, `qa_report_2026-06-05.json` (read-only) — **done**
- [x] Verify Gold Parquet exists (no pipeline run) — **done** (10,350 daily rows, 107,706 events)
- [x] EDA on Gold + Silver (Polars) — **done** (6 insights captured)
- [x] Write `docs/CONTEXT.md` — **done**
- [x] Write `docs/HACKATHON_CRITERIA.md` — **done**

## Phase 1 — Ideation & ranking

Scored 1–5 on: Jury impact · Demo clarity · Data fit · ML credibility · Overnight feasible.

| # | Use case | Jury | Demo | Data | ML | Feas | **Total** | Verdict |
|---|----------|:----:|:----:|:----:|:--:|:----:|:---------:|---------|
| 1 | **SLA-breach prediction → risk-ranked dispatch + Reliability Index** | 5 | 5 | 5 | 5 | 5 | **25** | **SELECTED** |
| 2 | Anomaly detection on daily signals (Isolation Forest) | 4 | 4 | 4 | 4 | 5 | 21 | folded in as supporting signal |
| 3 | Unified ops dashboard (Streamlit on Gold) | 4 | 5 | 5 | 2 | 5 | 21 | folded in as the demo surface |
| 4 | Energy anomaly + comfort (Aurora kWh vs occupancy) | 4 | 4 | 4 | 3 | 4 | 19 | folded into Reliability Index for IoT sites |
| 5 | Next-day alarm/incident forecast | 5 | 4 | 2 | 3 | 3 | 17 | cut — alarms only dense from 2025 |
| 6 | Need-based cleaning optimizer (utilization → intensity) | 4 | 3 | 2 | 3 | 3 | 15 | cut — utilization only 25% coverage |
| 7 | Cross-domain root-cause hints (alarm ↔ HVAC ↔ temp) | 3 | 3 | 2 | 2 | 3 | 13 | future work |
| 8 | Finnish alarm-text clustering (TF-IDF/embeddings) | 3 | 3 | 3 | 3 | 2 | 14 | future work |
| 9 | Elevator vs desk utilization narrative | 2 | 3 | 2 | 1 | 4 | 12 | future work |
| 10 | Digital-twin-lite single-site week view | 2 | 4 | 3 | 1 | 4 | 14 | future work |

**Why #1 wins:** densest + fully-labelled target (44k WOs, 53.8% breach), genuinely *predictive*
(creation-time features), directly answers "from calendar to risk-based maintenance," and the
Reliability Index roll-up gives the jury the cross-source "single reliability metric" they ask
for. #2/#3/#4 are not dropped — they become *supporting layers* of the one hero, so we keep focus.

## Phase 2 — Implementation (hero only)

### Data & features
- [x] `src/config.py` — add Silver work-order path + SLA feature lists
- [x] `src/data/loader.py` — add `load_work_orders()`
- [x] `src/features/work_orders.py` — leakage-safe creation-time features + time split
- [x] `src/features/reliability_index.py` — daily 0–100 composite index (cross-site)

### Model
- [x] `src/models/sla_risk.py` — sklearn pipeline (OHE + HistGradientBoosting), baselines, eval
- [x] `src/models/train_sla.py` — train, time-split eval, save model + metrics + predictions
- [x] Baselines: majority-class, priority-rate lookup, logistic regression
- [x] Metrics on held-out time period: ROC-AUC, PR-AUC, F1, precision@k, Brier, calibration
- [x] Figures: ROC/PR, calibration, feature importance, reliability index timeline, dispatch
- [x] Keep existing anomaly detector; wire its score into the Reliability Index

### Demo
- [x] `src/demo/app.py` — Streamlit: dispatch list, reliability index, model card, cross-source view
- [x] `src/demo/build_demo_artifacts.py` — precompute everything the app + slides need
- [ ] Update `claude-shenanigans/README.md` — run demo in <5 commands
- [x] `requirements.txt` — pinned deps

### Tests
- [x] `tests/test_loaders.py` — Gold/Silver load + schema smoke
- [x] `tests/test_features.py` — no-leakage guarantee + split integrity
- [x] `tests/test_model.py` — end-to-end train path beats baseline on holdout

## Phase 3 — Real-world documentation
- [x] `docs/ARCHITECTURE.md` — how the ML app sits on the pipeline
- [x] `docs/REAL_WORLD.md` — customer persona, before/after, rollout, production

### Usability & scaling (user request)
- [x] `Makefile` — whole flow in minimal commands (`make demo`, `make app`, train/predict/test)
- [x] `docs/SCALING.md` — minimal-command flow + how to scale + roadmap + forward TODO for Luotea
- [x] `README.md` — strong quickstart front door (2-command demo, results, structure)

### User-facing / operations (user request)
- [x] `src/features/assignment.py` — attribute risk-ranked work orders to the right crew member (+3 tests)
- [x] **Manager view** — portfolio reliability + crew workload + attributed risk-ranked queue
- [x] **Maintainer "My tasks" view** — per-worker task list, riskiest first, plain-language reason
- [x] **Mobile responsivity** — CSS so columns stack / type shrinks on phones (field staff use handsets)
- [x] `outputs/operations_briefing.md` + `.json` — plain-language morning briefing artifact

## Phase 4 — Presentation (gated on Phase 2–3 complete + tests green + demo runs)
- [x] **App-as-presentation** — the Streamlit app *is* the deck (added a 🎤 Story/pitch tab); Marp deck + HTML retired
- [x] `presentation/SPEAKER_NOTES.md` — app-driven 5-min run sheet (tab-by-tab) + Q&A + fallback
  - [x] Phase 2 items done · REAL_WORLD.md exists · `make demo` runs end-to-end · 16 tests green · demoable ≤5 min

## Final
- [x] `OVERNIGHT_SUMMARY.md`
