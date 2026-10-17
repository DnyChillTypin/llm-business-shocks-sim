# Stage 2 complete: genuine pilots and cost review

Technical pilot work and quality review finished on **17 October 2026**. Full evaluations have not started; their budget approval is the next-stage entry gate.

## Completed diagnostic coverage

| Track | Genuine coverage |
|---|---|
| Firm reasoning | One frozen case per dataset: 11 cases, 8 correct, 3 incorrect; Factset remains an extension |
| Consulting | One 12-message interview plus separate judge; overall 8/10 |
| BeerGame | One full 25-week scenario with native metrics |
| EDT | One valid setup decision, unchanged by normalization, then 96 native ABM steps |
| RetailBench | One complete day in each of four configurations, with explicit date advancement and no forced end_today |
| ICBE | Six ordered pairs, two rounds each, 24 decisions, native workbook and reconciled points |
| Kaggle | One training-selected validation series; control and delivery disruption, 21 days each; four matched free baseline episodes |

All **19 native task IDs** have validated pilot artifacts. Six complete Kaggle validation episodes contain 126 daily rows, including 42 LLM-policy days. No full native evaluation or primary Kaggle comparison is marked complete. The frozen full-evaluation coverage plan remains separate.

## Spending and retained failures

The user raised the inclusive pilot cap to **$2 gateway credit**, retaining the **250 client-completion-attempt ceiling**. Final accounting: **237 attempts**, **$0.849863719 known uncached estimates**, **$0.019009592 fully held unknown charges**, **$0.868873311 exposure**. There are no pending requests.

Three failed runs remain visible:

- Original Consulting: HTTP 503 without usage; a new complete case run succeeded.
- Original ICBE: the native 150-token limit truncated a decision and its paired request was canceled. The corrected output-limit cohort completed. Both known cost and the canceled request's full reserve remain counted.
- First Kaggle control: a 90-second timeout after seven completed days. It remains incomplete; a fresh full episode completed without combining trajectories.

The 503, cancellation and timeout have unknown actual charges. Their full reservations remain in the same ledger; no tokens, zero charges or successful decisions were invented. Continuation amendments retain prior manifests and spending. See [amendments](STAGE2_AMENDMENTS.md), [budget](results/stage2/budget_summary.json).

Detailed request telemetry, approval history and provider account/billing records are preserved in Git-ignored local storage. The public package contains sanitized aggregate research metrics and project cost estimates only. Returned model identifiers do not independently attest actual served models.

## Kaggle quality review

The complete LLM episodes used 57 requests: 42 first attempts plus 15 repairs. There were 18 invalid responses, **27/42 first-pass valid decisions**, **39/42 model decisions after repair**, and **3/42 (7.1%) adaptive fallback days**. This exceeded the frozen 5% review trigger; the required review is complete and linked to action-file hashes.

Every failure was a material cash-affordability violation, with overruns of approximately 1.98?34,386 synthetic monetary units. Invalid actions never mutated state. Final actions were valid, fallbacks exactly matched the frozen adaptive baseline, and cash, inventory and contribution reconciled. The review retains the frozen operational policy and its failures. No prompt was tuned to improve these scores. Primary outcomes must include fallback days and cannot be described as pure unassisted LLM performance.

| Validation scenario | Fixed contribution | Adaptive contribution | LLM with fallback contribution |
|---|---:|---:|---:|
| Control | 38,527.03 | 40,167.99 | 35,313.17 |
| Delivery disruption | 37,715.83 | 39,436.45 | 35,854.40 |

These are synthetic simulator monetary units, not API dollars. The LLM policy underperformed adaptive contribution in both inspected validation episodes. One validation series is not primary test evidence or population inference. Initial observations, prepared inputs and private base demand matched; future demand and scenario labels were absent from policy inputs.

## Cost decision and limitations

Full agreed scope projects to **$136.58 gateway credit and about 33 experiment hours**, before writing. Low/high planning scenarios are $102.44 / $273.16; these are not statistical intervals or worst-case guarantees. Retail accounts for $134.63 of the base estimate. One-day pilots do not establish later context costs or agent survival. Genuine ICBE pilots cover phase 1 only; all four native phase prompts and payoffs were checked separately offline.

The full-scope proposal is **$350 total**, inclusive of pilot exposure and at least 20% reserve. The recommended first-draft route is **$6 total** for non-Retail native evaluation plus the primary Kaggle matrix, also inclusive of pilots and reserve. Full Retail remains for the longer route without a horizon reduction. Both proposals are **unapproved**: [cost details](COST_ESTIMATE.md).

Native qualifications remain: substituted gateway models, Factset extension, Windows formula helper, native EDT ABM compatibility, explicit Retail failure handling and documented ICBE output-budget change. Some BeerGame native aggregate fields remain null despite available episode metrics; identify any later locally derived aggregation.

## Saved-only reproduction

Open [notebook 04](../notebooks/04_results_analysis.ipynb) and Run All without API calls. Inspect [coverage](results/stage2/pilot_coverage.csv), [native validations](results/stage2/native_pilot_validations.json), [Kaggle validations](results/stage2/kaggle_pilot_validations.json), [fallback reviews](results/stage2/kaggle_quality_reviews.json), [projections](results/stage2/cost_projections.csv) and [daily rows](results/stage2/kaggle_validation_daily.csv).

From the project root:

    .\.venv\Scripts\python.exe -m unittest discover -s tests -v
    .\.venv\Scripts\python.exe scripts/check_research_design.py
    .\.venv\Scripts\python.exe scripts/summarize_pilot_costs.py
    .\.venv\Scripts\python.exe scripts/export_stage2_evidence.py
    .\.venv\Scripts\python.exe scripts/verify_notebook.py --notebook notebooks/04_results_analysis.ipynb

All **52 tests** passed. The Stage 1 frozen design and primary-window prior-use uncertainty remain unchanged. Evaluation needs a separate explicit budget/scope decision preserving pilot exposure.
