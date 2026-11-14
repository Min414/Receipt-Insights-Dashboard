"""Turns messy receipt rows into clean, tagged rows ready for the receipts table."""
import re
import pandas as pd

SIZE = re.compile(r"^\d+(KG|G|ML|L)$")


def fix_token(t):
    """OCR often swaps O/0 and I/1 inside words. Fix words, leave sizes like 500G alone."""
    if SIZE.match(t) or not re.search(r"[A-Z]", t):
        return t
    return t.replace("0", "O").replace("1", "I")


SHORT = {
    r"\bW/UP LIQ\b": "WASHING UP LIQUID",
    r"\bWASH LIQ\b": "WASHING LIQUID",
    r"\bT/TISSUE\b": "TOILET TISSUE",
    r"\bSKIM\b": "SKIMMED",
    r"\bCHOC\b": "CHOCOLATE",
    r"\bPROT\b": "PROTECTION",
}


def normalise(name):
    s = " ".join(fix_token(t) for t in str(name).upper().split())
    for pat, rep in SHORT.items():
        s = re.sub(pat, rep, s)
    return s


def build_canon(names):
    """Map every raw name to one canonical name (truncated variants merge into the longest)."""
    norm = {n: normalise(n) for n in names}
    longest = {}
    for v in norm.values():
        k = v[:30]
        if len(v) > len(longest.get(k, "")):
            longest[k] = v
    return {n: longest[v[:30]] for n, v in norm.items()}


BRANDS = ["HEAD AND SHOULDERS", "ORAL-B", "ARIEL", "FAIRY", "LENOR", "PANTENE", "FLASH",
          "PERSIL", "SURF", "COMFORT", "COLGATE", "AQUAFRESH", "ALBERTO", "CIF", "DETTOL",
          "DOMESTOS", "DOVE", "RADOX", "IMPERIAL"]
PG = {"ARIEL", "FAIRY", "LENOR", "PANTENE", "HEAD AND SHOULDERS", "ORAL-B", "FLASH"}


def brand(p):
    return next((b for b in BRANDS if p.startswith(b)), p.split()[0])


def category(p):
    if p.startswith(("PERSIL WASHING UP", "FAIRY ORIG")): return "Washing-up liquid"
    if p.startswith(("ARIEL", "PERSIL NON", "SURF", "FAIRY NON")): return "Laundry detergent"
    if p.startswith(("COMFORT", "LENOR SPRING AWAKENING FAB")): return "Fabric conditioner"
    if p.startswith("LENOR"): return "Scent booster"
    if p.startswith(("ORAL-B", "COLGATE", "AQUAFRESH")): return "Toothpaste"
    if p.startswith(("HEAD AND", "PANTENE", "ALBERTO")): return "Shampoo"
    if p.startswith(("FLASH", "CIF", "DETTOL", "DOMESTOS")): return "Surface cleaner"
    if p.startswith(("DOVE", "RADOX", "IMPERIAL")): return "Body wash"
    return "Other"


REQUIRED = ["Consumer_ID", "Receipt_ID", "Store_Name", "Date", "Time", "Product_Name",
            "Quantity", "Unit_Price", "Line_Total", "Promotion", "Total_Spend", "Line_Number"]


def clean_frame(raw, extra_names=()):
    """raw: DataFrame with the original CSV columns. extra_names: product names already in the
    database, so new variants map to the same canonical names as before."""
    raw = raw.copy()
    raw.columns = [c.replace(" ", "_") for c in raw.columns]
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise ValueError("Missing columns in the CSV: " + ", ".join(missing))

    canon = build_canon(set(raw["Product_Name"].unique()) | set(extra_names))
    out = pd.DataFrame({
        "ts": pd.to_datetime(raw["Date"].astype(str) + " " + raw["Time"].astype(str)),
        "consumer_id": raw["Consumer_ID"],
        "receipt_id": raw["Receipt_ID"],
        "line_number": raw["Line_Number"],
        "store_name": raw["Store_Name"],
        "product_raw": raw["Product_Name"],
        "product": raw["Product_Name"].map(canon),
        "quantity": raw["Quantity"],
        "unit_price": raw["Unit_Price"],
        "line_total": raw["Line_Total"],
        "promotion": raw["Promotion"],
        "total_spend": raw["Total_Spend"],
    })
    out["brand"] = out["product"].map(brand)
    out["category"] = out["product"].map(category)
    out["is_pg"] = out["brand"].isin(PG)
    return out
