# Findings draft outline

Target: a concise 5–8-page main LaTeX report plus a short appendix, written for the research lead. Create `report/main.tex`, `report/references.bib`, `report/tables/` and `report/figures/` in Stage 7. No numerical result is implied by this outline. Generate all tables/figures from saved result manifests.

| Section | Content and evidence | Planned generated asset |
|---|---|---|
| Abstract and completion boundary | RQs, actual completed scope, key measured effects and limitations; identify unfinished work | Coverage counts derived from run manifests |
| Research questions | Native capability versus Kaggle performance/behavior/reliability; operational meaning of adaptation | RQ-to-experiment table |
| Data and simulation | Synthetic Kaggle data, training selection, chronology, uncertain prior primary-window use, supplier/price/cost assumptions | Selected-series and date table |
| Methods | Native CoT/ReAct coverage and substitutions; JSON LLM policy, baselines, matched controls, repair/fallback, experimental units | Frozen policy/scenario matrix |
| Native findings | Family-specific scores and denominators; completions/failures; separate Factset extension and EDT qualification | Native coverage and score tables |
| Kaggle findings | Per-block contribution effects, fill rate/stockouts, prices/orders/inventory, matched shock effects and recovery | Business outcome table; control-adjusted effect figure; event-aligned trace with shock window |
| Reliability and cost | First-response/repair validity, fallback, incomplete runs, tokens/latency/USD provenance | Reliability and cost table |
| Robustness | Only completed and explicitly labeled secondary studies; no day-level pseudoreplication | Optional paired sensitivity table |
| Limitations and conclusions | Small selected sample; synthetic/assumed mechanisms; prior-use uncertainty; gateway identity; finite horizon; evidence-proportional implications | Claim-to-artifact mapping in analysis manifest |
| Appendix | Nineteen native task statuses and case manifest reference; exact pins/models; FormulaEval/Factset/EDT/ICBE changes; prompt/config hashes; reproduction instructions | Coverage, attribution and implementation-change tables |

Keep native metrics and Kaggle contribution in distinct tables. Use dataset monetary units for simulated business results and USD only for available API costs. Include all selected scenarios and failures; a partial run must not appear as a full-horizon result. Use “right-censored” for unobserved recovery by day 21. Avoid “statistically significant,” “real-world causal improvement,” pristine unseen claims, or broad model rankings unsupported by the design.

Verify citations against the pinned upstream READMEs/CITATION files and actual papers before writing the bibliography. Use dataset version/checksum metadata and preserve all upstream attribution and terms. The verified local MiKTeX command is documented in `STAGE0_HANDOFF.md`; final PDF compilation and page-by-page visual verification remain Stage 7 work.
