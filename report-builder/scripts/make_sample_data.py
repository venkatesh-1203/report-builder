"""Creates deliberately MESSY sample files for demos:  python scripts/make_sample_data.py"""
import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

random.seed(7)
OUT = Path(__file__).resolve().parent.parent / "sample_data"
OUT.mkdir(exist_ok=True)

products = {"Widget A": 499, "Widget B": 899, "Gadget Pro": 2499, "Cable Pack": 199, "Desk Lamp": 1299}
regions = ["North", "South", "East", "West"]
start = date.today() - timedelta(days=34)

rows = []
for i in range(320):
    d = start + timedelta(days=random.randint(0, 33))
    p = random.choices(list(products), weights=[5, 4, 2, 6, 3])[0]
    qty = random.randint(1, 6)
    price = products[p]
    rows.append({
        "Order Date": d.strftime(random.choice(["%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y"])),
        "Product Name": random.choice([p, p.lower(), p.upper(), f" {p} "]),
        "Region ": random.choices(regions + [r.lower() for r in regions[:2]], weights=[4, 4, 4, 4, 1, 1])[0],
        "Qty": qty,
        "Unit Price": f"Rs. {price:,}" if random.random() < 0.5 else price,
        "Total Sales": random.choice([f"${qty * price:,.2f}", f"{qty * price:,}", qty * price]),
        "Notes (ignore)": random.choice(["", "gift", "repeat customer"]),
    })

df = pd.DataFrame(rows)
df.loc[5, "Total Sales"] = None            # missing revenue -> calculated from qty x price
df.loc[10, "Order Date"] = "not a date"     # bad row
df.loc[20, "Total Sales"] = "-500"          # negative revenue -> bad row
df.loc[30, "Product Name"] = None           # missing product -> bad row
df = pd.concat([df, df.iloc[[40, 41, 42]]], ignore_index=True)  # exact duplicates

# Title rows above the header and a Total row at the bottom
title = [["Monthly Sales Export - DO NOT EDIT"] + [None] * 6, [None] * 7]
footer = [["Total", None, None, None, None, "999,999", None]]
body = [list(df.columns)] + df.astype(object).where(df.notna(), None).values.tolist() + footer
sheet = pd.DataFrame(title + body)

sheet.to_excel(OUT / "messy_sales.xlsx", header=False, index=False)
sheet.to_csv(OUT / "messy_sales.csv", header=False, index=False)
print("Created:", *(p.name for p in OUT.iterdir()))
