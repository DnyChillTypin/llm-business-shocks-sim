# Stage 4 complete: offline Kaggle experiment readiness

Stage 4 completed its software and integration quality gate without new model calls or primary-window policy episodes. The frozen policy, prompts, schema, model settings, data split, selected series and business assumptions are unchanged. The retained ICBE failure and four deferred native Retail evaluations remain incomplete coverage, separately reported from this Kaggle adaptation.

## Verified coverage

| Evidence | Completed coverage |
|---|---:|
| Training-selected series | 3 |
| Scenarios per series | 4 |
| Validation baseline episodes | 24: fixed and adaptive |
| Validation scripted episodes | 12 |
| Validation policy-days | 756: all episodes last 21 days |
| Baseline parity against legacy runner | All 24 episodes |
| Independent saved-action/environment replays | All 36 episodes |
| Genuine historical LLM pilots revalidated | 2; 57 saved requests audited, none reissued |
| Automated tests | 82 passed, including 16 new execution/replay regressions |
| Frozen research-design checks | 31 passed |
| New model calls / primary policy episodes | 0 / 0 |

All expansion checks use **2–22 April 2023 validation data** for S001/P0001, S004/P0006 and S003/P0016. Within each series, all policies/scenarios match on initial state and exogenous base-demand paths. Different actions can legitimately change subsequent inventory, realized price-sensitive demand and observations.

The scripted client uses the actual daily policy parser/repair/fallback implementation with deliberately invalid fixture JSON. Each scripted episode contains two repair days and one adaptive fallback day. These are software fixtures, not genuine model outcomes or estimates of model reliability.

## Implemented checks and safeguards

`src/experiments/kaggle_validation.py` independently prepares inputs from the frozen raw dataset and replays every saved action through the actual environment. It compares observations, daily outcomes, cash, inventory/pipeline assets, service metrics, summaries and exported repair/fallback flags. It checks hidden private demand and scenario privacy on every day, allowing the legitimate observable change in current delivery lead time. For genuine episodes it replays the frozen policy using actual saved responses, verifies exact requests and raw usage/response provenance, and matches recorded costs to the cumulative local ledger. No request is sent during validation.

`src/experiments/kaggle_protocol.py` preserves the canonical episode identities used by the genuine pilots and adds an immutable primary matrix registry. It rejects completed/active duplicates, concurrent executions and stale reviews. Interrupted primary episodes require evidence-bound review before another paid episode; retrying requires a fresh complete environment, not partial state reconstruction. Failed and replacement attempts both count toward the primary 504-attempt ceiling.

The primary launcher requires one explicitly selected episode, an approved matrix-bound run manifest, authorization for the primary task in the existing allowance, an existing nonempty cumulative ledger, and matching validated primary baselines. Reviews are bound to action or failure evidence. Fallback on more than 5% of an episode's decisions blocks the next paid episode until reviewed. Transport/accounting failures stop incomplete rather than concealing an outage behind fallback.

The budget amendment API now permits an explicitly authorized monotonic task extension. Tests confirm that existing known spending and unknown-charge holds survive it; task removal, implicit task changes and unreviewed unknown charges remain blocked. **No amendment was applied to the real allowance in Stage 4.**

`scripts/validate_kaggle_run.py` now distinguishes baseline, scripted and genuine provenance in validation or primary windows. Tests reject missing days, rehashed altered observations, edited daily outcomes, hidden fallback flags, mislabeled fixtures, stale evidence and accidental primary execution before credentials/data access. The two genuine Stage 2 pilots still pass the stronger validator without changing their outcomes.

## Reproduce and inspect

From the project root, using the prepared environment/data:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py -m unittest discover -s tests -v
& $py scripts/check_research_design.py
& $py scripts/check_kaggle_matrix.py
& $py scripts/check_public_stage4.py
& $py scripts/verify_notebook.py --notebook notebooks/06_kaggle_experiment_readiness.ipynb
```

The matrix command creates a fresh validation-only directory under ignored `results/verification/stage4/` with all inputs, observations, actions, fixture requests, daily results, independent replay checks and legacy comparisons. `latest_matrix.json` points to the latest successful matrix. Complete test/design logs and genuine-pilot revalidation stay local.

Reviewed public evidence is in [results/stage4](results/stage4/): `status.json`, `qc_summary.json`, `validation_coverage.csv`, the **unexecuted** `primary_plan.csv`, historical `preparation.json`, and a portable artifact hash manifest. [Notebook 06](../notebooks/06_kaggle_experiment_readiness.ipynb) loads saved aggregates only; Run All incurs no spending. CI runs all tests, reproduces the validation matrix, checks the publication boundary and executes all six notebooks without paid calls.

`scripts/export_stage4_evidence.py` rebuilds the public package from local passing tests/matrix checks, revalidates the genuine historical pilots and verifies that the shared ledger is unchanged. It requires the ignored local pilot evidence/allowance; the public notebook and publication checker do not.

## Expenses, findings limits and Stage 5 handoff

Project exposure remains **1.934083294 credits over 1,438 attempts**, including all eight fully held unknown charges. The inclusive cap remains six credits. The Kaggle scope has 0.552548736 credits remaining from its 0.6 allocation. Stage 4 spent zero model credits and did not reset or amend the real ledger.

The genuine validation policy's previously observed 27/42 first-pass valid decisions, 39/42 model decisions after repair and three fallback days remain negative reliability findings. Its contribution was below the adaptive baseline in both pilot scenarios. No prompt/model was tuned to remove those findings. Primary operational results must include fallback days.

The primary study remains **three matched series-window blocks, 36 episodes, 756 policy-days and 252 LLM first attempts**, with at most 504 attempts including repairs. Use the frozen 22 September–12 October 2023 window. Its prior manual outcome use is uncertain; no pristine unseen-data claim is allowed. Synthetic demand, prices, costs and shock responses are assumptions. Correlated daily rows are not independent replications, and these checks establish readiness rather than adaptation or real-world causal performance.

The checked-in `configs/runs/kaggle_primary.template.json` is **unapproved** and has no budget identity. The actual allowance still excludes the primary Kaggle task. Stage 5 must record explicit run authorization and a task-only allowance extension under the same ledger/caps, then run matching primary baselines and one LLM episode at a time. Do not use a new budget file identity to erase prior costs. The frozen execution order and canonical matrix indices can be inspected without execution:

```powershell
& $py scripts/run_kaggle_experiment.py --config configs/study.json --dry-run
& $py scripts/run_kaggle_experiment.py --config configs/study.json --episode-index 2 --dry-run
```

Index 2 is the first planned LLM episode. A future paid invocation additionally requires `--execute-paid`, the existing amended `--budget`, and a separately approved `--execution-manifest`. The template and a dry run do not authorize spending. No primary comparison was launched as part of this checkpoint.
