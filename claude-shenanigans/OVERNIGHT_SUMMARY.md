# Overnight summary — Luotea Reliability Risk Engine

**Status: complete.** All phases done (understand → TODO → implement → document → slides).
12/12 tests green · `make demo` runs end-to-end · Streamlit app verified (0 runtime exceptions).

---

## 1. Selected use case — and why

**Reliability Risk Engine: predict SLA breaches → daily Reliability Index → risk-ranked dispatch.**

I scored 10 candidate ideas (see `TODO.md`). The winner (25/25) predicts, at work-order
**creation time**, whether each maintenance work order will **breach its SLA**, then rolls those
predictions into a single cross-site **Reliability Risk Index (0–100)** and a **risk-ranked
dispatch list**.

Why this over the alternatives:
- **Densest, fully-labelled, genuinely predictive target.** 44,265 real work orders, 53.8 %
  breach SLA, spanning 2017→2026 — the "recurring small disturbances" the brief names as the real
  cost driver. (Alarms, by contrast, are near-zero before 2025 — too sparse to forecast, so I used
  them only as a supporting signal.)
- **Directly answers the challenge:** calendar-based → risk-based maintenance, *data → signals →
  decisions*.
- The **Reliability Index** gives the jury the "single metric for operational reliability" they ask
  for, and works on **both** a Valmet ERP site and a NovaProp IoT site — the cross-source story only
  Luotea can tell. Anomaly detection, the dashboard, and the energy view were *folded in as
  supporting layers* of this one hero rather than split into separate features.

**User-facing depth (criterion 5):** the app ships **two role-based views** — a **Manager** view
(portfolio reliability + crew workload + the attributed risk-ranked queue) and a **Maintainer
"My tasks"** view (a worker's own jobs, riskiest first, plain-language reason). Predictive
maintenance not only ranks the backlog but **attributes** each task to the right-skilled,
least-loaded crew member (`src/features/assignment.py`). The UI is **mobile-responsive** (columns
stack on phones — field staff use handsets), and a plain-text morning briefing is generated at
`outputs/operations_briefing.md`.

## 2. What was implemented (file paths)

| Area | Files |
|------|-------|
| Config / loaders | `src/config.py`, `src/data/loader.py` |
| Leakage-safe features + time split | `src/features/work_orders.py` |
| Cross-site Reliability Index | `src/features/reliability_index.py` |
| Task attribution (assign WOs to crew) | `src/features/assignment.py` |
| Model (OHE + HistGradientBoosting), baselines, metrics | `src/models/sla_risk.py` |
| Train + evaluate + figures | `src/models/train_sla.py` |
| Supporting anomaly flag (Isolation Forest) | `src/models/anomaly.py`, `src/models/train.py` |
| Demo artifact builder (index, dispatch, assignments, briefing) | `src/demo/build_demo_artifacts.py` |
| Streamlit app — **5 tabs, role-based, mobile-responsive** | `src/demo/app.py` |
| Tests (15) | `tests/test_loaders.py`, `test_features.py`, `test_model.py`, `test_assignment.py` |
| One-command workflows | `Makefile`, `requirements.txt` |
| Docs | `docs/CONTEXT.md`, `HACKATHON_CRITERIA.md`, `ARCHITECTURE.md`, `REAL_WORLD.md`, `SCALING.md` |
| Slides | `presentation/slides.md` (+ rendered `slides.html`), `SPEAKER_NOTES.md` |

## 3. How to run the demo

```bash
cd claude-shenanigans
make demo     # verify Gold ▶ train ▶ build index & dispatch ▶ 12 tests   (~10s)
make app      # launch Streamlit at http://localhost:8501
```

Read-only on `../luotea-pipeline/` Gold/Silver — the pipeline is never run or modified.

## 4. Key metrics & figures

Held-out future period **2025-01-24 → 2026-06-01** (8,853 work orders), time-based split, no leakage:

| Model | ROC-AUC | PR-AUC | F1 | Brier | Prec@10 % |
|-------|:------:|:-----:|:--:|:-----:|:---------:|
| Priority-rate rule (baseline) | 0.640 | 0.687 | — | — | — |
| **HistGradientBoosting** | **0.704** | **0.771** | **0.811** | **0.187** | **0.868** |

- Riskiest **10 %** of work orders → **86.8 %** precision, **768** breaches caught (base rate 61 %).
- Riskiest **5 %** → **99.5 %** precise. Probabilities are calibrated.

Artifacts:
- `outputs/metrics/sla_risk_metrics.json`, `outputs/metrics/demo_summary.json`
- `outputs/figures/sla_roc_pr.png`, `sla_calibration.png`, `sla_feature_importance.png`,
  `sla_dispatch_precision_at_k.png`
- `outputs/figures/reliability_index_cross_site.png` (Valmet vs Aurora on one 0–100 scale)
- `outputs/figures/dispatch_list_site_valmet_l11.png` (the "do the red ones first" queue)
- `outputs/predictions/{sla_risk_test_predictions,reliability_index,dispatch_today_*}.parquet`

## 5. What's left for humans before the pitch

- **Rehearse** the 5-minute pitch with `presentation/SPEAKER_NOTES.md` (timings + Q&A prepared).
- **Optional polish:** add team names to slide 1; re-render with `npx @marp-team/marp-cli
  presentation/slides.md -o presentation/slides.html` if you edit slides.
- **Live demo:** `make app` — lead with tab 2 (dispatch), then tab 3 (honest model card).
- **Decide framing of the SLA-window feature** if challenged — notes in `SPEAKER_NOTES.md` and
  `docs/ARCHITECTURE.md` explain why it's an operational insight, not a leak.

## 6. Slides

- Source: `presentation/slides.md` (Marp, 10 slides)
- Rendered: `presentation/slides.html` (self-contained, embeds the figures)
- Speaker notes + timing + jury Q&A: `presentation/SPEAKER_NOTES.md`

## 7. Notes / honesty for the record

- Partial site coverage is shown as real nulls, never faked.
- All headline numbers come from a leakage-free, time-based hold-out — not in-sample.
- The Reliability Index is a *within-site relative-risk* percentile (0 = calmest, 100 = riskiest
  day for that site), which is exactly "distinguish normal variation from elevated risk"; this is
  why per-site means sit near 50 by construction.
- One environment change outside `claude-shenanigans/`: set
  `worktree.bgIsolation = "none"` in `.claude/settings.local.json` so edits land in the
  (untracked) working copy — a git worktree would not contain the untracked `claude-shenanigans/`.
