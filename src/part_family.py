"""
Part-family risk segmentation.

Category is treated as part family (Avionics, Propulsion Components,
Fasteners, Composites, Electronics, Machined Parts, Raw Metals). This module
rolls the supplier-level scorecard up to the family level so an ops lead can
see, at a glance, which commodity areas carry the most risk and what to do
about each one.

Per family it reports:

    - family spend and share of total spend
    - supplier count and sole-source share (spend with no qualified alternate)
    - average on-time rate and defect PPM
    - a family risk tier (High / Medium / Low) from the spend-weighted mean of
      its suppliers' risk scores
    - the top risk driver (the dimension pushing the family's risk highest)
    - a recommended action tied to that driver

Writes output/part_family_segmentation.csv and prints the segmentation.
"""

import os
import sqlite3

import numpy as np
import pandas as pd

from supplier_scorecard import compute_scores, load_supplier_metrics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "procurement.db")
OUTPUT_DIR = os.path.join(ROOT, "output")


def family_tier(score):
    if score >= 45:
        return "High"
    if score >= 28:
        return "Medium"
    return "Low"


# Map the dominant risk driver to a concrete recommended action.
DRIVER_ACTIONS = {
    "Sole-source exposure": "Qualify a second source for the sole-source spend in this family",
    "Spend concentration": "Consolidate volume and renegotiate on the leading supplier",
    "Defect rate": "Open supplier quality corrective action on the top defect drivers",
    "Lead-time variance": "Add delivery buffers and set lead-time SLAs with the variable suppliers",
    "On-time delivery": "Put chronic-late suppliers on a delivery improvement plan",
    "Late-order risk": "Reduce expedite exposure by re-timing releases on late suppliers",
}


def build_segmentation(scored):
    """Aggregate the scored supplier table up to part-family level."""
    total_spend = scored["total_spend"].sum()
    rows = []

    for family, g in scored.groupby("category"):
        family_spend = g["total_spend"].sum()
        sole_source_spend = g["sole_source_exposure_usd"].sum()

        # Spend-weighted average risk score is the family's headline risk.
        weighted_risk = float(np.average(g["risk_score"], weights=g["total_spend"]))

        # Spend-weighted operational metrics for context.
        weighted_on_time = float(np.average(g["on_time_pct"], weights=g["total_spend"]))
        weighted_ppm = float(np.average(g["defect_ppm"], weights=g["total_spend"]))

        # The top risk driver is the normalized dimension with the highest
        # spend-weighted mean across the family's suppliers.
        drivers = {
            "Spend concentration": np.average(g["n_concentration"], weights=g["total_spend"]),
            "Sole-source exposure": np.average(g["n_sole_source"], weights=g["total_spend"]),
            "Defect rate": np.average(g["n_defect_ppm"], weights=g["total_spend"]),
            "Lead-time variance": np.average(g["n_lead_time_cv"], weights=g["total_spend"]),
            "On-time delivery": np.average(g["n_on_time"], weights=g["total_spend"]),
            "Late-order risk": np.average(g["n_late_exposure"], weights=g["total_spend"]),
        }
        top_driver = max(drivers, key=drivers.get)

        rows.append(
            {
                "part_family": family,
                "supplier_count": int(len(g)),
                "family_spend": round(family_spend, 2),
                "pct_of_total_spend": round(100.0 * family_spend / total_spend, 1),
                "sole_source_spend": round(sole_source_spend, 2),
                "sole_source_share_pct": round(
                    100.0 * sole_source_spend / family_spend, 1
                ) if family_spend else 0.0,
                "avg_on_time_pct": round(weighted_on_time, 1),
                "avg_defect_ppm": round(weighted_ppm, 0),
                "family_risk_score": round(weighted_risk, 1),
                "risk_tier": family_tier(weighted_risk),
                "top_risk_driver": top_driver,
                "recommended_action": DRIVER_ACTIONS[top_driver],
            }
        )

    seg = pd.DataFrame(rows).sort_values("family_risk_score", ascending=False).reset_index(drop=True)
    return seg


def print_segmentation(seg):
    print("=" * 104)
    print("PART-FAMILY RISK SEGMENTATION".center(104))
    print("=" * 104)
    header = (
        f"{'Part Family':<22}{'Tier':<8}{'Spend':>13}{'Share':>7}"
        f"{'SoleSrc%':>9}{'OnTime%':>9}{'Score':>7}  Top Driver"
    )
    print(header)
    print("-" * 104)
    for _, r in seg.iterrows():
        print(
            f"{r['part_family']:<22}"
            f"{r['risk_tier']:<8}"
            f"${r['family_spend']:>11,.0f} "
            f"{r['pct_of_total_spend']:>5.1f}% "
            f"{r['sole_source_share_pct']:>7.1f}% "
            f"{r['avg_on_time_pct']:>8.1f} "
            f"{r['family_risk_score']:>6.1f}  "
            f"{r['top_risk_driver']}"
        )
    print("-" * 104)
    print("\nRecommended actions by family:")
    for _, r in seg.iterrows():
        print(f"  {r['part_family']:<22} [{r['risk_tier']:<6}] {r['recommended_action']}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        metrics = load_supplier_metrics(conn)
    finally:
        conn.close()

    scored = compute_scores(metrics)
    seg = build_segmentation(scored)
    print_segmentation(seg)

    out_path = os.path.join(OUTPUT_DIR, "part_family_segmentation.csv")
    seg.to_csv(out_path, index=False)
    print()
    print(f"Part-family segmentation written to {out_path}")


if __name__ == "__main__":
    main()
