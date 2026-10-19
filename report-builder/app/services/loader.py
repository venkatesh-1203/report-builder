"""Step 1: safely read an uploaded CSV/XLSX into a raw table.

Safety rules:
- only .csv and .xlsx
- size and row limits
- the file is read from memory and never saved or executed
- xlsx zip-bomb check
- formulas are NOT evaluated (openpyxl reads stored values only)
"""
import csv
import io
import zipfile
from pathlib import Path

import pandas as pd

from app.config import settings
from app.exceptions import FileRejected

ALLOWED_EXTENSIONS = {".csv", ".xlsx"}
MAX_UNZIPPED_BYTES = 100 * 1024 * 1024


def check_upload(filename: str | None, content: bytes) -> str:
    """Validate the raw upload. Returns the extension."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileRejected("Only .csv and .xlsx files are supported.", {"received": ext or "no extension"})
    if not content:
        raise FileRejected("The file is empty.")
    if len(content) > settings.max_upload_bytes:
        raise FileRejected(f"File is too large. Maximum is {settings.max_upload_bytes // (1024 * 1024)} MB.")

    # Check the real content, not just the name
    if ext == ".xlsx":
        if not content.startswith(b"PK\x03\x04"):
            raise FileRejected("This does not look like a real .xlsx file.")
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED_BYTES:
                    raise FileRejected("The Excel file expands to an unsafe size.")
        except zipfile.BadZipFile:
            raise FileRejected("The Excel file is corrupted.")
    else:
        if b"\x00" in content[:4096]:
            raise FileRejected("This does not look like a text CSV file.")
    return ext


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise FileRejected("Could not read the text encoding of this CSV.")


def _detect_delimiter(text: str) -> str:
    lines = [ln for ln in text.splitlines()[:30] if ln.strip()]
    best, best_score = ",", -1
    for d in (",", ";", "\t", "|"):
        score = sum(ln.count(d) for ln in lines)
        if score > best_score:
            best, best_score = d, score
    return best


def _read_csv(content: bytes) -> pd.DataFrame:
    text = _decode(content)
    delimiter = _detect_delimiter(text)
    rows = []
    try:
        for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
            if i > settings.max_rows + 50:
                raise FileRejected(f"Too many rows. Maximum is {settings.max_rows:,}.")
            rows.append(row)
    except csv.Error as exc:
        raise FileRejected(f"The CSV is malformed: {exc}")
    if not rows:
        raise FileRejected("The CSV has no rows.")
    width = max(len(r) for r in rows)
    padded = [[(c if c != "" else None) for c in r] + [None] * (width - len(r)) for r in rows]
    return pd.DataFrame(padded, dtype=object)


def _read_xlsx(content: bytes) -> pd.DataFrame:
    try:
        df = pd.read_excel(
            io.BytesIO(content), sheet_name=0, header=None, dtype=object,
            engine="openpyxl", nrows=settings.max_rows + 50,
        )
    except Exception:
        raise FileRejected("Could not read the Excel file. Is it password-protected or damaged?")
    return df


def read_table(filename: str | None, content: bytes) -> pd.DataFrame:
    """Return the raw sheet as a DataFrame with NO header (cleaner finds it)."""
    ext = check_upload(filename, content)
    df = _read_csv(content) if ext == ".csv" else _read_xlsx(content)

    if df.shape[1] > settings.max_cols:
        raise FileRejected(f"Too many columns ({df.shape[1]}). Maximum is {settings.max_cols}.")
    if df.shape[0] > settings.max_rows + 50:
        raise FileRejected(f"Too many rows. Maximum is {settings.max_rows:,}.")
    df = df.dropna(how="all")
    if df.empty:
        raise FileRejected("The file contains no data.")
    return df
