# Stage 2 checkpoint: paid work stopped on unresolved usage

This checkpoint introduces persistent budget reservations, raw request/response
artifacts and bounded native run plans. It is not completion of full benchmarks.
The frozen Stage 1 design and evaluation settings are unchanged.

The user approved **$1.00 in gateway credit and at most 250 attempts total**:
$0.75 for native pilots and $0.25 reserved for the later Kaggle validation pilot.
The first paid call was one frozen CodeFinQA case; its output, score and cost were
reviewed before further pilots. No full evaluation is authorized by this allowance.
The local approved manifest and SQLite spending ledger are ignored by Git.

## First genuine end-to-end result

Run `firm_CodeFinQA/20261017T105521982277Z`: one genuine response through the
native CoT agent and scorer, **0/1 correct**, no missing answer. The model returned
`-10705`; the native reference was `10705`. This wrong answer remains a pilot
outcome. API latency was 3.2374 seconds; usage was 925 input / 144 output tokens;
the uncached tariff estimate was **$0.000961841 gateway credit**. Requested and
returned identifiers were `gpt-4.1-mini-2025-04-14`; the gateway does not provide
independent model-identity attestation. Validation reconciles the raw response,
parse event, native score artifact, selected case ID and settled budget entry.

An earlier launch stopped on a UTF-8 BOM in the PowerShell-written allowance
before any completion. The loader now accepts UTF-8 with or without a BOM.

## Commands and artifacts

```powershell
# Offline: inspect the exact one-case / bounded-horizon plan.
.\.venv\Scripts\python.exe scripts/run_benchmarks.py run --task firm:CodeFinQA --config configs/pilots/native.json --dry-run
# Paid: requires the separately approved local manifest.
.\.venv\Scripts\python.exe scripts/run_benchmarks.py run --task firm:CodeFinQA --config configs/pilots/native.json --budget .cache/approvals/stage2_pilot_v1.json
# Offline: validate a saved run, preserving wrong-but-valid answers.
.\.venv\Scripts\python.exe scripts/validate_benchmark_run.py results/benchmarks/<task>/<run_id>
```

Each run saves launch/config/identity manifests, console and exit status,
`api_attempts.jsonl`, sanitized raw files under `attempts/`, native result files,
usage totals and budget snapshots. `validation.json` records artifact checks;
an exit code alone does not establish complete coverage. Actual evaluation must
use the original full-horizon config, a separate approved allowance, and artifact
validation. Do not reuse a diagnostic result as evaluation evidence.

Reservations are shared across task processes, count every attempt, and retain
unknown charges. Missing usage or a failed transport blocks further paid work
until reconciled. SDK retries are disabled; native retries cannot conceal fatal
budget, gateway or invalid-decision conditions. Limits are conditional on the
published applicable tariff, the conservative input envelope and gateway output
limits; this is **not a provider-enforced dollar quota**. Rate-derived estimates
are not independently verified invoices or the cash price of purchased credit.

## Offline evidence and remaining gate

All 20 native readiness checks passed in the fresh batch
`results/setup_checks/20261017T105103832125Z/`. All 38 automated tests passed,
including shared-budget races, persistent attempts, missing usage, failed streams,
redaction and invalid-decision failure paths. The scripted native scorer fixture
passed separately; its synthetic responses/tokens are excluded from research and
cost estimates.

## Current outcome

Eleven one-case reasoning pilots passed artifact checks: eight correct and three
incorrect (CodeFinQA, formula, Factset). This is diagnostic coverage, not an estimate
of full-dataset accuracy. Factset remains a separate local extension.

The Consulting pilot `20261017T110343057610Z` made ten successful completions,
then stopped on HTTP 503 at **2026-10-17 11:04:39 UTC**, requested model
`gpt-4o-mini-2024-07-18`. No judge score or complete interview is reported. The
failed request had no returned usage; attempt ID
`78b37b3af16842ad81504f03fa222ae9` is local, not a provider request identifier.
The original failure saved type/status and timing, but no provider error body;
the adapter now also preserves sanitized error bodies/request IDs for future
diagnosis. It does not infer an unbilled request from a 503.

There were **22 client attempts**, 21 completed responses, one failed response:
the ledger holds **$0.018997480** in known token-derived upper estimates plus
**$0.007690500** unresolved reservation, **$0.026687980** total exposure.
This is a charging-evidence stop, not exhaustion of the $1 allowance. Both native
and Kaggle paid calls are blocked by the same ledger.

Two read-only account checks after the failure reported rounded balance **$19.98**.
The later snapshot at 11:09:32 UTC uniquely matches all 21 completed responses to
provider history by model, token counts and time, totaling **$0.017866** provider
reported credit. The failed request has no unique matching charge row. Account
history totals include earlier calls; neither those totals nor an absent failed
row prove this request cost zero. No reservation was released and no paid call
was attempted after the failure. See [reconciliation](results/stage2/billing_reconciliation.json).

The unpaid Stage 4 prerequisites now include the frozen JSON policy, one repair
then explicit adaptive fallback, complete-portfolio validation before mutation,
a shared baseline/LLM episode loop, validation-window preparation and a guarded
pilot command. Offline checks show exact legacy/shared baseline equivalence and
21-day scripted completion for all four scenarios. Scripted results are not
genuine LLM outcomes. Full primary evaluation remains disabled in the new paid
Kaggle command. The genuine 42-decision validation pilot has not started.

All **49 automated tests** passed, including the observed failure paths, cross-track
blocking, BOM loading, wrong-but-valid scoring, repair/fallback export and action
atomicity. Notebook 04 executes from committed sanitized artifacts without API
access. The Stage 1 frozen design remains unchanged. The earlier infrastructure
milestone `4001cf7` passed [CI](https://github.com/DnyChillTypin/llm-business-shocks-sim/actions/runs/39026932102).

## Remaining Stage 2 gate

1. Obtain request-specific charging evidence for the failed request, record an
   auditable reconciliation in the existing ledger, and preserve the original
   failed run. Do not reset the ledger, label missing usage zero, or buy a new
   allowance to evade this check.
2. Resume bounded native pilots under the existing approval, reviewing Consulting,
   Beer, EDT, Retail dynamic middle/hard and ICBE separately. Retry a corrected or
   recovered pilot as a new run; retain all consumed attempts and prior failures.
3. Validate one full 21-day Kaggle control episode before the delivery-disruption
   episode, under the reserved $0.25. Inspect fallback frequency before continuing.
4. Finish family-specific cost/time projections, including long-context Retail
   uncertainty and the late ICBE phase qualification. Then request a concrete
   total evaluation cap, stating whether pilot spending is included and preserving
   a recommended 20% reserve. No full evaluation is currently authorized.

**Stage 2 is incomplete.** Neither Stage 3 nor primary Kaggle comparisons should
start from this checkpoint. See [partial cost estimate](COST_ESTIMATE.md) and
[saved analysis notebook](../notebooks/04_results_analysis.ipynb).
