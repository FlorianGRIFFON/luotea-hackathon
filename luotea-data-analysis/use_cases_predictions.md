# ML Predictions & Use Cases — Luotea Hackathon 2026

What can be built on top of the standardized Bronze → Silver → Gold pipeline data.

---

## High feasibility

### 1. SLA Violation Prediction
**Data:** `fact_work_order` — 44,265 rows, 9 years  
**Task:** Binary classification — given a new work order's site, contract type, work type, and assignment → will it violate SLA?  
**Why it works:** 53.8% violation rate means balanced classes. All features are known at intake time (before the outcome), so the model predicts before the violation happens.  
**Output:** "This cleaning order has 78% chance of SLA miss — escalate now."

---

### 2. Work Order Volume Forecasting
**Data:** `fact_work_order` — 9 years of history  
**Task:** Time series — predict how many work orders per type per site per week  
**Why it works:** Long history with clear seasonality (seasonal maintenance, winter/summer cycles). Useful for staffing and resource planning.  
**Output:** "Expect 40 reactive orders at Venttiilitehdas next week."

---

### 3. Alarm Escalation Prediction
**Data:** `fact_alarm` + `fact_work_order` joined via `WORKORDER_NO`  
**Task:** Binary classification — given an alarm's type, device (`hwid`), priority, and site → will it generate a work order?  
**Why it works:** Only 4% of alarms become work orders. The model separates signal from noise: which alarm patterns actually require action.  
**Output:** "This HVAC alarm has historically escalated to work orders 60% of the time — flag for review."

---

### 4. Energy Anomaly Detection
**Data:** `fact_sensor_reading` — ~792k readings, 5 years for Aurora House and Horizon Plaza  
**Task:** Unsupervised anomaly detection (Isolation Forest, LSTM autoencoder) on hourly electricity/heating/water consumption  
**Why it works:** Long history enables learning normal seasonal and weekly patterns. Spikes or drops flag equipment issues before they become alarms.  
**Output:** "Heating consumption at Horizon Plaza yesterday was 3σ above the March baseline — possible heat exchanger issue."

---

## Medium feasibility

### 5. Usage-Driven Cleaning Demand (Lentokentänkatu 11 only)
**Data:** `fact_utilization` (176 desks + 38 rooms) + robot task logs + work orders  
**Task:** Regression — predict how much cleaning a zone needs based on that day's occupancy  
**Why it works:** This is the core hackathon hypothesis — replace calendar-based with data-driven cleaning. Sensor data and robot outcomes exist at the same site and can be directly correlated.  
**Output:** "Floor 3 had 87% desk utilization today — schedule robot pass tonight. Floor 5 was empty — skip."

---

### 6. Equipment Failure Pattern Detection
**Data:** `fact_alarm` — 18,702 events with device IDs (`hwid`)  
**Task:** Identify devices with accelerating alarm frequency — a classic reliability signature before failure (CUSUM / trend detection per `hwid`)  
**Output:** "Device FA-3821 has had 12 alarms in the last 30 days vs. 2/month baseline — schedule inspection."

---

### 7. Planned Maintenance Quality Prediction
**Data:** `fact_maintenance_plan` joined to `fact_work_order` via `PM_NO`  
**Task:** Predict which scheduled maintenance plans will generate reactive/unplanned follow-up work orders  
**Why it works:** If a planned maintenance event consistently generates reactive work within 2 weeks, either the plan is insufficient or the equipment is degrading.  
**Output:** "PM plan 90122 (HVAC filter) consistently generates reactive alarms within 10 days — shorten interval."

---

## What needs more data to work well

| Prediction | Blocker |
|---|---|
| Climate comfort prediction (CO2/temp) | Only 6 months of climate data — not enough seasonality |
| Cross-site maintenance benchmarking | Coverage is split: Valmet has ERP, NovaProp has Smartti — no overlap |
| Robot wear/failure prediction | Only 332 Phantas tasks — too few for a stable model |
| Energy normalization by m² | `gross_area_m2` is null for all properties |

---

## Recommended starting point

The highest value + most data combination is:

**SLA violation prediction + work order volume forecasting** — both use the same 44k-row, 9-year work order table, they are complementary (volume = planning, SLA = operations), and the business value is immediately legible: "flag this order before it misses SLA."

Second best is **energy anomaly detection** on Smartti — 5 years of hourly data for 2 buildings is genuinely strong for time series models, and it directly demonstrates the "move from reactive to predictive" theme of the hackathon.

---

## Gold tables available as feature input

| Table | Grain | Key signals |
|---|---|---|
| `site_daily_signals.parquet` | site × day | alarm_count, sla_violations, avg_co2_ppm, electricity_kwh, avg_room_utilization_pct |
| `event_timeline.parquet` | event | unified alarms + work order lifecycle + incidents |
| `fact_work_order` (Silver) | work order | full row-level detail, 9 years |
| `fact_alarm` (Silver) | alarm event | hwid, type, priority, escalated flag |
| `fact_sensor_reading` (Silver) | metric × timestamp | hourly energy + climate per building |
| `fact_utilization` (Silver) | asset × day | room/desk occupancy percentage |
