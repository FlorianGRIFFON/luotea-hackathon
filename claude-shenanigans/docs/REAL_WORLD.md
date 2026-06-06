# Real-world value — from data to a maintenance decision

This is the story for the jury and for Luotea's product team: who uses this, what changes, and
how it reaches production.

## 1. Customer persona

**Sari, Facility & Service Manager at Valmet's Lentokentänkatu 11 (Tampere).** She owns the
service contract: cleaning, technical maintenance, security, outdoor care. Her performance is
measured on **SLA compliance** and tenant satisfaction. Today she manages a backlog of dozens of
open work orders per day across multiple subcontractors, and she finds out a job breached its SLA
**after** it happened — when the report lands or a tenant complains.

A parallel persona: **Mikko, property-ops lead at NovaProp**, who runs Aurora House with no ERP
work orders at all — only Smartti energy/IoT. He needs the *same* reliability picture from a
completely different data shape.

And the people who actually do the work: **Aino (cleaner), Ville (groundskeeper), Mika
(technician)** — maintainers who don't care about AUC. They need one thing on their phone: *"what
are my jobs today, and which one first?"* The engine serves them too (see §4, two role-based views).

## 2. Before Luotea

- **Siloed data.** ERP work orders in one system, alarms in a CSV, energy in Smartti, elevators
  in KONE, cleaning in spreadsheets — different IDs, formats, encodings, languages.
- **Calendar-driven maintenance.** Work happens because the schedule says so, not because risk
  rose. Over-maintenance on calm assets, under-maintenance on stressed ones.
- **Reactive SLA management.** Breaches are discovered after the fact. The recurring small
  disturbances accumulate invisibly — exactly the pain the hackathon brief names.

## 3. After the pipeline (already built)

The medallion pipeline unifies six source families into a QA-gated **`site_daily_signals`** and
**`event_timeline`**, keyed by one canonical `site_id`, with honest nulls where a source is
absent. Sari and Mikko now have a single, trustworthy daily view of their sites — the hard part
Luotea solves. But a unified *report* still only describes the past.

## 4. After the Reliability Risk Engine (our layer)

We turn that unified data into **forward-looking decisions**:

1. **Risk-ranked dispatch.** Every open work order gets a **breach-probability** at creation time.
   Sari opens the morning queue already sorted "do these first." Acting on the riskiest 10 %
   surfaces breaches at **~87 % precision** instead of working in arrival/calendar order. In our
   held-out backlog sample, the riskiest third of the day's jobs contained **10 of 25** breaches —
   and the jobs the model pushes to the top (outdoor/periodic maintenance at 90–97 % risk) are
   *not* the ones a static priority field would have flagged, while genuinely low-risk repairs
   (~20 %) can safely wait.
2. **A single reliability number.** The **Reliability Risk Index (0–100)** tells Sari *and* Mikko,
   on one comparable scale, whether today is a normal day or an elevated-risk day for their site —
   even though one site speaks "ERP work orders" and the other speaks "kWh and incidents."
3. **A dynamic calendar.** When the index crosses the elevated band, the system recommends pulling
   maintenance forward; when an asset is calm for weeks, it recommends relaxing the cadence —
   directly attacking both **over- and under-maintenance**.

**The decision that changes:** Sari stops dispatching in calendar order and starts dispatching in
**risk order**, with a defensible, explainable reason per work order. Mikko gets the same
elevated-risk early-warning from pure IoT. Spend shifts from *working hours* to *operational
reliability* — the contractual shift the brief calls for.

### Two role-based views (one engine, mobile-ready)

The same predictions drive two operations-facing screens in the demo app (`src/demo/app.py`),
because reliability is only useful if it reaches the person who acts:

- **🧑‍💼 Manager view** — the *global* picture: every site's reliability today on one 0–100 scale,
  the **crew workload** (who is carrying the high-risk jobs), and the **risk-ranked queue with each
  task already attributed to a crew member**. Predictive maintenance doesn't just rank the backlog —
  it *assigns* it (`src/features/assignment.py`): the riskiest job goes to the right-skilled,
  least-loaded worker first.
- **🧰 Maintainer view ("My tasks")** — a cleaner/technician picks their name and sees *only their*
  jobs, riskiest first, each with a plain-language reason ("long/complex job that has historically
  slipped — start now"). No model jargon, no clutter.

Both views are **mobile-responsive** (columns stack, padding and type shrink below ~680 px) — the
jury flagged that field staff use phones, and a maintainer in the building checks "my tasks" on a
handset, not a desktop. A reproducible plain-text **morning briefing** is also generated at
`outputs/operations_briefing.md`.

## 5. Rollout path

```
Customer export  ─▶  Bronze ingest  ─▶  Silver clean/conform  ─▶  Gold marts  ─▶  Risk Engine  ─▶  Sari's queue / API
 (CSV, JSON)         (immutable)        (types, site_id)          (daily, QA)     (model+index)     (dispatch, alerts)
```

1. **Onboard a customer** = add their export to Bronze + a `sites.yaml` mapping row. No new model.
2. **Nightly:** pipeline rebuilds Gold and runs the QA gate; the model scores the day's new work
   orders and refreshes each site's Reliability Index.
3. **Serve:** push the risk-ranked queue into the FM tool the team already uses, and raise an alert
   when a site crosses its elevated-risk band.

## 6. What changes in production

| Area | Hackathon prototype | Production |
|------|---------------------|-----------|
| Scheduling | `make demo` on demand | Nightly job after the pipeline QA gate passes |
| Serving | Streamlit + Parquet | Scoring API / write-back into the FM/ERP work queue |
| Alerting | Elevated-risk band on a chart | Threshold + trend alerts to the on-call manager |
| Human-in-the-loop | Read-only ranking | Manager confirms/overrides; overrides become training feedback |
| Drift | Time-based split shows it exists | Scheduled retrain + monitored AUC/calibration over time |
| Models per site | One cross-site model | Same, with per-customer calibration as data grows |
| GDPR / PII | Pipeline PII-scans Gold (QA: no leak) | Same scan in CI; access controls; anonymized IoT (as Aurora already is) |

## 7. Honest limitations (and why they're fine)

- **Alarms are sparse before 2025** → used as a supporting signal, not the primary target.
- **Utilization covers ~25 % of L11 days** → an optional feature, never required.
- **AUC 0.70, not 0.95** → this is a genuinely noisy operational target on real data; the value is
  in the **ranking** (precision@k) and the **decision**, and every number is from a leakage-free
  future hold-out, not a flattering in-sample fit.
