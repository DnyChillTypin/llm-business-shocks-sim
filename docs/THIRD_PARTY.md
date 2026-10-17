# Sources and attribution

This repository contains our research adapter, tests, notebooks, and analysis.
External repositories are obtained separately and retain their own licenses.
The project MIT license does not relicense external code or datasets.

## RetailBench: implemented integration

- Source: https://github.com/linghuazhang01/RetailBench
- Pinned commit: `f1d37b35abfa60ef5599e56d2cdbdaa4fd9b8bf3`
- License: MIT; copyright 2026 RetailBench Contributors. The upstream license
  is retained in the downloaded source checkout.
- Authors: Linghua Zhang, Jun Wang, Jingtong Wu, and Zhisong Zhang.
- Paper: *RetailBench: Evaluating Long-Horizon Autonomous Decision-Making and
  Strategy Stability of LLM Agents in Realistic Retail Environments*.
  https://doi.org/10.48550/arXiv.2603.16453

Our subclass adaptation replaces the native demand generator, corrects stock
depletion in the no-review branch, changes inventory valuation, and introduces
explicit supplier/cost/shock assumptions. These changes are in our code; the
upstream checkout remains unmodified. This is not an official leaderboard run.

## Dataset

- Publisher: atomicd on Kaggle.
- Source: https://www.kaggle.com/datasets/atomicd/retail-store-inventory-and-demand-forecasting
- Version: 8; synthetic retail data, not confidential business records.
- CSV checksum and source metadata are recorded in `configs/sources.json` and
  `data/raw/kaggle/dataset_metadata.json`.
- The CSV and ZIP are not redistributed in this repository. Download them from
  Kaggle through the setup script and consult the publisher's current terms.
- Small aggregate results and figures are supplied as a project demonstration.

## Additional benchmark references: execution not yet implemented here

- FirmBench: https://github.com/sduyangmin/FirmBench
  (upstream Apache-2.0 license).
- ICBE strategic-behavior simulator:
  https://github.com/ruxi-stnmr/icbe-2026-strategic-behavior-llms
  (consult the upstream repository for its terms).

These sources inform planned benchmark work. Their presence in the research plan
does not imply that their suites have been reproduced by this project.
