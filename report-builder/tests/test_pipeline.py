import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.exceptions import FileRejected, ValidationFailed
from app.services import analyzer, cleaner, loader, validator

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data"
settings.reports_dir = Path(__import__("tempfile").mkdtemp())
KEY = {"X-API-Key": "test-key-123456789"}


# ---------- unit tests ----------
def test_cleaner_and_validator_on_messy_csv():
    raw = loader.read_table("messy_sales.csv", (SAMPLE / "messy_sales.csv").read_bytes())
    df, log = cleaner.clean(raw)
    assert log["header_row"] == 3                      # title rows skipped
    assert log["footer_rows_removed"] == 1             # "Total" row removed
    assert log["duplicates_removed"] >= 3
    assert log["names_unified"] > 0
    valid, issues, _, invalid = validator.validate(df)
    assert invalid >= 3 and len(issues) == invalid     # bad rows are explained
    assert (valid["revenue"] >= 0).all()
    assert valid["product"].nunique() == 5             # casing variants merged


def test_xlsx_reads_the_same_as_csv():
    raw = loader.read_table("m.xlsx", (SAMPLE / "messy_sales.xlsx").read_bytes())
    df, _ = cleaner.clean(raw)
    valid, *_ = validator.validate(df)
    assert len(valid) > 250
    assert analyzer.analyze(valid)["totals"]["orders"] == len(valid)


def test_analytics_include_currency_and_sales_averages():
    import pandas as pd

    df = pd.DataFrame([
        {"sale_date": "2024-01-01", "product": "A", "region": "North", "quantity": 1, "revenue": 100},
        {"sale_date": "2024-01-03", "product": "B", "region": "South", "quantity": 3, "revenue": 300},
    ])

    analysis = analyzer.analyze(df, currency_code="INR")

    assert analysis["currency"] == "INR"
    assert analysis["totals"]["revenue"] == 400
    assert analysis["totals"]["avg_order_value"] == 200
    assert analysis["totals"]["avg_daily_revenue"] == 133.33
    assert analysis["totals"]["avg_units_per_order"] == 2
    assert analysis["active_days"] == 2
    assert analysis["product_count"] == 2


@pytest.mark.parametrize("name,content", [
    ("evil.exe", b"MZ..."), ("a.csv", b""), ("a.xlsx", b"not a zip"), ("a.csv", b"\x00\x01\x02binary"),
])
def test_bad_files_are_rejected(name, content):
    with pytest.raises(FileRejected):
        loader.check_upload(name, content)


def test_missing_columns_gives_clear_error():
    with pytest.raises(ValidationFailed) as err:
        raw = loader.read_table("a.csv", b"date,product\n2024-01-01,A\n2024-01-02,B\n")
        cleaner.clean(raw)
    assert "revenue" in err.value.message


def test_mostly_bad_file_is_rejected():
    csv = "date,product,revenue\n" + "\n".join("bad,,x" for _ in range(10)) + "\n2024-01-01,A,10\n"
    raw = loader.read_table("a.csv", csv.encode())
    df, _ = cleaner.clean(raw)
    with pytest.raises(ValidationFailed):
        validator.validate(df)


# ---------- API tests ----------
@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_requires_api_key(client):
    assert client.get("/api/reports").status_code == 401
    assert client.get("/api/reports", headers={"X-API-Key": "wrong-key-wrong"}).status_code == 401


def test_upload_to_pdf_flow(client, monkeypatch):
    content = (SAMPLE / "messy_sales.csv").read_bytes()
    r = client.post("/api/reports", headers=KEY, files={"file": ("messy_sales.csv", content, "text/csv")})
    assert r.status_code == 202
    rid = r.json()["id"]
    data = client.get(f"/api/reports/{rid}", headers=KEY).json()
    for _ in range(60):
        if data["status"] in {"ready", "rejected", "failed"}:
            break
        time.sleep(0.5)
        data = client.get(f"/api/reports/{rid}", headers=KEY).json()
    assert data["status"] == "ready", data
    assert data["summary"] and len(data["charts"]) == 3
    assert data["analysis"]["currency"] == "INR"
    assert data["analysis"]["totals"]["avg_daily_revenue"] is not None
    pdf = client.get(f"/api/reports/{rid}/pdf", headers=KEY)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    sent = {}
    monkeypatch.setattr("app.main.emailer.email_configured", lambda recipients=None: True)

    def capture_email(pdf_path, subject, body, recipients=None):
        sent.update(pdf_path=pdf_path, subject=subject, body=body, recipients=recipients)
        return True

    monkeypatch.setattr("app.main.emailer.send_report", capture_email)
    email = client.post(f"/api/reports/{rid}/email", headers=KEY,
                        json={"recipients": ["owner@example.com"]})
    assert email.status_code == 200
    assert sent["pdf_path"].is_file()
    assert sent["body"] == data["summary"]
    assert sent["recipients"] == ["owner@example.com"]

    invalid_email = client.post(f"/api/reports/{rid}/email", headers=KEY,
                                json={"recipients": ["not-an-email"]})
    assert invalid_email.status_code == 422

    # same file again -> blocked
    dup = client.post("/api/reports", headers=KEY, files={"file": ("again.csv", content, "text/csv")})
    assert dup.status_code == 409


def test_bad_upload_and_bad_ids(client):
    r = client.post("/api/reports", headers=KEY, files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and r.json()["error"]["code"] == "file_rejected"
    assert client.get("/api/reports/../../etc/passwd", headers=KEY).status_code in (404, 422)
    assert client.get("/api/reports/" + "0" * 32, headers=KEY).status_code == 404


def test_security_headers(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in r.headers["content-security-policy"]
