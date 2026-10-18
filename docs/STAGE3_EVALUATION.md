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

Normal model-call adapters are unchanged from preparation commit `8322966`; the completed-session recovery described below adds an execution wrapper around independent Consulting cases. Reporting and post-run validation work can make the tracked working tree dirty during a run; the run identity records that flag. Frozen prompts, model settings, case selection, native scoring and horizons remain unchanged.

### Consulting transport interruption

The first evaluation cohort stopped on HTTP 503 during its fourth session, after 49 valid responses and three complete judgments. The runner had not written state-complete combined session checkpoints. All original responses and partial judgments are retained; the failed request's full unknown-charge reservation is carried in the same ledger. The three observed overall judgments were 8, 8 and 8.5.

Before observing restart outcomes, the review selected a fresh ten-session cohort with identical frozen settings. Use the **first fully completed, artifact-validated cohort regardless of score** for the complete-cohort table. Keep the interrupted cohort, its partial judgment aggregates, all paid attempts and the full unknown-charge hold visible separately. This is a manual transport-related restart under the documented interactive failure handling, not verified state resume, score-based selection or an SDK retry. Do not call the eventual full cohort an uninterrupted first-pass evaluation.

The replacement launcher was subsequently terminated between chat turns after 93 completed responses and seven judgments, with one request still outstanding. No worker remained. Its provider outcome is unknown: the original reservation is retained in full, not treated as an observed provider failure or a free request. This cohort is explicitly incomplete and its seven judgments remain visible. Following the user's continuation instruction, the next identical cohort runs in a separate hidden background process. The first-complete-cohort rule applies to transport or process interruptions; no cohort is selected by score. Spending and attempt ceilings are unchanged.

### Completed independent-case recovery amendment

The separate-process cohort also encountered HTTP 503, after 114 valid responses and eight judgments. Its full failed-request reservation and partial outcomes remain counted. Before collecting further outcomes, execution switched from full-cohort restarts to **the earliest fully evidenced completed judgment for each frozen case**, with no selection by score. This explicitly supersedes the initial first-complete-cohort execution rule; no uninterrupted ten-session cohort is claimed.

The pinned CoT agent's case-start and case-end hooks keep no memory. Completed sessions are independent; partially completed conversations are restarted rather than resumed. Recovery rechecks frozen models/settings/source pins, each request digest and raw response identity/usage, valid parse events, native dialogue order and termination, exact case text and reconstructed transcript in the actual judge request, and valid rubric scores. The wrapper returns the original observed history and judgment to the unchanged native ten-case aggregator. Existing responses incur no new API call or duplicate cost. Current native-loader case hashes must match, and final saved histories/judgments must exactly equal the re-audited evidence.

Eight frozen cases passed these checks; only the two missing cases require fresh sessions. Completed cases now receive durable per-session checkpoints. Synthetic tests reject altered or incomplete evidence and verify that aggregating independent saved sessions produces the same native mean scores. The frozen ten-case plan, message limits, models, prompts, source data and native scorer remain unchanged, and all interrupted cohorts remain separately visible.

### ICBE exact-request replay amendment

The initial full ICBE run stopped at round 20 of its first match on HTTP 503 and cancellation of the paired request. Both requests retain their full unknown-charge reservations. The preceding 38 responses cover 19 complete rounds and passed parsing and usage checks.

Before new calls, an offline probe passed those actual observed responses through the pinned native simulator and verified every reconstructed full request. Recovery uses the first observed validated response for each frozen ordered-pair/round/actor identity, only if its entire request digest matches the native request at that point. The native code reconstructs histories, phase transitions, moves and scores. Different requests stop execution before transport; invalid model decisions cannot be resampled through this recovery path.

Each replay is recorded with its evidence digest. Replayed responses make no new API call and incur no new reported charge; every source cohort, failed request and reservation remains visible. Full validation requires all 1,200 logical choices exactly once, native workbook points and pair/round coverage, and agreement between replayed moves and workbook records. Synthetic tests verify zero transport for exact matches, rejection of changed histories, one new call for a missing choice, and prefix reconstruction through the actual native simulator. Frozen models, prompts, 100-round horizons, 25-round phase boundaries, native payoffs, history limits, temperature and the documented 4,096-token ceiling remain unchanged.

## Evidence and publication

### Invalid ICBE response checkpoint

The exact-request continuation reused 38 verified responses and made 318 new calls. At the second ordered match's round 78, DeepSeek reached the frozen 4,096-token ceiling with reasoning only, empty final content, and no decision. Parsing correctly rejected the response. The 317 fresh valid responses plus 38 replays cover 177 complete valid rounds, with one additional valid actor response in the failed round. Neither the invalid response nor its successful peer is retried. No full native workbook or final ICBE score exists.

This is a model-response validity failure, distinct from the preceding transport interruptions. The recovery verifier rejects sources containing an invalid decision, so further exact-request recovery cannot silently replace this outcome. The current evaluation is stopped for methodology review. Retaining the failure under the frozen protocol, or designing a separately labeled amended experiment, requires an explicit research decision before further ICBE spending. The existing six-credit cap is not exhausted.

The checkpoint preserves all cohorts and costs, updates the saved-output notebook and aggregate evidence, and distinguishes the 14 validated tasks from failed ICBE and four deferred Retail tasks. QC checks of evidence and software can pass while experimental coverage remains incomplete.

Raw responses, transcripts, request identifiers, account snapshots, allowance approval history and detailed run mappings stay under ignored `results/` or `.cache/`. Publish aggregate task metrics, anonymous cohort labels, coverage, model identifiers, token-derived project costs, limitations and saved-output analysis only. Push code and reviewed aggregate results at useful milestones.

The final checkpoint must distinguish completed non-Retail coverage from deferred Retail coverage, and must retain every failed or incomplete cohort in the local audit and public aggregate denominators.
