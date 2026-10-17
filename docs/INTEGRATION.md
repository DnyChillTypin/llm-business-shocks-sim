# Can LLMs Adapt to Business Shocks?

Notebook-first research using the Kaggle retail dataset and three external
benchmarks. The first working milestone is a **Kaggle-driven RetailBench
adaptation**: real RetailBench machinery, driven by our downloaded CSV.

## Start here in VS Code

```powershell
cd A:\paper\llm-business-shocks-sim
.\.venv\Scripts\python.exe -m pip install -r requirements-research.txt
code .
```

Install Microsoft's Python and Jupyter extensions if needed. Open
`notebooks/01_kaggle_retailbench_integration.ipynb`, choose **Select Kernel →
Python Environments → .venv\Scripts\python.exe**, then run the cells in order.
The notebook finds the project root whether its working directory is the root
or `notebooks`. A fresh kernel is recommended: upstream uses generic module names.

The notebook validates and prepares the CSV, shows which native components are
reused, checks a daily transition, runs the validity tests, and compares two
unpaid rule-based policies across four 21-day scenarios. No API keys or large
RetailBench LFS assets are needed for this milestone. No LLM results exist yet.

## Where things go

| Location | Contents |
|---|---|
| `data/raw/kaggle` | Original CSV, original ZIP, source/version/checksum metadata |
| `data/processed/kaggle_retailbench/pilot` | Selected catalog, chronological episode, past-only history, assumed supplier files, manifest and artifact checksums |
| `src/data` | Validation and Kaggle-to-environment preparation |
| `src/envs` | RetailEnvironment/SKU/Inventory subclasses, demand and delivery-shock integration |
| `src/agents` | Fixed and adaptive policies using native tool dispatch |
| `configs` | Explicit experimental assumptions |
| `notebooks` | Research narrative and runnable analysis |
| `results/runs/kaggle_retailbench` | Separate run sessions; SQLite records, tool logs, action logs, daily ledgers, metadata and summaries |
| `results/figures`, `results/tables` | Figures and tables exported by the notebook |
| `tests` | Integration and research-validity checks |
| `vendor` | Original upstream repositories, not edited by this integration |

Raw CSV/ZIP, processed artifacts, environments, vendor clones, and run outputs
are ignored by the parent Git repository. Dataset metadata, notebooks, our
code, and configuration are trackable. No Git commit or remote is created by
running the notebook.

## What is being adapted

We inherit `RetailEnvironment` and execute its native daily step, order placement,
pricing, inventory sales routine, delivery manager, supplier manager, records
database, and tool dispatch. A SKU subclass supplies Kaggle demand instead of
the native attraction/binomial calculation. This is not a standalone replacement
retail simulator and is not an official RetailBench leaderboard reproduction.

Only initial stock comes from the episode-start CSV row. Later recorded stock,
sales, prices and orders never overwrite agent-generated state. Training dates
set reference prices and series selection. Earlier observations seed demand
history. Future demand stays private to the environment; policy observations
contain past demand and current state only.

The environment's native day-end transition sells today's stock, advances the
date, and receives orders for the next day. A two-day order placed before day-1
sales is available before day-3 sales. End-of-day holding costs are charged
before counting next-day arrivals.

### Explicit deviations and assumptions

- Fix the upstream no-review path **in our Inventory subclass**: upstream only
  removes sold items inside its review branch. Our subclass removes exactly
  reported sales when reviews are disabled; vendor source stays unchanged.
- Disable reviews, returns, news, rent, spoilage and cross-product substitution:
  the Kaggle data does not supply the required inputs.
- Carry stock at purchase cost instead of applying native shelf-life depreciation.
- Use estimated `Demand` as reference-price demand, with assumed elasticity 1.5.
  This is not a causal price model or an exact reconstruction of historical sales.
- One assumed supplier, two-day normal lead time, five during delivery disruption,
  unit cost 60% of reference price, holding cost 0.1% of unit cost per day.
- Initial stock is observed, starting cash is an assumed 20 training-mean days
  of purchasing cost, and capacity is unlimited. Cash and daily order limits apply.
- Customer counts in the calendar are null; no customer footfall is invented.
- Daily requested demand (including unmet demand) is observable after the day.
- Native reset/checkpoint recovery is disabled: create a fresh instance/run folder
  because native serialization does not include the added Kaggle state.

`prepare_dataset(..., store_id="S001")` can prepare all 20 products in that
store. The default notebook uses one series selected by median training demand
variability to validate the integration before expansion.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Checks include actual native reuse, Kaggle demand driving sales, stock depletion
without reviews, stockout demand, delivery timing and disruptions, price response,
past-only observations, repeatability, input checksums, cash/asset reconciliation,
and episode boundaries. The notebook additionally runs the complete baseline
matrix and exports figures. Interpret outputs as simulation checks and baseline
comparisons; they cannot establish LLM adaptation before LLM runs are added.
