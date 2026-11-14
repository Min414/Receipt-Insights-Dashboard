# Receipt insights for P&G

Built for DurHack, P&G Challenge 1: innovating with complex receipt data for consumer and business insights.

Supermarket receipts are messy: truncated product names, OCR errors, missing context. This project cleans them, stores them in TigerData, and turns them into actions a P&G category team could take. A new CSV dropped into the dashboard updates every chart, and Gemini turns the computed numbers into three prioritised recommendations.

## What it does

- **Cleans product names.** Fixes OCR swaps (`ACT1VIA` becomes `ACTIVIA`), expands abbreviations and merges truncated variants. The 210 raw names in the sample data collapse to 99 products.
- **Tags every line** with brand, category and whether it is a P&G brand.
- **Stores receipts in TigerData** (Postgres with TimescaleDB), with a continuous aggregate for weekly P&G share by store and category.
- **Shows where P&G wins and leaks:**
  - share of spend in each category, and where P&G has no brand at all;
  - promotion intensity against rival brands;
  - repeat buyers lost to rival brands, per P&G brand;
  - cross-sell gaps, such as households that buy Ariel but never Lenor;
  - P&G share by store, and a single-household view.
- **Recommends actions.** Only the computed numbers (never the raw receipts) go to Gemini, which returns three prioritised actions with the evidence quoted. The exact numbers sent are shown in the app so anyone can check them.
- **Updates live.** Upload a new CSV in the sidebar. The app adds only receipts it has not seen, cleans them, and refreshes the weekly view.

## Stack

Python, pandas, Streamlit, Plotly, TigerData, Gemini API (`google-genai`).

## Project files

| File | Purpose |
|---|---|
| `app.py` | Streamlit dashboard, CSV upload and Gemini recommendations |
| `cleaning.py` | Product-name cleaning, brand and category tagging |
| `metrics.py` | All insight calculations (share, promotion, leakage, cross-sell) |
| `load.py` | One-off load from the raw uploaded table into `receipts` |
| `make_synthetic.py` | Generates a new batch of synthetic receipts in the same format |
| `.env.example` | The settings the app needs (copy to `.env`) |

## Setup

1. **Install the packages** (Python 3.10 or newer):

   ```
   pip install -r requirements.txt
   ```

2. **Create a TigerData service** in Tiger Console and save the connection string.

3. **Create `.env`** by copying `.env.example` and filling it in:

   ```
   DATABASE_URL=postgres://USER:PASSWORD@HOST:PORT/DBNAME?sslmode=require
   GEMINI_API_KEY=your-key
   GEMINI_MODEL=gemini-3.5-flash-lite
   ```

   Never commit `.env`. It is listed in `.gitignore`.

4. **Create the tables.** Run this once in the Tiger Console SQL Editor:

   ```sql
   CREATE TABLE receipts (
     ts timestamptz NOT NULL,
     consumer_id text, receipt_id text, line_number int,
     store_name text, product_raw text, product text,
     brand text, category text, is_pg boolean,
     quantity int, unit_price numeric, line_total numeric,
     promotion text, total_spend numeric
   );
   SELECT create_hypertable('receipts', 'ts');

   CREATE MATERIALIZED VIEW weekly_share
   WITH (timescaledb.continuous) AS
   SELECT time_bucket('7 days', ts) AS week,
          store_name, category,
          SUM(line_total) AS total_rev,
          SUM(CASE WHEN is_pg THEN line_total ELSE 0 END) AS pg_rev,
          COUNT(*) AS lines,
          SUM(CASE WHEN promotion IS NOT NULL THEN 1 ELSE 0 END) AS promo_lines
   FROM receipts
   GROUP BY week, store_name, category
   WITH NO DATA;

   CALL refresh_continuous_aggregate('weekly_share', NULL, NULL);
   ```

5. **Load the data.** Upload the receipt CSV to TigerData as a raw table, set `RAW_TABLE` in `load.py` to its name, then run:

   ```
   python load.py
   ```

   It should print `products: 99 | P&G lines: 2243` for the sample data.

6. **Run the dashboard:**

   ```
   python -m streamlit run app.py
   ```

## Running without a database

Set `CSV_MODE=1` in `.env` and keep the receipt CSV in the project folder (override the file name with `CSV_FILE`). The dashboard then reads the CSV directly. Uploads and the weekly view refresh are switched off in this mode. It is useful as a demo fallback.

## Try the live update

`make_synthetic.py` generates a fresh batch in the same format as the original data:

```
python make_synthetic.py 2026-10-01 2026-10-31 october.csv
```

Upload the result in the dashboard sidebar and click **Process upload**. New receipts are added, duplicates are skipped, and the charts update.

## How the numbers are defined

- **Lost to rival brands:** of a household's repeat purchases of a P&G brand in a category, the share where the next purchase was a brand that is not P&G. A move from one P&G brand to another does not count as lost.
- **Promotion intensity:** the share of lines bought on a promotion, for a P&G brand against the other brands in its category.
- **Cross-sell gap:** households that buy brand A but never brand B.

## Data and privacy

- All data is **synthetic**. No real shopper data is used or collected.
- The LLM sees only aggregated metrics, never receipts or household IDs.
- Credentials live in `.env` and are never committed.

## Limitations

- The data is synthetic and the samples behind some metrics are small (100 to 200 repeat purchases per brand), so treat results as directional and validate them on real receipts.
- Name cleaning is rule-based and tuned to this dataset. Unrecognised new product names are listed after an upload so they can be reviewed.
- Gemini model names change often. If a call fails, set `GEMINI_MODEL` in `.env` to a current model name.
