"""
Executive purchasing dashboard builder.

Reads the pipeline outputs (supplier scorecard, savings breakdown, part-family
segmentation, and the four PNG charts) and renders a single self-contained
static HTML file at output/dashboard.html.

The dashboard is the decision surface for consolidation, renegotiation,
dual-sourcing, and process-improvement calls. It has no external network
dependency beyond the Tailwind CDN and the Inter web font: all data is
inlined as HTML tables and all charts are embedded as base64 data URIs.
"""

import base64
import os
import sqlite3

import pandas as pd

from part_family import build_segmentation
from supplier_scorecard import compute_scores, load_supplier_metrics, savings_model

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT, "procurement.db")
OUTPUT_DIR = os.path.join(ROOT, "output")

CHARTS = [
    ("Spend concentration (Pareto)", "spend_pareto.png"),
    ("Supplier risk ranking", "risk_ranking.png"),
    ("Quality vs delivery predictability", "quality_vs_delivery.png"),
    ("On-time delivery trend", "on_time_trend.png"),
]


def img_data_uri(filename):
    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def usd(x):
    return f"${x:,.0f}"


def band_badge(band):
    colors = {
        "High": "background:rgba(229,72,77,0.15);color:#f87171;border:1px solid rgba(229,72,77,0.35)",
        "Medium": "background:rgba(242,160,61,0.15);color:#fbbf24;border:1px solid rgba(242,160,61,0.35)",
        "Low": "background:rgba(79,124,255,0.12);color:#7c9bff;border:1px solid rgba(79,124,255,0.30)",
    }
    style = colors.get(band, colors["Low"])
    return (
        f'<span style="display:inline-block;padding:2px 10px;border-radius:9999px;'
        f'font-size:12px;font-weight:600;{style}">{band}</span>'
    )


def kpi_card(label, value, sub):
    return f"""
      <div style="background:#161a20;border:1px solid #232a33;border-radius:16px;padding:20px 22px;">
        <div style="font-size:12px;letter-spacing:0.04em;text-transform:uppercase;color:#8b93a1;font-weight:600;">{label}</div>
        <div style="font-size:30px;font-weight:800;color:#f4f6f8;margin-top:6px;letter-spacing:-0.02em;">{value}</div>
        <div style="font-size:13px;color:#8b93a1;margin-top:4px;">{sub}</div>
      </div>"""


def scorecard_rows(scored):
    rows = []
    for _, r in scored.iterrows():
        sole = r["sole_source_exposure_usd"]
        sole_str = usd(sole) if sole > 0 else "<span style='color:#5b6370'>none</span>"
        rows.append(f"""
        <tr style="border-top:1px solid #1f252d;">
          <td style="padding:9px 12px;color:#8b93a1;">{int(r['rank'])}</td>
          <td style="padding:9px 12px;color:#e6e8eb;font-weight:600;">{r['name']}</td>
          <td style="padding:9px 12px;color:#aab2bd;">{r['category']}</td>
          <td style="padding:9px 12px;text-align:right;color:#e6e8eb;">{usd(r['total_spend'])}</td>
          <td style="padding:9px 12px;text-align:right;color:#aab2bd;">{r['pct_of_total_spend']:.1f}%</td>
          <td style="padding:9px 12px;text-align:right;color:#aab2bd;">{sole_str}</td>
          <td style="padding:9px 12px;text-align:right;color:#aab2bd;">{r['lead_time_cv']:.2f}</td>
          <td style="padding:9px 12px;text-align:right;color:#aab2bd;">{r['defect_ppm']:,.0f}</td>
          <td style="padding:9px 12px;text-align:right;color:#aab2bd;">{r['on_time_pct']:.1f}%</td>
          <td style="padding:9px 12px;text-align:right;color:#f4f6f8;font-weight:700;">{r['risk_score']:.1f}</td>
          <td style="padding:9px 12px;text-align:center;">{band_badge(r['risk_band'])}</td>
        </tr>""")
    return "".join(rows)


def savings_rows(buckets, total):
    rows = []
    for b in buckets:
        rows.append(f"""
        <tr style="border-top:1px solid #1f252d;">
          <td style="padding:10px 12px;color:#e6e8eb;font-weight:600;">{b['bucket']}</td>
          <td style="padding:10px 12px;text-align:right;color:#aab2bd;">{usd(b['base_usd'])}</td>
          <td style="padding:10px 12px;text-align:right;color:#aab2bd;">{b['rate']*100:.2f}%</td>
          <td style="padding:10px 12px;text-align:right;color:#4ade80;font-weight:700;">{usd(b['savings_usd'])}</td>
          <td style="padding:10px 12px;color:#8b93a1;font-size:13px;">{b['basis']}</td>
        </tr>""")
    rows.append(f"""
        <tr style="border-top:2px solid #2a323d;background:#12161c;">
          <td style="padding:12px;color:#f4f6f8;font-weight:800;">Total modeled annual savings</td>
          <td style="padding:12px;"></td>
          <td style="padding:12px;"></td>
          <td style="padding:12px;text-align:right;color:#4ade80;font-weight:800;font-size:16px;">{usd(total)}</td>
          <td style="padding:12px;"></td>
        </tr>""")
    return "".join(rows)


def tier_badge(tier):
    return band_badge(tier)


def segmentation_rows(seg):
    rows = []
    for _, r in seg.iterrows():
        rows.append(f"""
        <tr style="border-top:1px solid #1f252d;">
          <td style="padding:10px 12px;color:#e6e8eb;font-weight:600;">{r['part_family']}</td>
          <td style="padding:10px 12px;text-align:center;">{tier_badge(r['risk_tier'])}</td>
          <td style="padding:10px 12px;text-align:right;color:#e6e8eb;">{usd(r['family_spend'])}</td>
          <td style="padding:10px 12px;text-align:right;color:#aab2bd;">{r['pct_of_total_spend']:.1f}%</td>
          <td style="padding:10px 12px;text-align:right;color:#aab2bd;">{r['sole_source_share_pct']:.1f}%</td>
          <td style="padding:10px 12px;text-align:right;color:#aab2bd;">{r['avg_on_time_pct']:.1f}%</td>
          <td style="padding:10px 12px;color:#aab2bd;">{r['top_risk_driver']}</td>
          <td style="padding:10px 12px;color:#8b93a1;font-size:13px;">{r['recommended_action']}</td>
        </tr>""")
    return "".join(rows)


def chart_cards():
    cards = []
    for title, filename in CHARTS:
        uri = img_data_uri(filename)
        cards.append(f"""
        <div style="background:#161a20;border:1px solid #232a33;border-radius:16px;padding:16px;">
          <div style="font-size:14px;font-weight:600;color:#e6e8eb;margin-bottom:12px;">{title}</div>
          <img src="{uri}" alt="{title}" style="width:100%;height:auto;border-radius:8px;display:block;" />
        </div>""")
    return "".join(cards)


def section_title(text, sub):
    return f"""
      <div style="margin:44px 0 16px;">
        <h2 style="font-size:20px;font-weight:700;color:#f4f6f8;letter-spacing:-0.01em;margin:0;">{text}</h2>
        <p style="font-size:14px;color:#8b93a1;margin:4px 0 0;">{sub}</p>
      </div>"""


def build_html(scored, buckets, total_savings, total_spend, seg):
    n_pos = int(scored["order_count"].sum())
    n_sole = int((scored["sole_source_exposure_usd"] > 0).sum())
    avg_on_time = float(
        (scored["on_time_pct"] * scored["order_count"]).sum() / scored["order_count"].sum()
    )

    kpis = "".join([
        kpi_card("Total spend", usd(total_spend), "24 month window"),
        kpi_card("Purchase orders", f"{n_pos:,}", f"{len(scored)} suppliers"),
        kpi_card("Savings identified", usd(total_savings), f"{100*total_savings/total_spend:.2f}% of spend"),
        kpi_card("Sole-source risks", str(n_sole), "material single-source suppliers"),
        kpi_card("Avg on-time", f"{avg_on_time:.1f}%", "PO-weighted delivery rate"),
    ])

    table_header_style = (
        "padding:9px 12px;font-size:11px;letter-spacing:0.04em;text-transform:uppercase;"
        "color:#6b7280;font-weight:700;text-align:left;"
    )
    th_r = table_header_style + "text-align:right;"
    th_c = table_header_style + "text-align:center;"

    scorecard_head = (
        f'<th style="{table_header_style}">Rank</th>'
        f'<th style="{table_header_style}">Supplier</th>'
        f'<th style="{table_header_style}">Part family</th>'
        f'<th style="{th_r}">Spend</th>'
        f'<th style="{th_r}">Share</th>'
        f'<th style="{th_r}">Sole-source</th>'
        f'<th style="{th_r}">Lead CV</th>'
        f'<th style="{th_r}">Defect PPM</th>'
        f'<th style="{th_r}">On-time</th>'
        f'<th style="{th_r}">Risk</th>'
        f'<th style="{th_c}">Band</th>'
    )
    savings_head = (
        f'<th style="{table_header_style}">Opportunity bucket</th>'
        f'<th style="{th_r}">Base spend</th>'
        f'<th style="{th_r}">Rate</th>'
        f'<th style="{th_r}">Savings</th>'
        f'<th style="{table_header_style}">Basis</th>'
    )
    seg_head = (
        f'<th style="{table_header_style}">Part family</th>'
        f'<th style="{th_c}">Tier</th>'
        f'<th style="{th_r}">Spend</th>'
        f'<th style="{th_r}">Share</th>'
        f'<th style="{th_r}">Sole-source share</th>'
        f'<th style="{th_r}">On-time</th>'
        f'<th style="{table_header_style}">Top risk driver</th>'
        f'<th style="{table_header_style}">Recommended action</th>'
    )

    table_wrap_open = (
        '<div style="background:#12151b;border:1px solid #232a33;border-radius:16px;'
        'overflow-x:auto;"><table style="width:100%;border-collapse:collapse;font-size:14px;">'
    )
    table_wrap_close = "</table></div>"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Supplier Spend & Risk Optimization Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet" />
<script src="https://cdn.tailwindcss.com"></script>
<style>
  html, body {{ background:#09090b; }}
  body {{ font-family:'Inter', system-ui, -apple-system, sans-serif; -webkit-font-smoothing:antialiased; color:#e6e8eb; margin:0; }}
  tbody tr:hover {{ background:#141922; }}
</style>
</head>
<body>
<div style="max-width:1200px;margin:0 auto;padding:40px 24px 72px;">

  <header style="border-bottom:1px solid #1f252d;padding-bottom:24px;">
    <div style="display:inline-block;padding:4px 12px;border-radius:9999px;font-size:12px;font-weight:600;background:rgba(79,124,255,0.12);color:#7c9bff;border:1px solid rgba(79,124,255,0.30);">
      Procurement analytics
    </div>
    <h1 style="font-size:34px;font-weight:800;letter-spacing:-0.03em;color:#f7f8fa;margin:14px 0 6px;">
      Supplier Spend & Risk Optimization Dashboard
    </h1>
    <p style="font-size:15px;color:#8b93a1;max-width:760px;margin:0;line-height:1.6;">
      Decision surface for consolidation, renegotiation, dual-sourcing, and process-improvement
      calls across a {len(scored)}-supplier hardware supply base. Suppliers are ranked on six
      dimensions: spend concentration, sole-source exposure, defect rate, lead-time variance,
      on-time delivery, and late-order risk.
    </p>
  </header>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-top:28px;">
    {kpis}
  </div>

  {section_title("Supplier risk scorecard", "Every supplier, ranked by weighted risk score. Higher score means higher risk.")}
  {table_wrap_open}
    <thead><tr style="background:#0f1319;">{scorecard_head}</tr></thead>
    <tbody>{scorecard_rows(scored)}</tbody>
  {table_wrap_close}

  {section_title("Modeled annual savings", "Five documented opportunity buckets. Each rate is a conservative assumption applied to a real dollar base.")}
  {table_wrap_open}
    <thead><tr style="background:#0f1319;">{savings_head}</tr></thead>
    <tbody>{savings_rows(buckets, total_savings)}</tbody>
  {table_wrap_close}

  {section_title("Part-family risk segmentation", "Supplier risk rolled up to commodity family, with the dominant risk driver and the action it calls for.")}
  {table_wrap_open}
    <thead><tr style="background:#0f1319;">{seg_head}</tr></thead>
    <tbody>{segmentation_rows(seg)}</tbody>
  {table_wrap_close}

  {section_title("Charts", "Spend concentration, risk ranking, quality against delivery predictability, and the on-time trend.")}
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px;">
    {chart_cards()}
  </div>

  <footer style="margin-top:56px;padding-top:20px;border-top:1px solid #1f252d;font-size:13px;color:#5b6370;">
    Generated by the Supply Chain Spend and Supplier Risk Optimizer pipeline. All figures are computed
    from the committed dataset and reproduce on every run.
  </footer>

</div>
</body>
</html>"""


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        metrics = load_supplier_metrics(conn)
        scored = compute_scores(metrics)
        scored["risk_band"] = scored["risk_score"].apply(
            lambda s: "High" if s >= 55 else "Medium" if s >= 35 else "Low"
        )
        buckets, total_savings, total_spend = savings_model(scored, conn)
    finally:
        conn.close()

    seg = build_segmentation(scored)
    html = build_html(scored, buckets, total_savings, total_spend, seg)

    out_path = os.path.join(OUTPUT_DIR, "dashboard.html")
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Executive dashboard written to {out_path}")


if __name__ == "__main__":
    main()
