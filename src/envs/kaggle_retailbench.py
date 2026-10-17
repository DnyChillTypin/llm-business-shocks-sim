"""Kaggle demand connected to real RetailBench inventory, orders, records and tools.

No vendor source is changed. Native attraction demand, reviews/returns, expiry,
and depreciating inventory valuation are explicitly replaced for this adaptation.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor/RetailBench"


def _load_native():
    # Upstream uses generic absolute imports and both 'sku' and 'module.sku'.
    # Reject foreign packages rather than silently binding to another benchmark.
    for name in ("module", "model", "util", "sku", "retail_environment"):
        loaded = sys.modules.get(name)
        if loaded is not None:
            locations = list(getattr(loaded, "__path__", []))
            if getattr(loaded, "__file__", None):
                locations.append(loaded.__file__)
            if locations and any(not Path(p).resolve().is_relative_to(VENDOR) for p in locations):
                raise ImportError(f"Module collision for {name}; use a fresh kernel for RetailBench.")
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    sku_module = importlib.import_module("module.sku")
    sys.modules["sku"] = sku_module
    return importlib.import_module("retail_environment")


native = _load_native()
from module.inventory import Inventory
from module.sku import SKU, Merchandise
from module.supplier_manager import SupplierManager

SCENARIOS = ("control", "demand_surge", "demand_decline", "delivery_disruption")


class KaggleSKU(SKU):
    """Bypass native attraction/binomial demand; inventory still calls get_sales."""
    today_demand = 0

    def compute_attribute_attraction(self, date, external_attraction_rate=0):
        return 0.0

    def compute_attraction(self, currnet_market_skus_ids):
        return 0.0

    def get_sales(self, currnet_market_skus_ids, customer_count=None):
        self.sales = self.today_demand
        return self.sales


class KaggleInventory(Inventory):
    def step(self, *args, **kwargs):
        if kwargs.get("review_manager") is not None or kwargs.get("new_manager") is not None:
            raise ValueError("This adaptation disables reviews, returns and news.")
        result = super().step(*args, **kwargs)
        # Upstream removes sold items only inside `if review_manager:`.
        # With reviews disabled, remove exactly the native reported sales here.
        for sku_id, sold in result[2].items():
            items = list(self.items_by_sku.get(sku_id, []))[:sold]
            for item in items:
                self.remove_item(item)
        return result

    def compute_net_worth(self, current_date=None):
        # No spoilage is modeled: carry inventory at purchase cost, not a
        # fabricated shelf-life depreciation schedule.
        return sum(item.buy_price for items in self.items_by_sku.values() for item in items) + sum(
            item.buy_price for item in self.waiting_items)


class ScenarioSuppliers(SupplierManager):
    def __init__(self, *args, adapter, **kwargs):
        self.adapter = adapter
        super().__init__(*args, **kwargs)

    def get_transport_range(self, supplier_id, sku_id, target_date):
        days = self.adapter.lead_days(target_date)
        return days, days

    def get_sku_date(self, sku_id, target_date):
        entries = super().get_sku_date(sku_id, target_date)
        days = self.adapter.lead_days(target_date)
        return [dict(entry, transport_days_min=days, transport_days_max=days) for entry in entries]


class KaggleRetailEnvironment(native.RetailEnvironment):
    """Native RetailEnvironment with a bounded Kaggle episode and safe tools.

    Construct a fresh instance/run_dir for a new episode. Persisted native
    checkpoints are deliberately unsupported until adapter state is serialized.
    """
    ALLOWED_TOOLS = {
        "place_order", "modify_sku_price", "end_today", "view_current_orders",
        "view_sku_sales_history", "view_current_date_supplier_prices",
        "view_supplier_price_history", "view_inventory", "view_funds_and_date",
        "view_sku_prices", "add_note", "view_notes", "view_business_context",
    }

    def __init__(self, prepared_dir: str | Path, run_dir: str | Path, scenario="control"):
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario: {scenario}")
        self.prepared_dir, self.run_dir = Path(prepared_dir).resolve(), Path(run_dir).resolve()
        self.manifest = json.loads((self.prepared_dir / "manifest.json").read_text(encoding="utf-8"))
        checksums = json.loads((self.prepared_dir / "artifact_checksums.json").read_text())
        for relative, checksum in checksums.items():
            path = (self.prepared_dir / relative).resolve()
            if not path.is_relative_to(self.prepared_dir) or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
                raise ValueError(f"Modified or invalid prepared artifact: {relative}")
        self.scenario, self.settings = scenario, self.manifest["settings"]
        self.start_date = date.fromisoformat(self.manifest["test_start"])
        self.end_date = date.fromisoformat(self.manifest["episode_end"])
        self.catalog = {p["sku_id"]: p for p in self.manifest["catalog"]}
        self._episode = pd.read_csv(self.prepared_dir / "episode.csv", parse_dates=["Date"])
        self._episode["Product ID"] = self._episode["Product ID"].astype(str)
        self._episode = self._episode.set_index(["Date", "Product ID"])
        history = pd.read_csv(self.prepared_dir / "history.csv", parse_dates=["Date"])
        self._history = {sku: [
            {"date": row["Date"].date().isoformat(), "reference_demand": float(row["Demand"])}
            for _, row in history.loc[history["Product ID"].astype(str) == sku].iterrows()
        ] for sku in self.catalog}
        self.ledger = []
        if (self.run_dir / "records/records.db").exists():
            raise FileExistsError("Use a new run directory; reusing a records database would mix episodes.")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        config = {
            "debug": False, "data_dir": str(self.prepared_dir),
            "customer_data_path": str(self.prepared_dir),
            "data_begin_time": self.start_date.strftime("%m/%d/%y"),
            "data_end_time": self.end_date.strftime("%m/%d/%y"),
            "begin_time": self.start_date.strftime("%m/%d/%y"),
            "end_time": self.end_date.strftime("%m/%d/%y"),
            "store_begin_time": self.start_date.strftime("%m/%d/%y"),
            "store_id": self.manifest["store_id"],
            "order_record_dir": str(self.run_dir / "records"),
            "log_dir": str(self.run_dir / "logs"),
            "initial_funds": self.manifest["initial_funds"],
            "everyday_rent": 0.0, "inventory_capacity": None,
            "enable_review": False, "enable_new": False,
            "global_random_seed": 42,
        }
        super().__init__(config)
        self.inventory = KaggleInventory(capacity=None)
        self.supplier_manager = ScenarioSuppliers(
            store_root=str(self.prepared_dir), store_id=self.store_id,
            begin_date=self.start_date, end_date=self.end_date,
            allowed_sku_ids=list(self.catalog), adapter=self)
        for sku_id, product in self.catalog.items():
            for unit in range(product["initial_inventory"]):
                self.inventory.add_item(Merchandise(
                    sku=self.skus_id_map[sku_id], begin_time=self.start_date,
                    expired_time=self.end_date + timedelta(days=365), supplier_id="initial_stock",
                    merch_id=f"initial-{sku_id}-{unit}", quality_score=5, buy_price=product["unit_cost"]))
        (self.run_dir / "run_metadata.json").write_text(json.dumps({
            "scenario": scenario, "manifest": self.manifest,
            "prepared_checksums": checksums,
            "native_components": ["RetailEnvironment.step", "RetailEnvironment.place_order", "RetailEnvironment.modify_sku_price",
                                  "Inventory.step", "OrderManager", "SupplierManager", "RecordManager"],
            "adaptations": ["Kaggle SKU loader and reference-price demand", "No-review inventory depletion fix",
                            "Purchase-cost inventory valuation", "Assumed supplier and delivery shocks",
                            "Bounded observations/actions and holding costs"],
        }, indent=2) + "\n", encoding="utf-8")

    def _load_sku_data(self, store_data_path, store_id=""):
        categories = {}
        for product in self.catalog.values():
            sku = KaggleSKU(sku_id=product["sku_id"], category=product["category"],
                            init_price=product["reference_price"], promotion_day=36500,
                            description={"category": product["category"], "source": "Kaggle synthetic data"})
            sku.set_same_category_skus([])  # No inferred cross-product substitution.
            categories.setdefault(sku.category, []).append(sku)
        return categories

    def _active_shock(self, target_date):
        if isinstance(target_date, str):
            target_date = date.fromisoformat(target_date)
        day = (target_date - self.start_date).days + 1
        return self.settings["shock_start_day"] <= day <= self.settings["shock_end_day"]

    def lead_days(self, target_date):
        return self.settings["disrupted_lead_days"] if (
            self.scenario == "delivery_disruption" and self._active_shock(target_date)
        ) else self.settings["lead_days"]

    @property
    def done(self):
        return self.current_date > self.end_date

    def observe(self):
        return {
            "date": self.current_date.isoformat(), "funds": float(self.funds), "done": self.done,
            "lead_days": self.lead_days(self.current_date),
            "products": {sku: {
                "category": product["category"], "inventory": len(self.inventory.items_by_sku.get(sku, [])),
                "on_order": sum(order.ordered_sku.get(self.skus_id_map[sku], 0) for order in self.order_manager.get_current_orders()),
                "price": self.skus_id_map[sku].price, "reference_price": product["reference_price"],
                "unit_cost": product["unit_cost"], "training_mean_demand": product["training_mean_demand"],
                "max_order_quantity": product["max_order_quantity"],
                "history": [dict(row) for row in self._history[sku][-14:]],
            } for sku, product in self.catalog.items()},
            "price_multipliers": list(self.settings["price_multipliers"]),
            "elasticity_assumption": self.settings["elasticity"],
        }

    def modify_sku_price(self, sku_id, new_price):
        if self.done:
            raise RuntimeError("Episode has ended.")
        if sku_id not in self.catalog or not isinstance(new_price, (int, float)) or isinstance(new_price, bool) or not math.isfinite(new_price):
            raise ValueError("Unknown SKU or invalid price.")
        reference = self.catalog[sku_id]["reference_price"]
        if not any(math.isclose(new_price, reference * multiplier, rel_tol=1e-9) for multiplier in self.settings["price_multipliers"]):
            raise ValueError("Price must use an allowed reference-price multiplier.")
        return super().modify_sku_price(sku_id, new_price)

    def place_order(self, items, supplier_id):
        if self.done:
            raise RuntimeError("Episode has ended.")
        totals = {}
        already_ordered = {sku: sum(order.ordered_sku.get(self.skus_id_map[sku], 0)
                                   for order in self.order_manager.get_current_orders()
                                   if order.created_at == self.current_date) for sku in self.catalog}
        for item in items:
            sku, quantity = item.get("sku_id"), item.get("quantity")
            if sku not in self.catalog or type(quantity) is not int or quantity < 1:
                raise ValueError("Order requires a known SKU and a positive integer quantity.")
            totals[sku] = totals.get(sku, 0) + quantity
        if any(qty + already_ordered[sku] > self.catalog[sku]["max_order_quantity"] for sku, qty in totals.items()):
            raise ValueError("Order exceeds the daily quantity limit.")
        return super().place_order(items, supplier_id)

    def step(self):
        if self.done:
            raise RuntimeError("Episode has ended; future rows cannot be consumed.")
        day = self.current_date
        before = {sku: len(self.inventory.items_by_sku.get(sku, [])) for sku in self.catalog}
        base_demand, requested = {}, {}
        multiplier = 1.0
        if self._active_shock(day):
            if self.scenario == "demand_surge":
                multiplier = self.settings["surge_multiplier"]
            elif self.scenario == "demand_decline":
                multiplier = self.settings["decline_multiplier"]
        arrivals = {sku: sum(order.ordered_sku.get(self.skus_id_map[sku], 0)
                            for order in self.order_manager.get_current_orders()
                            if order.expected_delivery_date <= day + timedelta(days=1)) for sku in self.catalog}
        for sku, product in self.catalog.items():
            base_demand[sku] = float(self._episode.loc[(pd.Timestamp(day), sku), "Demand"])
            price_ratio = self.skus_id_map[sku].price / product["reference_price"]
            requested[sku] = int(math.floor(base_demand[sku] * multiplier * price_ratio ** -self.settings["elasticity"] + 0.5))
            self.skus_id_map[sku].today_demand = requested[sku]
        wrapped = super().step()  # Native sales, funds, supplier records, day advancement and arrivals.
        result = wrapped["result"]
        holding_total = 0.0
        for sku, product in self.catalog.items():
            sold = int(result["sales_by_sku"].get(sku, 0))
            closing = before[sku] - sold
            actual = len(self.inventory.items_by_sku.get(sku, []))
            if sold != min(before[sku], requested[sku]) or actual != closing + arrivals[sku]:
                raise AssertionError("Native inventory/delivery conservation failed.")
            price = self.skus_id_map[sku].price
            holding = closing * product["unit_cost"] * self.settings["holding_cost_ratio"]
            holding_total += holding
            row = {
                "date": day.isoformat(), "sku_id": sku, "scenario": self.scenario,
                "opening_inventory": before[sku], "base_demand": base_demand[sku],
                "demand": requested[sku], "sales": sold, "lost_sales": requested[sku] - sold,
                "closing_inventory": closing, "arrivals_next_day": arrivals[sku],
                "price": price, "revenue": sold * price, "cost_of_goods_sold": sold * product["unit_cost"],
                "holding_cost": holding, "contribution": sold * (price - product["unit_cost"]) - holding,
            }
            self.ledger.append(row)
            self._history[sku].append({"date": day.isoformat(), "reference_demand": requested[sku] * (
                price / product["reference_price"]) ** self.settings["elasticity"]})
            with (self.run_dir / "daily_ledger.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row) + "\n")
        self.funds -= holding_total
        result["insufficient_skus"] = [self.skus_id_map[sku] for sku in self.catalog
                                       if requested[sku] > result["sales_by_sku"].get(sku, 0)]
        result["demand_by_sku"] = requested
        result["unmet_demand_by_sku"] = {sku: requested[sku] - result["sales_by_sku"].get(sku, 0) for sku in self.catalog}
        result.update(funds=self.funds, net_worth=self.inventory.compute_net_worth(self.current_date) + self.funds + sum(
            order.cost for order in self.order_manager.get_current_orders()), holding_cost=holding_total)
        return self._wrap_tool_result(result, self._format_step_result(result))

    def get_tools(self):
        tools = {name: tool for name, tool in super().get_tools().items() if name in self.ALLOWED_TOOLS}
        tools["view_business_context"] = {
            "name": "view_business_context", "description": "Current state and past demand only; no future scenario information.",
            "input_schema": {"type": "object", "properties": {}},
            "parameters": {"type": "object", "properties": {}},
        }
        return tools

    def exec_tools(self, tool_name, **kwargs):
        if tool_name not in self.ALLOWED_TOOLS:
            raise ValueError(f"Tool unavailable in the Kaggle adaptation: {tool_name}")
        if tool_name == "view_business_context":
            observation = self.observe()
            return self._wrap_tool_result(observation, json.dumps(observation, indent=2))
        return super().exec_tools(tool_name, **kwargs)

    def reset(self):
        raise NotImplementedError("Construct a new adapter with a fresh run_dir for each episode.")

    def save_checkpoint(self, checkpoint_path):
        raise NotImplementedError("Native checkpoints omit Kaggle state; use a fresh complete run.")

    @classmethod
    def recover_from_checkpoint(cls, checkpoint_path):
        raise NotImplementedError("Native checkpoints do not serialize this adapter.")
