"""The whole flow, one state at a time:
uploaded -> cleaning -> validating -> stored -> analyzing -> charting -> summarizing -> ready
(rejected = bad data, failed = our bug)
"""
import logging
import shutil
import uuid
from datetime import timedelta

import pandas as pd
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal, engine
from app.exceptions import AppError
from app.models import Report, SaleRecord, Status, utcnow
from app.services import analyzer, charts, cleaner, emailer, loader, report as pdf_report, summarizer, validator

log = logging.getLogger(__name__)


def _set(db, report: Report, status: str, **fields) -> None:
    report.status = status
    for k, v in fields.items():
        setattr(report, k, v)
    db.commit()


def generate_outputs(db, report: Report, df: pd.DataFrame, title: str, quality: dict) -> None:
    """analyze -> charts -> summary -> PDF. Shared by uploads and scheduled reports."""
    _set(db, report, Status.ANALYZING)
    analysis = analyzer.analyze(df, currency_code=settings.currency_code)
    report.analysis = analysis

    _set(db, report, Status.CHARTING)
    out_dir = settings.reports_dir / report.id
    chart_names = charts.make_charts(analysis, out_dir)

    _set(db, report, Status.SUMMARIZING)
    summary, source = summarizer.summarize(analysis)

    pdf_path = pdf_report.build_pdf(
        out_dir / "report.pdf", title=title, analysis=analysis, summary=summary,
        charts_dir=out_dir, chart_names=chart_names, quality=quality,
        issues=report.issues or [], warnings=report.warnings or [],
    )
    _set(db, report, Status.READY, summary=summary, summary_source=source, pdf_path=str(pdf_path))


def process_upload(report_id: str, filename: str, content: bytes) -> None:
    """Runs in the background after the upload is accepted."""
    db = SessionLocal()
    report = db.get(Report, report_id)
    try:
        _set(db, report, Status.CLEANING)
        raw = loader.read_table(filename, content)
        clean_df, log_info = cleaner.clean(raw)
        report.cleaning_log = log_info
        report.rows_read = log_info["rows_in_file"]

        _set(db, report, Status.VALIDATING)
        valid_df, issues, warnings, invalid = validator.validate(clean_df)
        report.issues, report.warnings = issues, warnings
        report.rows_valid, report.rows_rejected = len(valid_df), invalid

        db.bulk_insert_mappings(SaleRecord, [
            {"report_id": report.id, "sale_date": r["sale_date"], "product": r["product"],
             "region": r["region"], "quantity": r["quantity"], "revenue": r["revenue"]}
            for r in valid_df.to_dict("records")
        ])
        _set(db, report, Status.STORED)

        quality = {"rows_read": report.rows_read, "rows_valid": report.rows_valid,
                   "rows_rejected": report.rows_rejected, "duplicates_removed": log_info["duplicates_removed"]}
        generate_outputs(db, report, valid_df, f"Sales report: {report.filename}", quality)

    except AppError as exc:  # expected problems with the user's data
        db.rollback()
        report = db.get(Report, report_id)
        issues = exc.details.get("issues")
        _set(db, report, Status.REJECTED, error=exc.message, issues=issues or report.issues,
             rows_rejected=exc.details.get("invalid_rows", report.rows_rejected))
    except Exception:  # our own bug: log details privately, show a safe message
        log.exception("Report %s failed", report_id)
        db.rollback()
        report = db.get(Report, report_id)
        _set(db, report, Status.FAILED, error="Something went wrong while building this report. Please try again.")
    finally:
        db.close()


def run_scheduled_report() -> str | None:
    """Weekly job: report on the most recent N days of stored data, then email it."""
    db = SessionLocal()
    try:
        latest = db.scalar(select(func.max(SaleRecord.sale_date)))
        if latest is None:
            log.info("Scheduled report skipped: no data stored yet.")
            return None
        since = latest - timedelta(days=settings.schedule_days_back - 1)
        df = pd.read_sql(
            select(SaleRecord.sale_date, SaleRecord.product, SaleRecord.region,
                   SaleRecord.quantity, SaleRecord.revenue).where(SaleRecord.sale_date >= since),
            engine,
        )
        report = Report(id=uuid.uuid4().hex, source="scheduled",
                        filename=f"Scheduled report {latest.isoformat()}", status=Status.ANALYZING,
                        rows_read=len(df), rows_valid=len(df), created_at=utcnow())
        db.add(report)
        db.commit()
        try:
            quality = {"rows_read": len(df), "rows_valid": len(df), "rows_rejected": 0}
            generate_outputs(db, report, df, f"Scheduled sales report ({since} to {latest})", quality)
            emailer.send_report(
                settings.reports_dir / report.id / "report.pdf",
                f"Sales report {since} to {latest}",
                report.summary or "Your report is attached.",
            )
            return report.id
        except Exception:
            log.exception("Scheduled report failed")
            db.rollback()
            report = db.get(Report, report.id)
            shutil.rmtree(settings.reports_dir / report.id, ignore_errors=True)
            _set(db, report, Status.FAILED, error="Scheduled report failed. Check the server logs.")
            return None
    finally:
        db.close()
