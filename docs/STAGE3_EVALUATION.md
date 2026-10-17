# Stage 3: native evaluation

The execution route is the recommended non-Retail first pass. The user requested execution after reviewing this route. The total allowance is 6 USD-formatted gateway credits and 3,000 client attempts, inclusive of all earlier pilots and fully held unknown charges. This is a project spending limit conditional on the gateway tariff and token ceilings, not a provider-enforced quota or the cash purchase price of credits.

## Coverage and order

Run FinCode (7 cases), then the ten remaining reasoning datasets (50 cases each), EDT (96 steps), BeerGame (both scenarios, 25 weeks each), Consulting (10 seeded sessions and judgments), and ICBE (six ordered matches, 100 rounds each, 1,200 decisions). Factset's 50 cases remain a separately classified extension. Run and inspect one task at a time; do not start the next task until the preceding artifacts have been reviewed.

The original four Retail configurations at 180 days each remain deferred. Finishing this execution route completes the non-Retail subset; it does **not** complete Stage 3's original full coverage. Kaggle evaluation belongs to later stages and is not launched here.

## Controls

Retain frozen models, prompts, case IDs, seeds, horizons and scoring. Disclose the Stage 2 compatibility adapters, including ICBE's 4,096-token output ceiling. Pilot scores are not substituted for fresh evaluation scores.

The same SQLite allowance ledger carries forward existing spending, attempt counts and all unknown-charge holds. Allocate 4.2 credits to native work and 0.6 to Kaggle, leaving 1.2 unallocated (20% of the total). The Kaggle allocation is reserved for later-stage work; its evaluation task is not authorized by this stage's execution manifest. Retail evaluation is excluded from that manifest.

For reasoning, save each native case result durably, including the frozen case ID and input digest. Genuine wrong answers remain scored wrong. A case error stops queued cases before further transport. There is no implicit replay or automatic reuse: any reuse after an interruption requires inspection and validated case identity, input, response, score and method consistency. Interactive episodes restart with a new run identifier unless state-complete resume has been verified.

Require successful execution, complete raw local artifacts, valid decisions, reconciled usage, scorer outputs and exact case/horizon coverage before marking a task complete. Keep failed or incomplete attempts visible. Earlier held failed-call charges remain unknown and reserved. Inspect unusual BeerGame supply-chain totals against episode records; missing upstream metrics remain missing.

Keep native metric units explicit: finer's native accuracy is over individual entity labels, while its `correct / total` counts exact cases. Publish both measures with their own denominators; do not relabel label accuracy as case accuracy. Offline saved-action replay audits BeerGame's cost totals. Its native backlog proxy repeats the final backlog, so a time average derived from weekly observations is reported separately without changing the native score.

Paid decision adapters are unchanged from preparation commit `8322966`. Subsequent reporting and post-run validation work can make the tracked working tree dirty during a run; the run identity records that flag. Frozen prompts, model settings, case selection, native scoring and horizons remain unchanged.

## Evidence and publication

Raw responses, transcripts, request identifiers, account snapshots, allowance approval history and detailed run mappings stay under ignored `results/` or `.cache/`. Publish aggregate task metrics, anonymous cohort labels, coverage, model identifiers, token-derived project costs, limitations and saved-output analysis only. Push code and reviewed aggregate results at useful milestones.

The final checkpoint must distinguish completed non-Retail coverage from deferred Retail coverage, and must retain every failed or incomplete cohort in the local audit and public aggregate denominators.
