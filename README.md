# Can LLMs Adapt to Business Shocks?

**Inventory, pricing and business-shock evaluation with a configured LLM policy,
transparent baselines and an auditable simulator.**

[![Research validation](https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/workflows/tests.yml/badge.svg)](https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/workflows/tests.yml)
![Python](https://img.shields.io/badge/Python-3.12-blue)
![License](https://img.shields.io/badge/License-MIT-green)

**Status: preliminary findings and portfolio release.** The completed retail study
contains **36 matched episodes, 756 policy-days and 252 LLM decision opportunities**.
The separate native track has **14 validated tasks, one retained ICBE validity
failure and four deferred Retail configurations**. Original native coverage is
incomplete. This is a research findings draft, not an official leaderboard result
or evidence of real-world causal effects.

Start with the [12-page findings report](report/main.pdf),
[final release checklist](docs/results/release_checklist.md) and
[reproduction guide](docs/REPRODUCIBILITY.md).
The [LaTeX source bundle](report/README.md) builds without credentials or private runs.
[Stage 8 execution](docs/STAGE8_EXECUTION.md) records the release checks and their limits.

## What the evidence says

- Raw LLM-with-fallback contribution exceeds the adaptive rule in **2/9 shock
  comparisons**. The control-adjusted contrast is positive in **7/9**; the mean
  adjusted effect remains negative for demand surge. These are different comparisons.
- Strong service comes with high inventory. Recovery is measured relative to each
  policy's own control; six adaptive episodes are right-censored. Faster inventory
  recovery does not establish better profit or cost efficiency.
- **108/252** decisions are valid on the first response. One bounded repair succeeds
  on **127** further days; **17** days use the explicit adaptive fallback. All outcomes
  and request costs remain included.
- Three purposively selected store-product blocks share one 21-day window, with one
  LLM realization per condition. All nine LLM shock/control pairs already diverge
  before the shock. Results are descriptive simulator evidence; uncertain prior use
  of the window, synthetic demand and assumed mechanisms restrict generalization.

[Complete contrasts](docs/results/stage6/paired_shock_contrasts.csv),
[claim map](docs/results/stage6/claim_map.csv) and
[native coverage](docs/results/stage6/native_task_coverage.csv) retain unfavorable
outcomes and the relevant denominators. The earlier single-series baseline pilot
is documented separately in [Stage 0](docs/STAGE0_HANDOFF.md); its results are not LLM findings.

## Work demonstrated

- Validate 76,000 synthetic records across 100 series and verify downloaded inputs by SHA-256.
- Use chronological 60/20/20 splits, training-only series selection, matched starting
  observations and common external demand paths across policies.
- Implement a shared observation/action interface, strict affordability checks,
  bounded repair and explicit fallback with independent saved-action replay.
- Reconcile contribution with cash, stock and pipeline assets; analyze service,
  stockouts, inventory, behavioral response, recovery and request costs.
- Preserve frozen designs, source pins, failed requests and accounting holds;
  provide eight executed notebooks, tests, generated figures/tables and a LaTeX report.

## Reproduce without API spending

Requires Git, Python 3.12 and internet access for initial public source/data downloads.
The full offline test/design path needs the three small pinned source checkouts:

```powershell
git clone https://github.com/DnyChillTypin/llm-business-shocks-sim.git
cd llm-business-shocks-sim
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-research.txt
.\.venv\Scripts\python.exe scripts/setup_project.py
.\.venv\Scripts\python.exe scripts/setup_benchmarks.py --only FirmBench
.\.venv\Scripts\python.exe scripts/setup_benchmarks.py --only ICBE
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/check_public_stage8.py
```

On macOS/Linux use `python3.12 -m venv .venv` and `.venv/bin/python`.
These commands do not need `.env`, private runs or the 29 GB historical RetailBench
LFS archive. External input checksums and commits are fixed; installed package
versions from the tested fresh environment are recorded in the
[release environment snapshot](docs/results/stage8/environment.json).
Requirements contain ranges rather than a complete lock.

The [reproduction guide](docs/REPRODUCIBILITY.md) distinguishes public baseline/fixture
reproduction, saved aggregate analysis, the private evidence audit and the report build.
Public aggregates cannot independently rescore private model conversations.
New model requests need separately reviewed execution manifests and may return different outputs.

## Explore the notebooks

Open a notebook in VS Code, select the project `.venv` interpreter and run cells in order.
All eight run without paid API calls. The verifier writes fresh outputs into its input
notebook, so use a disposable clone to preserve the published versions.

| Notebook | Purpose |
|---|---|
| [01: Integration](notebooks/01_kaggle_retailbench_integration.ipynb) | Data, native transitions and the exploratory baseline pilot |
| [02: Setup](notebooks/02_benchmark_setup.ipynb) | Pinned sources, compatibility and saved readiness evidence |
| [03: Design](notebooks/03_kaggle_llm_experiment.ipynb) | Training-only selection and the frozen research matrix |
| [04: Pilots](notebooks/04_results_analysis.ipynb) | Genuine pilot outputs, failures and measured costs |
| [05: Native](notebooks/05_native_evaluation.ipynb) | Dataset-specific native results, coverage and retained ICBE failure |
| [06: Validation](notebooks/06_kaggle_experiment_readiness.ipynb) | Shared interfaces, fixtures and guarded execution readiness |
| [07: Primary](notebooks/07_primary_shock_comparisons.ipynb) | All 36 saved matched episodes, repairs and fallbacks |
| [08: Findings](notebooks/08_findings_and_robustness.ipynb) | Contrasts, recovery, behavior and baseline-only elasticity sensitivity |

```powershell
.\.venv\Scripts\python.exe scripts/verify_notebook.py --notebook notebooks/08_findings_and_robustness.ipynb
```

## Scope, costs and remaining research

The configured retail policy requests `gpt-4.1-mini-2025-04-14` through ShopAIKey.
Native interviewer/judge requests use `gpt-4o-mini-2024-07-18`; ICBE also requests
`deepseek-v3.2`. Requested/returned identifiers are logged, but served model weights
are not independently attested. Native benchmark units and compatibility changes
are documented in the [release attribution notes](docs/RELEASE_ATTRIBUTION.md).

The cumulative ceiling is **10 gateway credits**. Recorded exposure is
**2.186206858 credits**, including **0.059084209** in retained old unknown-charge
holds; primary request expense was **0.252123564 credits**. These are token-derived
estimates with conservative holds, not a current account balance or independently
verified provider bill. Stage 8 made no new model requests or paid experiments.

The [staged execution plan](docs/EXECUTION_PLAN.md) and individual checkpoints retain
the historical decisions, including earlier caps and preparation-only states.
The report and final release notes describe what actually finished.
Completed stages and useful milestones are committed and pushed to GitHub.

Remaining research includes the four full native Retail evaluations, a separately
reviewed ICBE protocol if desired, more series/windows and LLM repetitions, and
matched LLM sensitivity/ablations. The current 48-episode elasticity extension is
baseline-only. None of these extensions is claimed by this release.

## License and attribution

Our implementation is MIT licensed. External code and datasets retain their own
terms. The three upstream checkouts are obtained separately and remain unchanged;
raw datasets and model conversations are excluded from Git.
See [current attribution and compatibility](docs/RELEASE_ATTRIBUTION.md),
[the pinned source notes](docs/THIRD_PARTY.md) and
[integration details](docs/INTEGRATION.md).
