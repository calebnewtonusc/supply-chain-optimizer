# Supply Chain Spend and Supplier Risk Optimizer

A procurement analytics tool that ranks a hardware supply base by spend concentration, lead-time variance, defect rate, delivery reliability, and dollarized late-order exposure, then surfaces where to negotiate, where to dual-source, and which suppliers to put on a corrective action plan.

## Why this matters

An organization that builds complex hardware runs on hundreds of suppliers, and the risk is never spread evenly. A small number of them quietly control most of the spend, gate the build schedule, or drift on quality until a line goes down. The job of business operations is to find those suppliers before they cost you a launch date, and to redirect spend and attention where the return is highest. This tool does that mechanically: it turns 5,000 purchase orders into a ranked, defensible action list a buyer or an ops lead can work down on a Monday morning.

## What the analysis found

Numbers below are the actual output of the pipeline in this repository, computed from the committed dataset (`data/`), the scorecard (`output/supplier_scorecard.csv`), and the SQL analytics.

- **Total spend analyzed:** $350,360,938 across 5,000 purchase orders and 40 suppliers over a 24 month window.
- **Concentration:** the top 10 suppliers control 60.3% of total spend. Composites is the most concentrated category (Herfindahl index 5,511, one supplier owns 72% of it across only 4 qualified suppliers).
- **Single-source, high-spend risk:** Kestrel Metals is single-source and carries 14.6% of all spend ($51.2M) at the highest risk score in the base (45). Keystone Technologies is single-source at 10.2% of spend ($35.7M). These are the two clearest dual-sourcing gaps.
- **Delivery:** the supply-base average on-time rate is 69.2%. The worst performer, Quantum Precision Works, delivers on time only 16.9% of the time across 65 POs.
- **Quality:** Helios Technologies runs 15,015 defective parts per million, and Redwood Systems runs 13,282 PPM, both an order of magnitude above the base. These are the top corrective-action targets.
- **Schedule risk in dollars:** $108,055,633 of PO value arrived after the promised date. The single largest concentration of that exposure sits with Kestrel Metals ($13.0M).
- **Estimated annualized opportunity:** ~~$7.7M, split between tail-spend consolidation (~$2.8M from the 16 smallest suppliers) and renegotiation on concentrated single-source categories (~~$4.9M).

### Recommended actions, in priority order

1. **Qualify a second source for Kestrel Metals (Composites) and Keystone Technologies (Propulsion).** Together they represent roughly a quarter of total spend with no backup, which is both a continuity risk and a negotiating disadvantage.
2. **Open corrective action on Helios Technologies and Redwood Systems.** Both are running defect rates that will generate rework and scrap cost regardless of price.
3. **Put Quantum Precision Works and Everest Metals on a delivery improvement plan.** Everest also has the highest lead-time variance in the base, which makes its delivery timing impossible to plan around.
4. **Consolidate the 16-supplier tail.** Fragmented low-volume spend is where the easiest pricing and overhead savings live.

## How it works

```
data/generate_data.py   ->  suppliers.csv, purchase_orders.csv     (synthetic, seeded)
sql/schema.sql          ->  procurement.db tables + indexes
src/load_db.py          ->  loads CSVs into SQLite
sql/analytics.sql       ->  the analytical query library
src/analyze.py          ->  executive summary + four charts
src/supplier_scorecard  ->  weighted risk score, ranking, action list, CSV
```

Everything runs on SQLite through Python's built-in `sqlite3`, so there is no database to stand up. The synthetic data is deterministic (the RNG is seeded), so the numbers above reproduce on every run.

## Supplier Risk Score methodology

Each supplier gets a single score from 0 to 100, where higher means riskier. Five metrics feed the score. Each is normalized to a 0 to 1 scale across the supply base using min-max scaling, oriented so that 1 is always the riskier end, then combined with the weights below.

| Metric              | What it measures                                       | Direction         | Weight |
| ------------------- | ------------------------------------------------------ | ----------------- | ------ |
| Spend concentration | Share of total spend on this supplier                  | Higher is riskier | 0.25   |
| Defect rate (PPM)   | Defective parts per million received                   | Higher is riskier | 0.25   |
| Lead-time variance  | Coefficient of variation of lead time (stddev / mean)  | Higher is riskier | 0.20   |
| On-time delivery    | Percent of POs received on or before the promised date | Lower is riskier  | 0.15   |
| Late-order exposure | Dollar value of POs that arrived late                  | Higher is riskier | 0.15   |

Concentration and defect rate carry the heaviest weight because they are the two failure modes that cost the most: a single-source supplier can halt a build, and a high defect rate silently taxes every unit. Lead-time variance is weighted above raw on-time rate because unpredictability is harder to plan around than a supplier that is reliably a few days slow. Weights sum to 1.0 and live in one dictionary at the top of `src/supplier_scorecard.py`, so the model is easy to re-weight and defend.

The scorecard then applies two rules on top of the score:

- **Dual-source flag:** any single-source supplier at or above 3% of total spend is flagged as a dual-sourcing candidate.
- **Process-improvement targets:** suppliers are re-ranked by combined quality and delivery risk to produce the corrective-action shortlist.

The savings estimate is deliberately conservative: 8% of tail spend recovered through consolidation, and 3% of concentrated single-source spend recovered through renegotiation. Both are defensible bottom-of-range procurement assumptions, not aspirational figures.

## Charts

**Spend concentration (Pareto).** How few suppliers make up most of the spend.

![Spend Pareto](output/spend_pareto.png)

**Supplier risk ranking.** The full score, top 15, colored by risk band.

![Risk ranking](output/risk_ranking.png)

**Quality vs delivery predictability.** Defect PPM against lead-time variance, bubble sized by spend. The suppliers in the upper right that are also large bubbles are the ones that matter most.

![Quality vs delivery](output/quality_vs_delivery.png)

**On-time delivery trend.** Fleet on-time rate by order month.

![On-time trend](output/on_time_trend.png)

## How to run

```bash
# from the repo root
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# run the full pipeline end to end
./run.sh
# or, equivalently
.venv/bin/python run_all.py
```

The pipeline regenerates the data, rebuilds `procurement.db`, prints the executive summary and the ranked scorecard to the terminal, and writes the charts and `supplier_scorecard.csv` into `output/`. The generated CSVs and charts are committed, so the analysis is fully viewable without running anything.

## Repository layout

```
data/generate_data.py       synthetic procurement data generator (seeded)
data/suppliers.csv          40 suppliers (committed)
data/purchase_orders.csv    5,000 purchase orders (committed)
sql/schema.sql              table definitions, keys, indexes
sql/analytics.sql           commented analytical query library
src/load_db.py              CSV to SQLite loader
src/supplier_scorecard.py   weighted risk score and action list (core deliverable)
src/analyze.py              executive summary and chart generation
output/                     scorecard CSV and charts (committed)
run.sh / run_all.py         full pipeline runners
```

## What I would do next

- **Bring in real data.** Swap the synthetic generator for an ERP extract (SAP, Oracle, or NetSuite) and keep the schema and scoring untouched. The pipeline is built so only the loader changes.
- **Add supplier financial health.** A concentration risk is far worse when the sole source is also financially fragile. Layering a credit or D&B signal into the score would catch the suppliers most likely to fail without warning.
- **Model the true cost of a late part.** Right now late exposure is measured as PO dollar value. The sharper metric is schedule impact: which late parts actually sat on the critical path, and what did the slip cost downstream.
- **Ship a weekly digest.** The scorecard is a batch job today. The natural next step is a scheduled run that flags any supplier whose score moves more than a threshold week over week, so the ops team watches deltas instead of re-reading the whole list.

All glory to God! ✝️❤️
