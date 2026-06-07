# Pitch guide — the app *is* the presentation

We retired the slide deck: the **Streamlit app drives the whole pitch**. One artifact, nothing to
keep in sync, and the strongest possible signal — "this is real and it runs."

```bash
cd claude-shenanigans
make demo     # ensure artifacts are fresh (verify ▶ train ▶ predict ▶ tests)
make app      # open the app — present from here
```

> **Before you walk on stage:** run `make app` once and leave it open. Have the browser zoomed so
> text is readable from the back. The **🎤 Story** tab is your title + problem + solution slide.

## 5-minute run sheet (tab by tab)

| ~Time | Tab | What to say / show |
|------:|-----|--------------------|
| 0:45 | **🎤 Story** | Read the arc: maintenance runs on the *calendar*, the real cost is *recurring small SLA breaches*, data is *fragmented*. "We add a thin predictive layer on Luotea's unified pipeline: **predict → measure → decide**." Point at the three headline metrics on the right. |
| 1:15 | **🧑‍💼 Manager** | "Here's what a facility manager sees." Portfolio reliability per site (one 0–100 scale), crew workload, and the **risk-ranked queue with each job already attributed to a worker**. Stress: the engine doesn't just rank — it *assigns*. |
| 1:00 | **🧰 My tasks** | Switch the dropdown to **Ville (Grounds)** — he has the high-risk jobs. "This is the maintainer's phone view: only my work, riskiest first, with a plain reason. No jargon." Mention it's **mobile-responsive** — field staff use handsets. |
| 0:45 | **📈 Reliability** | "One 0–100 index, every site. For ERP sites it's the model's *absolute* breach probability — Valmet genuinely runs ~50% breach, the IoT sites sit much lower. It *persists* — a bad week stays elevated, it doesn't snap back." |
| 0:45 | **🤖 Model card** | The honesty slide. Baseline-vs-model table (AUC 0.704 vs 0.640 rule), **time-based split, no leakage**, calibration curve. "Acting on the riskiest 10% catches 768 breaches at 87% precision." |
| 0:30 | **🧩 Unified data** | "Same schema spans Valmet ERP and NovaProp IoT — partial coverage shown honestly. New customer = one export, **not** a new model." Close on the roadmap line. |

Total ≈ 5:00. If you only get 3 minutes: **Story → Manager → Model card.**

## Likely jury questions & answers
- **"Is AUC 0.70 good enough?"** — Noisy operational target on a *future* hold-out. The value is the
  **ranking**: 87% precision on the riskiest 10% is what a capacity-limited team actually uses.
- **"Why does the index sit near 50 for Valmet?"** — Because that site genuinely breaches ~50% of its
  work — it's an *absolute* probability, not an artifact. Calmer IoT sites sit at ~15–23. It also
  *persists* (7-day smoothed), so a bad stretch stays elevated.
- **"Is the SLA-window feature a leak?"** — No. The deadline is set at creation; the breach is decided
  later by the actual finish. Post-completion fields are asserted out (enforced by tests).
- **"Why Luotea specifically?"** — Cross-source, cross-customer unification: one model + one index
  across ERP and IoT. Onboarding scales without new models.

## Fallback if the laptop/projector won't run Streamlit
The pre-rendered figures in `outputs/figures/` (`reliability_index_cross_site.png`,
`sla_roc_pr.png`, `sla_dispatch_precision_at_k.png`, `dispatch_list_site_valmet_l11.png`,
`sla_calibration.png`, `sla_feature_importance.png`) and `outputs/operations_briefing.md` tell the
same story as static images — open them directly and narrate the run sheet above.
