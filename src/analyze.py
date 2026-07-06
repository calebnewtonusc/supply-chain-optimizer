"""
Executive analytics and charts.

Runs the query library in sql/analytics.sql against the SQLite database,
prints an executive summary of the findings, and renders four charts to
output/:

    spend_pareto.png            spend concentration Pareto (bars + cumulative)
    risk_ranking.png            top suppliers by risk score
    quality_vs_delivery.png     lead-time variance vs defect PPM (bubble = spend)
    on_time_trend.png           on-time delivery rate by month

The scorecard scores are recomputed here via supplier_scorecard so the risk
ranking chart uses the same numbers the CSV export uses.
"""

import os
import re
import sqlite3

import matplotlib

matplotlib.use("Agg")  # headless rendering
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import pandas as pd

from supplier_scorecard import compute_scores, load_supplier_metrics

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "procurement.db")
SQL_DIR = os.path.join(ROOT, "sql")
OUTPUT_DIR = os.path.join(ROOT, "output")

# Chart palette. Dark, restrained, one accent.
BG = "#0f1115"
PANEL = "#161a20"
GRID = "#2a2f38"
TEXT = "#e6e8eb"
MUTED = "#8b93a1"
ACCENT = "#4f7cff"
ACCENT_2 = "#f2a03d"
RISK = "#e5484d"

plt.rcParams.update(
    {
        "figure.facecolor": BG,
        "axes.facecolor": PANEL,
        "savefig.facecolor": BG,
        "text.color": TEXT,
        "axes.labelcolor": TEXT,
        "axes.edgecolor": GRID,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "font.size": 11,
        "font.family": "DejaVu Sans",
    }
)


def load_named_queries(path):
    """Parse analytics.sql into a dict of {name: sql} using -- name: markers."""
    with open(path) as f:
        text = f.read()
    queries = {}
    blocks = re.split(r"-- name:\s*(\w+)\s*\n", text)
    # blocks[0] is any preamble; then name, body, name, body, ...
    for i in range(1, len(blocks), 2):
        name = blocks[i].strip()
        body = blocks[i + 1]
        # Trim trailing content that belongs to the next section header comment.
        queries[name] = body.strip()
    return queries


def run(conn, queries, name):
    return pd.read_sql_query(queries[name], conn)


def fmt_millions(x, _pos):
    return f"${x / 1e6:.1f}M"


def chart_spend_pareto(spend_by_supplier):
    df = spend_by_supplier.sort_values("total_spend", ascending=False).reset_index(drop=True)
    df["cum_pct"] = 100.0 * df["total_spend"].cumsum() / df["total_spend"].sum()

    top = df.head(20)
    fig, ax1 = plt.subplots(figsize=(11, 6))
    x = range(len(top))
    ax1.bar(x, top["total_spend"], color=ACCENT, width=0.72)
    ax1.set_ylabel("Total spend")
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(fmt_millions))
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(top["name"], rotation=55, ha="right", fontsize=8)
    ax1.grid(axis="y", color=GRID, linewidth=0.6, alpha=0.6)
    ax1.set_axisbelow(True)

    ax2 = ax1.twinx()
    ax2.plot(x, top["cum_pct"], color=ACCENT_2, marker="o", markersize=4, linewidth=2)
    ax2.set_ylabel("Cumulative share of total spend", color=ACCENT_2)
    ax2.set_ylim(0, 105)
    ax2.axhline(80, color=RISK, linestyle="--", linewidth=1, alpha=0.7)
    ax2.tick_params(axis="y", colors=ACCENT_2)
    ax2.text(0.4, 82, "80% of spend", color=RISK, fontsize=9, ha="left")

    ax1.set_title("Spend concentration: top 20 suppliers (Pareto)", fontsize=14, pad=14, color=TEXT)
    fig.tight_layout()
    path = os.path.join(OUTPUT_DIR, "spend_pareto.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def chart_risk_ranking(scored):
    top = scored.head(15).iloc[::-1]  # reverse so highest risk is at top of barh
    colors = [RISK if b == "High" else ACCENT_2 if b == "Medium" else ACCENT
              for b in top["risk_band"]]

    fig, ax = plt.subplots(figsize=(11, 6.5))
    y = range(len(top))
    ax.barh(list(y), top["risk_score"], color=colors)
    ax.set_yticks(list(y))
    ax.set_yticklabels(top["name"], fontsize=9)
    ax.set_xlabel("Supplier risk score (0 to 100)")
    ax.set_xlim(0, 100)
    ax.grid(axis="x", color=GRID, linewidth=0.6, alpha=0.6)
    ax.set_axisbelow(True)

    for yi, v in zip(y, top["risk_score"]):
        ax.text(v + 1, yi, f"{v:.0f}", va="center", fontsize=9, color=TEXT)

    ax.set_title("Supplier risk ranking (top 15)", fontsize=14, pad=14, color=TEXT)
    fig.tight_layout()
    path = os.path.join(OUTPUT_DIR, "risk_ranking.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def chart_quality_vs_delivery(scored):
    fig, ax = plt.subplots(figsize=(11, 6.5))
    sizes = 40 + 2400 * (scored["total_spend"] / scored["total_spend"].max())
    colors = [RISK if b == "High" else ACCENT_2 if b == "Medium" else ACCENT
              for b in scored["risk_band"]]

    ax.scatter(
        scored["lead_time_cv"],
        scored["defect_ppm"],
        s=sizes,
        c=colors,
        alpha=0.68,
        edgecolors="#0b0d10",
        linewidths=0.8,
    )

    # Label the worst offenders.
    worst = scored.sort_values("risk_score", ascending=False).head(6)
    for _, r in worst.iterrows():
        ax.annotate(
            r["name"],
            (r["lead_time_cv"], r["defect_ppm"]),
            textcoords="offset points",
            xytext=(7, 5),
            fontsize=8,
            color=MUTED,
        )

    ax.set_xlabel("Lead-time coefficient of variation (unpredictability)")
    ax.set_ylabel("Defect rate (PPM)")
    ax.grid(color=GRID, linewidth=0.6, alpha=0.5)
    ax.set_axisbelow(True)
    ax.set_title(
        "Quality vs delivery predictability (bubble size = spend)",
        fontsize=14, pad=14, color=TEXT,
    )
    fig.tight_layout()
    path = os.path.join(OUTPUT_DIR, "quality_vs_delivery.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def chart_on_time_trend(trend):
    fig, ax = plt.subplots(figsize=(11, 5.5))
    x = range(len(trend))
    ax.plot(x, trend["on_time_pct"], color=ACCENT, marker="o", markersize=4, linewidth=2)
    ax.fill_between(x, trend["on_time_pct"], min(trend["on_time_pct"]) - 3,
                    color=ACCENT, alpha=0.08)
    ax.set_xticks(list(x)[::2])
    ax.set_xticklabels(trend["order_month"][::2], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("On-time delivery rate (%)")
    ax.grid(color=GRID, linewidth=0.6, alpha=0.5)
    ax.set_axisbelow(True)
    ax.set_title("On-time delivery rate by order month", fontsize=14, pad=14, color=TEXT)
    fig.tight_layout()
    path = os.path.join(OUTPUT_DIR, "on_time_trend.png")
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def print_executive_summary(conn, queries, scored):
    total_spend = scored["total_spend"].sum()

    top_share = run(conn, queries, "top_n_share").iloc[0]
    cat_conc = run(conn, queries, "category_concentration_hhi")
    on_time = run(conn, queries, "on_time_delivery")
    ppm = run(conn, queries, "defect_ppm")
    late = run(conn, queries, "late_order_exposure")
    trend = run(conn, queries, "on_time_trend_by_month")

    print("=" * 96)
    print("EXECUTIVE SUMMARY".center(96))
    print("=" * 96)

    print(f"\nTotal spend analyzed: ${total_spend:,.0f} across "
          f"{scored['order_count'].sum():,} purchase orders and {len(scored)} suppliers.")

    print(f"\nConcentration:")
    print(f"  Top 10 suppliers control {top_share['top10_share_pct']:.1f}% of total spend.")
    worst_cat = cat_conc.iloc[0]
    print(f"  Most concentrated category: {worst_cat['category']} "
          f"(HHI {worst_cat['hhi']:.0f}, top supplier {worst_cat['top_supplier_share_pct']:.0f}% "
          f"of the category, {int(worst_cat['supplier_count'])} suppliers).")

    print(f"\nDelivery reliability:")
    overall_on_time = trend["on_time_pct"].mean()
    worst_delivery = on_time.iloc[0]
    print(f"  Supply-base average on-time rate: {overall_on_time:.1f}%.")
    print(f"  Worst on-time supplier: {worst_delivery['name']} "
          f"({worst_delivery['on_time_pct']:.1f}% on-time over "
          f"{int(worst_delivery['order_count'])} POs).")

    print(f"\nQuality:")
    worst_ppm = ppm.iloc[0]
    print(f"  Highest defect rate: {worst_ppm['name']} at {worst_ppm['defect_ppm']:,.0f} PPM.")

    print(f"\nSchedule risk in dollars:")
    total_late = late["late_exposure_usd"].sum()
    worst_late = late.iloc[0]
    print(f"  ${total_late:,.0f} of PO value arrived late across the supply base.")
    print(f"  Largest single-supplier late exposure: {worst_late['name']} "
          f"(${worst_late['late_exposure_usd']:,.0f}).")
    print()


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    queries = load_named_queries(os.path.join(SQL_DIR, "analytics.sql"))

    conn = sqlite3.connect(DB_PATH)
    try:
        metrics = load_supplier_metrics(conn)
        scored = compute_scores(metrics)
        scored["risk_band"] = scored["risk_score"].apply(
            lambda s: "High" if s >= 55 else "Medium" if s >= 35 else "Low"
        )

        print_executive_summary(conn, queries, scored)

        spend_by_supplier = run(conn, queries, "spend_by_supplier")
        trend = run(conn, queries, "on_time_trend_by_month")
    finally:
        conn.close()

    paths = [
        chart_spend_pareto(spend_by_supplier),
        chart_risk_ranking(scored),
        chart_quality_vs_delivery(scored),
        chart_on_time_trend(trend),
    ]
    print("Charts written:")
    for p in paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
