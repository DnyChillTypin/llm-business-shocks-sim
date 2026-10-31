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
new model results remain pending.

Each completed
milestone is committed and pushed for review before work on the next milestone.
All AI model runs are performed manually by the user. The manual pilot entry point
requires a reviewed authorization, current tariff, explicit monetary cap and the
existing cumulative budget ledger. It defaults to one development branch, blocks
duplicates and interrupted work, and never enables production evaluation.
The local milestone handoff records exact commands and outstanding budget inputs.
The current protocol authorizes no model calls.

Stage 3 preparation adds `scripts/prepare_report2_pilot.py` for read-only costing,
manual allowance activation, and post-run auditing. The first proposed branch has
14 decisions and at most 28 attempts. Its cost worksheet and approval files stay
under ignored `results/report2/`; the local review note contains the exact manual
command. Preparation preserves the cumulative ledger. Only an explicit user
`--activate-and-run --approve-credit-limit 0.50` command activates the narrower
allowance and launches the model. Measured pilot results remain pending until
that command has run and its evidence has been audited.

First development branch checkpoint: the user manually completed branch 0 and
its saved-state/ledger audit passed. Fourteen decisions used 19 requests: 9 were
valid on the first response, 5 succeeded after repair, and none used fallback.
Recorded token-derived expense was 0.011881723 gateway credits, with 45.42 seconds
of serial API time. This is one control/full-history development branch out of
24, not evidence of shock adaptation or completed production evaluation.
Replaying or auditing saved actions makes no model requests. Repeating activation
after a completed run is blocked; further branches need a separately reviewed allowance.

The remaining development pilot is prepared through
`scripts/continue_report2_development.py`. Its offline preparation and audit modes
preserve the first branch. Explicit manual model execution skips verified
completed branches and stops on incomplete claims. The proposed continuation
covers 23 branches and 322 decisions, with at most 644 additional attempts and a
1-credit incremental allowance inside the overall 20-credit cap.

The user manually launched the continuation. An offline interruption review
verified branches 0–9 (140 decisions, 176 requests) and 11 saved decisions in
branch 10. Its repair request timed out after 90 seconds. The incomplete branch
is excluded from completed outcomes; all charges and its unknown-charge reserve
remain in the cumulative ledger. Stage 3 remains incomplete, with branches
11–23 unstarted. `scripts/review_report2_interruption.py` audits this stopped
cohort without changing original evidence or authorizing retries. A separate
reviewed recovery handoff is prepared with `scripts/recover_report2_development.py`.
Its explicit user manual activation preserves the original partial trajectory in
an archive, retains the full timeout reserve, restarts branch 10 and finishes
branches 11–23. Existing credit and physical-attempt ceilings remain unchanged;
the recovery wrapper counts archived requests as well as replacement requests.
On success it automatically audits all completed branches and the archived
failure, then stops for Stage 3 review. Preparation and checks make no model calls.

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
