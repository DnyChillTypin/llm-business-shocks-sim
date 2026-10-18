# Stage 5: matched primary shock comparisons

## Execution checkpoint: two series complete

On 18 October 2026, the user authorized Stage 5 execution and raised the **cumulative** project ceiling to **10 gateway credits**, including all prior costs and held unknown charges. The existing ledger and budget identity were retained. The native scope remains 4.2 credits; Kaggle has 3.8 credits, with 2 credits unallocated as reserve. The frozen matrix remains 36 episodes with 252 primary LLM decisions and at most 504 physical attempts across all primary cohorts. A larger ceiling does not authorize extra repetitions, models or native Retail runs.

**Current checkpoint: 24/36 episodes and 504/756 policy-days**, covering S001/P0001 and S004/P0006 under all four scenarios and three policies. The eight LLM episodes account for 168 primary decision opportunities and 259 known-usage physical attempts, including 91 repairs. All 24 episodes passed independent fresh-input replay, provenance and financial/inventory accounting checks. Initial observations match across policies within scenario; each series' exogenous base-demand path matches across every policy and scenario. The execution code and frozen prompts/configuration remain unchanged since preparation.

Current reliability is **77/168 first-pass valid decisions**, **154/168 model decisions after repair**, and **14/168 adaptive fallback days**. Primary expense is **0.164114750 gateway credits**, with cumulative project exposure **2.098198044 credits over 1,697 attempts**. All earlier unknown-charge holds remain included; no Stage 5 transport failure or unknown charge has occurred.

This is a partial Stage 5 checkpoint, not completion. Matrix indices 24–35 remain unexecuted. [Status](results/stage5/status.json) and [coverage](results/stage5/coverage.csv) record the exact completion boundary. The frozen [launch plan](results/stage5/launch_plan.csv) determines the remaining sequence; only one paid episode runs at a time, with episode and series-block reviews.

## Observed first-block outcomes (historical checkpoint)

The LLM policy had **50/84 first-pass valid decisions**, **79/84 model decisions after repair**, and **5/84 adaptive fallback days**. Invalid responses were material cash-affordability errors, including repeated errors after the one allowed repair. Evidence-bound quality reviews retain the frozen policy, errors and fallback days. No prompt tuning, invalid-action clipping or response replacement was used.

The LLM contribution was below adaptive for control, demand surge and demand decline, and above adaptive for delivery disruption. Its fill rate was 100% in all four episodes, accompanied by substantially higher average inventory. These are descriptive outcomes from one selected series, not an overall adaptation finding. Contribution uses the dataset's unspecified monetary units; gateway credits measure experiment expense separately.

First-block primary expense is **0.074554563 gateway credits**, and cumulative project exposure is **2.008637857 credits over 1,556 attempts**. The cumulative total includes all eight earlier fully held unknown charges, totaling 0.059084209 credits. No Stage 5 transport failures or unknown charges occurred in this block. Detailed paired effects, phase behavior, recovery and robustness belong to Stage 6.

## Evidence and reproduction

The [saved primary notebook](../notebooks/07_primary_shock_comparisons.ipynb) loads the reviewed aggregate package and checks it without constructing an API client or executing episodes. The earlier Stage 4 notebook remains a historical readiness checkpoint.

- `coverage.csv`: complete episode metrics, validity/repair/fallback counts, costs, cohort counts and source evidence hashes.
- `daily_results.csv`: merged complete-episode business outcomes and daily fallback/repair flags, with no raw prompts or gateway identifiers.
- `matched_inputs.csv`: initial observation and base-demand hashes for each matched scenario cell.
- `retained_failures.csv`: any incomplete cohorts and their fully retained cost; currently header-only because this block had none.
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
& $py scripts/export_stage5_evidence.py --through-index 23
```

Use index 35 at the final series checkpoint; index 11 produced the earlier first-series checkpoint. The exporter refuses a live execution lock, active/unreviewed cohorts, missing planned episodes, changed execution code, stale failure/fallback reviews and unexplained ledger differences. It independently replays every included complete episode before publishing aggregate evidence. Failed cohorts remain visible and charged even if a separately reviewed fresh cohort later completes the planned episode.

## Interpretation and remaining work

The primary window is 22 September–12 October 2023; prior manual outcome use is uncertain, so there is no pristine unseen-data claim. The final matrix has three matched series-window blocks, with dependent daily observations and a single LLM realization per condition. Demand, prices, costs, supplier behavior and shocks are simulator assumptions. These checks establish traceable execution, not real-world causal performance or population-level model superiority.

Stage 5 still needs the final series block, the 36-episode/756-day/252-decision reconciliation and completion review. The native coverage limitation persists: 14 validated non-Retail tasks, the retained ICBE validity failure and four deferred Retail tasks. Stage 6 will analyze the completed matched comparisons and reliability together.
