"""Step 2: turn a messy raw sheet into a tidy table.

Handles: title rows above the header, odd column names, blank rows, "Total" rows,
currency symbols, mixed date formats, Excel date numbers, duplicate rows,
and inconsistent spelling/casing of product and region names.
"""
import re

import pandas as pd

from app.config import settings
from app.exceptions import ValidationFailed

ALIASES = {
    "date": ["date", "order date", "sale date", "sales date", "transaction date", "invoice date", "dt", "day"],
    "product": ["product", "product name", "item", "item name", "sku", "description"],
    "region": ["region", "area", "zone", "state", "location", "city", "store"],
    "quantity": ["quantity", "qty", "units", "units sold", "count", "no of units"],
    "unit_price": ["unit price", "price", "rate", "price per unit"],
    "revenue": ["revenue", "sales", "amount", "total", "total sales", "total amount", "sale amount", "net sales"],
}


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


LOOKUP = {_norm(alias): canon for canon, names in ALIASES.items() for alias in names}
FOOTER_WORDS = {"total", "grand total", "subtotal", "sub total", "average", "sum"}


def find_header_row(raw: pd.DataFrame) -> int:
    best_pos, best_score = 0, 0
    for pos in range(min(15, len(raw))):
        canon = {LOOKUP[_norm(v)] for v in raw.iloc[pos].tolist() if v is not None and _norm(v) in LOOKUP}
        if len(canon) > best_score:
            best_pos, best_score = pos, len(canon)
    if best_score < 2:
        raise ValidationFailed(
            "Could not find a header row. Expected column names like: date, product, revenue (or quantity + price).",
        )
    return best_pos


def to_number(series: pd.Series) -> pd.Series:
    """'$1,200.50', 'Rs. 1200', '(300)', '1,200 INR' -> numbers."""
    def one(v):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        negative = s.startswith("(") and s.endswith(")")
        s = re.sub(r"(?i)rs\.?|inr|usd|eur|gbp|[$€£₹,\s()]", "", s)
        if negative and s and not s.startswith("-"):
            s = "-" + s
        return s or None
    return pd.to_numeric(series.map(one), errors="coerce")


def to_date(series: pd.Series) -> pd.Series:
    """Mixed text dates, real dates and Excel serial numbers -> datetime."""
    as_num = pd.to_numeric(series, errors="coerce")
    serial = as_num.between(20000, 60000)  # Excel date numbers (~1955-2064)
    text = series.where(~serial)
    year_first = text.astype(str).str.match(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}")  # 2024-03-04 is never day-first
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    if year_first.any():
        parsed[year_first] = pd.to_datetime(text[year_first], errors="coerce", format="mixed", dayfirst=False)
    rest = ~year_first & ~serial
    if rest.any():
        parsed[rest] = pd.to_datetime(text[rest], errors="coerce", format="mixed", dayfirst=settings.date_dayfirst)
    if serial.any():
        parsed[serial] = pd.to_datetime(as_num[serial], unit="D", origin="1899-12-30")
    return parsed


def unify_text(series: pd.Series) -> tuple[pd.Series, int]:
    """'widget a', 'WIDGET A', 'Widget A ' -> the most common spelling."""
    s = series.astype("string").str.replace(r"\s+", " ", regex=True).str.strip()
    s = s.mask(s == "")
    key = s.str.lower()
    def pick(x):
        counts = x.value_counts()
        return max(counts.items(), key=lambda kv: (kv[1], kv[0].istitle()))[0]
    best = s.groupby(key).agg(pick)
    unified = key.map(best)
    changed = int(((unified != s) & s.notna()).sum())
    return unified, changed


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    log: dict = {"rows_in_file": 0, "columns_used": {}, "ignored_columns": []}

    header_pos = find_header_row(raw)
    header = raw.iloc[header_pos].tolist()
    body = raw.iloc[header_pos + 1:].copy()
    body["_row"] = body.index + 1  # row number as the user sees it in the file
    log["header_row"] = int(raw.index[header_pos]) + 1
    log["rows_in_file"] = int(len(body.dropna(how="all", subset=[c for c in body.columns if c != "_row"])))

    # Map messy column names -> standard names
    rename, used = {}, set()
    for col, name in zip(raw.columns, header):
        canon = LOOKUP.get(_norm(name)) if name is not None else None
        if canon and canon not in used:
            rename[col] = canon
            used.add(canon)
            log["columns_used"][str(name)] = canon
        elif name is not None:
            log["ignored_columns"].append(str(name))
    body = body[list(rename) + ["_row"]].rename(columns=rename)

    # Required columns
    missing = [c for c in ("date", "product") if c not in body.columns]
    if "revenue" not in body.columns and not {"quantity", "unit_price"} <= set(body.columns):
        missing.append("revenue (or quantity + unit price)")
    if missing:
        raise ValidationFailed(
            "Required columns are missing: " + ", ".join(missing),
            {"found_columns": list(log["columns_used"].keys())},
        )

    # Tidy text, drop blank rows
    for col in ("product", "region"):
        if col in body.columns:
            body[col] = body[col].map(lambda v: v.strip() if isinstance(v, str) else v)
    data_cols = [c for c in body.columns if c != "_row"]
    before = len(body)
    body = body.dropna(how="all", subset=data_cols)
    log["blank_rows_removed"] = before - len(body)

    # Remove "Total" footer rows and repeated header rows
    is_footer = body["product"].map(lambda v: isinstance(v, str) and _norm(v) in FOOTER_WORDS) | \
        body["date"].map(lambda v: isinstance(v, str) and _norm(v) in FOOTER_WORDS | {"date"})
    log["footer_rows_removed"] = int(is_footer.sum())
    body = body[~is_footer].copy()

    # Fix types
    body["date"] = to_date(body["date"])
    for col in ("quantity", "unit_price", "revenue"):
        if col in body.columns:
            body[col] = to_number(body[col])
    if "revenue" not in body.columns:
        body["revenue"] = pd.NA
    filled = body["revenue"].isna() & body.get("quantity", pd.Series(dtype=float)).notna() \
        & body.get("unit_price", pd.Series(dtype=float)).notna()
    if "unit_price" in body.columns and "quantity" in body.columns:
        body.loc[filled, "revenue"] = body.loc[filled, "quantity"] * body.loc[filled, "unit_price"]
    body["revenue"] = pd.to_numeric(body["revenue"], errors="coerce")
    log["revenue_calculated"] = int(filled.sum()) if hasattr(filled, "sum") else 0

    # Unify spelling
    body["product"], changed_p = unify_text(body["product"])
    changed_r = 0
    if "region" in body.columns:
        body["region"], changed_r = unify_text(body["region"])
    log["names_unified"] = changed_p + changed_r

    # Remove exact duplicates (ignoring row number)
    cols = [c for c in body.columns if c != "_row"]
    dup = body.duplicated(subset=cols, keep="first")
    log["duplicates_removed"] = int(dup.sum())
    body = body[~dup]

    if "quantity" not in body.columns:
        body["quantity"] = pd.NA
    if "region" not in body.columns:
        body["region"] = pd.NA
    log["rows_after_cleaning"] = int(len(body))
    return body[["_row", "date", "product", "region", "quantity", "revenue"]].reset_index(drop=True), log
