"""
Load the generated CSVs into a SQLite database.

Reads sql/schema.sql to build the tables, then bulk-inserts the two CSV
files. Running this is idempotent: the schema drops and recreates the
tables each time so the database always reflects the current CSVs.
"""

import csv
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
SQL_DIR = os.path.join(ROOT, "sql")
DB_PATH = os.path.join(ROOT, "procurement.db")


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def main():
    schema_path = os.path.join(SQL_DIR, "schema.sql")
    with open(schema_path) as f:
        schema_sql = f.read()

    suppliers = load_csv(os.path.join(DATA_DIR, "suppliers.csv"))
    orders = load_csv(os.path.join(DATA_DIR, "purchase_orders.csv"))

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(schema_sql)

        conn.executemany(
            """
            INSERT INTO suppliers
                (supplier_id, name, category, region, country,
                 is_dual_sourced, onboarding_date)
            VALUES
                (:supplier_id, :name, :category, :region, :country,
                 :is_dual_sourced, :onboarding_date)
            """,
            suppliers,
        )

        conn.executemany(
            """
            INSERT INTO purchase_orders
                (po_id, supplier_id, category, order_date, promised_date,
                 received_date, quantity, unit_cost, total_cost,
                 defect_units, on_time)
            VALUES
                (:po_id, :supplier_id, :category, :order_date, :promised_date,
                 :received_date, :quantity, :unit_cost, :total_cost,
                 :defect_units, :on_time)
            """,
            orders,
        )

        conn.commit()

        supplier_count = conn.execute("SELECT COUNT(*) FROM suppliers").fetchone()[0]
        order_count = conn.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]
        print(f"Loaded {supplier_count} suppliers and {order_count} purchase orders")
        print(f"Database written to {DB_PATH}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
