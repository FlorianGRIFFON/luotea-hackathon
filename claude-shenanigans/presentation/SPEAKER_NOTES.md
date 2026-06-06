# Speaker notes — 5-minute pitch

Render slides with [Marp](https://marp.app): `marp presentation/slides.md -o slides.html`
(or the VS Code Marp extension). Figures are referenced from `../outputs/figures/` — run
`make predict` first so they exist.

**Timing target: 5:00. Practice the transitions in bold.**

| # | Slide | ~Time | Say this | 
|---|-------|------:|----------|
| 1 | Title | 0:20 | "We move maintenance from the calendar to real risk. Three words: **data → signals → decisions**." |
| 2 | Problem | 0:40 | Hammer the brief's own point: the cost isn't one big failure, it's **recurring small SLA breaches** no one sees coming. Today's data reports, it doesn't guide. |
| 3 | Solution | 0:35 | "The pipeline already did the hard part — unifying six fragmented sources. **We add the predictive layer on top, read-only.**" Point at the two-site chart: same 0–100 scale. |
| 4 | Data | 0:35 | Be honest about coverage — Valmet has ERP, Aurora has IoT, nulls are real. **44k work orders, 54 % breach.** Honesty scores points. |
| 5 | Hero use case | 0:50 | This is the money slide. "Every work order gets a breach probability **at creation**. We re-rank the queue. The 97 %-risk outdoor job rises; the 20 %-risk repair waits — **the opposite of what the calendar says**." |
| 6 | Results | 0:45 | "Time-based split, **no leakage**. AUC 0.70 beats the priority rule. Act on the riskiest 10 % → **87 % precision, 768 breaches caught**." Stress it's a *future* hold-out, not in-sample. |
| 7 | Reliability Index | 0:35 | "One number, every site, comparable. 90 = top-decile risk day anywhere. Cross the band → pull work forward; calm → relax cadence. **Over- and under-maintenance, both solved.**" |
| 8 | Customer value | 0:40 | Tell Sari's story as a person. Before: finds out after. After: queue sorted, explainable. **Hours → reliability.** |
| 9 | Feasible & scalable | 0:30 | "Trains in seconds. New customer = one export + one row, **no new model**. Two commands to run. Then API, write-back, alerting." |
| 10 | Thank you | 0:15 | "Predict breaches, measure reliability, rank the work. Happy to demo live." |

## Likely jury questions & answers
- **"Is AUC 0.70 good enough?"** — It's a genuinely noisy operational target on real data, on a
  *future* hold-out. The value is the **ranking**: 87 % precision at the top-10 % is what a
  capacity-limited team actually uses. Baselines and calibration are in the model card.
- **"Is the SLA-window feature a leak?"** — No. The deadline is set at creation; the breach is
  decided later by the actual finish. We assert post-completion fields out of the feature set, and
  the test suite enforces it. The finding (no-deadline jobs breach 23 %, long-window jobs 81 %) is
  an operational insight.
- **"Why does this need Luotea specifically?"** — The cross-source, cross-customer unification.
  One model + one index spanning Valmet ERP and NovaProp IoT is something a single-source team
  can't show. Onboarding scales without new models.
- **"Live demo?"** — `make app`, tab 2 (dispatch) is the highlight; tab 3 is the honest model card.

## Live demo script (if asked, ~60s)
1. `make app` → **Reliability Index** tab: pick Valmet L11 + Aurora, show the same scale.
2. **Dispatch** tab: scroll the colour-ranked queue — "do the red ones first".
3. **Model card** tab: point at the baseline-vs-model table and the calibration curve.
