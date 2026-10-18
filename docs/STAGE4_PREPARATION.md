# Stage 4 preparation: Kaggle LLM experiment

This is the historical preparation plan. **Stage 4 implementation/validation is now complete**; see the [execution checkpoint](STAGE4_EXECUTION.md) for measured coverage, commands and limitations. Preparation and execution made no model calls and ran no primary-window policy episodes. The frozen ICBE failure and all four deferred Retail evaluations remain visible. Native benchmark scores remain separate from the Kaggle adaptation.

## Purpose and current evidence

Stage 4 prepares fair inventory/pricing comparisons under observable business shocks. The policy, shared environment loop and genuine validation pilots were implemented early for Stage 2, so they should be reused. The remaining work is to verify the three-series expansion and finish the execution/validation contract that Stage 5 will use.

| Requirement | Current evidence | Remaining work |
|---|---|---|
| Daily LLM policy | `src/agents/llm.py`: current serialized observation, strict JSON action validation, one repair, explicit adaptive fallback | Retain frozen prompts/model/schema; do not tune away pilot losses |
| Shared transition loop | `src/experiments/kaggle.py` applies the same action interface for all policies | Extend validation-window checks to all three selected series |
| Leakage and parity checks | Five existing Kaggle contract tests pass, including future-demand perturbation, strict past history, atomic validation, legacy-baseline parity and four-scenario mock rollouts | Check matching initial conditions and exogenous demand hashes across the expanded matrix |
| Genuine model validation | Two 21-day Stage 2 LLM episodes; 42 decisions, 15 repairs, three fallback days | Preserve reviewed failures and fallback-inclusive outcomes; no new pilot is needed solely to improve scores |
| Evaluation plan | Frozen 36-episode matrix; dry run confirms 252 primary LLM decisions | No primary outcomes generated during preparation |
| Primary execution | Launcher deliberately accepts paid validation pilots only | Implement and test explicit primary-episode authorization and duplicate protection before Stage 5 |
| Saved-run validation | `scripts/validate_kaggle_run.py` currently requires a paid validation pilot | Support free/scripted checks and primary episodes without relabeling fixtures as genuine LLM results |

The LLM scored below the adaptive baseline in both genuine validation episodes. First-pass validity was 27/42, model completion after repair was 39/42, and operational fallback was 3/42 (7.1%). The fallback review retained the operational policy and its negative findings. These are validation outcomes, not primary shock-comparison findings.

## Frozen expansion and information boundary

The smallest agreed expansion beyond the one-series pilot is already fixed by training-only variability ranks:

| Training variability rank | Series |
|---|---|
| 25 of 100, zero-based | S001 / P0001 |
| 50 of 100, zero-based | S004 / P0006 |
| 75 of 100, zero-based | S003 / P0016 |

Use control, demand surge, demand decline and delivery disruption; fixed, adaptive and `llm_with_fallback` policies; 21 days with shocks on days 8–14. The primary window remains **22 September–12 October 2023**. This is three matched series-window blocks, 36 episodes, 756 policy-days and 12 LLM episodes: 252 first attempts and at most 252 repairs. Additional windows, repetitions, products, severities and models remain outside this core plan.

Use **2–22 April 2023** for implementation checks. Calibration and series selection use training data through 1 April 2023. Primary-window prior manual outcome use is uncertain; never describe it as pristine unseen evaluation.

Every policy receives the same observation schema and action constraints. Within each block, initial cash, inventory, pipeline and past history must match, and exogenous base-demand paths must match across policies/scenarios. Later inventory, price-dependent demand and histories may legitimately differ because actions differ. Future demand, scenario labels and shock calendars stay private; a changed current delivery lead time is legitimate observable information. Synthetic demand, price elasticity and costs are assumptions, not real-world causal evidence.

## Stage 4 execution order and exit criteria

1. Reconfirm frozen hashes and keep model `gpt-4.1-mini-2025-04-14`, temperature 0, 1,024 output tokens, existing system/repair prompts, schema and failure policy unchanged.
2. Build free validation-window checks for all three selected series and all four scenarios. Run fixed/adaptive policies and a clearly labeled scripted policy through the shared loop. This yields 24 baseline and 12 scripted validation episodes; scripted actions are fixtures, never LLM performance evidence. Do not run primary-window outcomes to debug the policy.
3. Audit matching initial observations, private base-demand paths, strictly past history, allowed actions, explicit repair/fallback exports and cash/inventory/pipeline reconciliation within `1e-6`. Keep the existing legacy-baseline parity checks.
4. Extend saved-run validation to distinguish validation, primary, baseline and scripted provenance. It must reject missing days, mismatched paths, unlogged actions, invalid final actions and incorrect expense accounting.
5. Reuse the runner's canonical episode identities and add a primary matrix manifest. Test accidental-duplicate rejection, interrupted-episode retention, one episode at a time, cumulative expense carry-forward and review before the next episode when fallback exceeds 5%. New transport/budget failures stop incomplete; they do not become adaptive fallback.
6. Create `notebooks/06_kaggle_experiment_readiness.ipynb` during execution. Run All must use free fixtures/saved outputs and show the remaining gates. Retain notebooks 03 and 04 as the design and genuine-pilot references.
7. Close Stage 4 only after these offline gates pass. Publish aggregate QC/coverage and push the milestone. Stage 5 then runs the free primary baseline matrix and explicitly budgeted LLM episodes. Do not mark 36 planned episodes as completed research.

Existing files to reuse: `configs/study.json`, `configs/kaggle_retailbench.json`, `prompts/kaggle_policy_v1.txt`, `prompts/kaggle_repair_v1.txt`, `configs/kaggle_action.schema.json`, `src/data/kaggle.py`, `src/envs/kaggle_retailbench.py`, `src/agents/{baselines,llm}.py`, `src/experiments/kaggle.py`, `scripts/run_kaggle_experiment.py`, `scripts/validate_kaggle_run.py`, and `tests/test_kaggle_llm.py`. Add focused checks only where the expanded matrix or execution safety is not already covered.

The current preparation commands are executable and unpaid:

```powershell
$py = '.\.venv\Scripts\python.exe'
& $py scripts/check_research_design.py
& $py -m unittest discover -s tests -p test_kaggle_llm.py -v
& $py scripts/run_kaggle_experiment.py --config configs/study.json --dry-run
```

Inspect `docs/results/stage4/preparation.json` for the preparation snapshot. Complete local dry-run/test/design logs are under ignored `results/verification/stage4/`. Existing genuine pilot evidence is under `docs/results/stage2/`; notebook 04 loads it without API calls. During Stage 4 execution, put validation fixtures under ignored `results/verification/stage4/`, and publish only reviewed aggregate QC, contract coverage and the saved-output notebook. The new notebook and expanded validators listed above are **to be created**, not existing completed artifacts.

## Cost, stopping rules and next decision

Preparation and the planned offline Stage 4 checks cost **zero model credits**. Allow approximately **1–3 active hours** for the remaining expanded checks, validator/runner work and notebook review; defects may take longer. No model/network runtime is needed for those checks once dependencies/data are available.

The ledger remains at **1.934083294 credits of the inclusive 6-credit cap**, over 1,438 attempts; eight unknown charges remain fully reserved. The Kaggle allocation is 0.6 credits including 0.047451264 already spent/reserved, leaving **0.552548736** in that scope. Nothing resets prior spending or reallocates the unallocated reserve.

Stage 2 measured pilots project the later primary matrix at **0.21493599 credits base / 0.42987198 high planning scenario**, with 342 expected attempts versus a 504-attempt repair ceiling. These are planning scenarios, not guaranteed cost bounds. The high scenario would leave approximately 0.1227 credits in the Kaggle scope, with total project exposure about 2.364 credits. Reverify tariffs and headroom before Stage 5; a quota stop can still leave incomplete coverage. Pilot-scaled elapsed time is about 10.5 minutes before additional review or gateway delays; reserve 30–90 minutes for monitored execution and review, and revise this estimate from observed performance.

The present allowance/launcher authorizes Kaggle validation pilots, **not primary evaluation**. Stage 5 needs its own explicit run authorization under the same cumulative ledger, configured task identity and existing caps. This preparation neither grants that authorization nor raises the cap. No extra spending decision is needed for offline Stage 4 work. Changes to prompts/models, the frozen matrix, fallback policy, or budget/scope require a separate concrete amendment.

If an offline check fails, retain its evidence, fix the implementation on validation data and rerun affected checks. A behavior-changing correction requires a documented cohort/design amendment before primary calls. Keep all fallback days in operational primary results. Report later comparisons by the three matched blocks with descriptive effects; correlated days are not independent replications.

**Next action:** execute Stage 4's expanded offline validation and saved-run/execution safeguards. Primary comparisons remain Stage 5 work. Accepting the ICBE failure for progression does not complete its missing coverage or the deferred Retail suite.
