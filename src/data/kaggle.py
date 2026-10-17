"""Prepare Kaggle inputs for a RetailBench adaptation, never modifying raw data."""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PROJECT_ROOT / "configs/kaggle_retailbench.json"


def load_sales(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"Store ID": str, "Product ID": str})
    required = {"Date", "Store ID", "Product ID", "Category", "Demand", "Price",
                "Inventory Level", "Units Sold", "Units Ordered"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Missing columns: {sorted(required - set(frame.columns))}")
    if frame.empty or frame[list(required)].isna().any().any():
        raise ValueError("Required fields must be nonempty and nonmissing.")
    frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
    if frame.duplicated(["Date", "Store ID", "Product ID"]).any():
        raise ValueError("Duplicate store/product/date records.")
    for column in ["Demand", "Price", "Inventory Level", "Units Sold", "Units Ordered"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
        if not np.isfinite(frame[column]).all() or (frame[column] < 0).any():
            raise ValueError(f"{column} must be finite and nonnegative.")
    if (frame["Price"] <= 0).any():
        raise ValueError("Prices must be positive.")
    if (frame["Inventory Level"] % 1 != 0).any():
        raise ValueError("Initial inventories must be whole units.")
    if frame.groupby(["Store ID", "Product ID"])["Category"].nunique().max() != 1:
        raise ValueError("A product changes category within a store.")
    return frame.sort_values(["Date", "Store ID", "Product ID"]).reset_index(drop=True)


def prepare_dataset(raw_path: str | Path, output_dir: str | Path,
                    config_path: str | Path = DEFAULT_CONFIG, *,
                    store_id: str | None = None,
                    product_ids: list[str] | None = None,
                    episode_start: str | None = None) -> dict:
    """Select on training dates only; export a full store or a single pilot SKU.

    With no selection, use the upper-median training demand-CV series. Passing
    store_id with product_ids=None selects all products in that store.
    """
    raw_path, output_dir = Path(raw_path).resolve(), Path(output_dir).resolve()
    if output_dir == raw_path.parent or raw_path.parent in output_dir.parents:
        raise ValueError("Processed artifacts must not be written into the raw-data directory.")
    settings = json.loads(Path(config_path).read_text(encoding="utf-8"))
    train_fraction = settings["train_fraction"]
    validation_fraction = settings["validation_fraction"]
    if not (0 < train_fraction < 1 and 0 < validation_fraction < 1 - train_fraction):
        raise ValueError("Invalid chronological split fractions.")
    for name in ["horizon", "lead_days", "disrupted_lead_days"]:
        if not isinstance(settings[name], int) or isinstance(settings[name], bool) or settings[name] < 1:
            raise ValueError(f"{name} must be a positive integer.")
    for name in ["elasticity", "purchase_cost_ratio", "holding_cost_ratio", "max_order_days", "initial_cash_days"]:
        if not math.isfinite(settings[name]) or settings[name] < 0:
            raise ValueError(f"Invalid setting: {name}")
    if settings["purchase_cost_ratio"] == 0 or settings["max_order_days"] == 0:
        raise ValueError("Purchase cost and maximum order must be positive.")
    if not (1 <= settings["shock_start_day"] <= settings["shock_end_day"] <= settings["horizon"]):
        raise ValueError("Shock window must lie within the episode.")
    if any(not math.isfinite(p) or p <= 0 for p in settings["price_multipliers"]):
        raise ValueError("Price multipliers must be finite and positive.")
    frame = load_sales(raw_path)
    dates = pd.DatetimeIndex(frame["Date"].unique()).sort_values()
    train_count = int(len(dates) * train_fraction)
    test_index = train_count + int(len(dates) * validation_fraction)
    if train_count < 14 or test_index + settings["horizon"] > len(dates):
        raise ValueError("Insufficient chronological history or test dates.")
    train_end, test_start = dates[train_count - 1], dates[test_index]
    split_test_index = test_index
    if episode_start is not None:
        requested = pd.Timestamp(episode_start)
        if requested not in dates or requested < dates[train_count]:
            raise ValueError("Episode must start on a known validation/test date.")
        test_index = dates.get_loc(requested)
        if test_index + settings["horizon"] > len(dates):
            raise ValueError("Episode exceeds available dates.")
        test_start = dates[test_index]
    train = frame.loc[frame["Date"] <= train_end]
    statistics = train.groupby(["Store ID", "Product ID"])["Demand"].agg(["mean", "std"])
    statistics = statistics.loc[statistics["mean"] > 0].copy()
    statistics["cv"] = statistics["std"] / statistics["mean"]
    ranked = statistics.reset_index().sort_values(["cv", "Store ID", "Product ID"])
    if ranked.empty:
        raise ValueError("No positive-demand training series.")
    if store_id is None:
        if product_ids is not None:
            raise ValueError("Specify store_id when selecting products.")
        chosen = ranked.iloc[len(ranked) // 2]
        store_id, product_ids = str(chosen["Store ID"]), [str(chosen["Product ID"])]
        selection = "Upper-median training demand coefficient of variation; ties by store/product ID."
    else:
        selection = "Explicit store/product selection."
    selected = frame.loc[frame["Store ID"] == store_id].copy()
    if product_ids is not None:
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("Duplicate product selection.")
        selected = selected.loc[selected["Product ID"].isin(product_ids)]
        if set(selected["Product ID"]) != set(product_ids):
            raise ValueError("Unknown product selection.")
    if selected.empty:
        raise ValueError("Unknown or empty store selection.")
    episode_dates = dates[test_index:test_index + settings["horizon"]]
    expected_dates = pd.date_range(episode_dates[0], episode_dates[-1], freq="D")
    if not episode_dates.equals(expected_dates):
        raise ValueError("Pilot requires consecutive daily test dates.")
    episode = selected.loc[selected["Date"].isin(episode_dates)].copy()
    catalog = []
    for product_id, group in selected.groupby("Product ID", sort=True):
        if not pd.DatetimeIndex(group["Date"]).equals(dates):
            raise ValueError(f"Incomplete daily coverage for {product_id}.")
        training = group.loc[group["Date"] <= train_end]
        mean = float(training["Demand"].mean())
        if mean <= 0:
            raise ValueError(f"Zero training demand for {product_id}.")
        reference_price = float(training["Price"].median())
        initial = group.loc[group["Date"] == test_start].iloc[0]
        catalog.append({
            "sku_id": str(product_id), "category": str(training["Category"].iloc[0]),
            "reference_price": reference_price, "training_mean_demand": mean,
            "unit_cost": reference_price * settings["purchase_cost_ratio"],
            "initial_inventory": int(initial["Inventory Level"]),
            "max_order_quantity": int(math.ceil(mean * settings["max_order_days"])),
        })
    history = selected.loc[selected["Date"] < test_start].groupby("Product ID", group_keys=False).tail(14)
    vendor = PROJECT_ROOT / "vendor/RetailBench"
    commit = subprocess.run(["git", "-C", str(vendor), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    manifest = {
        "schema_version": 1, "study_type": "Kaggle-driven RetailBench adaptation, not a native benchmark reproduction",
        "source_url": "https://www.kaggle.com/datasets/atomicd/retail-store-inventory-and-demand-forecasting",
        "raw_sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "retailbench_commit": commit, "store_id": store_id, "selection": selection,
        "source_rows": len(frame), "source_series": frame.groupby(["Store ID", "Product ID"]).ngroups,
        "train_end": train_end.date().isoformat(),
        "validation_start": dates[train_count].date().isoformat(),
        "validation_end": dates[split_test_index - 1].date().isoformat(),
        "test_start": test_start.date().isoformat(), "episode_end": episode_dates[-1].date().isoformat(),
        "settings": settings, "catalog": catalog,
        "initial_funds": sum(p["training_mean_demand"] * p["unit_cost"] * settings["initial_cash_days"] for p in catalog),
        "assumptions": [
            "Synthetic estimated Demand is treated as reference-price demand, not causal ground truth.",
            "Only episode-start Inventory Level initializes stock; future recorded stock/sales/orders never overwrite simulated outcomes.",
            "Reference prices and demand means use training data only; initial inventory is observed at episode start.",
            "Supplier cost, lead time, holding cost and elasticity are assumptions; monetary units are unspecified.",
            "One assumed supplier; unlimited capacity; no reviews, returns, news, substitution, rent or spoilage.",
            "Daily unmet demand is observable after the day ends; future demand and shock schedules are hidden from policies.",
            "Calendar customer counts are null: no customer traffic is inferred or fabricated.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    episode.to_csv(output_dir / "episode.csv", index=False, date_format="%Y-%m-%d")
    history.to_csv(output_dir / "history.csv", index=False, date_format="%Y-%m-%d")
    # Native CustomerManager is retained only as a calendar, not a demand source.
    store_dir = output_dir / store_id
    store_dir.mkdir(exist_ok=True)
    (store_dir / "data.json").write_text(json.dumps([
        {"date": day.strftime("%m/%d/%y"), "custcoun": None} for day in episode_dates
    ]), encoding="utf-8")
    for product in catalog:
        suppliers = {"assumed_supplier": [
            {"date": day.date().isoformat(), "upc": product["sku_id"], "category": product["category"],
             "supplier_price": product["unit_cost"], "transport_days_min": settings["lead_days"],
             "transport_days_max": settings["lead_days"], "quality_score": 5}
            for day in episode_dates
        ]}
        (store_dir / f"{product['sku_id']}_suppliers.json").write_text(json.dumps(suppliers), encoding="utf-8")
    artifacts = [p for p in output_dir.rglob("*") if p.is_file() and p.name != "artifact_checksums.json"]
    (output_dir / "artifact_checksums.json").write_text(json.dumps({
        p.relative_to(output_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(artifacts)
    }, indent=2) + "\n", encoding="utf-8")
    return manifest
