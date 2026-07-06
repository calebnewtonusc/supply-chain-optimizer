-- Procurement analytics schema (SQLite).
--
-- Two tables model the procurement domain: a supplier master and the
-- purchase order transaction log. Indexes are added on the columns the
-- analytical queries filter and group by most often.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS purchase_orders;
DROP TABLE IF EXISTS suppliers;

-- Supplier master. One row per qualified supplier.
CREATE TABLE suppliers (
    supplier_id      TEXT PRIMARY KEY,
    name             TEXT    NOT NULL,
    category         TEXT    NOT NULL,
    region           TEXT    NOT NULL,
    country          TEXT    NOT NULL,
    is_dual_sourced  INTEGER NOT NULL CHECK (is_dual_sourced IN (0, 1)),
    onboarding_date  TEXT    NOT NULL
);

-- Purchase order transaction log. One row per PO.
--   total_cost   = unit_cost * quantity (denormalized for query speed)
--   on_time      = 1 if received on or before the promised date, else 0
--   defect_units = units rejected on incoming inspection
CREATE TABLE purchase_orders (
    po_id          TEXT PRIMARY KEY,
    supplier_id    TEXT    NOT NULL,
    category       TEXT    NOT NULL,
    order_date     TEXT    NOT NULL,
    promised_date  TEXT    NOT NULL,
    received_date  TEXT    NOT NULL,
    quantity       INTEGER NOT NULL CHECK (quantity > 0),
    unit_cost      REAL    NOT NULL CHECK (unit_cost >= 0),
    total_cost     REAL    NOT NULL CHECK (total_cost >= 0),
    defect_units   INTEGER NOT NULL CHECK (defect_units >= 0),
    on_time        INTEGER NOT NULL CHECK (on_time IN (0, 1)),
    FOREIGN KEY (supplier_id) REFERENCES suppliers (supplier_id)
);

CREATE INDEX idx_po_supplier   ON purchase_orders (supplier_id);
CREATE INDEX idx_po_category   ON purchase_orders (category);
CREATE INDEX idx_po_order_date ON purchase_orders (order_date);
CREATE INDEX idx_sup_category  ON suppliers (category);
