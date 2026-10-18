# Stage 6 preparation: findings and robustness

Prepared on 18 October 2026 against completed Stage 5 commit `0af4710`. **Preparation is complete; Stage 6 analysis has not been executed.** No new contrasts, recovery estimates, sensitivity episodes or model completions were generated. The [analysis template](../configs/analysis/stage6.template.json) remains unapproved planning metadata; the [source snapshot](results/stage6/source_snapshot.json) pins 38 public inputs by normalized text hash.

## Purpose and available evidence

Stage 6 will turn the saved native and Kaggle evidence into reproducible tables, figures and proportional claims. Raw contribution rankings alone do not answer whether behavior responds usefully to a shock: compare each condition with its matched control and connect actions to service, inventory, contribution and recovery.

The primary matrix is complete: **36 episodes, 756 policy-days, three matched series-window blocks and 252 LLM decision opportunities**. The saved 396 requests include 144 repairs; 108 decisions were first-pass valid, 127 repairs succeeded, and 17 decisions used adaptive fallback. All fallback days remain in the primary operational policy. Native coverage remains **14 validated tasks, one retained ICBE validity failure and four deferred Retail tasks**; Stage 6 does not rerun them.

Read-only preparation verified current evidence hashes, all 756 saved actions and observations, all 396 known-usage and latency records, 12 quality reviews and the existing ledger fingerprint. The 756-row public daily table lacks executed order quantities and request token/latency detail. Extract those from ignored saved actions, observations and API journals during execution; never reissue a request. Native scores and their qualifications can reuse the pinned Stage 3 package and `src/analysis/native_metrics.py`.

The reusable Kaggle metrics module and final analysis exporter/notebook still need implementation. Notebook 04 already records historical pilot costs; preserve it and create **notebook 08** for final findings. Notebooks 05 and 07 remain the saved native and primary-execution evidence checkpoints.

## Tasks and deliverables, in order

1. Verify the pinned source snapshot and current primary/native coverage. Extract a versioned analysis dataset from saved daily results, executed actions, observations and request journals. Bind the private source map to the existing episode evidence hashes. Stop on missing, duplicate or stale records.
2. Implement and test reusable metrics in `src/analysis/metrics.py`. Reconcile episode, phase, stock, pipeline, cash, reliability and expense totals before interpretation. Tests must cover weighted fill rate, negative/near-zero relative-gain denominators, recovery boundaries/censoring, fallback inclusion and stock-arrival timing.
3. Calculate the frozen matched comparisons versus adaptive (primary) and fixed (secondary), with controls always visible. Produce contribution/service contrasts, phase summaries, pricing/orders, behavioral response and recovery. Show every series before descriptive scenario summaries.
4. Build native coverage and family-specific result tables, preserving metric units, failures, absent values and recovered-case provenance. Include reliability, latency, token use and project expenses alongside business outcomes; keep simulator money separate from gateway credits.
5. Inspect all condition-level traces, then illustrate at least one positive outcome and one reliability failure. The template names S001/P0001 delivery disruption and S004/P0006 demand surge as **post-outcome diagnostic examples**, chosen from already reported Stage 5 outcomes. They supplement the complete tables/traces and are not confirmatory samples.
6. Implement the preselected **free baseline-only** elasticity sensitivity at 0.75 and 2.25, reusing the original 1.5 baselines. Keep sensitivity inputs/results separately labeled, validate their accounting and replay, and preserve primary inputs and outputs byte-for-byte.
7. Create `notebooks/08_findings_and_robustness.ipynb`, export generated CSV/LaTeX tables and PNG/PDF scientific figures, and write a claim-to-artifact map for Stage 7. Check the exported values, labels, censoring and figure layout; make notebook Run All work without paid calls.

| Output | Expected rows / scope |
|---|---:|
| Episode metrics | 36 |
| Paired shock contrasts, including control-adjusted effects | 18: nine adaptive primary, nine fixed secondary |
| Control comparisons | 6 |
| Policy shock-minus-control contrasts | 27 |
| Per-scenario descriptive summaries | 6: three shocks × two comparators, each with three blocks |
| Phase summaries | 108: 36 episodes × three phases |
| Executed action traces | 756 |
| Behavioral response and recovery | 27 each: three series × three policies × three shocks |
| LLM episode reliability and costs | 12, plus cumulative accounting |
| Baseline elasticity sensitivity summary | 72: 24 existing primary baselines + 48 new free baseline episodes |
| Native task coverage | 19, with scores separated by family |

Save the full analysis manifest, extraction data, tables and figures under ignored `results/analysis/<analysis_id>/`. Publish reviewed aggregates under `docs/results/stage6/`, figures under `docs/assets/stage6/`, and generated LaTeX tables for the report. Private request-level timing/token records, raw responses, runtime identifiers, account data and approval records stay ignored. Public figures and claim mappings must identify their source tables and evidence hashes.

## Frozen metric rules

Contribution is the 21-day sum of revenue minus goods and holding costs. Report `LLM - baseline` within each series/scenario, and `100 * difference / abs(baseline)` with NA when the denominator is at most `1e-9`. Also report each policy's shock-minus-control difference and `(LLM_shock - LLM_control) - (baseline_shock - baseline_control)`. These are simulator contrasts, not real-world causal estimates. Do not equate Stage 5's two raw positive shock comparisons with the control-adjusted adaptation result.

Phases are days **1–7, 8–14 and 15–21**. Compute fill rate as total sales divided by total requested demand within the relevant episode/phase, rather than an unweighted mean of daily fill rates. A zero-demand group has fill rate 1 with an explicit zero-demand flag. Report lost units, stockout SKU-days, mean closing inventory, prices and order quantities with their units.

Closing inventory is measured **before next-day arrivals**. Terminal on-hand units equal last closing units plus last `arrivals_next_day`; terminal pipeline units equal initial on-order units plus executed orders minus arrivals. Value both at purchase cost. Reconcile cash using purchases, revenue and holding costs, then reconcile final assets minus initial assets with contribution to absolute tolerance `1e-6`. Do not infer terminal stock from the last closing column alone.

Behavioral response is the first day on/after day 8 when executed order quantity differs by at least one unit or the allowed price multiplier differs from same-policy control. Plot pre-shock differences too. Demand shocks first appear in completed history on day 9; delivery lead time is observable on day 8. Independent model realizations can diverge before or after the shock even at temperature zero. Without a frozen-history ablation, action divergence cannot isolate the causal value of history or prove beneficial adaptation.

Recovery follows the unchanged frozen rule: earliest start at day 15 or later with **three consecutive observed days** of zero lost sales and inventory within `0.2 * max(control_inventory, 1)` of same-policy control on every day. Candidate starts are 15–19 so the confirming third day is observed by day 21. Report start day, confirmation day and delay `start - 14`. Otherwise retain **right-censoring at day 21**, seven postshock follow-up days and a null recovery delay. Never encode unrecovered cases as zero or exact day-21 recovery. This measures operational normalization, not recovery of cumulative profit.

There are **three selected series-window blocks**, not 756 independent replications. Report per-block effects and per-scenario equal-weight mean, median, minimum/maximum and sign counts from unrounded values. Do not bootstrap daily rows, run day-level significance tests, invent population confidence intervals or claim practical superiority without an agreed threshold. Prior manual outcome use of the primary window remains uncertain; no pristine unseen-data claim is allowed.

## Native results and robustness boundaries

Keep the 457 supported native reasoning cases and separate 50-case Factset extension visible. Preserve `finer`'s entity-label denominator and label exact-case accuracy separately. Consulting has ten cases; retain the exact provenance of eight recovered complete cases and all earlier failed charges. BeerGame's native backlog field is a terminal proxy, not its verified time average; keep these quantities distinct, including large upstream costs and missing aggregates. EDT is one scenario decision followed by 96 ABM steps, not within-rollout adaptation. ICBE remains a validity failure after 177/600 complete valid rounds, without a final full-game score or full phase plot. Do not pool native families or impute the four deferred Retail scores.

The elasticity check adds **48 deterministic baseline episodes / 1,008 policy-days**, with zero model calls. Use isolated copies of prepared inputs and separately recorded assumptions; reuse the 24 primary baseline results at elasticity 1.5. Add a separate sensitivity validation path rather than relaxing the frozen primary validator. Keep raw demand, training calibration, initial state, costs, lead times and policy definitions fixed. Baseline sensitivity establishes simulator sensitivity only; do not replay original LLM actions and call that LLM robustness, or replace primary results with a more favorable assumption.

A second evaluation window, independent LLM repetitions or matched LLM sensitivity are optional paid extensions and remain **disabled**. They need a separately reviewed protocol, scope and allocation before calls; the 10-credit ceiling alone does not approve extra experiments. Core Stage 6 can finish without them. No ICBE amendment or additional native task is included.

## Commands, checks and completion gate

These commands exist now and perform source/readiness checks only:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py scripts/check_stage6_readiness.py
& $py scripts/check_stage6_readiness.py --private
& $py scripts/check_public_stage5.py
& $py scripts/check_research_design.py
```

The private option checks local saved evidence and the ledger read-only; it never creates an API client or reruns a simulation. The public option works in CI without credentials or raw private runs. Implement `scripts/export_stage6_analysis.py`, `scripts/run_baseline_sensitivity.py`, `scripts/check_public_stage6.py` and notebook 08 during Stage 6 execution; they are **planned files, not currently working launch commands**. Source availability is established; the analysis implementation remains the next task.

Stage 6 exits when every expected output reconciles to its pinned inputs, all primary conditions and fallback/censored/failed cases remain visible, native units stay separate, the 48 baseline sensitivity episodes pass isolated replay/accounting, all tables and figures are generated from saved results, notebook 08 executes for free, and every proposed claim has a source-artifact link and a limitation. On missing or contradictory evidence, stop the affected analysis and inspect provenance; do not fill gaps with zeros, drop outliers, change the frozen recovery rule or tune on primary outcomes. Corrected implementations require explicit version/provenance notes and regenerated affected outputs.

Budget remains **2.186206858 credits of a 10-credit cumulative ceiling over 1,834 attempts**, including eight earlier full unknown-charge holds totaling 0.059084209 credits. Preparation changed neither the ledger nor allowance. Core analysis and baseline sensitivity require **zero gateway credits**. Allow **2–4 active hours** for implementation, analysis and visual QC. Dependencies are the completed Stage 5 matrix and qualified Stage 3 native evidence. No user decision is needed for routine analysis choices within this frozen scope; optional paid experiments or material scope/method changes need a concrete separate review.
