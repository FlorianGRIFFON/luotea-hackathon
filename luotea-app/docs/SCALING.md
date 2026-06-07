# Scaling & Roadmap — where the Reliability Risk Engine goes for Luotea

> **Thesis:** the hard part — unifying fragmented facility data — is already solved by the
> medallion pipeline. The Reliability Risk Engine is a **thin, additive layer** on Gold, so
> scaling it is mostly *onboarding more sites*, not *rebuilding the product*.

## 1. The whole flow in minimum commands

Gold/Silver Parquet is already built, so the demo runs immediately.

```bash
cd claude-shenanigans
make demo     # verify Gold ▶ train model ▶ build index & dispatch ▶ run tests
make app      # open the Streamlit demo
```

That is the entire path. The individual steps, if you want them:

```bash
make verify    # confirm the pipeline's Gold data is present (read-only — never re-runs it)
make train     # train SLA-breach model  → outputs/models, outputs/metrics, outputs/figures
make predict   # Reliability Index + dispatch list + cross-site figures
make test      # 12 tests: loaders, no-leakage guarantee, time-split, model-beats-baseline
```

**Production / fresh data** (only when re-ingesting a customer's new export — not needed for the
hackathon, and we never run it here):

```bash
cd ../luotea-pipeline && python -m pipeline qa --date <YYYY-MM-DD>   # rebuild Gold + QA gate
cd ../claude-shenanigans && make train predict                       # re-score on the new Gold
```

So the **end-to-end customer loop is two commands**: rebuild Gold, then `make train predict`.

## 2. How it scales (data → model → serving)

| Dimension | Today | Scales by |
|-----------|-------|-----------|
| **New customer** | 7 sites, 3 customers | Add a Bronze export + one `sites.yaml` row. **No new model** — `site_id` is already a feature. |
| **New data source** | 6 source families | Pipeline adds a Silver table; the index gains a component, weights re-normalise automatically. |
| **More history** | 44k work orders | Same model; per-customer probability calibration improves as volume grows. |
| **Compute** | trains in seconds on a laptop | Trivially fits a nightly job; no GPU, no cluster. |
| **Serving** | Streamlit + Parquet | Swap the read layer for a scoring API / write-back into the customer's FM tool. |

Because every site lands on the **same Gold schema and the same 0–100 Reliability Index**,
cross-customer benchmarking ("how does Aurora's reliability compare to Horizon's this month?")
comes for free once more sites are mapped — a portfolio view no single-source competitor can offer.

## 3. The product arc for Luotea

1. **Describe** *(done — the pipeline)*: one trustworthy daily view per site.
2. **Predict** *(this hackathon)*: SLA-breach risk + Reliability Index turn the view forward-looking.
3. **Decide** *(this hackathon)*: risk-ranked dispatch and an elevated-risk band drive action.
4. **Automate** *(next)*: nightly scoring writes the ranked queue back into the FM/ERP tool and
   alerts the on-call manager — maintenance that re-plans itself from risk, not the calendar.
5. **Contract on outcomes** *(the business shift)*: sell *operational reliability* (measured by the
   Index and avoided breaches), not working hours — exactly what the hackathon brief asks for.

## 4. TODO — where this goes next (post-hackathon backlog)

> Concrete, ranked next steps to take this from prototype to a Luotea product line.

### Near-term (weeks)
- [ ] **Scoring API**: wrap `SLARiskModel` in a FastAPI `/score` endpoint; nightly batch + on-demand.
- [ ] **Write-back**: push the risk-ranked queue into the FM/ERP work list (Sari's real screen).
- [ ] **Elevated-risk alerting**: threshold + 14-day-trend alerts on the Reliability Index per site.
- [ ] **Per-customer calibration**: isotonic/Platt calibration layer so probabilities are tenant-true.
- [ ] **Human-in-the-loop feedback**: capture manager overrides as labels for the next retrain.

### Medium-term (1–2 quarters)
- [ ] **Scheduled retrain + drift monitoring**: track held-out AUC/Brier over time; auto-flag decay.
- [ ] **Dynamic maintenance calendar**: convert the Index band into concrete reschedule suggestions
      (pull-forward / relax-cadence) and measure over- vs under-maintenance avoided.
- [ ] **Alarm-onboarding for prediction**: once alarm history matures past 2025, add a next-7-day
      alarm/incident risk head alongside SLA risk.
- [ ] **Finnish work-order text features**: TF-IDF / embeddings on `work_description` for repeat-fault
      detection and finer risk (idea #8 from the ideation backlog).
- [ ] **Cross-customer benchmarking view**: portfolio reliability league table once ≥10 sites mapped.

### Bigger bets
- [ ] **Asset-level reliability**: join KONE elevator + Smartti node IDs to score *assets*, not just
      sites — true predictive maintenance of equipment, not contracts.
- [ ] **Cost model**: attach € cost of a breach / reactive call-out so the Index ranks by expected
      cost avoided, not just probability.
- [ ] **What-if simulator**: "if we add 1 dispatcher, how many more breaches do we catch?" from the
      precision@k curve.

## 5. Risks & honest constraints to carry forward

- **Noisy target:** AUC ~0.70 reflects real operational noise; value is in *ranking* + *decisions*.
- **Coverage varies:** keep the partial-coverage discipline — never let a missing source read as
  "calm". The Index already nulls structurally-absent components.
- **Drift is real:** breach rates moved 19 %→60 % over the years; retraining cadence is not optional.
- **Trust before automation:** ship as decision-support first; let managers learn to trust the rank
  before any auto-rescheduling writes back.
