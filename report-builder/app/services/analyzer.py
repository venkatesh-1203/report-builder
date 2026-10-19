"""Step 4: do the maths in plain pandas. The AI never calculates numbers."""
from datetime import timedelta

import pandas as pd


def _r(x, n=2):
    return None if x is None or pd.isna(x) else round(float(x), n)


def analyze(df: pd.DataFrame, currency_code: str = "INR") -> dict:
    d = df.copy()
    d["sale_date"] = pd.to_datetime(d["sale_date"])
    start, end = d["sale_date"].min(), d["sale_date"].max()
    days = int((end - start).days) + 1

    revenue = float(d["revenue"].sum())
    orders = int(len(d))
    units = float(d["quantity"].sum()) if d["quantity"].notna().any() else None

    top = d.groupby("product")["revenue"].sum().sort_values(ascending=False).head(5)
    top_products = [
        {"name": str(n), "revenue": _r(v), "share_pct": _r(v / revenue * 100, 1) if revenue else 0}
        for n, v in top.items()
    ]

    by_region = []
    if d["region"].notna().any():
        reg = d.groupby("region")["revenue"].sum().sort_values(ascending=False).head(8)
        by_region = [
            {"name": str(n), "revenue": _r(v), "share_pct": _r(v / revenue * 100, 1) if revenue else 0}
            for n, v in reg.items()
        ]

    freq, label = ("D", "day") if days <= 90 else (("W", "week") if days <= 730 else ("MS", "month"))
    series = d.set_index("sale_date")["revenue"].resample(freq).sum()
    trend_series = [{"date": idx.strftime("%Y-%m-%d"), "revenue": _r(v)} for idx, v in series.items()]

    daily = d.groupby("sale_date")["revenue"].sum()
    best = daily.idxmax()

    change = None
    if days >= 14:
        cur_start, prev_start = end - timedelta(days=6), end - timedelta(days=13)
        cur = float(d.loc[d["sale_date"] >= cur_start, "revenue"].sum())
        prev = float(d.loc[(d["sale_date"] >= prev_start) & (d["sale_date"] < cur_start), "revenue"].sum())
        change = {
            "last_7_days": _r(cur),
            "previous_7_days": _r(prev),
            "change_pct": _r((cur - prev) / prev * 100, 1) if prev > 0 else None,
        }

    return {
        "period": {"start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "days": days},
        "totals": {
            "revenue": _r(revenue), "orders": orders, "units": _r(units, 0),
            "avg_order_value": _r(revenue / orders) if orders else None,
            "avg_daily_revenue": _r(revenue / days) if days else None,
            "avg_units_per_order": _r(units / orders) if units is not None and orders else None,
        },
        "currency": currency_code,
        "active_days": int(d["sale_date"].nunique()),
        "product_count": int(d["product"].nunique()),
        "top_products": top_products,
        "by_region": by_region,
        "trend": {"granularity": label, "points": trend_series},
        "best_day": {"date": best.strftime("%Y-%m-%d"), "revenue": _r(daily.max())},
        "week_over_week": change,
    }
