# Native benchmark setup and execution

The prepared suite covers all agreed task families with bounded cases and full
native horizons. Model names are substitutions served through ShopAIKey; results
must not be described as exact reproduction of the papers' model scores.

## Coverage and defaults

| Task | Prepared run | Method |
|---|---|---|
| RetailBench | Dynamic/still × middle/hard; one 180-day episode each | Native ReAct strategy/execution loop |
| FirmBench Structured Reasoning | 11 included sampled datasets, 507 examples total | Native CoT agent and scorers; Factset extension described below |
| FirmBench Consulting | 10 cases selected with seed 42; at most 12 messages per case | Native CoT candidate; separate interviewer/judge model |
| FirmBench Beer Game | Both default scenarios, 25 weeks each | Native CoT, native MCP simulation |
| FirmBench EDT | One scenario decision followed by 96 native ABM steps | Native CoT and EDT model; supported full-episode BPTK execution |
| ICBE | Three models, all six ordered pairs, 100 rounds each, four phases | Native prompts/payoffs/export; 1,200 model decisions |

`configs/benchmarks.json` selects models, horizon, seed, output limits and workers.
Current candidate model: `gpt-4.1-mini-2025-04-14`; interviewer/judge:
`gpt-4o-mini-2024-07-18`. ICBE additionally uses `deepseek-v3.2`. Availability is
checked against the gateway before experiments. Returned model IDs are logged;
gateway routing and actual model identity are not independently attested.

## Install and check

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-benchmarks.txt
.\.venv\Scripts\python.exe scripts/setup_benchmarks.py
.\.venv\Scripts\python.exe scripts/run_benchmarks.py check
.\.venv\Scripts\python.exe scripts/check_gateway.py
```

The setup verifies pinned source commits and obtains native input data. For a
fresh RetailBench checkout it omits historical `paper_data` outputs. Existing
vendor code is not rewritten. Local checks block all LLM calls, exercise all
processors, run each Retail configuration for a day, complete both Beer Game
horizons, complete the EDT horizon, and export a scripted ICBE tournament.
These are readiness checks, not research results.

`scripts/check_gateway.py --smoke --budget <approved_manifest>` additionally makes four short paid calls:
JSON compatibility on all three configured models and native Retail streaming.
It writes usage evidence without saving keys. Credentials belong only in the
ignored `.env`; use `.env.example` as the template on another machine.

## Start one real task

```powershell
.\.venv\Scripts\python.exe scripts/run_benchmarks.py list
.\.venv\Scripts\python.exe scripts/run_benchmarks.py run --task firm:CodeFinQA --config configs/pilots/native.json --dry-run
# Paid, only with the separate approved allowance:
.\.venv\Scripts\python.exe scripts/run_benchmarks.py run --task firm:CodeFinQA --config configs/pilots/native.json --budget .cache/approvals/stage2_pilot_v1.json
```

Replace `firm:CodeFinQA` with any listed task. A `run` command starts paid calls;
the checks above do not. Start with one task, inspect its traces and actual
usage, and estimate the remaining suite before launching long episodes.

Each run has a unique directory under `results/benchmarks/` with configuration,
native outputs, console log, token usage and process exit status. Use another
PowerShell window to watch its `console.log` with `Get-Content -Wait`.
Native Retail checkpoints are retained. The unified launcher starts a new run;
it does not automatically resume partially completed tasks.

Paid execution now requires an immutable approved allowance and a persistent,
shared spending ledger. The pilot allowance excludes full evaluation. Missing
usage retains its full reservation; only explicitly recorded bounded failure
holds under an approved continuation can avoid blocking subsequent calls.
see [Stage 2 status](STAGE2_PILOTS.md) and [measured costs](COST_ESTIMATE.md).

Calls have a 90-second request timeout, an output ceiling of 4,096 tokens, and a
6,000-call ceiling per task. These are operational bounds, not a monetary cap.
Full Retail horizons can require many calls; $20 gateway credit is not a promise
that the entire suite will finish. API failures stop a run instead of being
silently scored as incorrect answers or cooperative moves.

## Compatibility changes recorded for the report

All changes live in our launcher; pinned vendor files remain unchanged.

- RetailBench's inconsistent `sku` import is aliased to `module.sku`. Relative
  input paths are resolved, and middle-setting news paths point to the matching
  dynamic/still input directory. Its native loop and simulation are retained.
  Forced `end_today` after invalid-tool/turn exhaustion now stops as an explicit
  failed decision rather than silently advancing a day. This documented failure
  handling change leaves the vendor source unchanged.
- All clients use the configured gateway, including Consulting's hard-coded
  endpoint. Unsupported reasoning settings are removed for the selected GPT-4
  models. Native output requests are capped by the local run configuration.
- Windows FormulaEval uses a separate, time-limited process in place of Linux
  `fork`/`SIGALRM`. Formula assembly, generated tests and scoring tolerances stay
  native. API credentials are omitted from the formula process environment.
  Imports and builtins are restricted; it is not an operating-system sandbox.
- FirmBench ships `factset` samples but its CLI and processor reject that name.
  Our explicitly labeled extension uses its numeric-span scorer for binary
  decisions and removes `source_label` hints from model-visible context. Report
  this extension separately from the ten natively supported datasets.
- EDT's upstream server calls an SD-only session API with an ABM model. Our
  adapter uses BPTK `run_scenarios` with the native EDT agents, equations, schema
  normalization and scenario changes. It exports all 96 steps and terminal
  controlling-agent metrics. This is scenario-level decision-making, not an LLM
  choosing new actions at every step. See [BPTK's documented API](https://bptk.transentis.com/api/api_bptk.html).
- ICBE keeps native ordered matches, phase payoffs, prompts and Excel sheets;
  model IDs and endpoint are configured locally. API and decision-parse failures
  stop execution instead of defaulting to cooperation.
  Stage 2 found the native 150-token output limit truncated a decision. The
  documented compatibility cohort uses the configured 4,096-token ceiling and
  requires one explicit, unambiguous decision. See [amendments](STAGE2_AMENDMENTS.md).

The prepared suite uses CoT/ReAct, as agreed. Other upstream memory, ensemble,
debate and prompt-training methods need their own experiments and configurations.
Installing the embedding libraries does not run or download optional memory
models. All raw datasets remain subject to their upstream terms.
