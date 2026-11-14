import json
import os

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st
from dotenv import load_dotenv
from psycopg2.extras import execute_values

import metrics
from cleaning import clean_frame

load_dotenv(override=True)
st.set_page_config(page_title="Receipt insights for P&G", layout="wide")

BLUE = "#0B4EA2"
COLS = ["ts", "consumer_id", "receipt_id", "line_number", "store_name", "product_raw", "product",
        "brand", "category", "is_pg", "quantity", "unit_price", "line_total", "promotion",
        "total_spend"]


# ---------- database helpers ----------
def connect(autocommit=False):
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    conn.autocommit = autocommit
    return conn


def query(sql):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])
    finally:
        conn.close()


@st.cache_data(show_spinner="Loading receipts...")
def load_receipts():
    df = query("SELECT ts, consumer_id, receipt_id, line_number, store_name, product, brand, "
               "category, is_pg, quantity, unit_price, line_total, promotion FROM receipts")
    for c in ["unit_price", "line_total"]:
        df[c] = df[c].astype(float)
    return df


@st.cache_data(show_spinner=False)
def load_weekly():
    df = query("SELECT week, store_name, category, total_rev, pg_rev FROM weekly_share ORDER BY week")
    for c in ["total_rev", "pg_rev"]:
        df[c] = df[c].astype(float)
    return df


def ingest(file):
    """Clean an uploaded CSV, add only receipts we don't have yet, refresh the weekly view."""
    raw = pd.read_csv(file)
    raw.columns = [c.replace(" ", "_") for c in raw.columns]
    have = set(query("SELECT DISTINCT receipt_id FROM receipts")["receipt_id"])
    new = raw[~raw["Receipt_ID"].isin(have)]
    skipped = raw["Receipt_ID"].nunique() - new["Receipt_ID"].nunique()
    if new.empty:
        return f"No new receipts. {skipped} receipts were already loaded."

    known_raw = query("SELECT DISTINCT product_raw FROM receipts")["product_raw"]
    known_clean = set(query("SELECT DISTINCT product FROM receipts")["product"])
    clean = clean_frame(new, extra_names=known_raw)
    unmatched = sorted(set(clean["product"]) - known_clean)

    data = clean[COLS].astype(object).where(clean[COLS].notna(), None)
    conn = connect()
    try:
        with conn, conn.cursor() as cur:
            execute_values(cur, f"INSERT INTO receipts ({','.join(COLS)}) VALUES %s",
                           [tuple(r) for r in data.itertuples(index=False)])
    finally:
        conn.close()

    conn = connect(autocommit=True)  # refresh cannot run inside a transaction
    try:
        with conn.cursor() as cur:
            cur.execute("CALL refresh_continuous_aggregate('weekly_share', NULL, NULL)")
    finally:
        conn.close()

    st.cache_data.clear()
    msg = (f"Added {clean['receipt_id'].nunique()} receipts "
           f"({len(clean)} lines). Skipped {skipped} already loaded.")
    if unmatched:
        msg += " New product names to review: " + "; ".join(unmatched)
    return msg


# ---------- Gemini ----------
def ask_gemini(facts):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                          http_options=types.HttpOptions(timeout=30_000))  # give up on each model after 30 s
    prompt = (
        "You advise a P&G category team using supermarket receipt data. Use ONLY the numbers in "
        "the JSON below. Do not invent figures. Give exactly three prioritised actions. For each: "
        "the action, the evidence (quote the exact numbers), the expected impact, and one caveat. "
        "Keep it under 250 words. The data is synthetic and samples are small, so say what you "
        "would validate on real data.\n\n" + json.dumps(facts))
    # Low thinking keeps this fast. Gemini 3 models think a lot by default.
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        max_output_tokens=4000)
    models = []
    for m in [os.getenv("GEMINI_MODEL"), "gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash"]:
        if m and m not in models:
            models.append(m)
    retry_on = ("404", "NOT_FOUND", "503", "UNAVAILABLE", "504", "DEADLINE_EXCEEDED", "429")
    last = None
    for m in models:
        try:
            resp = client.models.generate_content(model=m, contents=prompt, config=config)
            return resp.text or "Gemini returned no text. Try again."
        except Exception as e:
            last = e
            if not any(code in str(e) for code in retry_on):
                break  # a different kind of error (e.g. bad key): stop
    raise last


# ---------- sidebar: upload ----------
st.sidebar.header("Add receipts")
up = st.sidebar.file_uploader("CSV with the same columns", type="csv")
if up is not None and st.sidebar.button("Process upload", type="primary"):
    try:
        st.session_state["msg"] = ingest(up)
        st.session_state.pop("recs", None)
    except Exception as e:
        st.session_state["msg"] = f"Upload failed: {e}"
    st.rerun()
if "msg" in st.session_state:
    st.sidebar.info(st.session_state["msg"])

# ---------- main ----------
df = load_receipts()
if df.empty:
    st.warning("The receipts table is empty. Run load.py first.")
    st.stop()

st.title("Where P&G wins and leaks in the basket")
st.caption(f"{df['receipt_id'].nunique():,} receipts from {df['consumer_id'].nunique()} households, "
           f"{df['ts'].min().date()} to {df['ts'].max().date()}. Synthetic data.")

cats = df[df["category"] != "Other"]
pg_share = 100 * cats.loc[cats["is_pg"], "line_total"].sum() / cats["line_total"].sum()
promo_pct = 100 * cats["promotion"].notna().mean()
c1, c2, c3 = st.columns(3)
c1.metric("P&G share of home and personal care spend", f"{pg_share:.1f}%")
c2.metric("Lines bought on promotion", f"{promo_pct:.1f}%")
c3.metric("Categories with no P&G brand", int((metrics.category_penetration(df)["pg_households"] == 0).sum()))

tab1, tab2, tab3, tab4 = st.tabs(["Share and promotions", "Where P&G leaks",
                                  "Shopper view", "Recommendations"])

with tab1:
    wk = load_weekly()
    left, right = st.columns(2)
    cat_pick = left.selectbox("Category", ["All"] + sorted(wk["category"].unique()))
    store_pick = right.selectbox("Store", ["All"] + sorted(wk["store_name"].unique()))
    w = wk
    if cat_pick != "All":
        w = w[w["category"] == cat_pick]
    if store_pick != "All":
        w = w[w["store_name"] == store_pick]
    w = w.groupby("week")[["total_rev", "pg_rev"]].sum().reset_index()
    w["P&G share (%)"] = 100 * w["pg_rev"] / w["total_rev"]
    fig = px.line(w, x="week", y="P&G share (%)", markers=True, color_discrete_sequence=[BLUE])
    fig.update_layout(yaxis_range=[0, 100], margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("Promotion intensity against competitors")
    bt = metrics.brand_table(df)
    pgbt = bt[bt["is_pg"]].sort_values("promo_pct", ascending=False)
    show = pgbt[["category", "brand", "lines", "lines_share_in_category_pct", "promo_pct",
                 "competitor_promo_pct"]].rename(columns={
        "lines_share_in_category_pct": "share of category lines (%)",
        "promo_pct": "on promo (%)", "competitor_promo_pct": "competitors on promo (%)"})
    st.dataframe(show, hide_index=True, use_container_width=True)

    st.subheader("Household reach by category")
    pen = metrics.category_penetration(df)
    st.dataframe(pen.rename(columns={
        "pg_household_pct": "households buying P&G (%)",
        "pg_revenue_share_pct": "P&G revenue share (%)"}), hide_index=True, use_container_width=True)

with tab2:
    st.subheader("Repeat buyers who switch to another brand")
    lk = metrics.leakage(df)
    fig = px.bar(lk, x="switched_pct", y="brand", color="category", orientation="h",
                 hover_data=["repeat_purchases"], labels={"switched_pct": "next purchase was a different brand (%)"})
    fig.update_layout(margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)
    st.caption("Based on repeat purchases per household and category. Small samples: directional only.")

    st.subheader("Cross-sell gaps")
    gaps = pd.DataFrame([metrics.cross_sell_gap(df, a, b) for a, b in metrics.CROSS_SELL_PAIRS])
    st.dataframe(gaps.rename(columns={
        "if_buys": "buys", "but_not": "but never buys", "households_buying_a": "households",
        "of_which_never_buy_b": "gap (households)", "pct": "gap (%)"}), hide_index=True)

    st.subheader("P&G share of spend by store")
    st.dataframe(metrics.store_skew(df), hide_index=True)

with tab3:
    cid = st.selectbox("Household", sorted(df["consumer_id"].unique()))
    h = df[df["consumer_id"] == cid]
    a, b, c = st.columns(3)
    a.metric("Receipts", h["receipt_id"].nunique())
    b.metric("Total spend", f"£{h['line_total'].sum():,.2f}")
    c.metric("Lines on promotion", f"{100 * h['promotion'].notna().mean():.0f}%")
    by_cat = h.groupby("category")["line_total"].sum().reset_index().sort_values("line_total")
    fig = px.bar(by_cat, x="line_total", y="category", orientation="h",
                 labels={"line_total": "spend (£)"}, color_discrete_sequence=[BLUE])
    fig.update_layout(margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)
    st.write("Most bought:", ", ".join(h["product"].value_counts().head(5).index.str.title()))

with tab4:
    facts = metrics.summary(df)
    st.write("Gemini sees only the computed numbers below, never the raw receipts.")
    if st.button("Generate recommendations", type="primary"):
        try:
            with st.spinner("Asking Gemini..."):
                st.session_state["recs"] = ask_gemini(facts)
        except Exception as e:
            st.session_state["recs"] = f"Could not reach Gemini: {e}"
    if "recs" in st.session_state:
        st.markdown(st.session_state["recs"])
    with st.expander("Numbers sent to Gemini"):
        st.json(facts)
