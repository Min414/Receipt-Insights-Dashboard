"""Generate a new batch of synthetic receipts in the same format as DH_Synthtic_Receipt_Database.csv.
Each household keeps its own habits (stores, products, basket size), so new data behaves like the old.
Usage:  python make_synthetic.py            -> October 2026 batch
        python make_synthetic.py 2026-11-01 2026-11-30 receipts_nov.csv
"""
import sys, hashlib
import numpy as np
import pandas as pd
from cleaning import build_canon

SRC = "DH_Synthtic_Receipt_Database.csv"
start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2026-10-01")
end = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-10-31")
out_path = sys.argv[3] if len(sys.argv) > 3 else "synthetic_receipts_october.csv"
rng = np.random.default_rng(2026)

df = pd.read_csv(SRC)
df["product"] = df["Product Name"].map(build_canon(df["Product Name"].unique()))
PROMO = df.dropna(subset=["Promotion"]).groupby("Store Name")["Promotion"].first().to_dict()
PROMO_RATE = df["Promotion"].notna().mean()
QTY2 = (df["Quantity"] == 2).mean()
times = df.drop_duplicates("Receipt ID")["Time"].tolist()
catalog = df["product"].unique()
raw_variants = df.groupby("product")["Product Name"].agg(list).to_dict()
base_prices = {k: g["Unit Price"].to_numpy() for k, g in df[df["Promotion"].isna()].groupby(["product", "Store Name"])}
all_prices = {k: g["Unit Price"].to_numpy() for k, g in df[df["Promotion"].isna()].groupby("product")}

last_id = int(df["Receipt ID"].str[-6:].astype(int).max())
days = pd.date_range(start, end)
rows, receipts = [], []

for cid, h in df.groupby("Consumer ID"):
    n_hist = h["Receipt ID"].nunique()
    n_new = max(1, int(round(n_hist / 6 * (len(days) / 30) * rng.uniform(0.7, 1.3))))
    sizes = h.groupby("Receipt ID").size().to_numpy()
    freq = h["product"].value_counts()
    stores = h.drop_duplicates("Receipt ID")["Store Name"].value_counts()
    for _ in range(n_new):
        store = rng.choice(stores.index, p=(stores / stores.sum()).to_numpy())
        addr = rng.choice(h[h["Store Name"] == store]["Store Address"].unique())
        day = rng.choice(days)
        k = int(rng.choice(sizes))
        chosen = []
        for _ in range(k):  # mostly habitual products, occasionally something new
            pool = catalog if rng.random() < 0.03 else freq.index.to_numpy()
            w = None if pool is catalog else (freq / freq.sum()).to_numpy()
            for _try in range(20):
                p = rng.choice(pool, p=w)
                if p not in chosen:
                    chosen.append(p); break
        receipts.append((cid, store, addr, pd.Timestamp(day).date().isoformat(), rng.choice(times), chosen))

receipts.sort(key=lambda r: (r[0], r[3]))
for i, (cid, store, addr, date, time, chosen) in enumerate(receipts, start=1):
    rid = last_id + i
    img = f"synthetic_receipt_{rid:06d}_{hashlib.md5(str(rid).encode()).hexdigest()[:6]}.jpg"
    lines = []
    for p in chosen:
        pool = base_prices.get((p, store), all_prices[p])
        price = float(rng.choice(pool))
        promo = "None"
        if rng.random() < PROMO_RATE:
            price = round(price * float(np.clip(rng.normal(0.825, 0.06), 0.68, 0.998)), 2)
            promo = PROMO[store]
        qty = 2 if rng.random() < QTY2 else 1
        lines.append((rng.choice(raw_variants[p]), qty, round(price, 2), promo, round(price * qty, 2)))
    total = round(sum(l[4] for l in lines), 2)
    for n, (name, qty, price, promo, lt) in enumerate(lines, start=1):
        rows.append([cid, f"SYN-R-{rid:06d}", img, store, addr, date, name, qty, price, promo, lt, total, time, n])

cols = ["Consumer ID", "Receipt ID", "Image Filename", "Store Name", "Store Address", "Date",
        "Product Name", "Quantity", "Unit Price", "Promotion", "Line Total", "Total Spend", "Time", "Line Number"]
pd.DataFrame(rows, columns=cols).to_csv(out_path, index=False, encoding="utf-8-sig")
print(f"{len(receipts)} receipts, {len(rows)} lines -> {out_path}")
