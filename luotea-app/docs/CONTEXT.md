# Context — Luotea Hackathon 2026

> **data → signals → decisions** — how fragmented facility data becomes predictive maintenance.

## 1. Hackathon goal (in our words)

Building maintenance today is **calendar-driven and reactive**: work is done because it is
scheduled, and risk stays invisible until an end user files a fault report. The challenge is
*not* a lack of data — fault reports, alarms, energy, IoT, work orders all exist — but its
**fragmentation**. The task is to turn that fragmented data into a **coherent, forward-looking
signal of disruption risk** that actively guides maintenance decisions, so the fixed calendar
becomes a **dynamic, risk-based** one.

The README is explicit that the real pain is *"recurring small disturbances that accumulate
unnoticed as a result of static maintenance and reactive operating models"* — not one big
failure. That points us at the **work-order / SLA backlog** as the heartbeat of reliability.

Judged on 5 categories (1–5 pts each, max 25): impact on RE business, use of data & analytics,
feasibility & scalability, innovation & distinctiveness, user/customer/ops perspective. See
[`HACKATHON_CRITERIA.md`](./HACKATHON_CRITERIA.md).

## 2. What the pipeline already gives us (read-only inputs)

A **medallion pipeline** (`../luotea-pipeline/`) already unifies **6 source families** —
ERP alarms, ERP work orders, ERP maintenance plans, Smartti IoT, KONE elevators, cleaning
utilization — into one canonical model keyed by `site_id`:

| Layer | Asset | Grain | Rows |
|-------|-------|-------|------|
| Gold | `site_daily_signals.parquet` | site × day | 10,350 |
| Gold | `event_timeline.parquet` | one event | 107,706 |
| Silver | `fact_work_order` | one work order | 44,265 |
| Silver | `fact_alarm` | one alarm | 18,702 |
| Silver | `fact_sensor_reading` | hourly Smartti | 792,506 |
| Silver | + incidents, occupancy, utilization, maintenance plans, dims | | |

Latest QA report (`qa_report_2026-06-05.json`) is **PASS**, 0 errors / 0 warnings, idempotent,
no PII leak. We consume these outputs directly and never re-run the pipeline.

## 3. Coverage per site (what data actually exists)

Overall date range **2017-05-29 → 2026-06-01**. Partial coverage is **structural and real** —
Valmet sites carry ERP, NovaProp sites carry IoT — and the Gold layer keeps nulls rather than
dropping rows.

| `site_id` | rows | date range | dense signals | absent |
|-----------|------|------------|---------------|--------|
| `site_valmet_l11` | 2,538 | 2018-06 → 2026-05 | work orders, SLA, open backlog, alarms (2025+) | energy, CO₂, elevator |
| `site_valmet_venttiilitehdas` | 3,237 | 2017-05 → 2026-06 | work orders, SLA, alarms | energy, utilization |
| `site_aurora` (NovaProp) | 1,928 | 2021-02 → 2026-05 | electricity (98%), heating (95%), incidents | ERP alarms, work orders |
| `site_horizon`, `site_meridian` | 1,903 / 305 | 2021+ | electricity, heating | ERP |
| `site_valmet_toimistotalo`, `_std` | 365 / 74 | 2021+ / 2024+ | sparse work orders | most |

## 4. Exploratory insights (Polars on Gold + Silver)

1. **SLA breaches are the dense, multi-year reliability signal.** Of **44,265** Valmet work
   orders, **53.8 %** breach SLA — a balanced, fully-labelled target spanning 2017→2026. This is
   the "small recurring disturbance" the README calls the real pain point, and it is present
   every year (unlike alarms).

2. **SLA breach is strongly predictable from creation-time attributes.** Breach rate ranges
   **4 %→84 % by priority**, **27 %→69 % by work type**, **52 % (`Tilaustyö`) vs 81 % (`EH-työ`)**
   by order type, and **38 %→61 % by contract type**. A model has real signal to learn — without
   touching any post-completion field.

3. **Alarms are data-starved before 2025.** At `site_valmet_l11`, `alarm_count` is **0 for all of
   2018–2024** and only becomes non-zero in 2025 (89 alarm-days, max 104/day). A pure
   alarm-forecast would train on ~1 year — so alarms are used as a *supporting* reliability signal,
   not the primary ML target.

4. **NovaProp reliability is an energy story.** `site_aurora` has **no ERP events at all** but
   dense electricity (98 % of days, 2,971–10,608 kWh) and heating (95 %); CO₂/temp are sparse
   (7–9 %) and incidents rare (mean 0.05/day). Aurora's risk signal must come from
   **energy anomaly + incidents**, proving the unified model spans very different customers.

5. **Honest temporal drift exists.** Valmet breach rate climbs **19 % (2017) → ~60 % (2025–26)**.
   This makes a **time-based train/test split** essential (no random leakage) and makes a strong
   held-out result genuinely credible.

6. **Utilization is ~25 % coverage at L11** (628 of 2,538 days) — matching the README note that
   IoT cleaning sensors cover only ~10 % of the site. We treat it as an optional feature, never
   a requirement.

## 5. What we build on top (one hero)

A **Reliability Risk Engine**: a leakage-safe model that scores every work order's SLA-breach
probability at creation time, rolled up into a daily, cross-site **Reliability Index** that turns
the static maintenance calendar into a **risk-ranked dispatch list**. See
[`ARCHITECTURE.md`](./ARCHITECTURE.md) and [`REAL_WORLD.md`](./REAL_WORLD.md).
