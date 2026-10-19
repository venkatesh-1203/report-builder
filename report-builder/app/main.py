import hashlib
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Path as PathParam, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import BASE_DIR, settings
from app.database import get_db, init_db
from app.exceptions import AppError, DuplicateFile, FileRejected, NotFound
from app.models import Report, Status
from app.security import CSP, SECURITY_HEADERS, RateLimiter, require_api_key, safe_display_name
from app.services import emailer, loader, pipeline
from app.services.charts import CHART_NAMES
from app.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")

STATIC_DIR = BASE_DIR / "app" / "static"
REPORT_ID = PathParam(pattern=r"^[0-9a-f]{32}$")  # blocks path tricks like ../../


class EmailReportRequest(BaseModel):
    recipients: list[str]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate()  # refuses to start with unsafe config
    init_db()
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="Automated Report Builder", version="1.0.0", lifespan=lifespan)

upload_limit = RateLimiter(max_calls=10, window_seconds=60)
general_limit = RateLimiter(max_calls=120, window_seconds=60)


# ---------- errors: always JSON, never a stack trace ----------
def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}}})


@app.exception_handler(AppError)
async def app_error_handler(_req: Request, exc: AppError):
    return _error(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_req: Request, exc: StarletteHTTPException):
    return _error(exc.status_code, "http_error", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def request_error_handler(_req: Request, _exc: RequestValidationError):
    return _error(422, "bad_request", "The request was not in the expected format.")


@app.exception_handler(Exception)
async def unexpected_error_handler(_req: Request, exc: Exception):
    log.exception("Unhandled error: %s", type(exc).__name__)
    return _error(500, "server_error", "Something went wrong on our side.")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
        response.headers["Content-Security-Policy"] = CSP
    return response


# ---------- helpers ----------
async def read_limited(file: UploadFile) -> bytes:
    """Read the upload in chunks and stop as soon as it is too big."""
    chunks, size = [], 0
    while chunk := await file.read(1024 * 256):
        size += len(chunk)
        if size > settings.max_upload_bytes:
            raise FileRejected(f"File is too large. Maximum is {settings.max_upload_bytes // (1024 * 1024)} MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def _get_report(db: Session, report_id: str) -> Report:
    report = db.get(Report, report_id)
    if not report:
        raise NotFound("Report not found.")
    return report


def _chart_list(report: Report) -> list[str]:
    folder = settings.reports_dir / report.id
    return [n for n in CHART_NAMES if (folder / f"{n}.png").exists()]


def _to_dict(r: Report, detail: bool = False) -> dict:
    data = {
        "id": r.id, "source": r.source, "filename": r.filename, "status": r.status,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "rows_read": r.rows_read, "rows_valid": r.rows_valid, "rows_rejected": r.rows_rejected,
        "error": r.error,
    }
    if detail:
        data.update({
            "summary": r.summary, "summary_source": r.summary_source, "analysis": r.analysis,
            "issues": r.issues or [], "warnings": r.warnings or [], "cleaning_log": r.cleaning_log,
            "charts": _chart_list(r) if r.status == Status.READY else [],
        })
    return data


# ---------- API ----------
@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/reports", status_code=202, dependencies=[Depends(require_api_key), Depends(upload_limit)])
async def upload_report(background: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    content = await read_limited(file)
    loader.check_upload(file.filename, content)  # fast checks before we accept it

    digest = hashlib.sha256(content).hexdigest()
    existing = db.scalar(select(Report).where(
        Report.file_hash == digest, Report.status.notin_([Status.REJECTED, Status.FAILED])))
    if existing:
        raise DuplicateFile("This exact file was already uploaded.", {"report_id": existing.id})

    report = Report(id=uuid.uuid4().hex, source="upload", filename=safe_display_name(file.filename),
                    file_hash=digest, status=Status.UPLOADED)
    db.add(report)
    db.commit()
    background.add_task(pipeline.process_upload, report.id, report.filename, content)
    return {"id": report.id, "status": report.status}


@app.get("/api/reports", dependencies=[Depends(require_api_key), Depends(general_limit)])
def list_reports(db: Session = Depends(get_db)):
    rows = db.scalars(select(Report).order_by(Report.created_at.desc()).limit(30)).all()
    return [_to_dict(r) for r in rows]


@app.post("/api/reports/scheduled/run", status_code=202,
          dependencies=[Depends(require_api_key), Depends(upload_limit)])
def run_scheduled_now(background: BackgroundTasks):
    background.add_task(pipeline.run_scheduled_report)
    return {"message": "Scheduled report started. It will appear in the list shortly."}


@app.get("/api/reports/{report_id}", dependencies=[Depends(require_api_key), Depends(general_limit)])
def get_report(report_id: str = REPORT_ID, db: Session = Depends(get_db)):
    return _to_dict(_get_report(db, report_id), detail=True)


@app.post("/api/reports/{report_id}/email",
          dependencies=[Depends(require_api_key), Depends(general_limit)])
def email_report(report_id: str = REPORT_ID, body: EmailReportRequest = Body(...),
                 db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    if report.status != Status.READY or not report.summary:
        raise NotFound("The summary and PDF are not ready yet.")

    recipients = list(dict.fromkeys(address.strip() for address in body.recipients))
    if not recipients or len(recipients) > 10 or any(not emailer.valid_email_address(address) for address in recipients):
        return _error(422, "invalid_recipients", "Enter between 1 and 10 valid email addresses.")

    pdf_path = settings.reports_dir / report.id / "report.pdf"
    if not pdf_path.is_file():
        raise NotFound("The PDF is not available.")
    if not emailer.email_configured(recipients):
        return _error(503, "email_not_configured",
                      "Email is not configured. Set SMTP_HOST and SMTP_FROM in .env, then restart the app.")

    subject = f"Sales report: {report.filename}"[:150]
    sent = emailer.send_report(pdf_path, subject, report.summary, recipients=recipients)
    if not sent:
        return _error(502, "email_delivery_failed",
                      "Email could not be sent. Check your SMTP host, port, sender, and credentials in .env.")
    return {"message": f"Report summary and PDF sent to {', '.join(recipients)}."}


@app.get("/api/reports/{report_id}/pdf", dependencies=[Depends(require_api_key), Depends(general_limit)])
def download_pdf(report_id: str = REPORT_ID, db: Session = Depends(get_db)):
    report = _get_report(db, report_id)
    path = settings.reports_dir / report.id / "report.pdf"
    if report.status != Status.READY or not path.exists():
        raise NotFound("The PDF is not ready yet.")
    return FileResponse(path, media_type="application/pdf", filename=f"report-{report.id[:8]}.pdf")


@app.get("/api/reports/{report_id}/charts/{name}", dependencies=[Depends(require_api_key), Depends(general_limit)])
def get_chart(name: str = PathParam(pattern=r"^[a-z_]{3,20}$"), report_id: str = REPORT_ID,
              db: Session = Depends(get_db)):
    _get_report(db, report_id)
    if name not in CHART_NAMES:  # whitelist, never build paths from raw input
        raise NotFound("Chart not found.")
    path = settings.reports_dir / report_id / f"{name}.png"
    if not path.exists():
        raise NotFound("Chart not found.")
    return FileResponse(path, media_type="image/png")


# ---------- frontend ----------
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
