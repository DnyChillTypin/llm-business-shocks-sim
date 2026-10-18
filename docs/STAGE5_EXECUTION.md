# Stage 5: matched primary shock comparisons

## Stage 5 complete

On 18 October 2026, the user authorized Stage 5 execution and raised the **cumulative** project ceiling to **10 gateway credits**, including all prior costs and held unknown charges. The existing ledger and budget identity were retained. The native scope remains 4.2 credits; Kaggle has 3.8 credits, with 2 credits unallocated as reserve. The frozen matrix remains 36 episodes with 252 primary LLM decisions and at most 504 physical attempts across all primary cohorts. A larger ceiling does not authorize extra repetitions, models or native Retail runs.

**Completed: 36/36 episodes and 756/756 policy-days**, covering S001/P0001, S004/P0006 and S003/P0016 under all four scenarios and three policies. The 12 LLM episodes account for 252 primary decision opportunities and 396 known-usage physical attempts, including 144 repairs. All 36 episodes passed independent fresh-input replay, provenance and financial/inventory accounting checks. Initial observations match across policies in all 12 scenario cells; each series' exogenous base-demand path matches across every policy and scenario. The execution code and frozen prompts/configuration remained unchanged since preparation.

Final reliability is **108/252 first-pass valid decisions (42.9%)**, **235/252 model decisions after repair (93.3%)**, and **17/252 adaptive fallback days (6.7%)**. Of 144 repaired decisions, 127 became valid model actions and 17 required adaptive fallback. All 252 final operational actions were valid. There were 161 invalid raw responses, all material cash-affordability errors; no response was silently replaced or action clipped.

Primary expense is **0.252123564 gateway credits**, with cumulative project exposure **2.186206858 credits over 1,834 attempts**. The cumulative total includes all eight earlier fully held unknown charges, totaling 0.059084209 credits. No Stage 5 transport failure, incomplete cohort or unknown charge occurred. Physical attempts stayed below the 504-attempt matrix ceiling and 3,000-attempt global ceiling; cumulative exposure stayed below the new 10-credit cap. These are token-derived project estimates with full unknown-charge holds, not independently verified provider billing.

The Stage 5 exit gate passed with **no missing matrix positions**. [Status](results/stage5/status.json), [coverage](results/stage5/coverage.csv) and [QC evidence](results/stage5/qc_summary.json) record completion. Execution followed the frozen [launch plan](results/stage5/launch_plan.csv), with one paid episode at a time, reviews of every episode and all three complete series blocks, and evidence-bound quality reviews for all 12 LLM episodes.

## Observed operational outcomes

Evidence-bound quality reviews retain the frozen policy, cash-affordability errors and all fallback days. No prompt tuning, invalid-action clipping, selective omission or response replacement was used. The operational LLM policy includes its explicit adaptive fallback; the results do not describe a purely unassisted LLM.

Raw LLM contribution was **below adaptive in 10/12 matched conditions and above it in 2/12**. Restricting to the nine shock comparisons, it was above adaptive in two and below in seven. The two positive comparisons were delivery disruption for S001/P0001 and S004/P0006. These counts are descriptive; they do not establish adaptation, population-level superiority or statistical significance. Detailed control-adjusted effects and phase behavior belong to Stage 6.

The LLM had full service in the eight S001/P0001 and S003/P0016 conditions; each S004/P0006 condition had one stockout day. Service and inventory must be read alongside contribution. Contribution uses the dataset's unspecified monetary units; gateway credits measure experiment expense separately. The saved notebook lists all condition-level contribution, service, inventory, repair and fallback outcomes.

The first-series checkpoint was pushed as `5b39efc` and the two-series checkpoint as `4cc3399`, each with passing GitHub validation. Their intermediate expenses and completion boundaries are preserved in Git history. The final artifact package supersedes those partial snapshots.

## Evidence and reproduction

The [saved primary notebook](../notebooks/07_primary_shock_comparisons.ipynb) loads the reviewed aggregate package and checks it without constructing an API client or executing episodes. The earlier Stage 4 notebook remains a historical readiness checkpoint.

- `coverage.csv`: complete episode metrics, validity/repair/fallback counts, costs, cohort counts and source evidence hashes.
- `daily_results.csv`: merged complete-episode business outcomes and daily fallback/repair flags, with no raw prompts or gateway identifiers.
- `matched_inputs.csv`: initial observation and base-demand hashes for each matched scenario cell.
- `retained_failures.csv`: any incomplete cohorts and their fully retained cost; header-only because Stage 5 had none.
- `qc_summary.json`, `status.json`, `artifact_manifest.json`: validation counts, exact missing coverage, shared-budget reconciliation and portable public artifact hashes.

Raw requests/responses, observations, actions, attempt journals, run identifiers, returned response identifiers, account data and approval records remain local and ignored. Independent validation checks exact saved requests against replay observations and reconciles every request's usage and cost with the same cumulative ledger. Public model names do not independently attest the served weights.

To reproduce public checks and the saved notebook for free:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py scripts/check_public_stage5.py
& $py scripts/verify_notebook.py --notebook notebooks/07_primary_shock_comparisons.ipynb
```

The public checker independently reconciles daily contribution/revenue, service, inventory, repairs, fallbacks, attempt counts and cumulative expense with the episode summaries. It verifies hashes, frozen matrix positions, dates and matched base paths. All 85 automated tests passed locally, including three new tests proving that edited contribution, fallback flags or costs still fail reconciliation after their public file hashes are recomputed. CI runs the full suite, this checker and all seven notebooks without paid calls.

The local export command requires private completed evidence and the approved allowance; it never issues a completion request:

```powershell
& $py scripts/export_stage5_evidence.py --through-index 35
```

Indices 11 and 23 produced the earlier series checkpoints. The exporter refuses a live execution lock, active/unreviewed cohorts, missing planned episodes, changed execution code, stale failure/fallback reviews and unexplained ledger differences. It independently replays every included complete episode before publishing aggregate evidence. Failed cohorts would remain visible and charged even if a separately reviewed fresh cohort later completed the planned episode; none occurred in Stage 5.

## Interpretation and remaining work

The primary window is 22 September–12 October 2023; prior manual outcome use is uncertain, so there is no pristine unseen-data claim. The final matrix has three matched series-window blocks, with dependent daily observations and a single LLM realization per condition. Demand, prices, costs, supplier behavior and shocks are simulator assumptions. These checks establish traceable execution, not real-world causal performance or population-level model superiority.

Stage 5 is complete. The native coverage limitation persists: 14 validated non-Retail tasks, the retained ICBE validity failure and four deferred Retail tasks. Stage 6 will analyze paired effects, phase behavior, recovery, reliability and affordable preselected robustness checks. No Stage 6 paid extensions or additional model repetitions were launched as part of this stage.
