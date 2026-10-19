"""Step 3: check every row against clear rules (Pydantic).

Good rows continue. Bad rows are listed with the reason.
If too many rows are bad, the whole file is rejected with a helpful message.
"""
from datetime import date, timedelta

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.config import settings
from app.exceptions import ValidationFailed

MIN_DATE = date(2000, 1, 1)
MAX_ISSUES_KEPT = 50


class SaleRow(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    sale_date: date
    product: str = Field(min_length=1, max_length=200)
    region: str | None = Field(default=None, max_length=100)
    quantity: float | None = Field(default=None, ge=0, le=1_000_000)
    revenue: float = Field(ge=0, le=1_000_000_000)

    @field_validator("sale_date")
    @classmethod
    def sane_date(cls, v: date) -> date:
        if v < MIN_DATE:
            raise ValueError("date is before the year 2000")
        if v > date.today() + timedelta(days=1):
            raise ValueError("date is in the future")
        return v


FIELD_LABEL = {"sale_date": "date", "product": "product", "region": "region", "quantity": "quantity", "revenue": "revenue"}


def _clean_none(v):
    if v is None or v is pd.NA or v is pd.NaT:
        return None
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def _friendly(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        field = FIELD_LABEL.get(str(err["loc"][0]), str(err["loc"][0]))
        if err.get("input") is None:
            parts.append(f"{field} is missing")
        elif err["type"] == "value_error":
            parts.append(err["msg"].replace("Value error, ", ""))
        else:
            parts.append(f"{field}: {err['msg'].lower()}")
    return "; ".join(parts)


def validate(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict], list[str], int]:
    """Returns (valid_rows, issues, warnings, invalid_count)."""
    good, issues, invalid = [], [], 0
    for rec in df.to_dict("records"):
        ts = _clean_none(rec["date"])
        payload = {
            "sale_date": ts.date() if ts is not None else None,
            "product": _clean_none(rec["product"]),
            "region": _clean_none(rec["region"]),
            "quantity": _clean_none(rec["quantity"]),
            "revenue": _clean_none(rec["revenue"]),
        }
        try:
            good.append(SaleRow(**payload).model_dump())
        except ValidationError as exc:
            invalid += 1
            if len(issues) < MAX_ISSUES_KEPT:
                issues.append({"row": int(rec["_row"]), "problem": _friendly(exc)})

    total = len(df)
    if total == 0 or not good:
        raise ValidationFailed(
            "No valid rows were found in this file.",
            {"issues": issues, "invalid_rows": invalid},
        )
    if invalid / total > settings.max_invalid_ratio:
        raise ValidationFailed(
            f"{invalid} of {total} rows have problems (limit is {int(settings.max_invalid_ratio * 100)}%). "
            "Please fix the file and upload it again.",
            {"issues": issues, "invalid_rows": invalid},
        )

    valid_df = pd.DataFrame(good)
    warnings = []
    if invalid:
        warnings.append(f"{invalid} row(s) were skipped because of the problems listed below.")
    q1, q3 = valid_df["revenue"].quantile([0.25, 0.75])
    cutoff = q3 + 3 * (q3 - q1)
    outliers = int((valid_df["revenue"] > cutoff).sum()) if q3 > q1 else 0
    if outliers:
        warnings.append(f"{outliers} row(s) have unusually high revenue. Please double-check them.")
    return valid_df, issues, warnings, invalid
