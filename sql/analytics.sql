-- Procurement analytics query library.
--
-- Each query answers one procurement question. They are written to run
-- against the SQLite database produced by src/load_db.py and are executed
-- by src/analyze.py. Named markers (-- name: <id>) let the Python layer
-- pull an individual query out of this file.


-- name: spend_by_supplier
-- Question: Where does our money go? Total spend, order volume, and share
-- of total spend per supplier, ranked from largest to smallest.
SELECT
    s.supplier_id,
    s.name,
    s.category,
    s.is_dual_sourced,
    COUNT(po.po_id)                                   AS order_count,
    ROUND(SUM(po.total_cost), 2)                      AS total_spend,
    ROUND(
        100.0 * SUM(po.total_cost) /
        (SELECT SUM(total_cost) FROM purchase_orders), 3
    )                                                 AS pct_of_total_spend
FROM suppliers s
JOIN purchase_orders po ON po.supplier_id = s.supplier_id
GROUP BY s.supplier_id, s.name, s.category, s.is_dual_sourced
ORDER BY total_spend DESC;


-- name: spend_by_category
-- Question: How is spend distributed across commodity categories, and how
-- many suppliers cover each one?
SELECT
    category,
    COUNT(DISTINCT supplier_id)      AS supplier_count,
    COUNT(po_id)                     AS order_count,
    ROUND(SUM(total_cost), 2)        AS total_spend
FROM purchase_orders
GROUP BY category
ORDER BY total_spend DESC;


-- name: category_concentration_hhi
-- Question: How concentrated is spend within each category? The Herfindahl
-- Hirschman Index (HHI) sums the squared percentage market shares of the
-- suppliers in a category. Values approach 10000 when one supplier owns the
-- category and fall toward zero when spend is evenly spread. A category with
-- a high HHI and few suppliers is a single-source concentration risk.
WITH supplier_category_spend AS (
    SELECT
        category,
        supplier_id,
        SUM(total_cost) AS supplier_spend
    FROM purchase_orders
    GROUP BY category, supplier_id
),
category_totals AS (
    SELECT category, SUM(supplier_spend) AS category_spend
    FROM supplier_category_spend
    GROUP BY category
)
SELECT
    scs.category,
    COUNT(*)                                                       AS supplier_count,
    ROUND(ct.category_spend, 2)                                    AS category_spend,
    ROUND(SUM(
        (100.0 * scs.supplier_spend / ct.category_spend) *
        (100.0 * scs.supplier_spend / ct.category_spend)
    ), 1)                                                          AS hhi,
    ROUND(MAX(100.0 * scs.supplier_spend / ct.category_spend), 1)  AS top_supplier_share_pct
FROM supplier_category_spend scs
JOIN category_totals ct ON ct.category = scs.category
GROUP BY scs.category, ct.category_spend
ORDER BY hhi DESC;


-- name: top_n_share
-- Question: What share of total spend is controlled by the ten largest
-- suppliers? A high top-N share means bargaining power and continuity risk
-- are concentrated in a small number of relationships.
WITH ranked AS (
    SELECT
        supplier_id,
        SUM(total_cost) AS supplier_spend
    FROM purchase_orders
    GROUP BY supplier_id
    ORDER BY supplier_spend DESC
    LIMIT 10
)
SELECT
    ROUND(SUM(supplier_spend), 2) AS top10_spend,
    (SELECT ROUND(SUM(total_cost), 2) FROM purchase_orders) AS total_spend,
    ROUND(
        100.0 * SUM(supplier_spend) /
        (SELECT SUM(total_cost) FROM purchase_orders), 1
    ) AS top10_share_pct
FROM ranked;


-- name: on_time_delivery
-- Question: How reliable is each supplier on delivery schedule? On-time
-- delivery rate is the share of that supplier's POs received on or before
-- the promised date.
SELECT
    s.supplier_id,
    s.name,
    COUNT(po.po_id)                                         AS order_count,
    ROUND(100.0 * SUM(po.on_time) / COUNT(po.po_id), 1)     AS on_time_pct
FROM suppliers s
JOIN purchase_orders po ON po.supplier_id = s.supplier_id
GROUP BY s.supplier_id, s.name
ORDER BY on_time_pct ASC;


-- name: lead_time_stats
-- Question: How long and how predictable is each supplier's lead time?
-- Average lead time is the mean days from order to receipt. The population
-- standard deviation and the coefficient of variation (stddev / mean)
-- measure predictability. A high coefficient of variation means delivery
-- timing cannot be planned around.
SELECT
    s.supplier_id,
    s.name,
    COUNT(po.po_id) AS order_count,
    ROUND(AVG(julianday(po.received_date) - julianday(po.order_date)), 1) AS avg_lead_days,
    ROUND(
        SQRT(
            AVG(
                (julianday(po.received_date) - julianday(po.order_date)) *
                (julianday(po.received_date) - julianday(po.order_date))
            )
            -
            AVG(julianday(po.received_date) - julianday(po.order_date)) *
            AVG(julianday(po.received_date) - julianday(po.order_date))
        ), 1
    ) AS stddev_lead_days
FROM suppliers s
JOIN purchase_orders po ON po.supplier_id = s.supplier_id
GROUP BY s.supplier_id, s.name
ORDER BY stddev_lead_days DESC;


-- name: defect_ppm
-- Question: What is each supplier's incoming quality, expressed as defective
-- parts per million (PPM)? PPM is the industry standard quality metric:
-- (defective units / total units received) * 1,000,000.
SELECT
    s.supplier_id,
    s.name,
    SUM(po.quantity)                                                    AS units_received,
    SUM(po.defect_units)                                               AS defect_units,
    ROUND(1000000.0 * SUM(po.defect_units) / SUM(po.quantity), 0)      AS defect_ppm
FROM suppliers s
JOIN purchase_orders po ON po.supplier_id = s.supplier_id
GROUP BY s.supplier_id, s.name
ORDER BY defect_ppm DESC;


-- name: late_order_exposure
-- Question: How much dollar value is tied up in late deliveries per supplier?
-- Late-order exposure is the total cost of POs that arrived after the
-- promised date. It quantifies the schedule risk a supplier introduces in
-- dollar terms, which is what an operations org actually budgets around.
SELECT
    s.supplier_id,
    s.name,
    SUM(CASE WHEN po.on_time = 0 THEN 1 ELSE 0 END)                       AS late_orders,
    ROUND(SUM(CASE WHEN po.on_time = 0 THEN po.total_cost ELSE 0 END), 2) AS late_exposure_usd
FROM suppliers s
JOIN purchase_orders po ON po.supplier_id = s.supplier_id
GROUP BY s.supplier_id, s.name
ORDER BY late_exposure_usd DESC;


-- name: on_time_trend_by_month
-- Question: Is delivery reliability improving or degrading over time across
-- the whole supply base? On-time rate aggregated by order month.
SELECT
    substr(order_date, 1, 7)                          AS order_month,
    COUNT(po_id)                                      AS order_count,
    ROUND(100.0 * SUM(on_time) / COUNT(po_id), 1)     AS on_time_pct
FROM purchase_orders
GROUP BY order_month
ORDER BY order_month;
