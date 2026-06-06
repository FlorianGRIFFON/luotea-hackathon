# SLA Violation Prediction — Model Documentation

## What it does

Given a work order at the moment it is **created**, the model predicts the probability that it will miss its SLA deadline. The output is a number between 0 and 1 (e.g. `0.82` = 82% chance of violation).

This shifts the question from *"which orders violated SLA last month?"* (retrospective) to *"which open orders should we escalate right now?"* (operational).

---

## Architecture: segmented models

The system trains **one model per active contract type** rather than a single combined model. This was the result of discovering that SP (cleaning) orders were dragging the combined model below the usefulness threshold.

| Contract type | Description | Model | ROC-AUC | PR-AUC | Brier | Status |
|---|---|---|---|---|---|---|
| **KH** | Property maintenance | `model_KH.pkl` | **0.950** | **0.953** | 0.077 | Production-ready |
| **KT** | Technical maintenance | `model_KT.pkl` | **0.784** | **0.713** | 0.213 | Production-ready |
| **SP** | Cleaning services | — | 0.496 | — | — | Skipped — see below |
| **KIPA** | Facility services | — | — | — | — | Discontinued — absorbed into KH/KT |

### Why not a single combined model?

The first version trained one Random Forest on all 44,265 work orders. It achieved AUC 0.69 — below the 0.75 target. Breaking it down by contract type revealed the problem:

| Contract | AUC | False alarms |
|---|---|---|
| KH | 0.949 | 15 |
| KT | 0.836 | 38 |
| SP | **0.496** | **1,488** |

SP was generating 97% of all false alarms and scoring worse than a random coin flip. Training separate models eliminated that noise.

### Why SP is skipped

SP = *Siivouspalvelut* (cleaning services) — 60% of all work orders (26,616 rows) with a 68% SLA violation rate.

Three structural reasons the current features cannot predict SP violations:

1. **`priority_id` is always null for SP** — it is not collected for cleaning orders. One of the model's top-2 most important features simply does not exist for cleaning.
2. **Wrong signal.** SLA compliance for cleaning depends on operational capacity — how many staff are on shift, how many rooms need cleaning, whether the building had a heavy day. None of that is in the work order CSV.
3. **68% baseline is systemic, not predictable.** If two-thirds of cleaning orders routinely miss SLA, that is a contract/staffing issue. The correct approach is a **utilization-based cleaning scheduler** using room sensor data — a different model with different inputs, not a violation predictor.

### Why KIPA is removed

KIPA (facility services) was discontinued in 2021. Work previously categorised as KIPA is now handled under KH and KT contracts. No new KIPA orders are created, so no scoring model is needed.

---

## Input data

### Work order features (Silver layer)

**Source:** `luotea-pipeline/data/silver/fact_work_order/fact_work_order.parquet`

The Silver Parquet is used directly — already cleaned, typed, and enriched with `site_id` by the data pipeline. The model never reads from the raw CSV.

**Coverage:** 44,265 work orders across multiple Valmet sites, May 2017 – June 2026.

### Site context features (Gold layer)

**Source:** `luotea-pipeline/data/gold/site_rolling_context/site_rolling_context.parquet`

For each work order, the model also uses **rolling 7-day signals from the site** where the work will happen. These are joined by `site_id` and the day *before* the work order was created (T-1), so no future information leaks into the prediction.

The rolling window smooths daily noise: a site that has been consistently overloaded for a week is a stronger signal than a single bad day.

---

## The leakage rules

**Rule 1 — only use features that exist at order creation time.**

A work order is created with: site, contract type, work type, priority, start time, and SLA deadline. That is what the models use.

What the models do NOT use:

| Column | Why excluded |
|---|---|
| `work_finished_days` | How long it actually took — only known after completion |
| `worktime_hours` | Billed hours — only known after completion |
| `work_order_performed_action` | Technician notes — written after the work is done |

**Rule 2 — join site context on T-1 (yesterday), not today.**

Joining on the same day the work order was created would cause leakage: the site's `open_work_orders` count for today already includes the order being predicted. The previous day is fully settled and safe.

---

## Features used

### Categorical (one-hot encoded)

| Feature | Values | Why it matters |
|---|---|---|
| `site_id` | site_valmet_l11, site_valmet_venttiilitehdas, … | Different sites have different compliance profiles |
| `contract_type` | KH, KT | Constant within each segmented model — kept for pipeline consistency |
| `work_order_type` | EH-työ, Tilaustyö | Scheduled vs on-demand — top predictor for KH |
| `work_type_eng` | ~20 categories | Fine-grained task type |

### Numeric — work order level (median-imputed, scaled)

| Feature | Notes |
|---|---|
| `priority_id` | 1–6; always null for SP (SP is skipped) |
| `month` | Seasonal patterns |
| `day_of_week` | Friday orders may not start until Monday |
| `hour` | Time of day at order creation |
| `year` | Long-term trend (SLA policy and headcount changes) |
| `sla_window_days` | Days between order creation and SLA deadline — tight windows predict violations |
| `has_pm_no` | 1 if this is a scheduled maintenance order (linked to a PM plan) |
| `has_parent_wo` | 1 if this is a sub-order under a parent work order |
| `has_sla_deadline` | 1 if an SLA deadline was set at all |
| `is_invoicable` | Billing flag |
| `is_subcontractor_work` | Subcontractor orders have different completion dynamics |

### Numeric — site context from Gold (rolling 7-day window, T-1)

| Feature | Aggregation | What it captures |
|---|---|---|
| `site_open_wo_7d_avg` | Mean | Average open work orders at the site — team workload trend |
| `site_sla_violations_7d` | Sum | Total SLA violations closed at the site — recent pressure |
| `site_alarms_7d_avg` | Mean | Average daily alarms — site chaos level |
| `site_fire_alarms_7d` | Sum | Total fire/priority-1 alarms — safety events drive reactive WOs |
| `site_incidents_7d` | Sum | Total Smartti incidents — cross-source signal |
| `site_utilization_7d_avg` | Mean | Average room utilization — building busyness trend |

Means are used for level signals (the typical state); sums are used for event signals (rare events matter cumulatively, not as daily averages). Null values are median-imputed — sites without IoT coverage still get a usable prediction.

---

## Train/test split

Data is split **by time**, not randomly. A random split would leak future patterns into training.

| Model | Training set | Test set |
|---|---|---|
| KH | Before 2025-06-06 (5,327 orders) | Last 12 months (1,146 orders) |
| KT | Before 2024-01-01 (2,075 orders) | Jan 2024 – Jun 2026 (1,478 orders) |

---

## Model performance

All metrics are computed on the **held-out future test period** (chronological split, no shuffling). Permutation importance is model-agnostic — it measures the actual drop in ROC-AUC when a feature is shuffled on the test set, rather than tree impurity.

### KH — Property maintenance

| Metric | Model | Priority-rate baseline | Logistic regression |
|---|---|---|---|
| ROC-AUC | **0.950** | 0.837 | 0.944 |
| PR-AUC | **0.953** | 0.715 | 0.944 |
| Brier score | **0.077** | — | — |
| F1 | 0.873 | — | — |
| Test set (1,146 orders, 42.3% violation rate) | | | |

**Dispatch precision@k** (top-k% riskiest orders acted on first):

| Dispatch capacity | Precision | Recall | Breaches caught |
|---|---|---|---|
| Top 5% (57 orders) | **100%** | 11.8% | 57 |
| Top 10% (115 orders) | **100%** | 23.7% | 115 |
| Top 20% (229 orders) | **100%** | 47.2% | 229 |
| Top 30% (344 orders) | **100%** | 70.9% | 344 |

Every order in the top 30% riskiest actually breaches. A team with capacity to act on 30% of the queue catches 71% of all breaches without a single false alarm.

**Top features (permutation importance — Δ ROC-AUC):**

| Feature | Importance |
|---|---|
| `work_order_type` (EH-työ vs Tilaustyö) | +0.070 ± 0.007 |
| `priority_id` | +0.029 ± 0.004 |
| `has_pm_no` | +0.018 ± 0.003 |
| `site_id` | +0.010 ± 0.001 |
| `has_sla_deadline` | +0.004 ± 0.001 |

Interpretation: scheduled work (EH-työ, linked to a PM plan) vs reactive work (Tilaustyö) is the dominant signal. Scheduled work violates SLA far less often because the deadline is set with realistic lead times. Gold site-context features rank low for KH — the outcome is determined by the type of work, not site-level pressure.

---

### KT — Technical maintenance

| Metric | Model | Priority-rate baseline | Logistic regression |
|---|---|---|---|
| ROC-AUC | **0.784** | 0.686 | 0.748 |
| PR-AUC | **0.713** | 0.587 | 0.694 |
| Brier score | **0.213** | — | — |
| F1 | 0.704 | — | — |
| Test set (1,478 orders, 45.3% violation rate) | | | |

**Dispatch precision@k:**

| Dispatch capacity | Precision | Recall | Breaches caught |
|---|---|---|---|
| Top 5% (74 orders) | 71.6% | 7.9% | 53 |
| Top 10% (148 orders) | 83.1% | 18.4% | 123 |
| Top 20% (296 orders) | 79.4% | 35.1% | 235 |
| Top 30% (443 orders) | 73.1% | 48.4% | 324 |

The top-10% precision (83%) is substantially above the 45% base rate — tripling hit rate — and above the logistic regression baseline (AUC 0.748), showing the non-linear RF captures structure that linear models miss.

**Top features (permutation importance — Δ ROC-AUC):**

| Feature | Importance |
|---|---|
| `site_id` | +0.135 ± 0.010 |
| `priority_id` | +0.043 ± 0.005 |
| `work_type_eng` | +0.017 ± 0.005 |
| `work_order_type` | +0.012 ± 0.003 |
| `has_sla_deadline` | +0.012 ± 0.004 |

Interpretation: for KT, **site identity is the dominant predictor** — different sites have structurally different SLA compliance profiles. `priority_id` is second. Unlike KH, no single feature overwhelmingly dominates; the model integrates several moderate signals. Gold rolling features did not rank in the top 5 on this test period (KT training data predates most of the gold data coverage), but they are available and provide context for future orders.

---

## Algorithm benchmark (RF vs HistGradientBoosting)

Both classifiers were trained on the same segments and compared by ROC-AUC on the held-out test set:

| Contract | RF AUC | GBT AUC | Winner | Δ |
|---|---|---|---|---|
| KH | 0.950 | 0.938 | **RF** | +0.012 |
| KT | 0.784 | 0.711 | **RF** | +0.073 |

Random Forest outperforms HistGradientBoosting on both segments. The T-1 rolling gold features already provide smooth, low-noise 7-day context — GBT's boosting advantage (handling noisy/missing data incrementally) is less relevant when the input is already well-summarised. Random Forest also handles class imbalance more naturally with `class_weight="balanced"`.

---

## Output files

### Model files

| File | Contract | Load with |
|---|---|---|
| `models/model_KH.pkl` | KH orders | `joblib.load("models/model_KH.pkl")` |
| `models/model_KT.pkl` | KT orders | `joblib.load("models/model_KT.pkl")` |

`score_orders.py` handles routing automatically — you do not need to pick the right model manually.

### Report files

`reports/report_KH.json`, `reports/report_KT.json` — one per model, each contains:

```json
{
  "contract_type": "KH",
  "classifier": "RF",
  "eval_method": "time_split",
  "test_cutoff": "2025-06-06",
  "train_size": 5327,
  "test_size": 1146,
  "trained_on_date": "2026-06-06",
  "model": {
    "roc_auc": 0.950, "pr_auc": 0.953, "f1": 0.873, "brier": 0.077,
    "base_rate": 0.423,
    "precision_at_k": [
      {"k_frac": 0.05, "precision": 1.0, "recall": 0.118, "breaches_caught": 57},
      {"k_frac": 0.10, "precision": 1.0, "recall": 0.237, "breaches_caught": 115},
      ...
    ]
  },
  "baselines": {
    "majority_class":      {"roc_auc": 0.500, "pr_auc": 0.423, ...},
    "priority_rate":       {"roc_auc": 0.837, "pr_auc": 0.715, ...},
    "logistic_regression": {"roc_auc": 0.944, "pr_auc": 0.944, ...}
  },
  "calibration": [{"bin_mid": 0.05, "mean_pred": 0.03, "observed": 0.02, ...}, ...],
  "benchmark_auc": {"RF": 0.9503, "GBT": 0.9383},
  "feature_importance": [
    {"feature": "work_order_type", "importance": 0.0704, "std": 0.0065},
    ...
  ]
}
```

### Figure files

`reports/figures/` — 4 PNG files per model (8 total), saved at training time:

| File | Contents |
|---|---|
| `KH_roc_pr.png` | ROC and PR curves vs 3 baselines |
| `KH_calibration.png` | Reliability diagram (predicted probability vs observed rate) |
| `KH_feature_importance.png` | Top-12 features by permutation importance with error bars |
| `KH_dispatch_precision_at_k.png` | Precision and recall at different dispatch capacities |
| `KT_*.png` | Same 4 figures for the KT model |

---

## How to interpret the output

Each model outputs a **probability** (0–1). `score_orders.py` converts this to a risk label:

| Probability | Label | Suggested action |
|---|---|---|
| ≥ 65% | HIGH | Escalate or reassign immediately |
| 35–65% | MEDIUM | Monitor — check again at next shift |
| < 35% | LOW | No action needed |

The thresholds (35% / 65%) can be adjusted:
- If SLA fines are expensive → lower the threshold to catch more violations (more false alarms)
- If operations teams are overloaded → raise the threshold (fewer alerts, some violations missed)

---

## Scripts

| Script | Purpose | When to run |
|---|---|---|
| `train_segmented_models.py` | Trains KH and KT models | **Primary training script** — run monthly |
| `score_orders.py` | Loads segmented models, scores recent orders | On demand — any time |
| `train_sla_model.py` | Trains a single combined model (all types) | Baseline / comparison only |

---

## How to run

```bash
# Step 1 — run the data pipeline (Silver + Gold)
cd luotea-pipeline
python3.11 -m pipeline ingest --source all --date $(date +%Y-%m-%d)
python3.11 -m pipeline transform --layer silver --domain erp --date $(date +%Y-%m-%d)
python3.11 -m pipeline transform --layer gold --date $(date +%Y-%m-%d)

# Step 2 — train segmented models
cd ../luotea-ml
pip install -r requirements.txt
python3.11 scripts/train_segmented_models.py

# Step 3 — score current orders
python3.11 scripts/score_orders.py
python3.11 scripts/score_orders.py --cutoff 2026-01-01 --top 50
```

The Gold step is required for the site rolling context features. If Gold has not been run, training still works — gold feature columns are null-imputed to median, effectively falling back to work-order-only features.

---

## What comes next

| Priority | Task | Why |
|---|---|---|
| High | Dashboard integration | Load `.pkl` files by contract type; show risk table and `KH_dispatch_precision_at_k.png` as the business-value slide |
| Medium | Extend gold coverage for KT training period | KT training data (pre-2024) predates most gold coverage, so rolling features are null-imputed there; rebuilding gold for 2022–2023 could push KT AUC above 0.784 |
| Medium | Monthly retraining | Schedule `train_segmented_models.py` to run automatically as new Silver data arrives |
| Low | Work order volume forecasting | Predict orders per type per site per week — staffing and resource planning |
