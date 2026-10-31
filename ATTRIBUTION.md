# Third party sources and adaptations

The project implementation is MIT licensed. This license does not relicense
external software or datasets. Upstream checkouts are downloaded separately into
ignored `vendor/` directories and retain their license files. Source URLs and
commit pins are recorded in `configs/sources.json`.

| Source | Pinned version | Use |
|---|---|---|
| [RetailBench](https://github.com/linghuazhang01/RetailBench) | `f1d37b35abfa60ef5599e56d2cdbdaa4fd9b8bf3` | Retail simulation machinery; upstream MIT license |
| [FirmBench](https://github.com/sduyangmin/FirmBench) | `fe0edb02bfa298c0f407468255e2dbdf73f4b65b` | Native agents and processors; upstream Apache-2.0 license |
| [ICBE](https://github.com/ruxi-stnmr/icbe-2026-strategic-behavior-llms) | `ad29de11a0161cf6503516edc7d37f5104d22259` | Strategic-behavior game logic; consult upstream terms |
| [Retail Store Inventory and Demand Forecasting](https://www.kaggle.com/datasets/atomicd/retail-store-inventory-and-demand-forecasting) | Kaggle version 8, publisher `atomicd` | Synthetic retail data downloaded by setup; consult publisher terms |

The dataset CSV SHA-256 is
`96f107b42042d5b21fcae88c7dfc98aab036788aaae73fb3605546cfc06135ff`.
The CSV and ZIP are excluded from Git; saved provenance is in
`data/raw/kaggle/dataset_metadata.json`.

The retail adapter replaces native demand, corrects stock depletion when reviews
are disabled, values inventory at purchase cost, and introduces supplier, cost
and shock assumptions. Its 21-day daily JSON policy differs from the native
long-horizon tool-use benchmark. Upstream checkouts remain unmodified.

FirmBench integration includes a Windows-compatible FormulaEval subprocess
timeout, a separate Factset processor extension, and the BPTK ABM path for EDT.
ICBE transport recovery requires exact saved requests and retains invalid outputs
as failures. Substituted models and these adaptations mean this study is not an
exact reproduction of upstream scores. Research references are retained in
`report/references.bib`.
