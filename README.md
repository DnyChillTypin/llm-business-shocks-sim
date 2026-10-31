# Can LLMs Adapt to Business Shocks?

Inventory, pricing and business-shock evaluation with a configured LLM policy,
transparent baselines and an auditable simulator.

[![Research validation](https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/workflows/tests.yml/badge.svg)](https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/workflows/tests.yml)

## Current findings

The preliminary retail study contains 36 matched episodes, 756 policy-days and
252 LLM decision opportunities. Read the [findings report](report/main.pdf) or
the [professor-facing summary and report](output/pdf/professor_report.pdf).

- The LLM policy with repair and adaptive fallback exceeded adaptive contribution
  in 2 of 9 shock comparisons. Its control-adjusted contrast was positive in 7 of
  9 comparisons; these measure different outcomes.
- Of 252 decisions, 108 were valid on the first response, 127 more succeeded after
  repair, and 17 required adaptive fallback. All fallback days remain in outcomes.
- Three selected store-product series share one 21-day window, with one LLM
  realization per condition. All nine LLM shock/control pairs diverged before the
  shock. These descriptive simulator results do not establish beneficial adaptation.
- The separate native benchmark track has 14 validated tasks, one retained ICBE
  validity failure and four deferred Retail configurations.

Contribution is simulated revenue minus cost of goods sold and holding cost.
Synthetic demand, assumed mechanisms, a short horizon and dependent observations
limit the conclusions. This is a local adaptation, not an official leaderboard run.

## Setup and tests

Requires Git, Python 3.12 and internet access for initial pinned source/data downloads.

    git clone https://github.com/DnyChillTypin/llm-business-shocks-sim.git
    cd llm-business-shocks-sim
    py -3.12 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements-research.txt
    .\.venv\Scripts\python.exe scripts/setup_project.py
    .\.venv\Scripts\python.exe scripts/setup_benchmarks.py --only FirmBench
    .\.venv\Scripts\python.exe scripts/setup_benchmarks.py --only ICBE
    .\.venv\Scripts\python.exe -m unittest discover -s tests -v

On macOS/Linux use python3.12 to create the environment and .venv/bin/python.
These setup and test commands do not make paid model calls. Source commits and
dataset checksums are recorded in configs/sources.json. Requirements contain
ranges rather than a complete dependency lock.

## Repository contents

| Path | Purpose |
|---|---|
| src/ | Simulator adapter, policies, execution and analysis |
| configs/ and prompts/ | Source pins, experiment settings and policy prompts |
| scripts/ | Setup, execution, validation and report utilities |
| tests/ | Automated code and accounting checks |
| notebooks/ | Integration walkthrough and historical analysis notebooks |
| report/ | Self-contained LaTeX source, tables, figures and preliminary PDF |
| output/pdf/ | Professor-facing report and source |

The docs/ folder is a local research workspace containing plans, execution notes,
saved experiment evidence and intermediate figures. It is excluded from future
Git commits, along with temporary builds, raw datasets, vendor checkouts,
credentials, logs and private model runs. Keep a separate backup of local
research evidence.

Two execution inputs formerly stored with those notes remain versioned under
configs/design/: the frozen study manifest used for episode identities and the
selected native benchmark case list. Their contents are unchanged.

The integration notebook 01 can run from the public checkout after setup.
Historical notebooks 02-08, stage checkers and report exporters also require the
local docs/ evidence archive. Their saved outputs remain available for inspection,
but they cannot all be rerun from a fresh clone. Three Stage 5 archive-reconciliation
tests explicitly skip when that archive is absent. Public CI runs the code tests
and integration notebook; archive-dependent validation runs only when the archive
is present.

    .\.venv\Scripts\python.exe scripts/verify_notebook.py

The verifier executes and updates the selected notebook. Use a disposable copy
to preserve its saved output. See [report build instructions](report/README.md)
for the standalone LaTeX build, which does not require the local evidence archive.
The professor-report builder requires that archive.

## Model execution

Report 2 is being delivered in six review milestones. Milestone 1 freezes the
[research protocol](configs/report2/protocol.json) and
[sampling manifest](configs/report2/sampling_manifest.json). Milestone 2 adds
the [matched-prefix runner](src/experiments/report2.py) and a separately bound
[implementation manifest](configs/report2/implementation_manifest.json).
The protocol records research questions, history
treatments, outcome definitions, sampling, inference limits and review gates.

    .\.venv\Scripts\python.exe scripts/prepare_report2.py --check
    .\.venv\Scripts\python.exe scripts/check_report2_runner.py --check
    .\.venv\Scripts\python.exe scripts/run_report2_pilot.py --plan

These checks and planning commands are offline and never construct a model client.
Warm-up restoration uses seven saved adaptive decisions and verifies the full
economic state before activating a shock. Opaque native UUIDs and log timestamps
are excluded from equality checks. Full, frozen and empty history treatments
apply to both the LLM and its fallback. Saved-action replay checks results and
intervention denominators. Scripted completion tests are engineering evidence;
the manually executed development results are summarized below. Production
evaluation remains pending.

Each completed
milestone is committed and pushed for review before work on the next milestone.
All AI model runs are performed manually by the user. The manual pilot entry point
requires a reviewed authorization, current tariff, explicit monetary cap and the
existing cumulative budget ledger. It defaults to one development branch, blocks
duplicates and interrupted work, and never enables production evaluation.
The local milestone handoff records exact commands and outstanding budget inputs.
The frozen protocol itself authorizes no model calls; execution uses separate
reviewed user manual authorizations.

**Stage 3 complete:** all 24 development branches and 336 decisions were manually
executed and independently replayed. The completed trajectories used 434 requests:
238 decisions were valid on the first response, 87 succeeded after repair, and
11 used adaptive fallback. Recorded token-derived expense for these trajectories
was 0.242577599 gateway credits, with 943.50 seconds of serial API time.

Two transport interruptions required explicitly reviewed restarts. Their 15
additional requests remain archived, giving 449 physical pilot attempts in total.
Their known charges and full unknown-charge reservations are retained separately.
Total pilot exposure including archives/reservations was 0.265737394 credits.
This is a two-case development cohort, not the production sample or evidence of
population-level adaptation. Both cases, all four conditions and all three history
treatments are covered; the final audit preserves the original and replacement runs.

Costing, continuation and recovery tools are `scripts/prepare_report2_pilot.py`,
`scripts/continue_report2_development.py`, `scripts/recover_report2_development.py`
and `scripts/resume_report2_development.py`. Their offline modes make no model calls.
The final cohort audit reconciles all canonical and archived attempt IDs to the
same cumulative ledger without modifying original evidence. Raw responses,
ledger backups, audit receipts and review notes remain local and ignored.

The frozen production matrix contains 18,144 model decisions. The measured
development proxy gives 13.10 credits and 14.15 serial API hours before future
transport overhead; an all-repair/double-mean-request-usage scenario is 40.57
credits. These are extrapolations, not billing guarantees. Stage 4 should begin
with the unchanged 6,048-decision main cohort (4.37-credit base proxy), then review
measured costs before the diagnostic cohorts. Production requires new execution
support and a separate manual allowance/attempt authorization. No production
models have been launched.

New model requests require credentials and an explicit experiment budget. Copy
.env.example to .env for local configuration and keep secrets out of Git.
The current overall project limit is **20 gateway credits including prior usage**,
approved on 31 October 2026. Allocations are 4.2 credits for native benchmarks,
11.8 for retail experiments, and 4.0 held as an unallocated reserve. Individual
pilot limits and manual-execution review gates still apply. Historical report
caps describe their earlier releases.
The preliminary retail policy requested gpt-4.1-mini-2025-04-14 through ShopAIKey;
requested identifiers do not independently attest served model weights.

## License and attribution

Our implementation is MIT licensed. External code and datasets retain their own
terms. See [third-party sources and adaptations](ATTRIBUTION.md) and
configs/sources.json for the pinned inputs.
