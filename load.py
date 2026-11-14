import os, re, pandas as pd, psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv
load_dotenv()
RAW_TABLE = "DHRD"   # <- change this

# ---- cleaning ----
SIZE = re.compile(r"^\d+(KG|G|ML|L)$")
def fix_token(t):                     # 0->O, 1->I inside words, leave sizes like 500G alone
    if SIZE.match(t) or not re.search(r"[A-Z]", t): return t
    return t.replace("0", "O").replace("1", "I")
SHORT = {r"\bW/UP LIQ\b": "WASHING UP LIQUID", r"\bWASH LIQ\b": "WASHING LIQUID",
         r"\bT/TISSUE\b": "TOILET TISSUE", r"\bSKIM\b": "SKIMMED",
         r"\bCHOC\b": "CHOCOLATE", r"\bPROT\b": "PROTECTION"}
def normalise(name):
    s = " ".join(fix_token(t) for t in name.upper().split())
    for pat, rep in SHORT.items(): s = re.sub(pat, rep, s)
    return s
def build_canon(names):               # merge truncated variants into the longest name
    norm = {n: normalise(n) for n in names}
    longest = {}
    for v in norm.values():
        k = v[:30]
        if len(v) > len(longest.get(k, "")): longest[k] = v
    return {n: longest[v[:30]] for n, v in norm.items()}

BRANDS = ["HEAD AND SHOULDERS","ORAL-B","ARIEL","FAIRY","LENOR","PANTENE","FLASH","PERSIL","SURF",
          "COMFORT","COLGATE","AQUAFRESH","ALBERTO","CIF","DETTOL","DOMESTOS","DOVE","RADOX","IMPERIAL"]
PG = {"ARIEL","FAIRY","LENOR","PANTENE","HEAD AND SHOULDERS","ORAL-B","FLASH"}
def brand(p): return next((b for b in BRANDS if p.startswith(b)), p.split()[0])
def category(p):
    if p.startswith(("PERSIL WASHING UP","FAIRY ORIG")): return "Washing-up liquid"
    if p.startswith(("ARIEL","PERSIL NON","SURF","FAIRY NON")): return "Laundry detergent"
    if p.startswith(("COMFORT","LENOR SPRING AWAKENING FAB")): return "Fabric conditioner"
    if p.startswith("LENOR"): return "Scent booster"
    if p.startswith(("ORAL-B","COLGATE","AQUAFRESH")): return "Toothpaste"
    if p.startswith(("HEAD AND","PANTENE","ALBERTO")): return "Shampoo"
    if p.startswith(("FLASH","CIF","DETTOL","DOMESTOS")): return "Surface cleaner"
    if p.startswith(("DOVE","RADOX","IMPERIAL")): return "Body wash"
    return "Other"

# ---- load ----
conn = psycopg2.connect(os.environ["DATABASE_URL"])
raw = pd.read_sql(f'SELECT * FROM "{RAW_TABLE}"', conn)
canon = build_canon(raw["Product_Name"].unique())
df = pd.DataFrame({
    "ts": pd.to_datetime(raw["Date"].astype(str) + " " + raw["Time"].astype(str)),
    "consumer_id": raw["Consumer_ID"], "receipt_id": raw["Receipt_ID"],
    "line_number": raw["Line_Number"], "store_name": raw["Store_Name"],
    "product_raw": raw["Product_Name"], "product": raw["Product_Name"].map(canon)})
df["brand"] = df["product"].map(brand)
df["category"] = df["product"].map(category)
df["is_pg"] = df["brand"].isin(PG)
for c_out, c_in in [("quantity","Quantity"),("unit_price","Unit_Price"),("line_total","Line_Total"),
                    ("promotion","Promotion"),("total_spend","Total_Spend")]:
    df[c_out] = raw[c_in]
df = df.astype(object).where(df.notna(), None)

cols = ["ts","consumer_id","receipt_id","line_number","store_name","product_raw","product",
        "brand","category","is_pg","quantity","unit_price","line_total","promotion","total_spend"]
with conn, conn.cursor() as cur:
    cur.execute("DELETE FROM receipts")          # so you can re-run safely
    execute_values(cur, f"INSERT INTO receipts ({','.join(cols)}) VALUES %s",
                   [tuple(r) for r in df[cols].itertuples(index=False)])
print("products:", df["product"].nunique(), "| P&G lines:", int(df["is_pg"].sum()))