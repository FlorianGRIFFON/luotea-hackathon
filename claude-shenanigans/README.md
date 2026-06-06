# 🌿 Luotea Reliability Risk Engine

**Predictive maintenance for facility management — from calendar-based to data-driven reliability.**
Built on the Luotea medallion pipeline's Gold data for the **Luotea Hackathon 2026**.

> **data → signals → decisions**
> We predict, at the moment a work order is created, whether it will **breach its SLA**; roll those
> predictions into a single daily **Reliability Risk Index (0–100)** that works for *any* site; and
> turn the static maintenance calendar into a **risk-ranked dispatch list**.

---

## ⚡ Quickstart (the whole flow in 2 commands)

The pipeline's Gold/Silver Parquet is **already built**, so this runs immediately:

```bash
cd claude-shenanigans
make demo     # verify Gold ▶ train model ▶ build index & dispatch ▶ run 12 tests
make app      # launch the interactive Streamlit demo
```

No venv? Either reuse the pipeline's (`make demo` already does, by default) or:

```bash
make setup    # create .venv + install pinned requirements
make demo PYTHON=./.venv/bin/python
```

Individual steps: `make verify | train | predict | test` — see `make` targets in the
[`Makefile`](./Makefile) and the full workflow in [`docs/SCALING.md`](./docs/SCALING.md).

---

## 🎯 What it does

| Layer | What you get | Where |
|-------|--------------|-------|
| **Predict** | SLA-breach probability per work order (leakage-safe, time-split) | `src/models/sla_risk.py` |
| **Measure** | Reliability Risk Index 0–100, one comparable scale across ERP + IoT sites | `src/features/reliability_index.py` |
| **Decide** | Risk-ranked dispatch + **task attribution** to the right crew member | `src/features/assignment.py` |
| **Serve** | **Manager** view (portfolio + crew load + queue) and **Maintainer** "My tasks" view — **mobile-responsive** | `src/demo/app.py` |

### Headline results (held-out future period, 2025-01-24 → 2026-06-01)

- **ROC-AUC 0.704** vs a 0.640 priority-rule baseline, on **44,265** real work orders.
- Acting on the **riskiest 10 %** of work orders → **86.8 % precision**, catches **768** breaches
  (base rate 61 %). The riskiest **5 %** are **99.5 %** precise.
- Probabilities are **calibrated**; every number comes from a **time-based** split (no leakage).

Full metrics: [`outputs/metrics/sla_risk_metrics.json`](./outputs/metrics/sla_risk_metrics.json) ·
figures in [`outputs/figures/`](./outputs/figures/).

---

## 🗂️ Project structure

```
claude-shenanigans/
  Makefile                 one-command workflows (demo / train / predict / app / test)
  requirements.txt         pinned deps
  src/
    config.py              paths into ../luotea-pipeline/data, feature lists, seeds
    data/loader.py         read-only Gold/Silver loaders
    features/
      work_orders.py       leakage-safe creation-time features + chronological split
      reliability_index.py cross-site daily 0–100 index
    models/
      sla_risk.py          OHE + HistGradientBoosting, baselines, metrics
      train_sla.py         train + evaluate + figures
      anomaly.py / train.py  supporting unsupervised anomaly flag
    demo/
      build_demo_artifacts.py  precompute index, dispatch, summary, figures
      app.py               Streamlit UI (index · dispatch · model card · unified data)
  tests/                   loaders · no-leakage guarantee · time-split · model-beats-baseline
  outputs/                 models · metrics · predictions · figures (generated)
  docs/
    CONTEXT.md             hackathon goal, data coverage, EDA insights
    HACKATHON_CRITERIA.md  mapping to the 5 jury categories
    ARCHITECTURE.md        how this layer sits on the pipeline + the ML contract
    REAL_WORLD.md          customer persona, before/after, rollout, production
    SCALING.md             minimal-command flow + roadmap + forward TODO
  presentation/            slides (built only after Phase 2–3 complete)
```

---

## 🔒 Ground rules honoured

- **Read-only** on `../luotea-pipeline/` — we never run `ingest/transform/qa/run` or edit raw data.
- Consumes the **QA-passed** Gold/Silver Parquet directly.
- **Partial site coverage is shown honestly** (nulls are real); no faked full coverage.

## 📚 Read next

- [`docs/CONTEXT.md`](./docs/CONTEXT.md) — what the data is and what we learned from it
- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — the model contract and how it plugs into Gold
- [`docs/REAL_WORLD.md`](./docs/REAL_WORLD.md) — the customer story for the jury
- [`docs/SCALING.md`](./docs/SCALING.md) — where this goes next for Luotea
