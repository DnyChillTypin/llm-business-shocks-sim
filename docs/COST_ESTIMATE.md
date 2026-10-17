# Pilot cost evidence — partial, 17 October 2026

The full-suite estimate is **not yet available**. Reasoning pilots completed, but
Consulting stopped on a gateway 503 with unknown usage. Beer, EDT, ICBE, Retail
and genuine Kaggle pilots remain unmeasured. Do not treat missing values as zero
or use the partial subtotal to approve the full study.

| Quantity | Gateway credit |
|---|---:|
| User-approved pilot allowance, at most 250 client attempts | $1.00 |
| Native allocation / later Kaggle validation allocation | $0.75 / $0.25 |
| Known uncached tariff estimate, 21 completed responses | $0.018997480 |
| Provider history cost matched to those 21 responses | $0.017866 |
| Failed request's retained reservation | $0.007690500 |
| Conservative ledger exposure, 22 attempts total | $0.026687980 |

The local ledger uses the higher uncached estimate even when provider history
reports less, including cache discounts. The failed request remains unresolved;
the provider's rounded $19.98 balance and absence of a matching row do not prove
it was unbilled. No paid work continued after this stop. Prior account usage is
excluded from the pilot total. [Request reconciliation](results/stage2/billing_reconciliation.json)
preserves the matching rule and the unresolved request.

## Rates and what the dollar unit means

The [official gateway page](https://shopaikey.com/en) documents the balance/history
interface; the [public tariff endpoint](https://api.shopaikey.com/pricing) supplies
the applicable group rates. The saved snapshot was checked at 10:43:54 UTC with
pricing version `a42d372ccf0b5dd13ecf71203521f9d2`. Rates below take the maximum
across this key's accessible groups; the group ratio is already included.

| Requested model | Input per million tokens | Output per million tokens |
|---|---:|---:|
| gpt-4.1-mini-2025-04-14 | $0.6408 | $2.5632 |
| gpt-4o-mini-2024-07-18 | $0.18 | $0.72 |
| deepseek-v3.2 | $2.40 | $3.60 |

These are USD-formatted gateway credits, not the cash purchase price of credit.
The local estimate is `(input × input rate + output × output rate) / 1,000,000`.
It does not claim independently audited billing or verified upstream identity.
Cached/reasoning token details are preserved in the attempt logs where returned.

## Measured reasoning projections

One frozen case per reasoning dataset was measured. Applying each case's observed
cost and latency to its dataset's full configured count gives:

| Coverage | Low scenario | Base scenario | High scenario | Base serial API time |
|---|---:|---:|---:|---:|
| 507 reasoning cases, including the 50-case Factset extension | $0.333725 | $0.444967 | $0.889933 | 90.1 minutes |
| Consulting, Beer, EDT, ICBE, four Retail configurations, Kaggle | Unmeasured | Unmeasured | Unmeasured | Unmeasured |

Low/base/high are declared **0.75× / 1× / 2× planning assumptions**, not confidence
intervals, empirical bounds or a promise of sufficient funds. One case cannot
measure within-dataset heterogeneity. The time projection sums measured request
latencies and excludes local work, queues, retries and provider drift. In
particular, it does not estimate Retail's 720 days from 720 calls: calls/day and
late context still need measurement. ICBE needs 1,200 decisions with actual
concurrency accounted for; Kaggle needs 252 primary decisions and up to 252
repairs. None has been priced by substituting a scripted or unrelated call.

Per-task evidence and nulls are exported in
[pilot usage](results/stage2/pilot_usage.csv),
[cost scenarios](results/stage2/cost_projections.csv) and
[machine-readable report](results/stage2/pilot_cost_report.json).
Open [notebook 04](../notebooks/04_results_analysis.ipynb) in VS Code and Run All
to inspect genuine outcomes, usage by model and partial projections without
spending. From the project root, regenerate local reports with:

```powershell
.\.venv\Scripts\python.exe scripts/summarize_pilot_costs.py
.\.venv\Scripts\python.exe scripts/verify_notebook.py --notebook notebooks/04_results_analysis.ipynb
```

## Budget decision

Keep the existing $1 pilot approval and its persistent ledger. Resolve the failed
request's charge before resuming. Complete the affordable pilot menu and its
artifact gates, then propose a total cap with native/Kaggle allocations, explicit
treatment of pilot spending and a recommended 20% reserve. No large-run cap is
recommended or requested from the currently partial evidence.
