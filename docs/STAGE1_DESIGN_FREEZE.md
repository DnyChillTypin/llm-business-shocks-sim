# Stage 1 checkpoint

The v1 research design was frozen on 17 October 2026 before new paid pilots or evaluation. No paid API calls or primary-window policy experiments were run during this stage.

## Artifacts

- [`RESEARCH_DESIGN.md`](RESEARCH_DESIGN.md): questions, comparisons, metrics, assumptions, chronology, native scope, action/failure rules, uncertainty and amendment policy.
- [`configs/study.json`](../configs/study.json): exact series, dates, models, matrix, assumptions and proposed execution contract. It records spending as unapproved at freeze; future authorization belongs in a separate budget/run manifest.
- [`results/study_design_manifest.json`](results/study_design_manifest.json): frozen artifact hashes with LF-normalized text hashing for Windows/Linux portability.
- [`results/native_case_manifest.csv`](results/native_case_manifest.csv): 507 reasoning row IDs and ten selected Consulting IDs, hashes only; no questions or answers redistributed.
- [`results/native_episode_manifest.json`](results/native_episode_manifest.json): four Retail configurations, two BeerGame scenarios, one EDT scenario and six ICBE ordered pairs.
- [`results/kaggle_episode_plan.csv`](results/kaggle_episode_plan.csv) and [`results/planned_coverage.csv`](results/planned_coverage.csv): 36 Kaggle episodes and all 19 native task IDs, with planned status and zero completed units.
- [`notebooks/03_kaggle_llm_experiment.ipynb`](../notebooks/03_kaggle_llm_experiment.ipynb): executed offline selection/design review and validation.
- [`REPORT_OUTLINE.md`](REPORT_OUTLINE.md): report sections mapped to evidence and planned generated assets.

## Frozen choices

Three separate series: S001/P0001, S004/P0006 and S003/P0016, selected only using training CV ranks 25/50/75. Four scenarios and three policies make 36 primary episodes, 756 policy-days and 252 primary LLM decision opportunities. The primary evaluation dates are September 22–October 12, 2023; validation pilots start April 2–22, 2023.

The adaptive baseline is the primary comparator, fixed is secondary. Contribution is the primary outcome; service, stockouts, inventory, pricing, recovery and API reliability/cost must accompany it. The LLM operational policy gets one repair for invalid actions, then an explicit adaptive fallback; those days remain in primary results. API/budget failures stop incomplete. Recovery requires three consecutive qualifying days and is right-censored when not observed by day 21.

The user is unsure whether primary-window outcomes previously informed tuning. The protocol therefore records uncertain prior manual outcome use and forbids a pristine unseen-data claim. Three selected matched blocks and one LLM realization per condition support descriptive comparisons; daily observations are not independent replications. No practical superiority threshold was supplied, so none is invented.

## Validation

The offline design checker passed 31 checks, including exact native case selection/horizons, training-only selection under future-value perturbation, chronology, artifact hashes and matched matrix counts. All 22 automated tests passed, including new regressions for future-outcome independence, deterministic ties and rejection of frozen-config drift. Notebook 03 executed all five code cells without errors. Portable evidence is under [`results/stage1/`](results/stage1/); complete local logs are under ignored `results/verification/stage1/`.

CI now prepares the small pinned FirmBench source, verifies the design and executes notebook 03, in addition to its existing tests and notebooks. CI checks source/selection metadata without running paid benchmarks. The stage commit's CI outcome is checked after pushing and reported in the checkpoint response.

## Next stage and remaining limits

Stage 2 starts with offline implementation of bounded pilot controls, attempt-level latency/failure/token logging and enforceable cost limits. A concrete pilot allowance is still needed before any paid calls. The proposed $1/250-attempt pilot ceiling is not authorization; account balance and full-suite cost remain unknown.

The Kaggle policy and shared runner remain Stage 4 work and must exist before the Kaggle paid pilot. Explicit split/window preparation is also still missing: the old preparer defaults to the original first test window. Frozen prompts/schema specify intended behavior; they do not constitute a completed policy implementation or prove leakage prevention at runtime. Genuine pilots and runtime checks remain necessary.
