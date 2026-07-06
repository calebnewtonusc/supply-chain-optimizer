"""
Synthetic procurement data generator.

Produces two CSV files used by the rest of the pipeline:

    data/suppliers.csv        ~40 suppliers across hardware categories
    data/purchase_orders.csv  ~5,000 purchase orders over 24 months

The data is deliberately seeded with signal, not noise. A handful of
suppliers are engineered to tell specific business stories that the
downstream analytics are meant to surface:

    - single-source suppliers carrying a large share of a category's spend
      (concentration risk that warrants a dual-source)
    - suppliers with high lead-time variance (unpredictable delivery)
    - suppliers with a rising defect rate over time (quality drift)
    - suppliers that are chronically late (schedule risk)

The RNG is seeded so every run reproduces the same dataset.
"""

import csv
import os
from datetime import date, timedelta

import numpy as np

SEED = 42
rng = np.random.default_rng(SEED)

DATA_DIR = os.path.dirname(os.path.abspath(__file__))

# 24 month window ending at a fixed date for reproducibility.
WINDOW_END = date(2026, 6, 30)
WINDOW_START = date(2024, 7, 1)
WINDOW_DAYS = (WINDOW_END - WINDOW_START).days

CATEGORIES = [
    "Avionics",
    "Propulsion Components",
    "Raw Metals",
    "Fasteners",
    "Composites",
    "Electronics",
    "Machined Parts",
]

REGIONS = {
    "North America": ["United States", "Mexico", "Canada"],
    "Europe": ["Germany", "France", "United Kingdom", "Italy"],
    "Asia": ["Japan", "South Korea", "Taiwan"],
}

# Category level typical unit cost bands (USD) used as a base for pricing.
CATEGORY_UNIT_COST = {
    "Avionics": (2200.0, 9000.0),
    "Propulsion Components": (4000.0, 18000.0),
    "Raw Metals": (12.0, 90.0),
    "Fasteners": (0.4, 6.0),
    "Composites": (300.0, 1800.0),
    "Electronics": (40.0, 900.0),
    "Machined Parts": (60.0, 1200.0),
}

SUPPLIER_PREFIXES = [
    "Apex", "Vanguard", "Titan", "Orbital", "Meridian", "Cascade", "Ironclad",
    "Sterling", "Precision", "Summit", "Keystone", "Halcyon", "Nova", "Redwood",
    "Anvil", "Beacon", "Cobalt", "Delta", "Everest", "Forge", "Granite",
    "Helios", "Ionic", "Juniper", "Kestrel", "Lumen", "Magnus", "Northwind",
    "Onyx", "Pinnacle", "Quantum", "Ridgeline", "Sable", "Trident", "Umbra",
    "Vertex", "Westgate", "Yardley", "Zenith", "Ascend",
]

SUPPLIER_SUFFIXES = [
    "Aerospace", "Industries", "Manufacturing", "Systems", "Metals",
    "Components", "Fabrication", "Technologies", "Precision Works", "Dynamics",
]


def build_suppliers(n_suppliers=40):
    """Create the supplier master with baked-in risk profiles."""
    suppliers = []
    used_names = set()
    region_names = list(REGIONS.keys())

    for i in range(n_suppliers):
        supplier_id = f"SUP-{i + 1:03d}"

        # Ensure unique readable names.
        while True:
            prefix = SUPPLIER_PREFIXES[i % len(SUPPLIER_PREFIXES)]
            suffix = str(rng.choice(SUPPLIER_SUFFIXES))
            name = f"{prefix} {suffix}"
            if name not in used_names:
                used_names.add(name)
                break

        category = str(rng.choice(CATEGORIES))
        region = str(rng.choice(region_names))
        country = str(rng.choice(REGIONS[region]))

        # Onboarding sometime in the last 6 years.
        onboard_offset = int(rng.integers(180, 2200))
        onboarding_date = WINDOW_END - timedelta(days=onboard_offset)

        suppliers.append(
            {
                "supplier_id": supplier_id,
                "name": name,
                "category": category,
                "region": region,
                "country": country,
                "is_dual_sourced": 0,  # set later based on category coverage
                "onboarding_date": onboarding_date.isoformat(),
            }
        )

    return suppliers


def assign_risk_profiles(suppliers):
    """
    Attach hidden generation parameters to each supplier that drive the
    behaviour of its purchase orders. These parameters are not written to
    the CSV. They only shape the sampled order records so the analytics
    have real underlying structure to detect.
    """
    profiles = {}
    for s in suppliers:
        cost_low, cost_high = CATEGORY_UNIT_COST[s["category"]]
        base_cost = float(rng.uniform(cost_low, cost_high))

        profiles[s["supplier_id"]] = {
            "base_unit_cost": base_cost,
            "orders_weight": float(rng.uniform(0.5, 1.5)),
            "lead_time_mean": float(rng.uniform(28, 55)),
            "lead_time_cv": float(rng.uniform(0.08, 0.20)),
            "base_defect_ppm": float(rng.uniform(200, 2500)),
            "defect_trend": 0.0,          # ppm added per month, default flat
            "base_on_time": float(rng.uniform(0.90, 0.98)),
            "on_time_trend": 0.0,         # change per month
        }

    # Story 1: concentration risk. A few single-source suppliers carry an
    # outsized share of spend by ordering large, expensive, frequent POs.
    for sid in ["SUP-003", "SUP-011", "SUP-025"]:
        profiles[sid]["orders_weight"] = 4.5
        profiles[sid]["base_unit_cost"] *= 1.15

    # Story 2: lead-time variance. Delivery timing is unpredictable.
    for sid in ["SUP-007", "SUP-019"]:
        profiles[sid]["lead_time_mean"] = 62.0
        profiles[sid]["lead_time_cv"] = 0.55

    # Story 3: rising defect rate. Quality drifts upward over the window.
    for sid in ["SUP-014", "SUP-022"]:
        profiles[sid]["base_defect_ppm"] = 3000.0
        profiles[sid]["defect_trend"] = 950.0

    # Story 4: chronic lateness. On-time performance is poor and worsening.
    for sid in ["SUP-009", "SUP-031"]:
        profiles[sid]["base_on_time"] = 0.78
        profiles[sid]["on_time_trend"] = -0.003

    return profiles


def set_dual_source_flags(suppliers):
    """
    Mark a supplier as dual-sourced when its category has more than one
    active supplier. Categories served by a single supplier are left as
    single-source so the scorecard can flag concentration.
    """
    by_category = {}
    for s in suppliers:
        by_category.setdefault(s["category"], []).append(s)

    for category, group in by_category.items():
        if len(group) > 1:
            # Roughly two thirds of suppliers in multi-supplier categories
            # are covered by a qualified alternate.
            for s in group:
                s["is_dual_sourced"] = 1 if rng.random() < 0.66 else 0
        else:
            for s in group:
                s["is_dual_sourced"] = 0

    # The engineered concentration-risk suppliers must remain single-source
    # so the story holds regardless of category coverage.
    single_source_ids = {"SUP-003", "SUP-011", "SUP-025"}
    for s in suppliers:
        if s["supplier_id"] in single_source_ids:
            s["is_dual_sourced"] = 0


def months_between(start, current):
    """Whole months elapsed from start to current (used for trends)."""
    return (current.year - start.year) * 12 + (current.month - start.month)


def build_purchase_orders(suppliers, profiles, target_orders=5000):
    """Sample individual purchase orders driven by supplier profiles."""
    orders = []

    # Weight how many orders each supplier gets by its orders_weight.
    weights = np.array([profiles[s["supplier_id"]]["orders_weight"] for s in suppliers])
    weights = weights / weights.sum()
    counts = rng.multinomial(target_orders, weights)

    po_counter = 1
    for supplier, n_orders in zip(suppliers, counts):
        sid = supplier["supplier_id"]
        p = profiles[sid]
        category = supplier["category"]

        for _ in range(int(n_orders)):
            # Order date uniformly across the window.
            order_offset = int(rng.integers(0, WINDOW_DAYS))
            order_date = WINDOW_START + timedelta(days=order_offset)
            month_idx = months_between(WINDOW_START, order_date)

            # Reliable suppliers quote a promised lead time with a small
            # buffer over their mean, so they usually land on or before it.
            # Chronically late suppliers (low base_on_time) quote an
            # optimistic promise they routinely miss.
            # Buffer is bounded so even the least reliable suppliers promise
            # a schedule they miss often but not implausibly (they would be
            # disqualified otherwise). The band keeps on-time rates realistic.
            buffer_frac = float(np.clip(p["base_on_time"] - 0.85, -0.06, 0.06))
            buffer_days = p["lead_time_mean"] * buffer_frac
            promised_lead = max(7, int(round(p["lead_time_mean"] + buffer_days)))
            # A drift toward tighter promises models a degrading supplier.
            promised_lead = max(
                7, promised_lead + int(round(p["on_time_trend"] * month_idx * p["lead_time_mean"]))
            )
            promised_date = order_date + timedelta(days=promised_lead)

            # Actual lead time varies around the mean by the supplier's CV.
            actual_lead = rng.normal(
                p["lead_time_mean"], p["lead_time_mean"] * p["lead_time_cv"]
            )
            actual_lead = max(3, int(round(actual_lead)))
            received_date = order_date + timedelta(days=actual_lead)

            # On-time is a direct fact of the record: received on or before
            # the promised date. The promise buffer above is what encodes
            # each supplier's reliability profile.
            on_time = 1 if received_date <= promised_date else 0

            # Quantity scales loosely with unit cost band (cheap parts ship
            # in bulk, expensive assemblies ship in small lots).
            if p["base_unit_cost"] < 10:
                quantity = int(rng.integers(500, 8000))
            elif p["base_unit_cost"] < 200:
                quantity = int(rng.integers(50, 1200))
            elif p["base_unit_cost"] < 2000:
                quantity = int(rng.integers(5, 150))
            else:
                quantity = int(rng.integers(1, 25))

            # Unit cost jitters around the supplier base cost.
            unit_cost = round(float(p["base_unit_cost"]) * float(rng.uniform(0.94, 1.08)), 2)
            total_cost = round(unit_cost * quantity, 2)

            # Defect rate drifts upward for suppliers with a quality trend.
            defect_ppm = p["base_defect_ppm"] + p["defect_trend"] * month_idx
            defect_ppm = max(0.0, defect_ppm)
            defect_rate = defect_ppm / 1_000_000.0
            defect_units = int(rng.binomial(quantity, min(defect_rate, 0.25)))

            orders.append(
                {
                    "po_id": f"PO-{po_counter:06d}",
                    "supplier_id": sid,
                    "category": category,
                    "order_date": order_date.isoformat(),
                    "promised_date": promised_date.isoformat(),
                    "received_date": received_date.isoformat(),
                    "quantity": quantity,
                    "unit_cost": unit_cost,
                    "total_cost": total_cost,
                    "defect_units": defect_units,
                    "on_time": on_time,
                }
            )
            po_counter += 1

    # Sort by order date so the file reads chronologically.
    orders.sort(key=lambda o: o["order_date"])
    return orders


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    suppliers = build_suppliers(n_suppliers=40)
    profiles = assign_risk_profiles(suppliers)
    set_dual_source_flags(suppliers)
    orders = build_purchase_orders(suppliers, profiles, target_orders=5000)

    suppliers_path = os.path.join(DATA_DIR, "suppliers.csv")
    orders_path = os.path.join(DATA_DIR, "purchase_orders.csv")

    write_csv(
        suppliers_path,
        suppliers,
        [
            "supplier_id",
            "name",
            "category",
            "region",
            "country",
            "is_dual_sourced",
            "onboarding_date",
        ],
    )
    write_csv(
        orders_path,
        orders,
        [
            "po_id",
            "supplier_id",
            "category",
            "order_date",
            "promised_date",
            "received_date",
            "quantity",
            "unit_cost",
            "total_cost",
            "defect_units",
            "on_time",
        ],
    )

    total_spend = sum(o["total_cost"] for o in orders)
    print(f"Wrote {len(suppliers)} suppliers to {suppliers_path}")
    print(f"Wrote {len(orders)} purchase orders to {orders_path}")
    print(f"Total spend across window: ${total_spend:,.0f}")


if __name__ == "__main__":
    main()
