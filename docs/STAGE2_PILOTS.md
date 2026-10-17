# Stage 2: bounded pilots (in progress)

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

Remaining work: run the affordable pilot menu sequentially, review family-specific
artifacts and fallback paths, complete the Stage 4 offline prerequisites before
the Kaggle validation pilot, and publish measured cost/time projections and a
total-budget decision. Long Retail context and late ICBE phases need separate
qualifications; short pilots cannot establish full-horizon reliability.
