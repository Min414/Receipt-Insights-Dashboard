"""All the insight calculations. Input: DataFrame with the columns of the receipts table."""
import json
import pandas as pd


def _records(df):
    return json.loads(df.to_json(orient="records"))


def _cats(df):
    return df[df["category"] != "Other"]


def category_penetration(df):
    """Per category: how many households buy it, and how many buy a P&G brand in it."""
    rows = []
    for cat, g in _cats(df).groupby("category"):
        hh = g["consumer_id"].nunique()
        pg = g[g["is_pg"]]
        rows.append({
            "category": cat,
            "households": hh,
            "pg_households": pg["consumer_id"].nunique(),
            "pg_household_pct": round(100 * pg["consumer_id"].nunique() / hh, 1),
            "pg_revenue_share_pct": round(100 * pg["line_total"].sum() / g["line_total"].sum(), 1),
        })
    return pd.DataFrame(rows)


def brand_table(df):
    """Per category and brand: volume, price and how often it is on promotion."""
    d = _cats(df).copy()
    d["on_promo"] = d["promotion"].notna()
    t = d.groupby(["category", "brand"]).agg(
        is_pg=("is_pg", "first"),
        lines=("line_total", "size"),
        revenue=("line_total", "sum"),
        avg_unit_price=("unit_price", "mean"),
        promo_pct=("on_promo", lambda s: 100 * s.mean()),
    ).reset_index()
    comp = d[~d["is_pg"]].groupby("category")["on_promo"].mean().mul(100).round(1)
    t["competitor_promo_pct"] = t["category"].map(comp)
    t["lines_share_in_category_pct"] = 100 * t["lines"] / t.groupby("category")["lines"].transform("sum")
    return t.round(2)


def leakage(df, min_repeats=20):
    """Of repeat purchases of a P&G brand, how often was the shopper's next purchase in the same
    category a brand that is NOT P&G (lost to a rival)? switched_pct also counts moves to another
    P&G brand."""
    d = _cats(df).sort_values(["consumer_id", "ts", "receipt_id", "line_number"])
    rows = []
    for (_, cat), g in d.groupby(["consumer_id", "category"]):
        b = g["brand"].tolist()
        rows += [(cat, b[i - 1], b[i]) for i in range(1, len(b))]
    t = pd.DataFrame(rows, columns=["category", "brand", "next_brand"])
    pg_brands = set(df.loc[df["is_pg"], "brand"])
    t = t[t["brand"].isin(pg_brands)].copy()
    t["switched"] = t["brand"] != t["next_brand"]
    t["lost"] = ~t["next_brand"].isin(pg_brands)
    res = t.groupby(["category", "brand"]).agg(
        repeat_purchases=("lost", "size"),
        lost_to_rival_pct=("lost", lambda s: round(100 * s.mean(), 1)),
        switched_pct=("switched", lambda s: round(100 * s.mean(), 1)),
    ).reset_index()
    return res[res["repeat_purchases"] >= min_repeats].sort_values("lost_to_rival_pct", ascending=False)


def cross_sell_gap(df, a, b):
    """Households that buy brand a but never buy brand b."""
    hh_a = set(df.loc[df["brand"] == a, "consumer_id"])
    hh_b = set(df.loc[df["brand"] == b, "consumer_id"])
    return {
        "if_buys": a, "but_not": b,
        "households_buying_a": len(hh_a),
        "of_which_never_buy_b": len(hh_a - hh_b),
        "pct": round(100 * len(hh_a - hh_b) / max(len(hh_a), 1), 1),
    }


CROSS_SELL_PAIRS = [("ARIEL", "LENOR"), ("LENOR", "ARIEL")]


def store_skew(df):
    d = _cats(df)
    t = d.groupby("store_name").apply(
        lambda g: round(100 * g.loc[g["is_pg"], "line_total"].sum() / g["line_total"].sum(), 1),
        include_groups=False)
    return t.rename("pg_revenue_share_pct").reset_index()


def summary(df):
    """Small, fully computed fact sheet. This is all the LLM gets to see."""
    bt = brand_table(df)
    pg_bt = bt[bt["is_pg"]][["category", "brand", "lines", "lines_share_in_category_pct",
                             "avg_unit_price", "promo_pct", "competitor_promo_pct"]]
    return {
        "data_note": "Synthetic receipts. Small samples: treat results as directional.",
        "receipts": int(df["receipt_id"].nunique()),
        "households": int(df["consumer_id"].nunique()),
        "date_range": [str(df["ts"].min().date()), str(df["ts"].max().date())],
        "category_penetration": _records(category_penetration(df)),
        "pg_brands": _records(pg_bt),
        "leakage_pg_brands": _records(leakage(df)),
        "cross_sell_gaps": [cross_sell_gap(df, a, b) for a, b in CROSS_SELL_PAIRS],
        "pg_revenue_share_by_store": _records(store_skew(df)),
    }
