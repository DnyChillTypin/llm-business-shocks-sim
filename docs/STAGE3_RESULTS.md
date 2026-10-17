# Stage 3 evaluation results

The non-Retail execution route is in progress. All 507 reasoning cases are validated; interactive families follow. The original Stage 3 scope remains incomplete because four 180-day native Retail episodes are deferred under the approved 6-credit route. Kaggle primary comparisons have not started.

## Reasoning

These are fresh evaluation runs with the frozen substituted gateway model, native prompts and dataset scorers. All 507 cases produced valid responses and known usage, with no evaluation retries, missing answers or substituted defaults. Native supported coverage is 457 cases across ten datasets; the 50-case Factset extension is separate.

| Dataset | Native accuracy | Native correct / scored units | Exact cases correct / evaluated |
|---|---:|---:|---:|
| FinCode | 100% | 7 / 7 cases | 7 / 7 |
| CodeFinQA | 82% | 41 / 50 cases | 41 / 50 |
| CodeTAT-QA | 98% | 49 / 50 cases | 49 / 50 |
| SEC-NUM | 88% | 44 / 50 cases | 44 / 50 |
| TAT-QA | 96% | 48 / 50 cases | 48 / 50 |
| ConvFinQA | 70% | 35 / 50 cases | 35 / 50 |
| FinKnow | 92% | 46 / 50 cases | 46 / 50 |
| FormulaEval | 94% | 47 / 50 cases | 47 / 50 |
| finer | 73% | 146 / 200 entity labels | 22 / 50 |
| formula | 74% | 37 / 50 cases | 37 / 50 |
| Factset **extension** | 50% | 25 / 50 binary decisions | 25 / 50 |

![Native reasoning scores with explicit metric denominators](assets/stage3/reasoning_accuracy.png)

Each dataset has one evaluation cohort. Native scoring definitions differ, and finer label accuracy must not be interpreted as whole-case accuracy. There is no pooled cross-family score, no claim of reproducing published-model performance, and no independent-run uncertainty estimate. Factset uses the documented local binary scorer and removes provenance hints from the model-visible context.

## EDT

The valid scenario decision was followed by all 96 ABM steps. Terminal accumulated earnings were **−4,836,000**, from revenue of 6,184,000 and expenses of 11,020,000 in native synthetic business units. The native schema normalization did not project the chosen decision. This is one scenario-level decision followed by a rollout, with no within-rollout LLM interventions or real-world causal interpretation.

## BeerGame

Both frozen scenarios completed 25 weeks. Independent offline replay of the actual saved orders matched every observation, transition and native metric; role-level costs sum exactly to the exported chain costs.

| Native opponent scenario | Retailer total cost | Full-chain total cost | Episode retailer bullwhip | Derived time-average retailer backlog |
|---|---:|---:|---:|---:|
| typical | 44,050 | 7,342,656,800 | 38.9227 | 232 |
| smoothing:4 | 49,208.5 | 1,019,970.5 | 47.3880 | 484.84 |

Costs are native simulation monetary units, not gateway credits. The typical heuristic's upstream brewery order reaches 6,527,377,200; the extreme chain total is reproducible native behavior and is retained as a realism limitation. Different opponent configurations and unreplicated LLM decisions prevent causal attribution of their outcome differences.

The native `avg_backlog_controlled` proxy is zero in both scenarios because it repeats the final backlog rather than averaging historical backlog. Actual time averages derived from the weekly observations are shown separately above. The upstream rollup's missing bullwhip, backlog and inventory aggregates remain null; episode bullwhip values are not silently inserted as replacement native aggregates.

## Evidence

The [coverage table](results/native_coverage.csv), [aggregate evaluation evidence](results/stage3/evaluation_cohorts.json) and [inclusive budget summary](results/stage3/budget_summary.json) retain current completion and expense denominators. The [executed analysis notebook](../notebooks/05_native_evaluation.ipynb) checks aggregate hashes and runs without credentials or paid calls. Request-level artifacts and account metadata remain local.

The [execution plan](STAGE3_EVALUATION.md) records scope, compatibility adapters and quality gates. All 59 automated tests passed at the reasoning checkpoint. Four original Retail evaluations remain outstanding regardless of the non-Retail route's eventual completion.
