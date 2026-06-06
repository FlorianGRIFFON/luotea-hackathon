# SLA Prediction — Business Value & Conclusions

## What the models enable

### 1. Morning risk briefing for operations managers
Every morning, `score_orders.py` produces a ranked list of orders by SLA risk. Instead of reviewing every open order, the operations manager looks at the flagged HIGH risk ones and decides: reassign, expedite, or call the technician.

The KH model does this with high precision — when it flags HIGH risk, it is almost certainly right. That is trustworthy enough to act on.

### 2. Escalation before the deadline, not after
Right now, SLA violations are discovered after they happen. The model flags them at order *creation* — potentially 2–5 days before the deadline. That window is enough to reassign the job or negotiate with the client.

### 3. Quantified: how many violations could be prevented

From the KH test set (1,146 orders, last 12 months):

| | Number |
|---|---|
| Actual violations | 485 |
| Caught by model (80% recall) | 388 |
| False alarms | 15 |

If operations intervenes on the 388 flagged orders and converts even half to compliant, that is **~194 KH SLA violations avoided per year at one site**. If each violation carries a contractual penalty or relationship cost, that number is a concrete business case.

---

## What the data reveals (structural insights)

These findings come from the data itself, not just the model. They are valuable regardless of whether the prediction tool is used.

### 4. The outdoor maintenance problem is specific and fixable
KH outdoor and green area maintenance has a **62% violation rate** vs 33% for indoor technical work — nearly double. Winter maintenance (snow clearing) has only **2% violation rate**.

This tells a precise story: either the outdoor SLA terms are too tight for the seasonal workload, or the crew is undersized in spring and autumn. This is actionable at the contract negotiation level, not just operationally.

### 5. Building automation is a bottleneck
KT building automation repairs have a **77% violation rate** — the highest of any technical work type. Electrical project services, by contrast, have only **11%**.

This means either there are not enough qualified BMS technicians available, or the SLA window is unrealistic for that type of work. The data makes the case for either hiring a specialist or renegotiating those specific SLA terms.

### 6. Team workload predicts KT failures
The KT model discovered that the rolling 7-day average of open work orders at a site is the **third most important predictor** of SLA violations — more important than site identity or most work type categories.

This is an operational insight: KT SLA compliance is not just about the type of work, it is about whether the team is already overloaded when the order arrives. A site running 18 open WOs over the past week will miss more SLAs than the same site at 8 open WOs, for the exact same type of job.

### 7. The SP cleaning contract has a structural problem
61% of all cleaning orders miss SLA. That is not a prediction problem — it is evidence that the current cleaning contract terms are routinely unachievable. This is powerful data for a contract review conversation with the client.

---

## SP cleaning: utilization-driven optimizer

Because SLA prediction does not work for cleaning, a different model was built: `cleaning_optimizer.py`. Instead of predicting SLA violations, it produces a **nightly priority list** — which rooms to clean and which to skip — based on how rooms were actually used that day.

### How it works

The model has two components:

**1. Usage tier clustering** — trained once on 2.5 years of sensor history, groups 38 rooms into three tiers:

| Tier | Rooms | Average utilization | Default frequency |
|---|---|---|---|
| HEAVY | Coffee lounge, Varpu, K14, K11, K12, K5, Naava, Mustikka, Norppa, Siili, Jäkälä | 45% | Daily or near-daily |
| MEDIUM | 23 rooms | 32% | 2–3× per week |
| LIGHT | 2.krs Neukkari, K16, K7, Räme | 10% | Weekly |

**2. Daily urgency score** — computed each evening from three signals:

| Signal | Weight | What it captures |
|---|---|---|
| Today's utilization | 50% | Immediate need — how busy was the room? |
| Rolling 3-day average | 30% | Accumulated use — has it been busy all week? |
| Accumulation days (max 5) | 20% | Rest penalty — how long without a zero-use day? |

Score ≥ 65 → **CLEAN tonight** | 35–65 → **MONITOR** | < 35 → **SKIP**

### Operational value

| Before (calendar-driven) | After (utilization-driven) |
|---|---|
| Same rooms cleaned every Tuesday and Friday | Only busy rooms cleaned that night |
| 2.krs Neukkari cleaned 104× per year (barely used) | 2.krs Neukkari cleaned when it's actually used |
| Cleaners spend time on empty rooms | Cleaners spend time where dirt has actually accumulated |
| Impossible to justify skipping any room | Data-backed skip decisions — easy to audit |

---

## What the dashboard should show

| Screen | Data source | Question it answers |
|---|---|---|
| **Risk inbox** | `score_orders.py` output | Which orders need attention today? |
| **SLA trend** | Gold `site_daily_signals` | Is compliance improving or getting worse over time? |
| **Violation breakdown** | Silver `fact_work_order` | Which work types and sites are the worst offenders? |
| **Model confidence** | Report JSONs | How reliable is each prediction? (AUC per contract type) |
| **SP alert** | Silver, filtered to SP | 61% systemic violation rate — not a prediction problem, a contract problem |

---

## Honest limits — what cannot be extracted yet

| Question | Why it is blocked |
|---|---|
| Why does Venttiilitehdas miss SLA more than L11 for KT? | No staffing or shift data available |
| Which technician or team causes the most violations? | Anonymised in the dataset |
| Will this week's cleaning be on time? | Needs room utilization sensor data — only available for Lentokentänkatu 11 |
| How much money is lost per violation? | No financial data in the dataset |

---

## Summary

The models turn a reactive process — *"we missed 53% of SLAs last month"* — into a proactive one: *"these orders are at high risk right now, act before the deadline."*

| Contract | Model quality | Practical use |
|---|---|---|
| KH — Property maintenance | AUC 0.950 — production ready | Flag reactive orders before they miss SLA |
| KT — Technical maintenance | AUC 0.784 — useful signal | Prioritise by workload pressure and work type |
| SP — Cleaning | No model | Reveals a structural contract problem — 61% baseline violation |

For KH, the prediction is reliable enough to act on directly. For KT, it is a useful prioritisation signal — especially valuable when the site is running a high open-WO backlog. For SP, the most valuable output is not a prediction — it is the number itself: **61% of cleaning orders miss SLA by default**, which is a finding that belongs in a client conversation, not a dashboard alert.
