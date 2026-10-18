# Stage 5 preparation: matched primary shock comparisons

Historical preparation checkpoint. Stage 5 execution is now authorized under a cumulative 10-credit ceiling; see the [current execution checkpoint](STAGE5_EXECUTION.md). The unexecuted counts, six-credit allowance and unapproved proposals below describe the preparation date before execution, not the current run state.

Prepared on 18 October 2026. **Ready for a later execution instruction; no primary episodes or model completions have been run.** Stage 4's [offline readiness gate](STAGE4_EXECUTION.md) passed. This checkpoint fixes the launch sequence, checks the existing budget and records unapproved local proposals. It does not complete Stage 5.

## What Stage 5 will measure

Run the frozen fixed, adaptive and LLM-with-fallback policies on the same three selected series under control, demand surge, demand decline and delivery disruption. Each episode covers **22 September–12 October 2023**, with shock days 8–14. This is **36 episodes, 756 policy-days, 12 LLM episodes and 252 primary LLM decisions**, with at most 504 physical attempts including repairs across all primary cohorts.

The main outcome is contribution, comparing LLM with adaptive within each shock condition and series. Fixed-policy comparisons and control-adjusted effects are secondary. Keep service, stockouts, inventory, prices, recovery, validity, fallbacks and cost alongside the financial outcome. Retain unfavorable results and fallback days. There are only three matched series-window blocks; daily rows are dependent. Prior manual use of this window is uncertain, so do not describe it as pristine unseen data. Synthetic demand and business assumptions limit claims to this simulator.

## Launch sequence and review points

[The 36-row launch plan](results/stage5/launch_plan.csv) follows the canonical matrix indices **0–35**. Series order is S001/P0001, S004/P0006, S003/P0016; scenario order is control, demand surge, demand decline, delivery disruption. Within each cell, run fixed, then adaptive, then LLM. This makes both independently validated matching baselines available before each paid episode and preserves the Stage 4 handoff order. It replaces the older plan's suggestion to run all baselines before all LLM episodes; it changes scheduling only, with no policy, data, scenario or analysis change.

LLM indices are **2, 5, 8, 11, 14, 17, 20, 23, 26, 29, 32 and 35**. Run one episode at a time. Review the first LLM episode before advancing. After every episode, inspect completeness, replay, accounting and fallback evidence. After indices 11, 23 and 35, review the complete four-scenario series block and remaining budget. Do not use an unattended loop over the launch CSV.

Fallback on more than 5% of completed decision opportunities requires an evidence-bound quality review before another paid episode. For a complete 21-day episode, two fallback days trigger review; one does not. The prior validation policy had three fallback days across 42 decisions and lower contribution than adaptive in both pilots. Its frozen policy remains unchanged.

Transport, usage/accounting, validation or budget failures stop execution and preserve incomplete evidence. Inspect failures before advancing to any other paid primary episode. A fresh full-episode retry needs an evidence-bound review and `--retry-failed`; there is no partial-state resume. All attempts, including failed or replacement cohorts, count toward cumulative costs and the 504-attempt ceiling. An invalid action receives the frozen single repair and then explicit adaptive fallback; it does not receive unlimited retries.

## Existing allowance and cost review

The read-only preparation check confirmed the existing ledger identity and allowance fingerprint, no pending or blocking unknown attempts, no primary episode artifacts, no active execution lock and accepted historical fallback reviews. All configured gateway models were available and their token tariffs matched the frozen allowance, including the primary GPT-4.1-mini rate of 0.6408 input / 2.5632 output credits per million tokens. Recheck access and rates before execution; account details remain private.

| Budget item | Gateway credits / attempts |
|---|---:|
| Existing inclusive cap | 6.000000000 |
| Current project exposure | 1.934083294 |
| Fully retained unknown charges, included above | 0.059084209 across 8 attempts |
| Kaggle allocation | 0.600000000 |
| Prior Kaggle exposure | 0.047451264 |
| Available Kaggle allocation | 0.552548736 |
| Primary base / high planning estimates | 0.214935990 / 0.429871980 |
| Kaggle headroom after high estimate | 0.122676756 |
| Project exposure after high estimate | 2.363955274 |
| Prior project attempts / global ceiling | 1,438 / 3,000 |
| Projected primary attempts / maximum | 342 / 504 |

These estimates scale the genuine validation pilots, including repairs; they are planning scenarios rather than cost guarantees. Local reservations depend on verified gateway tariffs and token limits, rather than a provider-enforced project quota. Even the 504-attempt maximum would leave total attempts at 1,942, below 3,000. A budget stop may still leave incomplete coverage. Pilot-scaled service time was approximately 10.5 minutes; allow 30–90 minutes for monitored execution and reviews, then revise from the first episode.

No new cap increase is proposed. On a later instruction to execute Stage 5, record the primary task authorization under the **same existing cumulative ledger**, adding only `kaggle:primary_matrix` to allowed/evaluation tasks. Preserve all prior charges, unknown holds, model rates, scope caps and attempt limits. Preparation has not applied that amendment. Unapproved allowance and run proposals are saved locally under ignored `.cache/stage5/`; the checked-in [primary template](../configs/runs/kaggle_primary.template.json) remains `approved: false` with no budget identity. No approved Stage 5 manifests have been created.

## Concrete launch commands

These two commands are safe metadata-only previews and were checked during preparation:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py scripts/run_kaggle_experiment.py --config configs/study.json --dry-run
& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index 2 --dry-run
```

The following commands are **for later Stage 5 execution**, after recording the task-only allowance amendment and approved private run manifest. The approved file paths deliberately do not exist during preparation. Do not merely rename the unapproved proposals or bypass the amendment API: the ledger fingerprint must be amended with `BudgetLedger.amend_allowance(..., authorize_evaluation=True)` using the actual later execution instruction as the new approval reference.

```powershell
# First matched cell; inspect each command's result before continuing.
& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index 0
& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index 1
& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index 2 --execute-paid --budget .cache/approvals/stage5_allowance.approved.json --execution-manifest .cache/approvals/stage5_primary.approved.json
```

The CSV supplies the remaining exact invocations in fixed order. Each episode produces ignored observations, actions, daily results, summary, manifest and independent validation evidence; paid episodes also retain raw requests/responses, attempt journal and budget reconciliation. The matrix registry records all attempted cohorts. Review saved artifacts with `scripts/validate_kaggle_run.py <episode-folder> --summary`, without calling a model.

## Preparation checks and Stage 5 exit gate

Preparation passed all 31 frozen-design checks, both dry-run denominators (36 episodes / 252 LLM decisions and one episode / 21 decisions), existing-ledger/fingerprint and carryover checks, primary authorization rejection, episode availability and historical review gates. Ledger and allowance bytes remained unchanged. [Saved preparation metadata](results/stage5/preparation.json) contains only reviewed aggregates. The portable checker validates that metadata and all 36 launch commands against the frozen matrix:

```powershell
& $py scripts/check_public_stage5.py
& $py -m unittest discover -s tests -p test_kaggle_execution.py -v
```

Stage 5 itself exits only after 36 distinct validated complete episodes, 756 daily rows and 252 primary decision opportunities are reconciled, or a separately agreed reduced scope is explicitly reported. Verify matched initial observations/base-demand paths, monetary and inventory accounting, all model attempts and fallback flags, and exact missing coverage after any stop. Export reviewed aggregate coverage, summaries and merged daily results with source evidence hashes; keep raw gateway and approval records private. Detailed contrasts and robustness belong to Stage 6. The native ICBE failure and four deferred Retail tasks remain part of the report's coverage limitations.
