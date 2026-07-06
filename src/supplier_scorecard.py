"""
Supplier Risk Scorecard: the core deliverable.

Computes a weighted Supplier Risk Score (0 to 100, higher is riskier) for
every supplier from five procurement metrics, then ranks the supply base and
surfaces the actions an operations team can take:

    - single-source, high-spend suppliers that need a qualified second source
    - top process-improvement targets (quality and delivery)
    - a quantified savings and risk-reduction opportunity

Scoring method (documented and reproduced in the README):

    Metric                 Direction   Weight   Rationale
    ---------------------  ---------   ------   -------------------------------
    Spend concentration    higher=risk   0.25   continuity + negotiation leverage
    Lead-time variance     higher=risk   0.20   schedule predictability
    Defect rate (PPM)      higher=risk   0.25   quality and rework cost
    On-time delivery       lower=risk    0.15   schedule reliability
    Late-order $ exposure  higher=risk   0.15   dollarized schedule risk

Each metric is min-max normalized to 0..1 across the supply base, oriented so
that 1 is always the riskier end, then combined with the weights above and
scaled to 0..100.

Outputs a ranked table to stdout and writes output/supplier_scorecard.csv.
"""

import os
import sqlite3

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "procurement.db")
OUTPUT_DIR = os.path.join(ROOT, "output")

# Risk score weights. Must sum to 1.0.
WEIGHTS = {
    "concentration": 0.25,
    "lead_time_cv": 0.20,
    "defect_ppm": 0.25,
    "on_time": 0.15,
    "late_exposure": 0.15,
}

# A supplier is a dual-source candidate if it is single-source and its spend
# share is at or above this threshold of total spend.
DUAL_SOURCE_SPEND_THRESHOLD_PCT = 3.0


def load_supplier_metrics(conn):
    """Pull one row per supplier with every raw metric the score needs."""
    query = """
        WITH totals AS (
            SELECT SUM(total_cost) AS total_spend FROM purchase_orders
        )
        SELECT
            s.supplier_id,
            s.name,
            s.category,
            s.region,
            s.is_dual_sourced,
            COUNT(po.po_id)                                    AS order_count,
            SUM(po.total_cost)                                 AS total_spend,
            100.0 * SUM(po.total_cost) / (SELECT total_spend FROM totals)
                                                               AS pct_of_total_spend,
            AVG(julianday(po.received_date) - julianday(po.order_date))
                                                               AS avg_lead_days,
            SUM(po.quantity)                                   AS units_received,
            SUM(po.defect_units)                               AS defect_units,
            100.0 * SUM(po.on_time) / COUNT(po.po_id)          AS on_time_pct,
            SUM(CASE WHEN po.on_time = 0 THEN po.total_cost ELSE 0 END)
                                                               AS late_exposure_usd
        FROM suppliers s
        JOIN purchase_orders po ON po.supplier_id = s.supplier_id
        GROUP BY s.supplier_id, s.name, s.category, s.region, s.is_dual_sourced
    """
    df = pd.read_sql_query(query, conn)

    # Lead-time standard deviation and coefficient of variation are computed
    # in pandas from the raw per-order lead times for numerical clarity.
    lead_times = pd.read_sql_query(
        """
        SELECT
            supplier_id,
            julianday(received_date) - julianday(order_date) AS lead_days
        FROM purchase_orders
        """,
        conn,
    )
    lead_stats = (
        lead_times.groupby("supplier_id")["lead_days"]
        .agg(["mean", "std"])
        .rename(columns={"mean": "lead_mean", "std": "lead_std"})
    )
    lead_stats["lead_time_cv"] = lead_stats["lead_std"] / lead_stats["lead_mean"]
    df = df.merge(lead_stats["lead_time_cv"], on="supplier_id", how="left")

    df["defect_ppm"] = 1_000_000.0 * df["defect_units"] / df["units_received"]
    return df


def min_max(series):
    """Min-max normalize to 0..1. Constant series map to 0 (no spread, no risk)."""
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - lo) / (hi - lo)


def compute_scores(df):
    """Normalize each metric to a risk-oriented 0..1 and combine into 0..100."""
    df = df.copy()

    # Higher raw value = higher risk for these four.
    df["n_concentration"] = min_max(df["pct_of_total_spend"])
    df["n_lead_time_cv"] = min_max(df["lead_time_cv"])
    df["n_defect_ppm"] = min_max(df["defect_ppm"])
    df["n_late_exposure"] = min_max(df["late_exposure_usd"])

    # On-time is protective, so invert: lower on-time percent = higher risk.
    df["n_on_time"] = 1.0 - min_max(df["on_time_pct"])

    df["risk_score"] = 100.0 * (
        WEIGHTS["concentration"] * df["n_concentration"]
        + WEIGHTS["lead_time_cv"] * df["n_lead_time_cv"]
        + WEIGHTS["defect_ppm"] * df["n_defect_ppm"]
        + WEIGHTS["on_time"] * df["n_on_time"]
        + WEIGHTS["late_exposure"] * df["n_late_exposure"]
    )

    df = df.sort_values("risk_score", ascending=False).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    return df


def risk_band(score):
    if score >= 55:
        return "High"
    if score >= 35:
        return "Medium"
    return "Low"


def print_scorecard(df):
    print("=" * 96)
    print("SUPPLIER RISK SCORECARD".center(96))
    print("(higher score = higher risk. weights: concentration .25, defect .25, "
          "lead-time CV .20,".center(96))
    print("on-time .15, late-$ exposure .15)".center(96))
    print("=" * 96)

    header = (
        f"{'Rk':>3}  {'Supplier':<26}{'Category':<22}"
        f"{'Spend%':>7}{'CV':>7}{'PPM':>8}{'OnTime%':>9}{'Score':>8}  Band"
    )
    print(header)
    print("-" * 96)

    for _, r in df.iterrows():
        print(
            f"{int(r['rank']):>3}  "
            f"{r['name'][:25]:<26}"
            f"{r['category'][:21]:<22}"
            f"{r['pct_of_total_spend']:>6.1f} "
            f"{r['lead_time_cv']:>6.2f} "
            f"{r['defect_ppm']:>7.0f} "
            f"{r['on_time_pct']:>8.1f} "
            f"{r['risk_score']:>7.1f}  "
            f"{risk_band(r['risk_score'])}"
        )
    print("-" * 96)


def dual_source_recommendations(df):
    """Single-source suppliers above the spend threshold: qualify a second source."""
    candidates = df[
        (df["is_dual_sourced"] == 0)
        & (df["pct_of_total_spend"] >= DUAL_SOURCE_SPEND_THRESHOLD_PCT)
    ].sort_values("total_spend", ascending=False)
    return candidates


def process_improvement_targets(df, top_n=5):
    """Highest combined quality + delivery risk suppliers."""
    df = df.copy()
    df["ops_risk"] = df["n_defect_ppm"] + df["n_on_time"] + df["n_lead_time_cv"]
    return df.sort_values("ops_risk", ascending=False).head(top_n)


def savings_opportunity(df):
    """
    Quantify two conservative, defensible opportunities:

    1. Tail-spend consolidation. Suppliers below the 40th percentile of spend
       make up the long tail. Consolidating that fragmented buy and retiring
       redundant suppliers conservatively recovers ~8 percent of tail spend
       through better pricing tiers and lower transaction overhead.

    2. Concentrated-category negotiation. In categories where the top supplier
       controls a large share, a targeted renegotiation on that leverage
       conservatively recovers ~3 percent of that supplier's spend.
    """
    total_spend = df["total_spend"].sum()

    tail_cutoff = df["total_spend"].quantile(0.40)
    tail = df[df["total_spend"] <= tail_cutoff]
    tail_spend = tail["total_spend"].sum()
    tail_savings = 0.08 * tail_spend

    # Concentration play: single-source suppliers above the dual-source
    # threshold are also the most concentrated negotiation targets.
    concentrated = df[
        (df["is_dual_sourced"] == 0)
        & (df["pct_of_total_spend"] >= DUAL_SOURCE_SPEND_THRESHOLD_PCT)
    ]
    concentrated_spend = concentrated["total_spend"].sum()
    negotiation_savings = 0.03 * concentrated_spend

    late_exposure = df["late_exposure_usd"].sum()

    return {
        "total_spend": total_spend,
        "tail_supplier_count": int(len(tail)),
        "tail_spend": tail_spend,
        "tail_savings": tail_savings,
        "concentrated_supplier_count": int(len(concentrated)),
        "concentrated_spend": concentrated_spend,
        "negotiation_savings": negotiation_savings,
        "total_savings": tail_savings + negotiation_savings,
        "late_exposure": late_exposure,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        metrics = load_supplier_metrics(conn)
    finally:
        conn.close()

    scored = compute_scores(metrics)
    scored["risk_band"] = scored["risk_score"].apply(risk_band)

    print_scorecard(scored)

    # Dual-sourcing recommendations.
    dual = dual_source_recommendations(scored)
    print()
    print("DUAL-SOURCE RECOMMENDATIONS "
          f"(single-source suppliers at or above {DUAL_SOURCE_SPEND_THRESHOLD_PCT:.0f}% of spend)")
    print("-" * 96)
    if dual.empty:
        print("No single-source concentration risks above threshold.")
    else:
        for _, r in dual.iterrows():
            print(
                f"  {r['name']:<26} {r['category']:<22} "
                f"spend ${r['total_spend']:>12,.0f}  "
                f"({r['pct_of_total_spend']:.1f}% of total)  risk {r['risk_score']:.0f}"
            )

    # Process-improvement targets.
    targets = process_improvement_targets(scored)
    print()
    print("TOP PROCESS-IMPROVEMENT TARGETS (quality + delivery risk)")
    print("-" * 96)
    for _, r in targets.iterrows():
        print(
            f"  {r['name']:<26} {r['category']:<22} "
            f"PPM {r['defect_ppm']:>6.0f}  on-time {r['on_time_pct']:>5.1f}%  "
            f"lead CV {r['lead_time_cv']:.2f}"
        )

    # Savings opportunity.
    opp = savings_opportunity(scored)
    print()
    print("ESTIMATED OPPORTUNITY")
    print("-" * 96)
    print(f"  Total spend analyzed:                ${opp['total_spend']:>14,.0f}")
    print(
        f"  Tail consolidation ({opp['tail_supplier_count']} suppliers, "
        f"${opp['tail_spend']:,.0f} spend): "
        f"${opp['tail_savings']:>12,.0f}  (~8% of tail)"
    )
    print(
        f"  Concentrated-category negotiation ({opp['concentrated_supplier_count']} suppliers): "
        f"${opp['negotiation_savings']:>12,.0f}  (~3% of concentrated spend)"
    )
    print(f"  Estimated annualized savings:        ${opp['total_savings']:>14,.0f}")
    print(f"  Dollar value currently in late POs:  ${opp['late_exposure']:>14,.0f}")

    # Write the scorecard CSV.
    out_path = os.path.join(OUTPUT_DIR, "supplier_scorecard.csv")
    export_cols = [
        "rank", "supplier_id", "name", "category", "region",
        "is_dual_sourced", "order_count", "total_spend", "pct_of_total_spend",
        "lead_time_cv", "defect_ppm", "on_time_pct", "late_exposure_usd",
        "risk_score", "risk_band",
    ]
    scored[export_cols].round(3).to_csv(out_path, index=False)
    print()
    print(f"Scorecard written to {out_path}")


if __name__ == "__main__":
    main()
