# Measured pilot cost and evaluation proposals

Stage 2 respected the **$2 total / 250-attempt** allowance: **237 attempts**, **$0.849863719 known uncached estimates** plus **$0.019009592 fully held unknown charges**, totaling **$0.868873311 exposure**. Full evaluations are not authorized.

## Rates and accounting

The [official gateway page](https://shopaikey.com/en) documents balance/history; the [public tariff](https://api.shopaikey.com/pricing) supplies rates. Checks before resuming and after the last pilot retained version a42d372ccf0b5dd13ecf71203521f9d2. These are maximum applicable uncached rates across accessible groups, with group ratios already included.

| Requested model | Input / million tokens | Output / million tokens |
|---|---:|---:|
| gpt-4.1-mini-2025-04-14 | $0.6408 | $2.5632 |
| gpt-4o-mini-2024-07-18 | $0.18 | $0.72 |
| deepseek-v3.2 | $2.40 | $3.60 |

Units are **gateway credits**, not the cash price of credit. Local cost is input tokens times input rate plus output tokens times output rate, divided by one million and rounded upward at nanocredit precision. Cache details are retained; uncached rates conservatively overestimate some provider charges.

Detailed billing reconciliation and request telemetry remain in ignored local storage. Public costs are token-derived project estimates and fully held uncertainty, not account balances or individually identified provider charge records.

Limits depend on tariff and gateway token ceilings; they are not provider-enforced quotas or independently audited bills. Original spending, failed runs, allowance amendments and held-charge records remain in the same ledger.

## Full-scope scenarios

| Coverage | Low: 0.75? | Base: 1? | High: 2? |
|---|---:|---:|---:|
| Four Retail configurations ? 180 days | $100.98 | $134.63 | $269.27 |
| Other native benchmarks | $1.30 | $1.73 | $3.47 |
| Kaggle primary matrix | $0.16 | $0.21 | $0.43 |
| **Total evaluation** | **$102.44** | **$136.58** | **$273.16** |

Factors are declared planning assumptions, not empirical bounds or confidence intervals. Base scales successful measured pilots by frozen case/horizon counts. ICBE uses the corrected 4,096-token-ceiling cohort; its failed 150-token cohort counts toward pilot spending only. Kaggle includes repair overhead: 57 requests for 42 decisions project to 342 requests for 252 primary decisions; at most 504 are permitted by the repair rule.

Retail uses measured **19 / 20 / 24 / 22 calls per day**. Base full-run costs are $29.11 dynamic middle, $30.25 dynamic hard, $31.66 still middle and $43.62 still hard. Later context, failures and restarts are unmeasured. Offline phase checks and synthetic payload sizing do not become late-horizon observations. A 2? scenario is not an overrun guarantee.

Base time is approximately **33.0 hours**: 30.2 Retail and 2.8 for remaining experiments. Native one-time initialization is counted once before scaling work. ICBE uses measured paired concurrency; serialized API time is exported separately. Writing and unobserved outages/restarts are excluded. The forecast assumes agents can finish their horizons.

## Next-stage budget decision

**Recommended first-draft route: $6 total gateway credit**, inclusive of pilots, up to 3,000 total client attempts, with at least 20% reserve. It covers the declared high scenario for non-Retail native tasks and the Kaggle primary matrix. Full Retail stays on the longer route without reducing its horizons.

**Full-scope route: $350 total gateway credit**, inclusive of pilots, up to 30,000 attempts, with at least 20% reserve. It rounds the high evaluation scenario plus pilot exposure, divided by 0.8, upward to the next ten credits. Full-scope completion remains open until funded and executed; sources, models and horizons were not reduced to fit $20.

Both proposals are **unapproved**: [first draft](results/stage2/budget_proposal_nonretail_first_draft.json), [full scope](results/stage2/budget_proposal_full_scope.json). Carry the existing ledger's spending and holds forward. Future batches must fit allocations and preserve stops. No evaluations were launched.

Kaggle's three fallback days out of 42 (7.1%) triggered review. The review confirmed material cash-limit errors and correct fallback/accounting behavior, and retains the frozen **LLM with fallback** policy with explicit reliability reporting. Its contribution was below adaptive in both validation scenarios. These inspected pilots are not primary findings or pure unassisted LLM performance.

## Reproduce without spending

Open [notebook 04](../notebooks/04_results_analysis.ipynb) and Run All. Inspect per-task [usage](results/stage2/pilot_usage.csv), [scenarios](results/stage2/cost_projections.csv) and [JSON evidence](results/stage2/pilot_cost_report.json).

    .\.venv\Scripts\python.exe scripts/summarize_pilot_costs.py
    .\.venv\Scripts\python.exe scripts/export_stage2_evidence.py
    .\.venv\Scripts\python.exe scripts/verify_notebook.py --notebook notebooks/04_results_analysis.ipynb
