# Stage 6 execution: findings and robustness

## Outcome

Stage 6 is complete on 18 October 2026. The analysis is bound to the pinned Stage 5 evidence (`0af4710`) and the frozen Stage 6 source snapshot. All primary tables were recomputed from saved episode summaries, actions, observations and request journals. The full matched matrix and all fallback outcomes remain included. No new model completion calls were made.

The free baseline-only elasticity sensitivity adds **48 validated episodes / 1,008 policy-days** at assumed elasticities 0.75 and 2.25, alongside 24 reused primary baseline episodes at 1.5. Independent replay and accounting passed for all 72 records. Primary source evidence, the approval allowance and gateway ledger remained unchanged. This sensitivity concerns simulator baseline behavior only.

The implementation adds reusable [metrics](../src/analysis/metrics.py), [robustness checks](../src/analysis/robustness.py), saved-evidence extraction, an independent public checker, a Stage 6 export pipeline and [notebook 08](../notebooks/08_findings_and_robustness.ipynb). The notebook reads public reviewed artifacts and runs without paid calls. All 98 automated tests passed, including 13 new metric and isolation checks. All ten exported figure designs were visually reviewed in PNG form; each paired PDF export is hash-bound to the same generated figure. Labels, units, censoring, all-block visibility and legibility passed review. The public table/figure manifest binds the shipped files by SHA-256.

## Findings

Among nine adaptive-policy shock comparisons, LLM-with-fallback contribution exceeded adaptive contribution in **2** blocks and was lower in **7**. Control-adjusted contribution was positive in **7** and negative in **2**, showing that raw shock rankings and within-policy change versus control differ. Equal-weight control-adjusted means across the three selected blocks were approximately **-310** dataset monetary units for surge, **+453** for decline and **+2,626** for delivery disruption. Each scenario has only three purposively selected series-window blocks; the averages are descriptive.

The LLM operational policy met the frozen recovery rule in **9/9** shock episodes, versus **3/9** adaptive episodes; the six remaining adaptive episodes are right-censored at day 21. Recovery means sustained service and inventory normalization relative to each policy's own control, not return of cumulative profit. Since the LLM control can itself carry high stock, this should not be read as low inventory or cost optimality.

Of **252** LLM decision opportunities, **108 (42.9%)** were valid on the first response, **127** invalid responses were corrected by a successful repair, and **17 (6.7%)** used adaptive fallback. All fallback days remain in the primary outcomes. The **161** invalid raw responses were cash-affordability errors. The 396 physical requests (252 primary plus 144 repairs) cost an estimated **0.252123564 gateway credits**, using token-derived rates rather than independently verified provider billing. Earlier uncertain charges remain in the project's cumulative budget exposure; gateway credits are separate from simulator money.

Before day 8, **9/9** LLM shock/control pairs already had at least one action difference. Action divergence can include independent model variation. Without a frozen-history ablation, these results do not isolate the value of history or establish model-weight learning.

Native benchmark results remain separate by task and unit: 14 validated non-Retail tasks, one retained ICBE validity failure and four deferred Retail tasks. No full ICBE score, imputed Retail result or pooled cross-family accuracy is reported.

## Artifacts and limits

- [Public results, tables and manifest](results/stage6/)
- [Figures (PNG and PDF)](assets/stage6/)
- [Claim-to-artifact map](results/stage6/claim_map.csv)
- [Reusable findings notebook](../notebooks/08_findings_and_robustness.ipynb)
- [Frozen methods and limitations](STAGE6_PREPARATION.md)
The full private analysis manifest, source map and per-episode replay evidence remain in the ignored local `results/analysis/stage6_v1/` bundle.

There are three selected matched blocks, dependent daily observations and one LLM realization per condition. Prior manual use of the primary window is uncertain. The analysis does not support day-level significance tests, population intervals, practical superiority, pristine unseen-data, real-world causal or exact published-model reproduction claims. Native failures, missing aggregates and deferred evaluations remain visible in the source tables. No paid experiments were added.
