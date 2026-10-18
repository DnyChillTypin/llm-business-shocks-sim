# Release attribution and compatibility

Reviewed on 18 October 2026. This is the current release addendum to
[the original source notes](THIRD_PARTY.md) and [benchmark setup](BENCHMARKS.md).
Those documents are frozen report inputs; their historical execution-status
statements do not supersede the current coverage below. The project's MIT license
applies to its own implementation, not external code or data.

## Sources and citation checks

| Source | Version actually used | Attribution and release treatment |
|---|---|---|
| [RetailBench source](https://github.com/linghuazhang01/RetailBench/tree/f1d37b35abfa60ef5599e56d2cdbdaa4fd9b8bf3) | `f1d37b35abfa60ef5599e56d2cdbdaa4fd9b8bf3` | Pinned LICENSE is MIT, copyright 2026 RetailBench Contributors. Kept in the downloaded checkout; no upstream code is vendored into Git |
| [FirmBench / EnterpriseBench](https://github.com/sduyangmin/FirmBench/tree/fe0edb02bfa298c0f407468255e2dbdf73f4b65b) | `fe0edb02bfa298c0f407468255e2dbdf73f4b65b` | Pinned LICENSE.txt is Apache-2.0. README heading is EnterpriseBench and its paper BibTeX block is empty; cite the software without inventing paper metadata |
| [ICBE simulator](https://github.com/ruxi-stnmr/icbe-2026-strategic-behavior-llms/tree/ad29de11a0161cf6503516edc7d37f5104d22259) | `ad29de11a0161cf6503516edc7d37f5104d22259` | No license file or formal paper citation was found in the pinned tree. Cite the repository and obtain it separately; no upstream source is redistributed |
| [Retail Store Inventory and Demand Forecasting](https://www.kaggle.com/datasets/atomicd/retail-store-inventory-and-demand-forecasting) | Kaggle version 8; publisher handle atomicd | Synthetic data; CSV SHA-256 `96f107b42042d5b21fcae88c7dfc98aab036788aaae73fb3605546cfc06135ff`. Publish aggregates and download instructions, not the CSV/ZIP |

The [RetailBench paper's v3 record](https://arxiv.org/abs/2603.16453v3) confirms
its title, Linghua Zhang/Jun Wang/Jingtong Wu/Zhisong Zhang author list and DOI.
The paper is cited separately from the fork/commit actually used; the pinned
CITATION.cff's repository-code URL points to Ice-Moon-28 rather than the frozen fork.
The [CoT v6](https://arxiv.org/abs/2201.11903v6) and
[ReAct v3](https://arxiv.org/abs/2210.03629v3) metadata also match the bibliography.
They provide method background, not additional experimental results for this project.
The seven report references remain unchanged and are bound to the
[Stage 7 citation register](results/stage7/citation_register.json).

The [public Kaggle metadata endpoint](https://www.kaggle.com/api/v1/datasets/view/atomicd/retail-store-inventory-and-demand-forecasting)
was rechecked during Stage 8: version 8, display name Wavelet and licenseName
Apache 2.0. The original saved metadata has an empty licenses array. These are
separate observations; the frozen record was not rewritten. Attribution uses the
stable atomicd publisher handle. This metadata observation does not relicense any
individual external benchmark case dataset.

## Adaptations, substitutions and actual coverage

- The Kaggle environment reuses RetailBench machinery but replaces demand, corrects
  stock depletion in the disabled-review branch, values inventory at purchase cost,
  and adds explicit supplier/cost/shock assumptions. Native tool-use environments
  and the daily JSON shock policy are separate evaluations.
- FormulaEval uses a Windows-compatible subprocess timeout helper while retaining
  native test assembly and scoring tolerance. Both the timeout test and the full
  suite passed in the fresh Windows environment; Linux CI is reported separately.
- Factset is a 50-case local processor extension, separate from 457 supported
  reasoning cases. Its binary decision scoring uses the local numeric-span scorer
  and removes provenance hints. The finer task's 146/200 correct entity labels and
  22/50 exact cases have different denominators.
- Consulting retains the earliest fully evidenced complete independent session
  for each frozen case: eight recovered cases and two fresh cases. Its 8.15 mean
  judge score is not pooled with other task families; failed charges remain included.
- BeerGame has two full 25-week scenarios. Extreme upstream chain cost is preserved;
  the upstream backlog field is a terminal proxy, with separately derived time means.
  EDT uses the native BPTK ABM path for one scenario decision and 96 simulation steps,
  not 96 independent LLM decisions. Missing upstream metrics are not imputed.
- ICBE reconstructed transport-interrupted state only with exact saved requests.
  Its later invalid DeepSeek response at the 4,096-token output ceiling was retained
  after 177/600 valid rounds. There is no replacement decision or complete tournament
  score. Four full native Retail configurations remain deferred.

The requested candidate is `gpt-4.1-mini-2025-04-14`; native interviewer/judge uses
`gpt-4o-mini-2024-07-18`, with `deepseek-v3.2` also requested in ICBE. ShopAIKey is
the gateway. Model identifiers and compatibility paths are documented, but model
weights are not independently verified. These are substituted-model evaluations
and a local adaptation, not exact published-score reproductions.

The [coverage table](results/stage6/native_task_coverage.csv) reports all 19 tasks:
14 validated, one failed and four deferred. Native capability scores do not prove
adaptation to business shocks and are not combined into a single ranking.

## Public and private material

Git contains project code, notebooks, small aggregate/trace exports, generated
charts/tables and the report source/PDF. Raw Kaggle archives, vendor checkouts,
native case contents, conversations, per-request identifiers, approved private
allowances, the cumulative ledger and account details stay excluded. Existing
licenses remain in downloaded source trees. The
[reproduction guide](REPRODUCIBILITY.md) describes what can be reproduced publicly
and what requires the original private evidence.
