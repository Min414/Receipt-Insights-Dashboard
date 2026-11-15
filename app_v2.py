import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

import metrics
from cleaning import clean_frame, clean_promotion

load_dotenv(override=True)
st.set_page_config(page_title="Receipt insights for P&G", layout="wide")

# Set CSV_MODE=1 in .env to run from the local CSV (no database). Useful as a demo fallback.
CSV_MODE = os.getenv("CSV_MODE") == "1"
CSV_FILE = os.getenv("CSV_FILE", "DH_Synthtic_Receipt_Database.csv")

# ---------- palette ----------
INK = "#141413"     # text
CLAY = "#C6613F"    # P&G (Claude clay)
GREY = "#D3CFC2"    # rival brands
RUST = "#8F3B22"   # leakage
SAND = "#F0EEE6"    # sidebar and quiet surfaces
LINE = "#E3E0D4"    # rules and gridlines
CREAM = "#FAF9F5"   # page background
MUTED = "#4B4A46"   # secondary text

COLS = ["ts", "consumer_id", "receipt_id", "line_number", "store_name", "product_raw", "product",
        "brand", "category", "is_pg", "quantity", "unit_price", "line_total", "promotion",
        "total_spend"]

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:wght@600;700&family=Public+Sans:wght@400;500;600&display=swap');
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {{ background: {CREAM}; }}
html, body, [data-testid="stAppViewContainer"], .stMarkdown, label, p, li {{
    font-family: 'Public Sans', system-ui, sans-serif; color: {INK}; }}
h1, h2, h3, h4, .hero h1, [data-testid="stHeading"] h2, [data-testid="stHeading"] h3 {{ font-family: 'Lora', Georgia, serif !important; color: {INK};
    letter-spacing: -0.015em; font-weight: 700; }}
.block-container {{ max-width: 1120px; padding-top: 2.2rem; padding-bottom: 4rem; }}
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stSidebar"] {{ background: {SAND}; border-right: 1px solid {LINE}; }}
[data-testid="stSidebar"] h3 {{ font-size: 1.05rem; }}

.hero h1 {{ font-size: 2.35rem; line-height: 1.12; max-width: 24em; margin: 0 0 .6rem 0; padding: 0; }}
.hero p {{ font-size: 1.02rem; line-height: 1.55; max-width: 44em; margin: 0; color: {MUTED}; }}
.stats {{ display: flex; flex-wrap: wrap; margin: 1.6rem 0 .4rem 0; border-top: 1px solid {LINE};
    border-bottom: 1px solid {LINE}; }}
.stats > div {{ flex: 1 1 220px; padding: 1rem 1.4rem 1rem 0; }}
.stats > div + div {{ padding-left: 1.4rem; border-left: 1px solid {LINE}; }}
.stats .num {{ display: block; font-family: 'Lora', Georgia, serif; font-weight: 700;
    font-size: 2rem; line-height: 1.1; color: {CLAY}; }}
.stats .lbl {{ display: block; font-size: .92rem; color: {MUTED}; margin-top: .25rem; }}
.note {{ font-size: .95rem; line-height: 1.5; color: {MUTED}; max-width: 46em; margin: .2rem 0 1.4rem 0; }}
.gap {{ padding: .7rem 0; border-bottom: 1px solid {LINE}; font-size: 1rem; }}
.gap b {{ color: {RUST}; }}

button[data-baseweb="tab"] {{ font-family: 'Public Sans', sans-serif; font-weight: 500; }}
button[data-baseweb="tab"][aria-selected="true"], button[data-baseweb="tab"][aria-selected="true"] p {{ color: {CLAY} !important; }}
[data-baseweb="tab-highlight"] {{ background-color: {CLAY} !important; }}
[data-testid="stTab"][aria-selected="true"], [data-testid="stTab"][aria-selected="true"] p {{ color: {CLAY} !important; }}
[data-testid="stTab"] .react-aria-SelectionIndicator {{ background-color: {CLAY} !important; }}
[data-testid="stToolbar"] {{ display: none; }}
[data-testid="stFileUploaderDropzone"] {{ background: #E9E5D8 !important; border: 1px dashed #B5B1A3 !important; }}
[data-testid="stFileUploaderDropzone"], [data-testid="stFileUploaderDropzone"] * {{ color: {INK} !important; }}
[data-baseweb="select"] > div {{ background: #FFFFFF !important; border: 1px solid #C9C5B8 !important; }}
[data-baseweb="select"] * {{ color: {INK} !important; }}
[data-testid="stFileUploaderDropzone"] button {{ background: #FFFFFF !important; border: 1px solid #B5B1A3 !important; }}
[data-testid="stAlert"], [data-testid="stAlertContainer"], div[role="alert"] {{ background: #E9E5D8 !important; color: {INK} !important; border-radius: 6px; }}
[data-testid="stBaseButton-primary"], button[kind="primary"] {{ background: {CLAY}; border: 0;
    border-radius: 6px; }}
[data-testid="stBaseButton-primary"]:hover {{ background: #A94F31; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------- data ----------
if not CSV_MODE:
    import psycopg2
    from psycopg2.extras import execute_values

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
    if CSV_MODE:
        return clean_frame(pd.read_csv(CSV_FILE))
    df = query("SELECT ts, consumer_id, receipt_id, line_number, store_name, product, brand, "
               "category, is_pg, quantity, unit_price, line_total, promotion FROM receipts")
    for c in ["unit_price", "line_total"]:
        df[c] = df[c].astype(float)
    df["promotion"] = clean_promotion(df["promotion"])
    return df


@st.cache_data(show_spinner=False)
def load_weekly():
    if CSV_MODE:
        d = load_receipts().copy()
        d["week"] = d["ts"].dt.to_period("W").dt.start_time
        d["pg_rev"] = d["line_total"].where(d["is_pg"], 0.0)
        w = d.groupby(["week", "store_name", "category"]).agg(
            total_rev=("line_total", "sum"), pg_rev=("pg_rev", "sum")).reset_index()
    else:
        w = query("SELECT week, store_name, category, total_rev, pg_rev FROM weekly_share "
                  "ORDER BY week")
        for c in ["total_rev", "pg_rev"]:
            w[c] = w[c].astype(float)
    return w[w["category"] != "Other"]


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
    msg = (f"Added {clean['receipt_id'].nunique()} receipts ({len(clean)} lines). "
           f"Skipped {skipped} already loaded.")
    if unmatched:
        msg += " New product names to review: " + "; ".join(unmatched)
    return msg


# ---------- Gemini ----------
def ask_gemini(facts):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"],
                          http_options=types.HttpOptions(timeout=30_000))
    prompt = (
        "You advise a P&G category team using supermarket receipt data. Use ONLY the numbers in "
        "the JSON below. Do not invent figures. Give exactly three prioritised actions. For each: "
        "the action, the evidence (quote the exact numbers), the expected impact, and one caveat. "
        "Write for a non-specialist: plain language, no jargon such as penetration or leakage; "
        "say competitor brands and items bought. Keep it under 250 words. The data is synthetic "
        "and samples are small, so say what you would validate on real data.\n\n" + json.dumps(facts))
    config = types.GenerateContentConfig(
        thinking_config=types.ThinkingConfig(thinking_level="low"), max_output_tokens=4000)
    models = []
    for m in [os.getenv("GEMINI_MODEL"), "gemini-3.5-flash-lite", "gemini-3.5-flash",
              "gemini-3.8-flash"]:
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
                break
    raise last


# ---------- small helpers ----------
def pretty(b):
    return {"HEAD AND SHOULDERS": "Head & Shoulders", "ORAL-B": "Oral-B"}.get(b, b.title())


def long_date(ts):
    return f"{ts.day} {ts:%B %Y}"


def style(fig, height=360):
    fig.update_layout(
        height=height, margin=dict(l=0, r=12, t=8, b=0),
        font=dict(family="Public Sans, system-ui, sans-serif", size=14, color=INK),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=1.1, x=0, title_text="",
                    font=dict(color=INK, size=14)))
    axis = dict(gridcolor=LINE, zeroline=False, linecolor="#9A978C", automargin=True,
                tickfont=dict(color=INK, size=14), title_font=dict(color=INK, size=14))
    fig.update_xaxes(**axis)
    fig.update_yaxes(**axis)
    return fig


def stat(num, label):
    return f'<div><span class="num">{num}</span><span class="lbl">{label}</span></div>'


def stacked_share(d, cat_col, pg_col, hover_extra=None, hover_label="", zero_label="no P&G brand"):
    """100% bars: P&G against other brands for each category."""
    d = d.sort_values(pg_col)
    pg = d[pg_col].tolist()
    other = [100 - v for v in pg]
    fig = go.Figure()
    fig.add_bar(
        y=d[cat_col], x=pg, orientation="h", name="P&G brands", marker_color=CLAY,
        text=[f"{v:.0f}%" if v >= 6 else "" for v in pg], textposition="inside",
        insidetextanchor="middle", textfont=dict(color="white"),
        customdata=d[hover_extra] if hover_extra else None,
        hovertemplate="%{y}: P&G holds %{x:.1f}% of spend"
                      + (f"<br>%{{customdata:.0f}}% {hover_label}" if hover_extra else "")
                      + "<extra></extra>")
    fig.add_bar(
        y=d[cat_col], x=other, orientation="h", name="Competitor brands", marker_color=GREY,
        text=[zero_label if v == 0 else ("" if v >= 100 else f"{100 - v:.0f}%") for v in pg],
        textposition="inside", insidetextanchor="middle", textfont=dict(color=INK),
        hovertemplate="%{y}: competitor brands hold %{x:.1f}% of spend<extra></extra>")
    fig.update_layout(barmode="stack", bargap=0.35, legend=dict(traceorder="normal"))
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False)
    fig.update_yaxes(showgrid=False)
    return fig


# ---------- sidebar ----------
st.sidebar.markdown("### Add receipts")
if CSV_MODE:
    st.sidebar.info("Running from the local CSV, so uploads are switched off.")
else:
    up = st.sidebar.file_uploader("CSV with the same columns as the original", type="csv")
    if up is not None and st.sidebar.button("Process upload", type="primary"):
        try:
            st.session_state["msg"] = ingest(up)
            st.session_state.pop("recs", None)
        except Exception as e:
            st.session_state["msg"] = f"Upload failed: {e}"
        st.rerun()
    if "msg" in st.session_state:
        st.sidebar.info(st.session_state["msg"])

# ---------- data ----------
df = load_receipts()
if df.empty:
    st.warning("The receipts table is empty. Run load.py first.")
    st.stop()

cats = df[df["category"] != "Other"]
pen = metrics.category_penetration(df)
lk = metrics.leakage(df)
bt = metrics.brand_table(df)
pg_share = 100 * cats.loc[cats["is_pg"], "line_total"].sum() / cats["line_total"].sum()
promo_pct = 100 * cats["promotion"].notna().mean()
households = df["consumer_id"].nunique()
receipts = df["receipt_id"].nunique()

with st.sidebar.expander("What the terms mean"):
    st.markdown(
        "**Share of spend:** out of every £100 spent in a category, the part that goes to P&G.\n\n"
        "**Bought on promotion:** the receipt shows a promotion label, such as a loyalty-card price.\n\n"
        "**Repeat purchase:** a household buying in the same category again.\n\n"
        "**Switching to a competitor:** the household's next purchase in that category was not a P&G brand.\n\n"
        "**Items:** individual product lines on receipts.")
st.sidebar.markdown(
    f"**{receipts:,}** receipts  \n**{households}** households  \n"
    f"{long_date(df['ts'].min())} to {long_date(df['ts'].max())}")

# ---------- headline ----------
worst = lk.iloc[0] if not lk.empty else None
zero_cats = pen.loc[pen["pg_households"] == 0, "category"].str.lower().tolist()
headline = f"P&G brands take {pg_share:.0f}% of home and personal care spend."
finding = ""
if worst is not None:
    finding = (f"After buying {pretty(worst['brand'])}, shoppers pick a competitor brand "
               f"{worst['lost_to_rival_pct']:.0f}% of the time for their next "
               f"{worst['category'].lower()}. ")
sub = (f"{households} households, {receipts:,} receipts, {long_date(df['ts'].min())} to "
       f"{long_date(df['ts'].max())}. Synthetic data.")
if zero_cats:
    sub += " No household bought a P&G brand in " + ", ".join(zero_cats) + "."
sub = f"<strong>{finding}</strong>" + sub if finding else sub
st.markdown(f'<div class="hero"><h1>{headline}</h1><p>{sub}</p></div>', unsafe_allow_html=True)
st.markdown(
    '<div class="stats">'
    + stat(f"{pg_share:.0f}%", "of home and personal care spend goes to P&G brands")
    + stat(f"{promo_pct:.0f}%", "of items were bought on promotion")
    + stat(f"{len(zero_cats)} of {len(pen)}", "categories where no household bought a P&G brand")
    + "</div>", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["Overview", "Switching and pairs", "Households", "Recommendations"])

# ---------- overview ----------
with tab1:
    st.subheader("P&G's share of spend in each category")
    st.markdown('<p class="note">Out of every £100 spent in a category, how much goes to P&G '
                'brands and how much to competitors. Hover a bar to see what share of households '
                'bought a P&G brand there.</p>', unsafe_allow_html=True)
    st.plotly_chart(style(stacked_share(pen, "category", "pg_revenue_share_pct",
                                        "pg_household_pct", "of households bought a P&G brand"), 390),
                    width="stretch", config={"displayModeBar": False}, theme=None)

    st.subheader("P&G's share of spend, week by week")
    wk = load_weekly()
    c1, c2 = st.columns(2)
    cat_pick = c1.selectbox("Category", ["All categories"] + sorted(wk["category"].unique()))
    store_pick = c2.selectbox("Store", ["All stores"] + sorted(wk["store_name"].unique()))
    w = wk
    if cat_pick != "All categories":
        w = w[w["category"] == cat_pick]
    if store_pick != "All stores":
        w = w[w["store_name"] == store_pick]
    w = w.groupby("week")[["total_rev", "pg_rev"]].sum().reset_index()
    w["share"] = 100 * w["pg_rev"] / w["total_rev"]
    fig = go.Figure(go.Scatter(x=w["week"], y=w["share"], mode="lines+markers",
                               line=dict(color=CLAY, width=2.5), marker=dict(size=6),
                               hovertemplate="%{x|%d %b}: %{y:.1f}%<extra></extra>"))
    fig.update_yaxes(range=[0, 100], ticksuffix="%")
    st.plotly_chart(style(fig, 300), width="stretch", config={"displayModeBar": False}, theme=None)

    st.subheader("How often each brand is bought on promotion")
    st.markdown('<p class="note">Each row compares a P&G brand with the competitor brands in the '
                'same category. The further right a dot sits, the larger the share of its items '
                'that were bought on promotion.</p>', unsafe_allow_html=True)
    d = bt[bt["is_pg"] & bt["competitor_promo_pct"].notna()].copy()
    d["label"] = d["brand"].map(pretty) + " in " + d["category"].str.lower()
    d["gap"] = d["promo_pct"] - d["competitor_promo_pct"]
    d = d.sort_values("gap")
    fig = go.Figure()
    for _, r in d.iterrows():
        fig.add_scatter(x=[r["competitor_promo_pct"], r["promo_pct"]], y=[r["label"]] * 2,
                        mode="lines", line=dict(color=LINE, width=3), showlegend=False,
                        hoverinfo="skip")
    fig.add_scatter(x=d["competitor_promo_pct"], y=d["label"], mode="markers", name="Competitor brands",
                    marker=dict(color=GREY, size=12),
                    hovertemplate="Competitors: %{x:.1f}% of items bought on promotion<extra></extra>")
    fig.add_scatter(x=d["promo_pct"], y=d["label"], mode="markers", name="P&G brand",
                    marker=dict(color=CLAY, size=12),
                    hovertemplate="P&G: %{x:.1f}% of items bought on promotion<extra></extra>")
    fig.update_xaxes(ticksuffix="%", title_text="Share of items bought on promotion", title_standoff=14)
    fig.update_yaxes(showgrid=False)
    st.plotly_chart(style(fig, 360), width="stretch", config={"displayModeBar": False}, theme=None)
    if not d.empty:
        hi, lo = d.iloc[-1], d.iloc[0]
        st.markdown(
            f'<p class="note">{pretty(hi["brand"])} is bought on promotion {hi["promo_pct"]:.1f}% '
            f'of the time, against {hi["competitor_promo_pct"]:.1f}% for competitor '
            f'{hi["category"].lower()} brands, and makes up '
            f'{hi["lines_share_in_category_pct"]:.0f}% of the items bought in its category. '
            f'{pretty(lo["brand"])} is bought on promotion {lo["promo_pct"]:.1f}% of the time, '
            f'against {lo["competitor_promo_pct"]:.1f}% for competitor {lo["category"].lower()} '
            f'brands, and makes up {lo["lines_share_in_category_pct"]:.0f}% of its category.</p>',
            unsafe_allow_html=True)

# ---------- switching and pairs ----------
with tab2:
    st.subheader("Shoppers who switch to a competitor")
    st.markdown('<p class="note">After a household buys a P&G brand, how often is its next '
                'purchase in the same category a competitor brand instead? Moving between two P&G '
                'brands does not count. Some brands have few repeat purchases, so treat these as '
                'a guide, not an exact figure.</p>', unsafe_allow_html=True)
    if lk.empty:
        st.info("Not enough repeat purchases yet.")
    else:
        l = lk.sort_values("lost_to_rival_pct")
        labels = l["brand"].map(pretty) + " in " + l["category"].str.lower()
        fig = go.Figure(go.Bar(
            x=l["lost_to_rival_pct"], y=labels, orientation="h", marker_color=RUST,
            text=[f"{p:.0f}% of {n} repeat purchases" for p, n in
                  zip(l["lost_to_rival_pct"], l["repeat_purchases"])],
            textposition="outside", cliponaxis=False,
            hovertemplate="%{y}: next purchase was a competitor %{x:.1f}% of the time<extra></extra>"))
        fig.update_xaxes(ticksuffix="%", showgrid=False,
                         range=[0, max(30, l["lost_to_rival_pct"].max() * 2.2)])
        fig.update_yaxes(showgrid=False)
        st.plotly_chart(style(fig, 340), width="stretch", config={"displayModeBar": False}, theme=None)

    st.subheader("Households that buy one brand but not the other")
    for a, b in metrics.CROSS_SELL_PAIRS:
        g = metrics.cross_sell_gap(df, a, b)
        st.markdown(
            f'<div class="gap"><b>{g["of_which_never_buy_b"]} of {g["households_buying_a"]}</b> '
            f'households that buy {pretty(a)} ({g["pct"]:.0f}%) have never bought {pretty(b)}.</div>',
            unsafe_allow_html=True)

    st.subheader("P&G share of spend by store")
    ss = metrics.store_skew(df).sort_values("pg_revenue_share_pct")
    fig = go.Figure(go.Bar(
        x=ss["pg_revenue_share_pct"], y=ss["store_name"], orientation="h", marker_color=CLAY,
        text=[f"{v:.0f}%" for v in ss["pg_revenue_share_pct"]], textposition="outside",
        cliponaxis=False, hovertemplate="%{y}: %{x:.1f}%<extra></extra>"))
    fig.update_xaxes(range=[0, 100], ticksuffix="%", showgrid=False)
    fig.update_yaxes(showgrid=False)
    st.plotly_chart(style(fig, 230), width="stretch", config={"displayModeBar": False}, theme=None)

# ---------- households ----------
with tab3:
    cid = st.selectbox("Household", sorted(df["consumer_id"].unique()))
    h = df[df["consumer_id"] == cid]
    hc = h[h["category"] != "Other"]
    st.markdown(
        '<div class="stats">'
        + stat(str(h["receipt_id"].nunique()), "receipts in the period")
        + stat(f"£{h['line_total'].sum():,.2f}", "total spend")
        + stat(f"{100 * h['promotion'].notna().mean():.0f}%", "of items bought on promotion")
        + "</div>", unsafe_allow_html=True)
    st.subheader("This household's spend by category")
    by = hc.groupby("category").apply(
        lambda g: pd.Series({"spend": g["line_total"].sum(),
                             "pg": 100 * g.loc[g["is_pg"], "line_total"].sum() / g["line_total"].sum()}),
        include_groups=False).reset_index()
    if by.empty:
        st.info("No home or personal care purchases for this household.")
    else:
        fig = stacked_share(by, "category", "pg", zero_label="no P&G purchase")
        st.plotly_chart(style(fig, 330), width="stretch", config={"displayModeBar": False}, theme=None)
        st.caption("Each bar is the household's spend in that category, split into P&G and competitor brands.")
    top = h["product"].value_counts().head(5).index.str.title().tolist()
    st.markdown(f'<p class="note">Most bought: {", ".join(top)}.</p>', unsafe_allow_html=True)

# ---------- recommendations ----------
with tab4:
    facts = metrics.summary(df)
    st.subheader("What to do next")
    st.markdown('<p class="note">Gemini reads the computed numbers only, never the raw receipts. '
                'Check each action against the numbers listed below it.</p>',
                unsafe_allow_html=True)
    if st.button("Generate recommendations", type="primary"):
        try:
            with st.spinner("Asking Gemini..."):
                st.session_state["recs"] = ask_gemini(facts)
        except Exception as e:
            st.session_state["recs"] = f"Could not reach Gemini: {e}"
    if "recs" in st.session_state:
        with st.container(border=True):
            st.markdown(st.session_state["recs"])
    with st.expander("Numbers sent to Gemini"):
        st.json(facts)
