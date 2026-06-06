# SLA Violation Prediction — Model Documentation

## What it does

Given a work order at the moment it is **created**, the model predicts the probability that it will miss its SLA deadline. The output is a number between 0 and 1 (e.g. `0.82` = 82% chance of violation).

This shifts the question from *"which orders violated SLA last month?"* (retrospective) to *"which open orders should we escalate right now?"* (operational).

---

## Architecture: segmented models

The system trains **one model per contract type** rather than a single combined model. This was the result of discovering that SP (cleaning) orders were dragging the combined model below the usefulness threshold.

| Contract type | Description | Model | AUC | Status |
|---|---|---|---|---|
| **KH** | Property maintenance | `model_KH.pkl` | **0.952** | Production-ready |
| **KT** | Technical maintenance | `model_KT.pkl` | **0.792** | Production-ready |
| **KIPA** | Facility services (discontinued 2021) | `model_KIPA.pkl` | **0.812** (CV) | Historical only |
| **SP** | Cleaning services | — | 0.496 | Skipped — see below |

### Why not a single combined model?

The first version trained one Random Forest on all 44,265 work orders. It achieved AUC 0.69 — below the 0.75 target. Breaking it down by contract type revealed the problem:

| Contract | AUC | False alarms |
|---|---|---|
| KH | 0.949 | 15 |
| KT | 0.836 | 38 |
| SP | **0.496** | **1,488** |

SP was generating 97% of all false alarms and scoring worse than a random coin flip. Training separate models eliminated that noise and raised KH to 0.952.

### Why SP is skipped

SP = *Siivouspalvelut* (cleaning services) — 60% of all work orders (26,616 rows) with a 68% SLA violation rate.

Three structural reasons the current features cannot predict SP violations:

1. **`priority_id` is always null for SP** — it is not collected for cleaning orders. One of the model's top-2 most important features simply does not exist for cleaning.
2. **Wrong signal.** SLA compliance for cleaning depends on operational capacity — how many staff are on shift, how many rooms need cleaning, whether the building had a heavy day. None of that is in the work order CSV.
3. **68% baseline is systemic, not predictable.** If two-thirds of cleaning orders routinely miss SLA, that is a contract/staffing issue. The correct approach is a **utilization-based cleaning scheduler** using room sensor data — a different model with different inputs, not a violation predictor.

---

## Input data

**Source:** `luotea-pipeline/data/silver/fact_work_order/fact_work_order.parquet`

The Silver Parquet is used directly — already cleaned, typed, and enriched with `site_id` by the data pipeline. The model never reads from the raw CSV.

**Coverage:** 44,265 work orders across 4 Valmet sites, May 2017 – June 2026 (9 years).

---

## The feature leakage rule

The most important design constraint: **only use features that exist when the work order is created**.

A work order is created with: site, contract type, work type, priority, start time, and SLA deadline. That is what the models use.

What the models do NOT use:

| Column | Why excluded |
|---|---|
| `work_finished_days` | How long it actually took — only known after completion |
| `worktime_hours` | Billed hours — only known after completion |
| `work_order_performed_action` | Technician notes — written after the work is done |

Using any of these would be **leakage**: the model would predict SLA violations using the answer to a question it is supposed to be answering.

---

## Features used (all contract types)

### Categorical (one-hot encoded)

| Feature | Values | Why it matters |
|---|---|---|
| `site_id` | site_valmet_l11, site_valmet_venttiilitehdas, … | Different sites have different compliance profiles |
| `contract_type` | KH, KT, KIPA | Constant within each segmented model — kept for pipeline consistency |
| `work_order_type` | EH-työ, Tilaustyö | Scheduled vs on-demand — top predictor for KH |
| `work_type_eng` | ~20 categories | Fine-grained task type |

### Numeric (median-imputed, scaled)

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

---

## Train/test split

Data is split **by time**, not randomly. A random split would leak future patterns into training.

| Model | Training set | Test set |
|---|---|---|
| KH | Before 2025-06-06 (5,327 orders) | Last 12 months (1,146 orders) |
| KT | Before 2024-01-01 (2,075 orders) | Jan 2024 – Jun 2026 (1,478 orders) |
| KIPA | 5-fold cross-validation on full 2017-2021 history | No recent data (discontinued) |

---

## Model performance

### KH — Property maintenance (AUC 0.952)

| Metric | Value |
|---|---|
| ROC-AUC | **0.952** |
| Precision (violation) | 95.8% |
| Recall (violation) | 80.0% |
| False alarms | 17 of 661 non-violations |

**Top drivers:** `work_order_type` (EH-työ vs Tilaustyö, 43% combined), `has_pm_no` (19%), `has_sla_deadline` (12%), `priority_id` (8%).

Interpretation: for KH orders, whether the work is scheduled (EH-työ with a PM plan) vs reactive (Tilaustyö) is by far the strongest signal. Scheduled work violates SLA far less often.

---

### KT — Technical maintenance (AUC 0.792)

| Metric | Value |
|---|---|
| ROC-AUC | **0.792** |
| Precision (violation) | 66.4% |
| Recall (violation) | 76.9% |
| False alarms | 261 of 808 non-violations |

**Top drivers:** `priority_id` (15%), `work_type_eng_Project services electrical` (11%), `year` (7%), `site_id` (11% combined across both sites).

Interpretation: priority and specific work type are the strongest signals. Electrical project work is a distinct predictor. The year feature captures a drift in KT compliance over time.

---

### KIPA — Facility services (AUC 0.812, cross-validation)

| Metric | Value |
|---|---|
| ROC-AUC (CV mean) | **0.812** |
| ROC-AUC (CV std) | ±0.085 |
| Eval method | 5-fold cross-validation |

**Top drivers:** `has_sla_deadline` (23%), `sla_window_days` (16%), `work_type_eng_Technical maintenance` (15%), `year` (7%).

Note: KIPA was discontinued in January 2021. No new orders have been created since. This model is trained on the full 2017–2021 history and may be used to score any legacy KIPA orders that appear, but no new scoring is expected in production.

---

## Output files

### Model files

| File | Contract | Load with |
|---|---|---|
| `models/model_KH.pkl` | KH orders | `joblib.load("models/model_KH.pkl")` |
| `models/model_KT.pkl` | KT orders | `joblib.load("models/model_KT.pkl")` |
| `models/model_KIPA.pkl` | KIPA orders | `joblib.load("models/model_KIPA.pkl")` |

`score_orders.py` handles routing automatically — you do not need to pick the right model manually.

### Report files

`reports/report_KH.json`, `reports/report_KT.json`, `reports/report_KIPA.json` — one per model, each contains:

```json
{
  "contract_type": "KH",
  "roc_auc": 0.9517,
  "false_alarms": 17,
  "classification_report": { ... },
  "confusion_matrix": [[644, 17], [97, 388]],
  "train_size": 5327,
  "test_size": 1146,
  "trained_on_date": "2026-06-06",
  "top_features": [
    {"feature": "work_order_type_EH-työ", "importance": 0.21663},
    ...
  ]
}
```

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
| `train_sla_model.py` | Trains a single combined model (all contract types) | Baseline / comparison only |
| `train_segmented_models.py` | Trains KH, KT, KIPA models separately | **Primary training script** — run monthly |
| `score_orders.py` | Loads segmented models, scores recent orders | On demand — run any time |
| `run_sla_prediction.py` | End-to-end demo: train + evaluate + score | Demos and verification only |

---

## How to run

```bash
# Step 1 — run the data pipeline (generates Silver Parquet)
cd luotea-pipeline
python3.11 -m pipeline ingest --source all --date $(date +%Y-%m-%d)
python3.11 -m pipeline transform --layer silver --domain erp --date $(date +%Y-%m-%d)

# Step 2 — train segmented models
cd ../luotea-ml
pip install -r requirements.txt
python3.11 scripts/train_segmented_models.py

# Step 3 — score current orders
python3.11 scripts/score_orders.py
python3.11 scripts/score_orders.py --cutoff 2026-01-01 --top 50   # custom date and count
```

---

## What comes next

| Priority | Task | Why |
|---|---|---|
| High | Dashboard integration | Load segmented `.pkl` files by contract type; show risk table and feature importance chart |
| ~~High~~ | ~~SP cleaning model~~ | ✅ Built — see `cleaning_optimizer.py` |
| Medium | KT improvement | Add alarm history feature (number of alarms at the site in the 30 days before the order) — expected to significantly improve KT AUC |
| Medium | Monthly retraining | Schedule `train_segmented_models.py` to run automatically as new Silver data arrives |
| Low | Work order volume forecasting | Predict how many orders per type per site per week — staffing and resource planning |
