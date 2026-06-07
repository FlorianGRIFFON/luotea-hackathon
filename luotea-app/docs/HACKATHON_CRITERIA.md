# Judging Criteria → Our Solution

**Max score: 25 pts (5 categories × 1–5).** Core challenge:
**predictive maintenance — from calendars to data-driven reliability.**
Narrative arc the jury wants: **data → signals → decisions.**

## The 5 categories

| # | Category | Pts |
|---|----------|-----|
| 1 | Impact on real estate business | 1–5 |
| 2 | Use of data and analytics | 1–5 |
| 3 | Feasibility and scalability | 1–5 |
| 4 | Innovation and distinctiveness | 1–5 |
| 5 | User, customer and operations perspective | 1–5 |

## Our hero use case

**Reliability Risk Engine** — predict, at the moment a maintenance work order is created,
the probability it will **breach its SLA**; aggregate those probabilities (plus alarms and an
unsupervised anomaly flag) into a single daily **Reliability Index** per site; and surface a
**risk-ranked dispatch list** that lets a facility manager re-order today's work *before* the
breach happens. Calendar-based → risk-based, in one screen.

### How it maps to each category

| Category | How we score | Evidence in repo |
|----------|--------------|------------------|
| **1. Impact on RE business** | SLA breaches are the "recurring small disturbances" the README names as the real cost driver. We move spend from working-hours to **outcomes** (avoided breaches, fewer reactive call-outs). We quantify how many breaches are caught at a given dispatch capacity (precision@k). | `outputs/metrics/sla_risk_metrics.json`, `REAL_WORLD.md` |
| **2. Use of data & analytics** | Supervised ML on 44k real labelled work orders, **leakage-safe** (creation-time features only), **time-based** holdout, baselines vs model, calibration + feature importance. Not "we used AI" — a defensible pipeline. | `src/models/sla_risk.py`, `outputs/figures/` |
| **3. Feasibility & scalability** | Sits directly on the existing **medallion pipeline + QA gate**. Same Gold schema and `site_id` join key already span Valmet ERP **and** NovaProp IoT, so onboarding a new customer = new Bronze export, no new model. Trains in seconds; runs on a laptop. | `ARCHITECTURE.md`, cross-site training |
| **4. Innovation & distinctiveness** | The **cross-customer, cross-source Reliability Index**: one comparable 0–100 reliability number computed from *whatever signals a site has* (ERP for Valmet, energy+incidents for Aurora). That unification is exactly what Luotea sells and what a single-source team cannot show. | `src/features/reliability_index.py` |
| **5. User / customer / ops** | Output is a **decision**, not a dashboard of metrics. **Two role-based, mobile-responsive views**: a **Manager** view (portfolio reliability + crew workload + risk-ranked queue) and a **Maintainer** "My tasks" view (a worker's own jobs, riskiest first, plain-language reason). Predictive maintenance **attributes** each task to the right-skilled, least-loaded crew member. Human-in-the-loop, persona-driven, works on a phone. | `src/demo/app.py`, `src/features/assignment.py`, `REAL_WORLD.md` |

### Narrative arc

- **Data** — Gold `site_daily_signals` + Silver `fact_work_order`, already cleaned & QA-passed.
- **Signals** — per-work-order breach probability + daily Reliability Index + anomaly flag.
- **Decisions** — risk-ranked dispatch list; dynamic maintenance calendar instead of fixed one.

### Honesty (jury rewards it)

- Partial site coverage is shown, not hidden (nulls are real).
- Alarms are sparse pre-2025 → used as a supporting signal, not over-claimed.
- Temporal drift is disclosed and handled with a time-based split.
- Baseline vs model is reported so the ML lift is verifiable.
