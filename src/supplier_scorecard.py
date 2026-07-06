"""
Supplier Risk Scorecard: the core deliverable.

Computes a weighted Supplier Risk Score (0 to 100, higher is riskier) for
every supplier from six explicitly named procurement dimensions, ranks the
supply base, and quantifies the actions an operations team can take:

    - single-source, high-spend suppliers that need a qualified second source
    - top process-improvement targets (quality and delivery)
    - a modeled annual savings opportunity built from five documented buckets

Scoring dimensions (reproduced in the README methodology table):

    Dimension              Direction    Weight   Rationale
    --------------------   ----------   ------   ------------------------------
    Spend concentration    higher=risk   0.20    negotiation leverage exposure
    Sole-source exposure   higher=risk   0.20    continuity risk with no backup
    Defect rate (PPM)      higher=risk   0.20    quality and rework cost
    Lead-time variance     higher=risk   0.15    schedule predictability
    On-time delivery       lower=risk    0.15    schedule reliability
    Late-order risk ($)    higher=risk   0.10    dollarized schedule risk

Spend concentration and sole-source exposure are kept as separate dimensions
on purpose. A supplier can be large but dual-sourced (concentration risk with
a fallback), or mid-sized but the only qualified source for a critical part
(continuity risk with no fallback). The two failure modes call for different
actions, so they are scored independently.

Each dimension is min-max normalized to 0..1 across the supply base, oriented
so 1 is always the riskier end, then combined with the weights above and
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

# Risk score weights across the six dimensions. Must sum to 1.0.
WEIGHTS = {
    "concentration": 0.20,
    "sole_source": 0.20,
    "defect_ppm": 0.20,
    "lead_time_cv": 0.15,
    "on_time": 0.15,
    "late_exposure": 0.10,
}

# A supplier is a dual-source candidate if it is single-source and its spend
# share is at or above this threshold of total spend.
DUAL_SOURCE_SPEND_THRESHOLD_PCT = 3.0

# Sole-source exposure is scored on single-source suppliers at or above this
# spend share. Below it, a sole source is small enough to be immaterial.
SOLE_SOURCE_SPEND_THRESHOLD_PCT = 2.0

# Savings model bucket rates. Each is a conservative, documented assumption.
SAVINGS_RATES = {
    # Recovered on fragmented low-volume tail spend through consolidation to
    # fewer suppliers and better pricing tiers.
    "tail_consolidation": 0.040,
    # Recovered by renegotiating price on concentrated single-source families
    # where volume gives leverage.
    "concentration_renegotiation": 0.006,
    # Cost avoidance from qualifying a second source on sole-source spend,
    # reducing the premium a monopoly supplier can command over time.
    "sole_source_risk_reduction": 0.003,
    # Expedite and premium-freight cost avoided by pulling late suppliers back
    # onto schedule, expressed against dollar value delivered late.
    "late_order_avoidance": 0.004,
    # Recovery of quantified rework and scrap cost through quality corrective
    # action, expressed as a share of the current defect dollar cost.
    "defect_reduction": 0.25,
}


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

    # Sole-source exposure: spend carried by a supplier that has no qualified
    # alternate. Zero for dual-sourced suppliers and for sole sources below
    # the materiality threshold. This is what the sole_source dimension scores.
    df["sole_source_exposure_usd"] = np.where(
        (df["is_dual_sourced"] == 0)
        & (df["pct_of_total_spend"] >= SOLE_SOURCE_SPEND_THRESHOLD_PCT),
        df["total_spend"],
        0.0,
    )
    return df


def min_max(series):
    """Min-max normalize to 0..1. Constant series map to 0 (no spread, no risk)."""
    lo, hi = series.min(), series.max()
    if hi == lo:
        return pd.Series(np.zeros(len(series)), index=series.index)
    return (series - lo) / (hi - lo)


def compute_scores(df):
    """Normalize each dimension to a risk-oriented 0..1 and combine into 0..100."""
    df = df.copy()

    # Higher raw value = higher risk for these five.
    df["n_concentration"] = min_max(df["pct_of_total_spend"])
    df["n_sole_source"] = min_max(df["sole_source_exposure_usd"])
    df["n_defect_ppm"] = min_max(df["defect_ppm"])
    df["n_lead_time_cv"] = min_max(df["lead_time_cv"])
    df["n_late_exposure"] = min_max(df["late_exposure_usd"])

    # On-time is protective, so invert: lower on-time percent = higher risk.
    df["n_on_time"] = 1.0 - min_max(df["on_time_pct"])

    df["risk_score"] = 100.0 * (
        WEIGHTS["concentration"] * df["n_concentration"]
        + WEIGHTS["sole_source"] * df["n_sole_source"]
        + WEIGHTS["defect_ppm"] * df["n_defect_ppm"]
        + WEIGHTS["lead_time_cv"] * df["n_lead_time_cv"]
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
    print("=" * 104)
    print("SUPPLIER RISK SCORECARD".center(104))
    print("(higher score = higher risk. six dimensions: concentration .20, sole-source .20, "
          "defect .20,".center(104))
    print("lead-time variance .15, on-time .15, late-order risk .10)".center(104))
    print("=" * 104)

    header = (
        f"{'Rk':>3}  {'Supplier':<26}{'Part Family':<22}"
        f"{'Spend%':>7}{'Sole$':>10}{'CV':>7}{'PPM':>8}{'OnTime%':>9}{'Score':>8}  Band"
    )
    print(header)
    print("-" * 104)

    for _, r in df.iterrows():
        sole = r["sole_source_exposure_usd"]
        sole_str = f"{sole / 1e6:.1f}M" if sole > 0 else "-"
        print(
            f"{int(r['rank']):>3}  "
            f"{r['name'][:25]:<26}"
            f"{r['category'][:21]:<22}"
            f"{r['pct_of_total_spend']:>6.1f} "
            f"{sole_str:>9} "
            f"{r['lead_time_cv']:>6.2f} "
            f"{r['defect_ppm']:>7.0f} "
            f"{r['on_time_pct']:>8.1f} "
            f"{r['risk_score']:>7.1f}  "
            f"{risk_band(r['risk_score'])}"
        )
    print("-" * 104)


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


def savings_model(df, conn):
    """
    Build modeled annual savings as the sum of five documented buckets.

    Each bucket applies a conservative, defensible rate to a real dollar base
    pulled from the data. The rates live in SAVINGS_RATES so the model is
    transparent and easy to re-tune.
    """
    total_spend = df["total_spend"].sum()

    # 1. Tail-spend consolidation: bottom 40% of suppliers by spend.
    tail_cutoff = df["total_spend"].quantile(0.40)
    tail = df[df["total_spend"] <= tail_cutoff]
    tail_base = tail["total_spend"].sum()
    tail_savings = SAVINGS_RATES["tail_consolidation"] * tail_base

    # 2. Concentrated-category renegotiation: single-source suppliers at or
    #    above the dual-source spend threshold carry the most leverage.
    concentrated = df[
        (df["is_dual_sourced"] == 0)
        & (df["pct_of_total_spend"] >= DUAL_SOURCE_SPEND_THRESHOLD_PCT)
    ]
    concentration_base = concentrated["total_spend"].sum()
    concentration_savings = (
        SAVINGS_RATES["concentration_renegotiation"] * concentration_base
    )

    # 3. Sole-source risk reduction: cost avoidance on material sole-source spend.
    sole_source_base = df["sole_source_exposure_usd"].sum()
    sole_source_savings = SAVINGS_RATES["sole_source_risk_reduction"] * sole_source_base

    # 4. Late-order / expedite cost avoidance: against dollar value delivered late.
    late_base = df["late_exposure_usd"].sum()
    late_savings = SAVINGS_RATES["late_order_avoidance"] * late_base

    # 5. Defect / quality cost reduction: recovery of current rework and scrap
    #    cost, valued at the fleet average unit cost.
    avg_unit_cost = conn.execute(
        "SELECT SUM(total_cost) / SUM(quantity) FROM purchase_orders"
    ).fetchone()[0]
    defect_units = int(df["defect_units"].sum())
    defect_base = defect_units * avg_unit_cost
    defect_savings = SAVINGS_RATES["defect_reduction"] * defect_base

    buckets = [
        {
            "bucket": "Tail-spend consolidation",
            "base_usd": tail_base,
            "rate": SAVINGS_RATES["tail_consolidation"],
            "savings_usd": tail_savings,
            "basis": f"{len(tail)} tail suppliers, {SAVINGS_RATES['tail_consolidation']*100:.1f}% of tail spend",
        },
        {
            "bucket": "Concentrated-category renegotiation",
            "base_usd": concentration_base,
            "rate": SAVINGS_RATES["concentration_renegotiation"],
            "savings_usd": concentration_savings,
            "basis": f"{len(concentrated)} concentrated suppliers, {SAVINGS_RATES['concentration_renegotiation']*100:.1f}% of their spend",
        },
        {
            "bucket": "Sole-source risk reduction",
            "base_usd": sole_source_base,
            "rate": SAVINGS_RATES["sole_source_risk_reduction"],
            "savings_usd": sole_source_savings,
            "basis": f"{SAVINGS_RATES['sole_source_risk_reduction']*100:.1f}% cost avoidance on material sole-source spend",
        },
        {
            "bucket": "Late-order / expedite avoidance",
            "base_usd": late_base,
            "rate": SAVINGS_RATES["late_order_avoidance"],
            "savings_usd": late_savings,
            "basis": f"{SAVINGS_RATES['late_order_avoidance']*100:.1f}% expedite premium avoided on late PO value",
        },
        {
            "bucket": "Defect / quality cost reduction",
            "base_usd": defect_base,
            "rate": SAVINGS_RATES["defect_reduction"],
            "savings_usd": defect_savings,
            "basis": f"{defect_units} defect units at ${avg_unit_cost:,.2f} avg unit cost, {SAVINGS_RATES['defect_reduction']*100:.0f}% recovered",
        },
    ]
    total_savings = sum(b["savings_usd"] for b in buckets)
    return buckets, total_savings, total_spend


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        metrics = load_supplier_metrics(conn)
        scored = compute_scores(metrics)
        scored["risk_band"] = scored["risk_score"].apply(risk_band)

        print_scorecard(scored)

        # Dual-sourcing recommendations.
        dual = dual_source_recommendations(scored)
        print()
        print("DUAL-SOURCE RECOMMENDATIONS "
              f"(single-source suppliers at or above {DUAL_SOURCE_SPEND_THRESHOLD_PCT:.0f}% of spend)")
        print("-" * 104)
        if dual.empty:
            print("No single-source concentration risks above threshold.")
        else:
            for _, r in dual.iterrows():
                print(
                    f"  {r['name']:<26} {r['category']:<22} "
                    f"spend ${r['total_spend']:>11,.0f}  "
                    f"({r['pct_of_total_spend']:.1f}% of total)  risk {r['risk_score']:.0f}"
                )

        # Process-improvement targets.
        targets = process_improvement_targets(scored)
        print()
        print("TOP PROCESS-IMPROVEMENT TARGETS (quality + delivery risk)")
        print("-" * 104)
        for _, r in targets.iterrows():
            print(
                f"  {r['name']:<26} {r['category']:<22} "
                f"PPM {r['defect_ppm']:>6.0f}  on-time {r['on_time_pct']:>5.1f}%  "
                f"lead CV {r['lead_time_cv']:.2f}"
            )

        # Savings model.
        buckets, total_savings, total_spend = savings_model(scored, conn)
    finally:
        conn.close()

    print()
    print("MODELED ANNUAL SAVINGS (sum of five documented buckets)")
    print("-" * 104)
    for b in buckets:
        print(
            f"  {b['bucket']:<38} ${b['savings_usd']:>10,.0f}   "
            f"({b['basis']})"
        )
    print("-" * 104)
    print(f"  {'TOTAL MODELED ANNUAL SAVINGS':<38} ${total_savings:>10,.0f}")
    print(f"  {'As share of total spend':<38} {100 * total_savings / total_spend:>10.2f}%")

    # Write the scorecard CSV.
    out_path = os.path.join(OUTPUT_DIR, "supplier_scorecard.csv")
    export_cols = [
        "rank", "supplier_id", "name", "category", "region",
        "is_dual_sourced", "order_count", "total_spend", "pct_of_total_spend",
        "sole_source_exposure_usd", "lead_time_cv", "defect_ppm", "on_time_pct",
        "late_exposure_usd", "risk_score", "risk_band",
    ]
    scored[export_cols].round(3).to_csv(out_path, index=False)

    # Write the savings breakdown CSV so the dashboard and README can read it.
    savings_path = os.path.join(OUTPUT_DIR, "savings_breakdown.csv")
    pd.DataFrame(buckets)[["bucket", "base_usd", "rate", "savings_usd", "basis"]].round(2).to_csv(
        savings_path, index=False
    )

    print()
    print(f"Scorecard written to {out_path}")
    print(f"Savings breakdown written to {savings_path}")


if __name__ == "__main__":
    main()
