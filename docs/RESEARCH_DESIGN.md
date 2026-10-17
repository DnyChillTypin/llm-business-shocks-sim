# Frozen research design, version 1

Frozen on 17 October 2026 before new paid pilots or evaluation. The executable specification is [`configs/study.json`](../configs/study.json); [`study_design_manifest.json`](results/study_design_manifest.json) records text hashes, with CRLF normalized to LF. This is a prospective analysis and execution protocol, not a claim that experiments have finished. A spending limit is not approved by this document.

## Questions and evidence

| Question | Comparison and evidence | What it can establish |
|---|---|---|
| RQ1: Can the configured agents complete the agreed native tasks, and what scores do they obtain? | Native RetailBench, FirmBench and ICBE coverage; native task-specific scores; failures and costs | Capability under substituted gateway models and documented compatibility paths |
| RQ2: How does the LLM retail policy compare with transparent rules under simulated shocks? | Within-series/scenario contribution differences versus adaptive (primary) and fixed (secondary) rules, with service and inventory outcomes | Descriptive performance in the specified synthetic simulation |
| RQ3: Do actions respond to new information, and how does operation recover? | Matched control/shock action traces, phase summaries, control-adjusted contribution and service, operational recovery | Behavioral response and its business consequences; no model-weight learning claim |
| RQ4: What reliability, latency and API expense does operation require? | All attempts, parse failures, repairs, fallback days, incomplete episodes, token/latency/cost records | Operational feasibility, including the cost of failed attempts |

“Adaptation” means action changes within an episode as observable conditions change. A changed action alone is insufficient: connect it to contribution, stockouts, inventory or recovery. Without a frozen-history LLM ablation, these runs cannot isolate the causal value of history or distinguish every reactive explanation. General benchmark reasoning scores do not establish retail shock adaptation. ICBE provides a separate descriptive phase-response study in a two-player payoff game, not evidence about inventory decisions.

## Native benchmark coverage

Retain the native CoT/ReAct approaches, complete agreed task-family coverage, bounded case counts and full configured horizons. Requested models are `gpt-4.1-mini-2025-04-14` for the primary candidate, `gpt-4o-mini-2024-07-18` for Consulting interviewer/judge, and those two plus `deepseek-v3.2` for ICBE. All use ShopAIKey. Log returned identifiers; model identity is not independently attested. These are model-substituted reruns, not exact reproduction of published model scores.

| Family | Fixed coverage | Main outputs to report |
|---|---|---|
| RetailBench | Dynamic/still × middle/hard, one episode each, 180 days | Completed days, terminal native net-worth measure, native funds/inventory/orders and validity/failure traces; starting-to-terminal change if both are recorded |
| Firm reasoning | Ten supported datasets, 457 cases | Native dataset accuracy; `finer` uses its native component-level aligned-item correctness ratio, not ordinary whole-case accuracy |
| Factset extension | 50 cases, separate table row | Local binary numeric-span correctness and completion/invalid counts |
| Firm Consulting | Ten seeded case IDs, at most 12 native messages per case | Judge overall score (0–10); structure, quant, business sense, communication; finished/failed denominators |
| Firm BeerGame | `default_typical` and `default_smoothing_4`, 25 weeks each | Controlled retailer total cost; native backlog/inventory/bullwhip where actually exported; missing aggregates remain missing |
| Firm EDT | `interactive`, one scenario decision workflow followed by 96 ABM steps | Terminal accumulated earnings, cash, margin and other native exported metrics; no within-rollout LLM interventions |
| ICBE | Six ordered pairs, 100 rounds each, 1,200 decisions | Points and Option A/B frequencies by player, match and phase; transitions and failure counts |

The reasoning datasets are FinCode (7 cases), CodeFinQA, CodeTAT-QA, SEC-NUM, TAT-QA, ConvFinQA, FinKnow, FormulaEval, finer, formula and factset (50 each except FinCode). [`native_case_manifest.csv`](results/native_case_manifest.csv) fixes every row/case ID, source-file hash and canonical case hash without redistributing questions or answers. Case hashes cover the original JSONL object for reasoning and the native-loader-normalized object for Consulting. Row IDs are project identifiers for zero-based nonempty JSONL rows, not asserted upstream IDs. Consulting uses the native loader and `random.Random(42).sample`, with exact order:

`case_0040, case_0007, case_0001, case_0047, case_0017, case_0015, case_0014, case_0008, case_0056, case_0006`.

[`native_episode_manifest.json`](results/native_episode_manifest.json) fixes simulation scenarios and model pairings. ICBE phases remain rounds 1–25, 26–50, 51–75 and 76–100. Do not shorten evaluation episodes to fit a budget. A partial horizon remains incomplete. A completed native run requires the expected records and scores, not merely process exit zero. Native scores are reported per task with observed coverage and errors; do not pool them into a cross-benchmark score. Parse/API errors remain separate from genuinely wrong model answers. Do not impute failed cases as valid answers; if a dataset is partial, show the scored-subset denominator and selected total separately.

Keep the compatibility qualifications from [`BENCHMARKS.md`](BENCHMARKS.md): Retail imports/paths and native loop; Windows FormulaEval process helper with native scoring; Factset as a local extension with provenance hints removed; EDT's native ABM through a full-episode BPTK path; ICBE parse/API failures stop execution. Vendor source remains unchanged. Native Retail net worth and its shelf-life/cost machinery are distinct from Kaggle contribution accounting.

## Kaggle sampling and chronology

The data is synthetic, with 76,000 rows, 100 store–product series and 760 dates. Retain chronological 456/152/152 dates (60/20/20):

| Purpose | Dates | Use |
|---|---|---|
| Train | 2022-01-01–2023-04-01 | Series selection, mean demand, reference price and assumed costs |
| Validation | 2023-04-02–2023-08-31 | Policy/prompt/integration development; initial paid pilot uses April 2–22 |
| Existing exploratory pilot | 2023-09-01–2023-09-21 | Previously inspected baseline results; retain as exploratory |
| Primary evaluation | 2023-09-22–2023-10-12 | Fixed new comparison matrix; no tuning on these results |
| Optional second window | 2023-10-13–2023-11-02 | Disabled pending time, cost and a recorded amendment |

The user reported being unsure whether primary-window outcomes had previously informed tuning. The workspace contains only the earlier pilot's saved policy outcomes. Accordingly, describe the primary window as held out by this protocol with **uncertain prior manual outcome use**. Do not claim pristine unseen or confirmatory evidence. This disclosure is not resolved by choosing another date arbitrarily. No primary-window policy simulation is run while freezing this design.

Rank positive-mean series by sample standard deviation (`ddof=1`) divided by mean training demand, ascending, with store/product IDs as tie-breakers. For quantile `q`, take zero-based rank `floor(N*q)`. This preserves the existing upper-median selection:

| Quantile | Zero-based rank | Series | Training mean demand | Training CV |
|---|---:|---|---:|---:|
| 0.25 | 25 | S001 / P0001 | 91.662281 | 0.382527 |
| 0.50 | 50 | S004 / P0006 | 122.736842 | 0.401812 |
| 0.75 | 75 | S003 / P0016 | 106.949561 | 0.434536 |

Run each as a separate one-SKU environment, avoiding a new shared-cash allocation problem. These purposively selected series span a narrow range of observed training variability; they are not a representative retail sample. One primary window and one LLM realization per block are the minimum descriptive design. More nominal seeds do not create new demand paths.

## Matrix, observations and actions

The primary matrix is **3 series × 4 scenarios × 3 policies = 36 episodes, 756 policy-days**, including 12 LLM episodes and 252 primary decision opportunities. One possible repair each means at most 504 LLM attempts before budget stops. All episodes last 21 days. [`kaggle_episode_plan.csv`](results/kaggle_episode_plan.csv) gives immutable episode/block IDs and fixed execution order; [`planned_coverage.csv`](results/planned_coverage.csv) lists all native tasks and Kaggle episodes with planned status and zero completed units. Pilots and optional expansions are excluded from this primary matrix.

| Scenario | Days 1–7 | Days 8–14 | Days 15–21 |
|---|---|---|---|
| Control | Standard | Standard | Standard |
| Demand surge | Standard | Reference demand ×1.5 | Standard |
| Demand decline | Standard | Reference demand ×0.7 | Standard |
| Delivery disruption | Two-day lead | Five-day lead on new orders | Two-day lead on new orders |

Existing in-transit orders keep their scheduled arrival; the delivery effect can persist after day 14. The episode's scenario label and schedule are private. Current supplier lead time is observable immediately; demand changes enter history after the day completes. This difference in shock observability is part of the design.

All policies receive the same public observation: date, current cash, current lead time, SKU stock and on-order units, current/reference price, unit cost, training mean, daily order limit, allowed price multipliers, assumed elasticity and the last 14 completed demand observations. History reports price-normalized requested demand, including unmet demand; in-episode values retain rounding effects. Initial history uses only dates before episode start, including earlier held-out dates when operationally available. It is not used to recalibrate frozen training statistics.

No future demand, later CSV inventory/sales/orders/prices, scenario name or shock schedule is sent to the LLM. The prompt does not reveal episode dates or phase boundaries. The LLM receives the serialized observation, never the environment object, private CSV or file tools. The user message is canonical JSON for that observation; the system and repair prompts are versioned under `prompts/`. Start a fresh request with the same system prompt each day, with no cross-day chat memory beyond the shared observation history.

Each product action has exactly `order_quantity` (integer, including zero) and `price_multiplier` (0.9, 1.0 or 1.1). The total procurement amount cannot exceed pre-sales cash; each SKU obeys its daily quantity limit. Validate the entire action before mutation, apply all prices, place one combined positive-quantity order, then end the day. Zero orders are omitted from the native order call. Reject booleans, nonfinite numbers, unknown/missing SKUs, extra keys, coercion and clipping. The shape schema is [`kaggle_action.schema.json`](../configs/kaggle_action.schema.json); exact SKU/resource validation still needs Stage 4 implementation.

The fixed rule uses the training mean, reference price, and a five-day inventory-position target. The adaptive rule uses the latest 14-day price-normalized mean and the same five-day target; it raises price to 1.1 below two days of current-stock coverage and lowers to 0.9 above seven. Both subtract current stock and on-order units and obey cash/quantity caps. Preserve these baseline definitions during shared-runner refactoring.

`llm_with_fallback` uses the frozen JSON-action prompt, one completion/day, temperature 0, 1,024 output-token limit, 90-second timeout and no SDK retries. Temperature 0 does not guarantee deterministic gateway output. After invalid output, allow one explicit repair with the same observation, quoted prior response and validation errors. If still invalid, execute the adaptive rule for that day and label the fallback. Record whether the original, repaired or fallback action was executed. A transport/auth/budget failure instead stops the episode as incomplete. Fallback days remain in the primary operational result. Pure-LLM completion and fallback-free episode results are secondary, selection-affected descriptions. Inspect fallback rates after each episode; pause before the next episode if more than 5% of completed opportunities required fallback. Do not delete those outcomes.

Within each series/window, control and shock copies start from identical initial cash, observed episode-start stock, empty pipeline, training calibration, history and private base-demand trace. Price and shock transformations change realized requested demand; identical realized sales are neither expected nor imposed. Fixed execution order and one initial paid worker simplify auditing; timestamps and returned model IDs help expose gateway drift. There is no seed-based demand resampling.

## Assumptions and accounting

Retain elasticity 1.5; purchase cost 60% of training reference price; daily holding cost 0.1% of unit cost per closing unit; cash equal to 20 training-mean days of purchase cost; daily order cap of ten training-mean days; two-/five-day lead times. Disable reviews, returns, rent, expiry, substitution and inventory capacity limits. Use assumed supplier inputs. Kaggle estimated `Demand` is reference-price demand, transformed by the shock multiplier and price ratio raised to −1.5, then rounded as in the current environment. This is not an estimated causal demand model.

Only episode-start inventory is observed from the corresponding CSV row. Subsequent state follows actions and simulation. The native end-of-day step sells current stock, advances the calendar and receives next-day arrivals. Charge holding cost before those arrivals. Value unsold and in-transit stock at purchase cost with no terminal liquidation gain or write-off. Verify contribution against the change in cash plus on-hand inventory and pipeline assets to absolute tolerance `1e-6`. The final report must distinguish synthetic dataset monetary units from USD API costs; they cannot be subtracted from each other.

## Outcomes, comparisons and uncertainty

Primary outcome: 21-day contribution, `sum(revenue - cost_of_goods_sold - holding_cost)`. The primary comparison is `llm_with_fallback - adaptive` within each shock scenario and series; fixed is secondary and control is always reported. Show every block, then per-scenario equal-weight mean, median, range and positive/zero/negative counts. Relative gain is `100*(LLM-baseline)/abs(baseline)`; report NA if the denominator is at most `1e-9`. Show the absolute values too, especially for negative baseline contribution.

Also compute each policy's shock-minus-control contrast and the interaction `(LLM_shock - LLM_control) - (baseline_shock - baseline_control)`. This helps distinguish a general control advantage from a different shock response; it remains a contrast inside the assumed simulator. Do not pool all scenarios or monetary scales into an unexplained single headline score.

| Outcome | Definition / interpretation |
|---|---|
| Fill rate | Total sales / total requested demand; 1 for an episode with zero requested demand, explicitly labeled as such |
| Stockouts | SKU-days with lost units >0, plus total lost units |
| Inventory | Mean closing units before next-day arrivals; terminal on-hand/pipeline units and their purchase-cost value separately |
| Pricing/orders | Daily multipliers, mean multiplier, order quantity, first action divergence from paired control, and phase means |
| Behavioral divergence | First day on/after day 8 with order quantity differing by at least one unit or a different allowed price multiplier versus same-policy control; not alone evidence of beneficial adaptation |
| Recovery | Earliest day ≥15 beginning three consecutive observed days with zero lost sales and `abs(I_shock-I_control) <= 0.2*max(I_control,1)` on every day, paired within policy and series |
| Recovery delay | First qualifying day minus 14; if none is fully observed by day 21, mark right-censored, not zero or an exact terminal recovery time |
| Reliability | First-response validity, repaired validity, unresolved invalidity, fallback count/rate, complete/incomplete episodes; denominator stated for each |
| Operating cost | Per-attempt and per-complete-episode tokens, latency, retries/repairs, missing usage and provider-supported USD estimates/billing provenance |

The recovery rule is equivalent to comparing stock coverage using a common training-demand denominator; the one-unit floor is applied in stock units. It measures operational normalization, not recovery of cumulative profit. Initial conditions and demand continue to affect later days; daily rows are correlated repeated measurements.

Matched inputs do not guarantee matched LLM randomness. One model realization per condition leaves sampling or gateway-routing variation unmeasured, even at temperature 0. A control/shock action difference can include that variation; do not attribute every difference causally to the shock.

There are only three selected series-window blocks, sharing a calendar window. Use descriptive effects and traces. No daily-row bootstrap, day-level significance tests, convincing population confidence intervals or universal superiority claims. There is no agreed practical profit/service threshold, so no practical-superiority claim is allowed. An LLM can earn more contribution while worsening service or fallback burden; report that tradeoff explicitly. Successful research means valid evidence and honest conclusions, including negative results.

Optional work is disabled in v1: a second window; three total LLM replays per block; elasticity 0.75/2.25; more series; shock-severity/duration changes; or a frozen-history ablation. Additional LLM replays describe decision variability conditional on the same demand, not independent demand replications. Baseline-only elasticity checks do not establish LLM robustness. Expand only after costs and dependencies are recorded.

## Gates, amendments and what to run

Before paid pilots: implement full attempt-level logging, bounded pilot selection and a budget guard; obtain an explicit pilot cap and current rate/balance evidence. Before evaluation: pass genuine end-to-end pilots and shared-interface/leakage/accounting checks; approve a measured total cap. Missing usage is unknown cost, never zero. The $1/250-attempt pilot proposal is not spending authorization.

The frozen study file records the unapproved spending state at this checkpoint. Later authorization and live limits belong in a separate approved budget/run manifest; do not alter the frozen design simply to turn a spending switch on.

The implementation must record gateway/provider, requested/returned model IDs, input/output and other available token fields, latency, finish/parse status, failures and all retries/repairs, available cost provenance, action source, observation/prompt/config/source hashes and immutable run IDs. Keep pilots, evaluation, failed/incomplete runs and replayed/scripted data distinguishable.

Run the offline design checks and notebook from the project root:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py scripts/check_research_design.py --output results/verification/stage1/design_check.json
& $py -m unittest discover -s tests -v
& $py scripts/verify_notebook.py --notebook notebooks/03_kaggle_llm_experiment.ipynb
```

A fresh clone also needs the pinned FirmBench and ICBE checkouts for case/scenario verification:

```powershell
& $py scripts/setup_project.py
& $py scripts/setup_benchmarks.py --only FirmBench
& $py scripts/setup_benchmarks.py --only ICBE
```

These source checks do not need the 29 GB historical RetailBench outputs or paid model calls. The design notebook displays selected training aggregates, dates, planned coverage and validation evidence. It does not prepare new evaluation episodes or run policies. The existing preparation function still starts at the first test window; Stage 4 must add explicit split/window selection before this primary matrix is executable.

Validation-only fixes before evaluation require a new design/prompt version, retained old manifest and explanation before any primary call. After evaluation starts, do not tune prompts, metrics, exclusions or case selection on primary outcomes. An implementation correction creates a separately labeled cohort and reruns invalidated comparisons. Native compatibility changes and model substitutions must remain explicit. Do not silently edit hashes until a check passes.

Stage 1 exits when the checker reproduces selections/case IDs/horizons/matrix, all artifact hashes match, the notebook executes offline, every RQ maps to outputs, and limitations/spending boundaries are explicit. Its artifacts are then committed and pushed, and CI is checked for that exact commit. The report structure and planned assets are in [`REPORT_OUTLINE.md`](REPORT_OUTLINE.md).
