# Report Builder

Upload a messy Excel/CSV file and get a **cleaned, validated report** with charts, a plain-English summary and a PDF. Can also send a **scheduled weekly report** by email.

**Stack:** Python, FastAPI, pandas, Pydantic, SQLAlchemy (SQLite or PostgreSQL), Matplotlib, ReportLab, APScheduler, optional AI summary (Claude or Gemini).

**Python:** 3.11. If VS Code already has another interpreter selected, choose the project `.venv` with **Python: Select Interpreter**.
**Currency:** Set `CURRENCY_CODE` in `.env` to the ISO 4217 code used by your sales data (defaults to `INR`).
**Email:** Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_FROM` in `.env` to enable the dashboard's **Send summary + PDF** action. `REPORT_EMAIL_TO` remains an optional default recipient list for scheduled reports. For Gmail, use an app password.

## Run it (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"   # paste the result as API_KEY in .env
python scripts/make_sample_data.py                              # creates messy demo files
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000, paste your API key, and drop in `sample_data/messy_sales.xlsx`.
API docs: http://127.0.0.1:8000/docs

Run the tests: `python -m pytest -q`

## How a file flows

`uploaded → cleaning → validating → stored → analyzing → charting → summarizing → ready`
If the data is not good enough: `rejected` (with a list of the problems). If we hit a bug: `failed`.

| Step | File | What it does |
|---|---|---|
| Read | `services/loader.py` | Checks type, size, real content; reads CSV/XLSX safely |
| Clean | `services/cleaner.py` | Finds header row, maps column names, fixes dates/money, removes totals and duplicates |
| Validate | `services/validator.py` | Pydantic rules per row; rejects the file if too many rows are bad |
| Analyze | `services/analyzer.py` | Totals, top products, regions, trend (plain pandas, never the AI) |
| Charts | `services/charts.py` | PNG charts |
| Summary | `services/summarizer.py` | AI writes the summary from totals only; falls back to a rule-based one |
| PDF | `services/report.py` | Builds the report |
| Email | `services/emailer.py` | Sends the PDF if SMTP is configured |
| Schedule | `services/scheduler.py` | Weekly job (turn on with `SCHEDULE_ENABLED=true`) |

## Expected columns (names can vary)

Required: **date**, **product**, and **revenue** (or **quantity + unit price**). Optional: **region**.
Recognised names include: `Order Date`, `Product Name`, `Qty`, `Unit Price`, `Total Sales`, `Amount`. Add more in `ALIASES` inside `cleaner.py`.

## Security built in

- API key required on every data endpoint (constant-time compare); app refuses to start without one
- Only `.csv`/`.xlsx`; size, row and column limits; content check (not just the extension); zip-bomb check
- Files are processed in memory and never saved or executed; formulas are not evaluated
- Filenames are display-only; report IDs and chart names are strictly validated (no path tricks)
- SQL via SQLAlchemy only (no string-built queries)
- Rate limiting, security headers + CSP, no stack traces in responses
- User text is escaped in the PDF and inserted with `textContent` in the browser
- The AI gets totals only, never raw rows; product names are sanitized and treated as untrusted
- Secrets live in `.env` (git-ignored)

## Good to know

- The same file cannot be uploaded twice (SHA-256 check), so scheduled reports don't double count.
- The scheduled report covers the last `SCHEDULE_DAYS_BACK` days **up to the newest date in the database**.
- `DATE_DAYFIRST=true` reads `03/04/2024` as 3 April. Set `false` for US dates.
- Before real client use: put it behind HTTPS (Caddy/Nginx), and use per-user logins instead of one shared key.
