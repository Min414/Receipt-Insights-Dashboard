"""One-off load: raw uploaded table -> cleaned, tagged `receipts` table in TigerData.
Uses cleaning.py, so the dashboard and this script always clean the same way.
Warning: it empties `receipts` first, so any receipts added through the dashboard are removed."""
import os

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

from cleaning import clean_frame

load_dotenv(override=True)
RAW_TABLE = "DHRD"   # the table you uploaded in Tiger Console

COLS = ["ts", "consumer_id", "receipt_id", "line_number", "store_name", "product_raw", "product",
        "brand", "category", "is_pg", "quantity", "unit_price", "line_total", "promotion",
        "total_spend"]

conn = psycopg2.connect(os.environ["DATABASE_URL"])
with conn.cursor() as cur:
    cur.execute(f'SELECT * FROM "{RAW_TABLE}"')
    raw = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])

clean = clean_frame(raw)
data = clean[COLS].astype(object).where(clean[COLS].notna(), None)

with conn, conn.cursor() as cur:
    cur.execute("DELETE FROM receipts")  # so you can re-run safely
    execute_values(cur, f"INSERT INTO receipts ({','.join(COLS)}) VALUES %s",
                   [tuple(r) for r in data.itertuples(index=False)])
conn.close()

conn = psycopg2.connect(os.environ["DATABASE_URL"])
conn.autocommit = True  # refresh cannot run inside a transaction
with conn.cursor() as cur:
    cur.execute("CALL refresh_continuous_aggregate('weekly_share', NULL, NULL)")
conn.close()

print("products:", clean["product"].nunique(), "| P&G lines:", int(clean["is_pg"].sum()),
      "| lines on promotion:", int(clean["promotion"].notna().sum()))
