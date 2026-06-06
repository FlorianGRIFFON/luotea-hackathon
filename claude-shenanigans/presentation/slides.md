---
marp: true
theme: default
paginate: true
size: 16:9
style: |
  section { font-size: 26px; }
  h1 { color: #1565C0; }
  h2 { color: #2E7D32; }
  strong { color: #E53935; }
  table { font-size: 22px; }
  footer { color: #9E9E9E; }
footer: "Luotea Hackathon 2026 · Reliability Risk Engine"
---

# 🌿 Reliability Risk Engine
## From calendar-based maintenance to **data-driven reliability**

**data → signals → decisions**

Predict tomorrow's SLA breaches today · one reliability score for every site · a maintenance queue that ranks itself by risk.

Built on the Luotea medallion pipeline (Gold) · Luotea Hackathon 2026

---

## The problem: maintenance runs on the calendar, not on risk

- Work happens because it's **scheduled**, not because risk rose.
- Facility data is **fragmented**: ERP work orders, alarms, Smartti energy, KONE, cleaning — different systems, IDs, formats, languages.
- The real cost isn't one big failure — it's **recurring small disturbances**: SLA breaches that pile up unseen until a tenant complains.
- Today's data **reports the past**; it doesn't **guide** the next decision.

> How do we move building maintenance from calendars to predictive, data-driven management?

---

## The solution: a thin predictive layer on a unified data backbone

![w:1100](../outputs/figures/reliability_index_cross_site.png)

The pipeline already unified **6 source families** into a QA-passed Gold model keyed by `site_id`.
We add **prediction + a single reliability metric** on top — read-only, additive.

---

## The data: two very different customers, one honest schema

| Site | What it has | What it lacks |
|------|-------------|---------------|
| **Valmet L11** (ERP) | work orders, **SLA**, backlog, alarms | energy, elevators |
| **Aurora** (NovaProp IoT) | electricity (98 %), heating, incidents | ERP work orders |

- **44,265** real work orders · **53.8 %** breach SLA · 2017→2026.
- Partial coverage is **kept as nulls**, never faked — that's production reality.
- A missing source never reads as "calm".

---

## Hero use case: predict SLA breaches → rank the dispatch queue

**At work-order creation time**, predict the probability it will **breach SLA** — then re-order the backlog so the riskiest jobs are done first.

![w:880](../outputs/figures/dispatch_list_site_valmet_l11.png)

90–97 %-risk jobs rise to the top (and *did* breach); 20 %-risk repairs sink — **not** what calendar/priority order would pick.

---

## The result: honest, leakage-free, beats the baseline

![w:560](../outputs/figures/sla_roc_pr.png) ![w:560](../outputs/figures/sla_dispatch_precision_at_k.png)

- **ROC-AUC 0.704** vs 0.640 priority-rule baseline · time-based hold-out, no leakage.
- Riskiest **10 %** → **86.8 % precision**, **768** breaches caught (base rate 61 %).
- Riskiest **5 %** → **99.5 %** precise · probabilities **calibrated**.

---

## One reliability number for every site

The **Reliability Risk Index (0–100)** blends *whatever signals a site has* —
SLA risk + alarms (ERP), energy anomaly + incidents (IoT) — into one comparable scale.

- **0** = a calm day · **100** = an unusually high-risk day *for that site*.
- Same number means the same thing on a factory or an office tower.
- Cross the **elevated band** → pull maintenance forward. Calm for weeks → relax the cadence.

→ Attacks **over- and under-maintenance** at once; the calendar becomes **dynamic**.

---

## Real customer value — two views, one engine, on a phone

**🧑‍💼 Manager (Sari):** global picture — every site's reliability today, crew workload, and the
**risk-ranked queue with each job already attributed to a worker**.

**🧰 Maintainer (Aino/Ville):** opens *"My tasks"* on a phone — only their jobs, riskiest first,
with a plain reason. No jargon.

- **Before:** breaches discovered *after* the fact; work done in calendar order.
- **After:** riskiest **10 %** acted on first → catches ~**87 %** of breaches early; the engine
  *assigns* the right job to the right-skilled, least-loaded crew member.
- **Mobile-responsive** — field staff live on handsets. **Mikko at NovaProp** gets the same from pure IoT.

Spend shifts from **working hours → operational reliability**. Decision-support, human-in-the-loop.

---

## Feasible & scalable — because the hard part is already done

- Sits on the existing **medallion pipeline + QA gate**; trains in **seconds** on a laptop.
- **Onboard a new customer = one Bronze export + one mapping row. No new model** (`site_id` is a feature).
- Whole flow in **two commands**: `make demo` · `make app`. 12 tests green.
- Roadmap: scoring API → write-back into the FM tool → alerting → scheduled retrain → **contract on outcomes, not hours**.

---

## Thank you 🌿

**Reliability Risk Engine** — predict breaches, measure reliability, rank the work.

`data → signals → decisions`

- **Demo:** `make app`  ·  **Code & docs:** `claude-shenanigans/`
- ROC-AUC 0.704 · 87 % top-10 % dispatch precision · one 0–100 index across ERP + IoT

*Questions?*
